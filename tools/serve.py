#!/usr/bin/env python3
r"""
serve.py — interface web « teleimprimeur » : des amis envoient des messages,
ils sortent en vrai sur du papier, sur l'une des deux imprimantes.

DEUX IMPRIMANTES, une seule page : le destinataire se choisit a l'envoi, et
l'etat de chacune est affiche en direct. Un fil d'execution par imprimante, donc
elles peuvent travailler en meme temps ; le journal des messages est commun.

  xerox   Xerox 575 via le Pico (IFD-2), protocole IFD1
      navigateur -> ce serveur -> USB -> Pico -> machine a ecrire
      Cote Pico, ifd2.run() doit tourner (deploye en main.py, voir
      pico/server_boot.py), et il faut presser ON LINE sur la machine.
      /!\ le port serie ne se partage pas : aucune session mpremote en cours.

  dmp     Amstrad DMP 3160 sur adaptateur USB <-> Centronics
      navigateur -> ce serveur -> /dev/usb/lp0 -> matricielle
      Beaucoup plus simple : de l'ASCII brut, ni protocole a deux octets, ni
      accuse DTR, ni index de marguerite. Utile aussi pour tester toute la
      chaine (page, file, service) sans la Xerox ni le Pico.

Exemples :
    ./tools/serve.py                        # les deux imprimantes, page au choix
    ./tools/serve.py --machines dmp         # la matricielle seule
    ./tools/serve.py --gras double          # essai d'un autre gras sur la DMP
    ./tools/serve.py --host 0.0.0.0         # visible sur le reseau local

Le serveur n'ecoute que sur 127.0.0.1 par defaut : il n'y a ni authentification
ni limitation de debit, donc ne l'ouvrir au reseau que sur un reseau de confiance,
et jamais sur Internet.
"""
import argparse
import base64
import hmac
import html
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import glob
import os
import sys

# pyserial n'est necessaire QUE pour la sortie Pico : la sortie Centronics
# n'ecrit que dans un fichier de peripherique. Import souple, donc, pour que la
# DMP 3160 fonctionne sur une machine sans pyserial.
try:
    import serial
except ImportError:
    serial = None


def _erreur_pyserial():
    venv = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "venv", "bin", "python")
    msg = ["pyserial manquant pour CET interpreteur :", "    %s" % sys.executable,
           "", "Attention : `pip` et `python3` ne pointent pas forcement sur le",
           "meme Python. Installer avec l'interpreteur qui execute le script :",
           "    %s -m pip install pyserial" % sys.executable]
    if os.path.exists(venv):
        msg += ["", "Ou plus simple, le venv du projet l'a deja :",
                "    %s %s" % (venv, os.path.abspath(__file__))]
    return IOError("\n".join(msg))


# ------------------------------------------------------------ authentification
def charger_identifiants(chemin):
    """Charge les comptes depuis un JSON, format par utilisateur :
        {"ami": {"mot_de_passe": "...", "credits": 20, "admin": false}, ...}
    "credits": null => illimite (typiquement pour un compte admin).
    Fichier VOLONTAIREMENT hors du depot (voir .gitignore) : jamais de mot de
    passe commite."""
    if not chemin or not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        brut = json.load(f)
    if not isinstance(brut, dict) or not brut:
        raise SystemExit(
            "credentials : JSON attendu {\"ami\": {\"mot_de_passe\": \"...\", "
            "\"credits\": 20, \"admin\": false}, ...} (voir "
            "tools/credentials.json.example)")
    comptes = {}
    for u, v in brut.items():
        if not isinstance(v, dict) or "mot_de_passe" not in v:
            raise SystemExit("credentials : l'entree %r doit etre un objet "
                             "avec au moins \"mot_de_passe\"" % u)
        comptes[u] = {"mot_de_passe": v["mot_de_passe"],
                      "credits": v.get("credits", 0),
                      "admin": bool(v.get("admin", False))}
    return comptes


class Credits:
    """Solde de credits par utilisateur, gere a la main par un admin -- pas
    une fenetre glissante automatique : proteger le papier/ruban d'un ami trop
    enthousiaste, et savoir qui a envoye quoi, avec un vrai humain aux
    commandes plutot qu'une limite arbitraire par heure."""

    def __init__(self, comptes):
        self.solde = {u: c["credits"] for u, c in comptes.items()}
        self.admins = {u for u, c in comptes.items() if c["admin"]}
        self.verrou = threading.Lock()

    def illimite(self, qui):
        return qui in self.admins or self.solde.get(qui) is None

    def depenser(self, qui):
        """True si le message peut partir (et decrement le solde)."""
        if self.illimite(qui):
            return True
        with self.verrou:
            if self.solde.get(qui, 0) <= 0:
                return False
            self.solde[qui] -= 1
            return True

    def ajuster(self, qui, delta):
        with self.verrou:
            self.solde[qui] = self.solde.get(qui, 0) + delta

    def etat(self):
        with self.verrou:
            return {u: ("illimite" if self.illimite(u) else s)
                    for u, s in self.solde.items()}


MAX_LEN = 500          # garde-fou : la machine tape ~1 caractere/seconde


def trouver_port():
    """Cherche le Pico sur le bus. Sur Mac les ports sont /dev/cu.usbmodemXXXX
    (numero variable selon la prise !), sur Linux /dev/ttyACM0."""
    for motif in ("/dev/cu.usbmodem*", "/dev/ttyACM*", "/dev/cu.usbserial*"):
        trouves = sorted(glob.glob(motif))
        if trouves:
            return trouves[0]
    return None


# =============================================================== sorties papier
# Deux imprimantes, deux mondes : la Xerox 575 parle un protocole a deux octets
# via le Pico, la DMP 3160 avale de l'ASCII brut sur un port parallele. La file
# d'attente, la page web et le journal sont communs ; seule cette couche change.

class Sortie:
    """Interface d'une sortie d'impression."""

    nom = "?"

    def disponible(self):
        """Chemin du peripherique s'il est present, None sinon."""
        raise NotImplementedError

    def ouvrir(self):
        raise NotImplementedError

    def fermer(self):
        pass

    def imprimer(self, texte, dire):
        """Imprime le texte. `dire(msg)` remonte l'avancement a la page."""
        raise NotImplementedError

    def absente(self):
        return "imprimante absente"


class SortiePico(Sortie):
    """Xerox 575 via le Pico (IFD-2), protocole ligne OK / ERR / # bavardage."""

    nom = "Xerox 575 (Pico)"

    def __init__(self, port=None, baud=115200):
        self.port, self.baud = port, baud
        self.fixe = port is not None       # port impose, ou detecte a chaud
        self.ser = None

    def disponible(self):
        return self.port if self.fixe else trouver_port()

    def ouvrir(self):
        if self.ser is not None:
            return self.port
        if serial is None:
            raise _erreur_pyserial()
        port = self.disponible()
        if not port:
            raise IOError("aucun Pico detecte")
        self.ser = serial.Serial(port, self.baud, timeout=5)
        self.port = port
        time.sleep(0.5)
        return port

    def fermer(self):
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def imprimer(self, texte, dire):
        for ligne in texte.split('\n'):
            # vider ce qui traine : un vieux bavardage du Pico lu comme accuse
            # ferait croire a une impression terminee.
            self.ser.reset_input_buffer()
            self.ser.write((ligne + '\n').encode('utf-8', 'replace'))
            self.ser.flush()
            self._attendre_ok(ligne, dire)

    def _attendre_ok(self, ligne, dire):
        """Protocole (voir ifd2.run()) : "OK" imprime, "ERR ..." echec,
        "# ..." bavardage humain — a remonter, pas a confondre avec un accuse.

        Delai proportionnel a la longueur : la machine tape environ un caractere
        par seconde, un timeout fixe declarerait en echec un long message en
        train de s'imprimer tres correctement."""
        timeout = 60 + 3 * len(ligne)
        t0 = time.time()
        while time.time() - t0 < timeout:
            brute = self.ser.readline()
            if not brute:
                continue
            msg = brute.decode("utf-8", "replace").strip()
            if msg == "OK":
                return True
            if msg.startswith("ERR"):
                raise IOError(msg[3:].strip() or "erreur signalee par le Pico")
            if msg:
                dire("Pico : %s" % msg.lstrip("# ").strip())
        raise IOError("pas d'accuse du Pico apres %d s "
                      "(session ouverte ? LED ON LINE allumee ?)" % timeout)

    def absente(self):
        return "imprimante absente (aucun Pico sur le bus USB)"


# Repli ASCII pour les caracteres que la matricielle ne sait pas rendre : mieux
# vaut un "e" qu'un point d'interrogation au milieu d'un mot doux.
TRANSLIT = {
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e', 'à': 'a', 'â': 'a', 'ä': 'a',
    'î': 'i', 'ï': 'i', 'ô': 'o', 'ö': 'o', 'ù': 'u', 'û': 'u', 'ü': 'u',
    'ç': 'c', 'ÿ': 'y', 'É': 'E', 'È': 'E', 'Ê': 'E', 'À': 'A', 'Ç': 'C',
    'Ô': 'O', 'Û': 'U', 'œ': 'oe', 'Œ': 'OE', 'æ': 'ae', '’': "'",
    '‘': "'", '“': '"', '”': '"', '–': '-', '—': '-', '…': '...', ' ': ' ',
}


class SortieCentronics(Sortie):
    """Amstrad DMP 3160 (ou toute matricielle) derriere un adaptateur
    USB <-> Centronics, qui se presente en classe imprimante.

    Bien plus simple que la Xerox : ni protocole a deux octets, ni accuse DTR,
    ni index de marguerite — la matricielle avale de l'ASCII."""

    nom = "DMP 3160 (Centronics)"

    # Plusieurs familles de sequences existent, et la DMP 3160 n'honore pas
    # forcement celle qu'on croit. MESURE DU 2026-07-27 : avec ESC E / ESC F
    # (Epson, "emphasized"), la ligne n'est PAS sortie du tout — l'imprimante
    # n'a pas ignore la sequence, elle a attendu une suite qui ne venait pas et
    # a avale le reste. Le gras est donc DESACTIVE par defaut ; utiliser
    # tools/dmp_probe.py pour trouver ce que cette imprimante accepte.
    GRAS = {
        "aucun":  (b'', b''),                    # defaut : les etoiles disparaissent
        "esc":    (b'\x1bE', b'\x1bF'),          # Epson "emphasized" — KO ici
        "double": (b'\x1bG', b'\x1bH'),          # Epson "double-strike" — a tester
    }

    def __init__(self, device=None, encodage="cp437", fin_ligne="\r\n",
                 fin_message="\n\n\n", gras="aucun"):
        self.device = device
        self.encodage = encodage
        self.fin_ligne = fin_ligne
        self.fin_message = fin_message
        self.gras = gras if gras in self.GRAS else "aucun"
        self.f = None

    def disponible(self):
        if self.device:
            return self.device if os.path.exists(self.device) else None
        # /!\ Sur Debian et Raspberry Pi OS, usblp cree son noeud dans un
        # SOUS-REPERTOIRE : /dev/usb/lp0. Le "usblp0" annonce par dmesg est le
        # nom du pilote, pas le chemin du fichier. D'autres distributions
        # utilisent /dev/usblp0, et le port parallele physique /dev/lp0.
        for motif in ("/dev/usb/lp*", "/dev/usblp*", "/dev/lp*"):
            trouves = sorted(glob.glob(motif))
            if trouves:
                return trouves[0]
        return None

    def ouvrir(self):
        # Revalider le chemin : un adaptateur debranche laisse la poignee de
        # fichier ouverte sur un peripherique disparu, et les ecritures partent
        # alors dans le vide en se declarant reussies.
        if self.f is not None:
            if self.device and os.path.exists(self.device):
                return self.device
            self.fermer()
        dev = self.disponible()
        if not dev:
            raise IOError("aucune imprimante parallele (%s introuvable)"
                          % (self.device or "/dev/usb/lp0"))
        # buffering=0 : un peripherique caractere n'aime pas les ecritures
        # differees, on veut que chaque octet parte quand on l'ecrit.
        self.f = open(dev, "wb", buffering=0)
        self.device = dev
        return dev

    def fermer(self):
        try:
            if self.f is not None:
                self.f.close()
        except Exception:
            pass
        self.f = None

    def _octets(self, s):
        """Encode pour l'imprimante, en repliant CARACTERE PAR CARACTERE.

        Un repli global serait dommageable : un seul caractere absent du jeu
        (une apostrophe typographique, des points de suspension) ferait perdre
        les accents de toute la ligne, alors que cp437 sait tres bien ecrire
        « é » et « à »."""
        try:
            return s.encode(self.encodage)
        except LookupError:              # encodage inconnu -> ASCII translitere
            return self._translit(s)
        except UnicodeEncodeError:
            pass
        out = bytearray()
        for c in s:
            try:
                out += c.encode(self.encodage)
            except UnicodeEncodeError:
                out += self._translit(c)
        return bytes(out)

    def _translit(self, s):
        return ''.join(TRANSLIT.get(c, c) for c in s).encode("ascii", "replace")

    def imprimer(self, texte, dire):
        dire("impression en cours (%s)" % self.device)
        on, off = self.GRAS[self.gras]
        # ESC @ (reset) en tete de chaque job : sans lui, un etat residuel du
        # job precedent (mode, buffer) peut faire "avaler" une commande valide
        # -- c'est ce que dmp_probe.py fait deja avant chaque essai, et qui
        # manquait ici. HYPOTHESE du 2026-07-28, a confirmer par plusieurs
        # impressions consecutives avec --gras esc.
        #
        # RETIRE (2026-07-28) : ESC R 0 forçait le jeu USA pour proteger la
        # ponctuation, mais tuait les accents (le remplacement France etait
        # leur seul mecanisme de rendu en mode Epson FX). Le vrai fix est
        # cote DIP switch : DS1-8 -> ON (mode IBM #2 avec DS1-7 deja ON),
        # qui active la table cp437 pour les octets hauts ET rend le
        # remplacement de ponctuation France caduc -- voir manuel : "pour les
        # caracteres internationaux, DS1-8 doit etre eteint" implique l'inverse
        # (DS1-8 allume) selectionne la table IBM/cp437 a la place. A confirmer
        # au banc.
        sortie = bytearray(b'\x1b@')
        for ligne in texte.split('\n'):
            if on:
                # meme balisage que la Xerox : *entoure d'etoiles* = gras
                for n, morceau in enumerate(ligne.split('*')):
                    if n % 2:
                        sortie += on + self._octets(morceau) + off
                    else:
                        sortie += self._octets(morceau)
            else:
                # gras non pris en charge : on retire les etoiles, mais on
                # imprime le texte — un mot doux qui ne sort pas est pire qu'un
                # mot doux sans gras.
                sortie += self._octets(ligne.replace('*', ''))
            sortie += self._octets(self.fin_ligne)
        sortie += self._octets(self.fin_message)
        self.f.write(bytes(sortie))
        self.f.flush()

    def absente(self):
        return ("imprimante absente (%s introuvable — adaptateur branche ? "
                "module usblp charge ?)" % (self.device or "/dev/usb/lp0"))


# --------------------------------------------------------------- file d'attente
class Printer(threading.Thread):
    """UN fil par imprimante : chaque liaison est sequentielle (deux messages
    entrelaces desynchroniseraient les paires d'octets de la Xerox), mais les
    deux imprimantes sont independantes et peuvent donc travailler en meme temps.

    Le serveur web ne depend PAS de la presence des imprimantes : sans elles la
    page s'affiche quand meme et annonce leur absence. Sortir en erreur quand
    rien n'est branche rendrait la page inaccessible au moment precis ou on en
    a besoin pour comprendre pourquoi."""

    daemon = True
    ESSAIS = 3             # tentatives d'ouverture du port par message
    ATTENTE = 3            # secondes entre deux tentatives

    def __init__(self, cle, sortie, journal, verrou):
        super().__init__()
        self.q = queue.Queue()
        self.cle = cle
        self.sortie = sortie
        self.journal = journal          # liste PARTAGEE entre les imprimantes
        self.verrou = verrou
        self.etat = "recherche..."
        self.prete = False

    def submit(self, text, qui="anonyme"):
        self.q.put((text, qui))
        return self.q.qsize()

    def _dire(self, msg):
        self.etat = msg

    def veiller(self):
        """Tient l'etat a jour meme quand personne n'imprime, pour que la page
        dise la verite au lieu de rester sur un vieux message."""
        while True:
            ou = self.sortie.disponible()
            if ou is None:
                self.sortie.fermer()
                self.etat = self.sortie.absente()
                self.prete = False
            elif not self.prete and self.q.empty():
                self.etat = "prete (%s)" % ou
                self.prete = True
            time.sleep(5)

    def run(self):
        threading.Thread(target=self.veiller, daemon=True).start()
        while True:
            text, qui = self.q.get()
            # En-tete imprime AVANT le message : sur le papier, on ne sait pas
            # qui ecrit ni quand. Ajoute ici (et pas dans les backends) pour
            # servir les deux imprimantes d'un seul endroit ; le journal, lui,
            # garde le texte brut -- l'expediteur et l'heure y figurent deja.
            a_imprimer = "%s, %s\n%s" % (qui, time.strftime("%H:%M"), text)
            for essai in range(1, self.ESSAIS + 1):
                try:
                    ou = self.sortie.ouvrir()
                    self.sortie.imprimer(a_imprimer, self._dire)
                    self._note(text, "imprime", qui)
                    self.etat = "prete (%s)" % ou
                    self.prete = True
                    break
                except Exception as e:                  # lien coupe, absente
                    self.sortie.fermer()
                    self.etat = "injoignable : %s" % e
                    self.prete = False
                    if essai == self.ESSAIS:
                        self._note(text, "ECHEC : %s" % e, qui)
                    else:
                        time.sleep(self.ATTENTE)

    def _note(self, text, etat, qui="anonyme"):
        # journal commun aux deux imprimantes : verrou obligatoire, deux fils
        # peuvent y ecrire en meme temps.
        with self.verrou:
            self.journal.insert(0, {"quand": time.strftime("%H:%M:%S"),
                                    "texte": text, "etat": etat, "qui": qui,
                                    "machine": self.sortie.nom})
            del self.journal[30:]


# --------------------------------------------------------------------- page web
PAGE = """<!doctype html>
<html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Téléimprimeur — Xerox 575</title>
<style>
  :root {
    color-scheme: light dark;
    --encre: #8a2f3b;              /* rouge-ruban : accent, jamais le texte courant */
    --encre-douce: color-mix(in srgb, var(--encre) 14%%, transparent);
    --papier: #faf7ef;             /* la feuille */
    --bureau: #ddd7c9;             /* le plan de travail sous la feuille */
    --texte:  #2b2926;
    --trou:   #ddd7c9;             /* perforations d'entrainement */
    --ok: #3a7a4a; --ko: #a33d2e;  /* semantique, distincte de l'accent */
  }
  @media (prefers-color-scheme: dark) {
    :root { --encre: #e2919c; --papier: #17191e; --bureau: #0b0c0f;
            --texte: #ded9d0; --trou: #0b0c0f; --ok: #6bbf7e; --ko: #e0796a; }
  }
  * { box-sizing: border-box; }
  body { font: 15px/1.65 ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace;
         color: var(--texte); background: var(--bureau);
         margin: 0; padding: 2.5rem 1rem; }

  /* La feuille de listing : bandes perforees le long des deux bords, comme le
     papier continu qui sort vraiment de la machine. */
  .feuille { position: relative; max-width: 38rem; margin: 0 auto;
             background: var(--papier); padding: 2.2rem 3.4rem;
             box-shadow: 0 1px 3px #0002, 0 12px 28px -12px #0003; }
  .feuille::before, .feuille::after {
    content: ""; position: absolute; top: 0; bottom: 0; width: 2.2rem;
    background-image: radial-gradient(circle at center,
                      var(--trou) 0 3.5px, transparent 3.6px);
    background-size: 100%% 1.15rem;
    border-color: color-mix(in srgb, var(--texte) 22%%, transparent);
    border-style: dashed; border-width: 0; }
  .feuille::before { left: 0;  border-right-width: 1px; }
  .feuille::after  { right: 0; border-left-width: 1px; }

  h1 { font-size: 1.15rem; font-weight: 700; letter-spacing: .22em;
       text-transform: uppercase; margin: 0 0 .1rem; }
  h1 .machine-nom { display: block; font-size: .65rem; letter-spacing: .3em;
                    font-weight: 400; color: var(--encre); margin-top: .35rem; }
  a { color: var(--encre); text-decoration: none;
      border-bottom: 1px solid color-mix(in srgb, var(--encre) 45%%, transparent); }
  a:hover { border-color: var(--encre); }
  p.sub { opacity: .7; margin: 1.4rem 0 1rem; font-size: .8rem; line-height: 1.7; }
  p.solde { display: inline-block; margin: 0 0 1.2rem; padding: .25rem .7rem;
            font-size: .72rem; letter-spacing: .08em; text-transform: uppercase;
            border: 1px solid var(--encre); color: var(--encre);
            font-variant-numeric: tabular-nums; }
  textarea { width: 100%%; min-height: 8rem; font: 1em/1.5 inherit;
             padding: .9rem; background: transparent; color: inherit;
             border: 1px solid color-mix(in srgb, var(--texte) 28%%, transparent);
             transition: border-color .15s; }
  textarea:focus { outline: none; border-color: var(--encre); }
  button { font: inherit; font-weight: 700; letter-spacing: .12em;
           text-transform: uppercase; font-size: .8rem;
           padding: .65rem 1.6rem; margin-top: .9rem;
           border: 1px solid var(--encre); background: transparent;
           color: var(--encre); cursor: pointer;
           transition: background-color .15s, color .15s; }
  button:hover:not(:disabled) { background: var(--encre); color: var(--papier); }
  button:disabled { opacity: .4; cursor: wait; }
  .compte { float: right; font-size: .75rem; opacity: .55;
            font-variant-numeric: tabular-nums; }
  ul { list-style: none; padding: 0; margin: 2.5rem 0 0;
       border-top: 1px dashed color-mix(in srgb, var(--texte) 25%%, transparent); }
  li { padding: .65rem 0; font-size: .82rem;
       border-bottom: 1px dashed color-mix(in srgb, var(--texte) 15%%, transparent); }
  li .quand { opacity: .5; margin-right: .6rem; font-variant-numeric: tabular-nums; }
  li .etat { float: right; opacity: .75; font-size: .72rem;
             letter-spacing: .06em; text-transform: uppercase; }
  li.echec .etat { color: var(--ko); opacity: 1; }
  li.imprime .etat { color: var(--ok); }
  li .machine { opacity: .45; font-size: .7rem; margin-left: .5rem; }
  #machines { display: flex; flex-direction: column; gap: .45rem;
              margin-bottom: 1.2rem; }
  label.mach { display: flex; align-items: baseline; gap: .6rem;
               font-size: .8rem; padding: .5rem .75rem; cursor: pointer;
               transition: border-color .15s, background-color .15s;
               border: 1px solid color-mix(in srgb, var(--texte) 22%%, transparent); }
  label.mach:has(input:checked) { border-color: var(--encre); background: var(--encre-douce); }
  label.mach.absente { border-style: dashed; opacity: .55; }
  label.mach .nom { font-weight: 700; }
  label.mach .etat { font-size: .72rem; opacity: .7; margin-left: auto;
                     text-align: right; }
  @media (max-width: 34rem) {
    body { padding: 1rem .4rem; }
    .feuille { padding: 1.6rem 2.6rem; }
    .feuille::before, .feuille::after { width: 1.6rem; }
  }
</style>
<div class="feuille">
<h1>Téléimprimeur<span class="machine-nom">Merde, ce con a réinventé le fax en 2026</span></h1>
<p class="sub">%(intro)s%(lien_admin)s</p>
<p class="solde" id="solde"></p>
<form id="f">
  <div id="machines">%(machines)s</div>
  <textarea id="t" maxlength="%(max)d" placeholder="Votre message…"
            autofocus></textarea>
  <span class="compte"><span id="n">0</span>/%(max)d</span>
  <button id="b">Envoyer à l'imprimante</button>
</form>
<ul id="journal"></ul>
</div>
<script>
const t = document.getElementById('t'), n = document.getElementById('n'),
      b = document.getElementById('b'), j = document.getElementById('journal'),
      s = document.getElementById('solde');
t.oninput = () => n.textContent = t.value.length;
const cible = () => (document.querySelector('input[name=cible]:checked')
                     || document.querySelector('input[name=cible]')).value;
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  if (!t.value.trim()) return;
  b.disabled = true; b.textContent = 'Envoi…';
  await fetch('/print?cible=' + encodeURIComponent(cible()),
              {method: 'POST', body: t.value});
  t.value = ''; n.textContent = '0';
  b.disabled = false; b.textContent = 'Imprimer';
  rafraichir();
};
const echapper = s => s.replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]));
async function rafraichir() {
  const r = await (await fetch('/journal')).json();
  for (const m of r.machines) {
    const l = document.querySelector(`label.mach[data-cle="${m.cle}"]`);
    if (!l) continue;
    l.querySelector('.etat').textContent = m.etat;
    l.classList.toggle('absente', !m.prete);
  }
  s.textContent = r.mon_solde === 'illimite' ? 'Crédits : illimités' :
    `Crédits : ${r.mon_solde} restant${r.mon_solde === 1 ? '' : 's'}`;
  j.innerHTML = r.messages.map(m =>
    `<li class="${m.etat.startsWith('ECHEC') ? 'echec' : 'imprime'}">` +
    `<span class="quand">${m.quand}</span>${echapper(m.texte)}` +
    `<span class="machine">${echapper(m.machine)} — ${echapper(m.qui || '?')}</span>` +
    `<span class="etat">${echapper(m.etat)}</span></li>`).join('');
}
rafraichir(); setInterval(rafraichir, 4000);
</script>
</html>"""


PAGE_ADMIN = """<!doctype html>
<html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comptes — Téléimprimeur</title>
<style>
  :root { color-scheme: light dark; --encre: #8a2f3b; }
  @media (prefers-color-scheme: dark) { :root { --encre: #e2919c; } }
  body { font: 15px/1.6 ui-monospace, "SF Mono", "Cascadia Code",
               Consolas, monospace; max-width: 30rem;
         margin: 4rem auto; padding: 0 1.5rem; }
  h1 { font-size: 1.1rem; font-weight: 700; letter-spacing: .2em;
       text-transform: uppercase; margin-bottom: 1.2rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: .5rem .3rem;
           border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent); }
  td.solde { font-variant-numeric: tabular-nums; text-align: right; }
  button { font: inherit; padding: .15rem .6rem; margin: 0 .15rem;
           border-radius: 6px; border: 1px solid var(--encre);
           background: transparent; color: var(--encre); cursor: pointer;
           transition: background-color .15s, color .15s; }
  button:hover { background: var(--encre); color: #fff; }
  a { color: var(--encre); text-decoration: none;
      border-bottom: 1px solid color-mix(in srgb, var(--encre) 45%, transparent); }
</style>
<h1>Comptes</h1>
<p><a href="/">← retour</a></p>
<table><thead><tr><th>Utilisateur</th><th>Solde</th><th></th></tr></thead>
<tbody id="lignes"></tbody></table>
<script>
async function ajuster(qui, delta) {
  await fetch('/admin/credit?qui=' + encodeURIComponent(qui) + '&delta=' + delta,
              {method: 'POST'});
  rafraichir();
}
async function rafraichir() {
  const soldes = await (await fetch('/admin/soldes')).json();
  document.getElementById('lignes').innerHTML = Object.entries(soldes).map(
    ([qui, solde]) => `<tr><td>${qui}</td><td class="solde">${solde}</td><td>` +
      (solde === 'illimite' ? '' :
        `<button onclick="ajuster('${qui}',-5)">−5</button>` +
        `<button onclick="ajuster('${qui}',-1)">−1</button>` +
        `<button onclick="ajuster('${qui}',1)">+1</button>` +
        `<button onclick="ajuster('${qui}',5)">+5</button>`) +
      `</td></tr>`).join('');
}
rafraichir();
</script>
</html>"""


def bloc_machines(printers, admin):
    """Boutons radio des imprimantes, avec etat en direct -- reserve aux
    administrateurs (on ne montre pas a un ami quelles machines physiques
    existent ni leur etat). Pour les autres : un champ cache vide, le serveur
    choisit lui-meme la cible a l'envoi (priorite a une imprimante DISPONIBLE
    a cet instant -- voir do_POST)."""
    if not admin:
        return '<input type="hidden" name="cible" value="">'
    # Meme priorite qu'a l'envoi (do_POST) : la case cochee par defaut doit
    # etre une imprimante DISPONIBLE si possible, pas juste "la premiere
    # configuree" -- sinon un admin qui envoie sans regarder cible l'absente.
    dispo = [c for c, p in printers.items() if p.prete]
    defaut = dispo[0] if dispo else next(iter(printers), None)
    out = []
    for cle, p in printers.items():
        out.append(
            '  <label class="mach" data-cle="%s">\n'
            '    <input type="radio" name="cible" value="%s"%s>\n'
            '    <span class="nom">%s</span>\n'
            '    <span class="etat">…</span>\n'
            '  </label>' % (cle, cle, " checked" if cle == defaut else "",
                            html.escape(p.sortie.nom)))
    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    printers = {}          # cle -> Printer
    journal = []           # liste partagee
    identifiants = None     # {utilisateur: mot_de_passe}, ou None = pas d'auth
    credits = None            # instance de Credits, ou None = pas de limite

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _qui(self):
        """Verifie l'en-tete Basic Auth. Retourne le nom d'utilisateur si
        valide, None sinon. Comparaison a temps constant (hmac) pour ne pas
        laisser deviner un mot de passe par le temps de reponse."""
        if self.identifiants is None:
            return "anonyme"                     # pas d'auth configuree
        entete = self.headers.get("Authorization", "")
        if not entete.startswith("Basic "):
            return None
        try:
            u, p = base64.b64decode(entete[6:]).decode("utf-8").split(":", 1)
        except Exception:
            return None
        compte = self.identifiants.get(u)
        if compte is not None and hmac.compare_digest(p, compte["mot_de_passe"]):
            return u
        return None

    def _refuser_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Mots doux"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _est_admin(self, qui):
        return (self.identifiants is not None
                and self.identifiants.get(qui, {}).get("admin", False))

    def do_GET(self):
        qui = self._qui()
        if qui is None:
            return self._refuser_auth()
        chemin = urlparse(self.path).path
        if chemin == "/":
            admin = self._est_admin(qui)
            lien_admin = ' — <a href="/admin">administration</a>' if admin else ''
            intro = (
                "Ce que vous écrivez ici est <strong>réellement imprimé</strong>, "
                "à l'encre et sur papier, chez moi — sur une imprimante "
                "matricielle (tzzzzt tzzzt tzzzt) ou une machine à écrire "
                "(tchak tchak tchak), selon la configuration du moment. "
                "Votre pseudo et l'heure sont tapés en tête du message. "
                "Chaque envoi coûte <strong>1 crédit</strong> ; quand vous "
                "n'en avez plus, demandez-en à l'administrateur.")
            self._send(200, PAGE % {"max": MAX_LEN, "lien_admin": lien_admin,
                                    "intro": intro,
                                    "machines": bloc_machines(self.printers, admin)})
        elif chemin == "/journal":
            admin = self._est_admin(qui)
            # Les imprimantes (existence, etat, chemin systeme) restent privees :
            # un ami curieux ouvrant les outils reseau du navigateur ne doit pas
            # en apprendre plus que ce que montre la page.
            machines = [{"cle": cle, "nom": p.sortie.nom, "etat": p.etat,
                         "prete": p.prete, "file": p.q.qsize()}
                        for cle, p in self.printers.items()] if admin else []
            messages = self.journal if admin else \
                [m for m in self.journal if m.get("qui") == qui]
            mon_solde = (self.credits.etat().get(qui, "illimite")
                        if self.credits else "illimite")
            self._send(200, json.dumps({"machines": machines,
                                        "messages": messages,
                                        "mon_solde": mon_solde}),
                       "application/json; charset=utf-8")
        elif chemin == "/admin":
            if not self._est_admin(qui):
                return self._send(403, "reserve aux administrateurs")
            self._send(200, PAGE_ADMIN)
        elif chemin == "/admin/soldes":
            if not self._est_admin(qui):
                return self._send(403, "reserve aux administrateurs")
            soldes = self.credits.etat() if self.credits else {}
            self._send(200, json.dumps(soldes),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "rien ici")

    def do_POST(self):
        qui = self._qui()
        if qui is None:
            return self._refuser_auth()
        u = urlparse(self.path)

        if u.path == "/admin/credit":
            if not self._est_admin(qui):
                return self._send(403, "reserve aux administrateurs")
            q = parse_qs(u.query)
            cible_compte = (q.get("qui") or [None])[0]
            try:
                delta = int((q.get("delta") or ["0"])[0])
            except ValueError:
                return self._send(400, "delta invalide")
            if cible_compte not in (self.identifiants or {}):
                return self._send(400, "compte inconnu : %s"
                                  % html.escape(str(cible_compte)))
            self.credits.ajuster(cible_compte, delta)
            print("  -> credits : %s ajuste de %+d par %s"
                  % (cible_compte, delta, qui))
            return self._send(200, json.dumps(self.credits.etat()),
                              "application/json; charset=utf-8")

        if u.path != "/print":
            return self._send(404, "rien ici")
        demandee = (parse_qs(u.query).get("cible") or [None])[0]
        if self._est_admin(qui) and demandee in self.printers:
            cible = demandee                    # choix explicite, respecte tel quel
        else:
            # priorite a une imprimante DISPONIBLE maintenant ; sinon la
            # premiere configuree (le message se met en file et affichera
            # clairement qu'elle est injoignable, plutot que de se perdre).
            dispo = [c for c, pr in self.printers.items() if pr.prete]
            cible = dispo[0] if dispo else next(iter(self.printers), None)
        p = self.printers.get(cible)
        if p is None:
            return self._send(400, "imprimante inconnue : %s" % html.escape(
                str(cible)))
        if self.credits is not None and not self.credits.depenser(qui):
            return self._send(429, "plus de credits -- demande a un "
                                   "administrateur d'en ajouter")
        n = int(self.headers.get("Content-Length", 0))
        texte = self.rfile.read(n).decode("utf-8", "replace")[:MAX_LEN].strip()
        if not texte:
            return self._send(400, "message vide")
        rang = p.submit(texte, qui)
        print("  -> %s (%s), en file (%d) : %s"
              % (cible, qui, rang, texte.replace("\n", " / ")))
        self._send(200, html.escape(texte))

    def log_message(self, *a):        # pas de log HTTP par requete
        pass


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--machines", default="xerox,dmp",
                    help="imprimantes a proposer, separees par des virgules : "
                         "xerox (via le Pico), dmp (Centronics). "
                         "Defaut : les deux — la page laisse choisir.")
    ap.add_argument("--port", help="sortie pico : port serie du Pico "
                                   "(detecte tout seul si omis)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--device", help="sortie centronics : peripherique "
                                    "(detecte /dev/usb/lp* si omis)")
    ap.add_argument("--encodage", default="cp437",
                    help="sortie centronics : jeu de caracteres de "
                         "l'imprimante (defaut cp437 ; repli en ASCII "
                         "translitere si l'encodage echoue)")
    ap.add_argument("--gras", choices=("aucun", "esc", "double"),
                    default="aucun",
                    help="matricielle : comment rendre *le balisage gras*. "
                         "aucun (defaut, les etoiles disparaissent), "
                         "esc (ESC E/F — ne marche PAS sur la DMP 3160), "
                         "double (ESC G/H, a tester). "
                         "Voir tools/dmp_probe.py.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 (defaut) ou 0.0.0.0 pour le reseau local")
    ap.add_argument("--http-port", type=int, default=8575)
    ap.add_argument("--credentials",
                    help="JSON par utilisateur (mot de passe, credits, admin) "
                         "pour exiger une authentification HTTP Basic. Voir "
                         "tools/credentials.json.example. Fichier a garder "
                         "HORS du depot git. OBLIGATOIRE avant d'exposer via "
                         "Tailscale Funnel ou tout reseau non prive.")
    a = ap.parse_args()

    Handler.identifiants = charger_identifiants(a.credentials)
    Handler.credits = Credits(Handler.identifiants) if Handler.identifiants else None

    fabriques = {
        "xerox": lambda: SortiePico(a.port, a.baud),
        "dmp": lambda: SortieCentronics(a.device, encodage=a.encodage,
                                       gras=a.gras),
    }
    demandees = [c.strip() for c in a.machines.split(",") if c.strip()]
    inconnues = [c for c in demandees if c not in fabriques]
    if inconnues:
        raise SystemExit("imprimante inconnue : %s (attendu : %s)"
                         % (", ".join(inconnues), ", ".join(fabriques)))
    if not demandees:
        raise SystemExit("aucune imprimante demandee")

    journal, verrou = [], threading.Lock()
    Handler.journal = journal
    Handler.printers = {}
    for cle in demandees:
        p = Printer(cle, fabriques[cle](), journal, verrou)
        Handler.printers[cle] = p
        p.start()

    # On NE sort PAS si une imprimante est absente : la page doit rester
    # accessible, c'est justement la qu'on en a besoin pour comprendre pourquoi.
    for cle, p in Handler.printers.items():
        ou = p.sortie.disponible()
        print("%-4s %-24s %s" % (cle, p.sortie.nom, ou or "ABSENTE"))
        if ou:
            continue
        if cle == "xerox":
            print("       - le Pico est-il sur le port USB de donnees "
                  "(celui du MILIEU sur un Zero W) ?")
            print("       - aucune session mpremote ne doit tenir le port "
                  "(exclusivite)")
        else:
            print("       - l'adaptateur USB<->Centronics est-il branche ?")
            print("       - /dev/usb/lp0 existe-t-il ? (`lsusb`, `dmesg | tail`, "
                  "`sudo modprobe usblp`)")
            print("       - l'utilisateur a-t-il le droit d'y ecrire "
                  "(groupe lp) ?")

    srv = ThreadingHTTPServer((a.host, a.http_port), Handler)
    print("\nMots doux : http://%s:%d/"
          % ("localhost" if a.host == "127.0.0.1" else a.host, a.http_port))
    if Handler.identifiants is None:
        print("/!\\ AUCUNE authentification (--credentials non fourni) -- "
              "ne JAMAIS exposer ainsi via Funnel ou tout reseau non prive.")
    else:
        admins = [u for u, c in Handler.identifiants.items() if c["admin"]]
        print("authentification : %d compte(s) charge(s) (%d admin : %s)"
              % (len(Handler.identifiants), len(admins), ", ".join(admins) or "-"))
        print("page admin : /admin")
    if a.host != "127.0.0.1":
        print("/!\\ ouvert sur le reseau (%s) — assure-toi que c'est voulu."
              % a.host)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nau revoir.")


if __name__ == "__main__":
    main()
