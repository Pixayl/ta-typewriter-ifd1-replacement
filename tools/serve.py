#!/usr/bin/env python3
r"""
serve.py — petite interface web pour envoyer des mots doux, sur deux imprimantes.

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
from collections import defaultdict, deque
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
    """Charge {utilisateur: mot_de_passe} depuis un JSON. Fichier VOLONTAIREMENT
    hors du depot (voir .gitignore) : jamais de mot de passe commite."""
    if not chemin or not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        creds = json.load(f)
    if not isinstance(creds, dict) or not creds:
        raise SystemExit("credentials : JSON attendu {\"ami\": \"mot de passe\", ...}")
    return creds


class LimiteDebit:
    """Fenetre glissante par utilisateur : proteger le papier/ruban d'un ami
    trop enthousiaste (ou d'un identifiant compromis), pas une securite forte."""

    def __init__(self, max_par_heure):
        self.max = max_par_heure
        self.horodatages = defaultdict(deque)
        self.verrou = threading.Lock()

    def autorise(self, qui):
        if not self.max:
            return True
        now = time.time()
        with self.verrou:
            q = self.horodatages[qui]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(now)
            return True


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
            for essai in range(1, self.ESSAIS + 1):
                try:
                    ou = self.sortie.ouvrir()
                    self.sortie.imprimer(text, self._dire)
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
<title>Mots doux — Xerox 575</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 16px/1.5 ui-serif, Georgia, serif; max-width: 34rem;
         margin: 4rem auto; padding: 0 1.5rem; }
  h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: .2rem; }
  p.sub { opacity: .65; margin-top: 0; font-size: .9rem; }
  textarea { width: 100%%; min-height: 8rem;
             font: 1em/1.4 ui-monospace, "SF Mono", "Cascadia Code",
                   Consolas, monospace;
             padding: .8rem; border: 1px solid currentColor; border-radius: 6px;
             background: transparent; color: inherit; box-sizing: border-box; }
  button { font: inherit; padding: .6rem 1.4rem; margin-top: .8rem;
           border-radius: 6px; border: 1px solid currentColor;
           background: transparent; color: inherit; cursor: pointer; }
  button:disabled { opacity: .4; cursor: wait; }
  .compte { float: right; font-size: .85rem; opacity: .6; }
  ul { list-style: none; padding: 0; margin-top: 2.5rem;
       border-top: 1px solid; border-color: color-mix(in srgb, currentColor 20%%, transparent); }
  li { padding: .6rem 0; font-size: .9rem;
       border-bottom: 1px solid color-mix(in srgb, currentColor 12%%, transparent); }
  li .quand { opacity: .5; margin-right: .6rem; font-variant-numeric: tabular-nums; }
  li .etat { float: right; opacity: .6; font-size: .8rem; }
  #machines { display: flex; flex-direction: column; gap: .5rem;
              margin-bottom: 1.2rem; }
  label.mach { display: flex; align-items: baseline; gap: .6rem;
               font-size: .9rem; padding: .55rem .8rem; border-radius: 6px;
               cursor: pointer;
               border: 1px solid color-mix(in srgb, currentColor 25%%, transparent); }
  label.mach:has(input:checked) { border-color: currentColor;
               background: color-mix(in srgb, currentColor 7%%, transparent); }
  label.mach.absente { border-style: dashed; opacity: .6; }
  label.mach .nom { font-weight: 600; }
  label.mach .etat { font-size: .8rem; opacity: .7; margin-left: auto;
                     text-align: right; }
  li .machine { opacity: .45; font-size: .75rem; margin-left: .5rem; }
</style>
<h1>Mots doux</h1>
<p class="sub">Choisissez l'imprimante, écrivez, et ça sort sur le papier.
Entourez un mot d'<code>*étoiles*</code> pour le mettre en gras.</p>
<form id="f">
  <div id="machines">%(machines)s</div>
  <textarea id="t" maxlength="%(max)d" placeholder="Écris quelque chose de gentil…"
            autofocus></textarea>
  <span class="compte"><span id="n">0</span>/%(max)d</span>
  <button id="b">Imprimer</button>
</form>
<ul id="journal"></ul>
<script>
const t = document.getElementById('t'), n = document.getElementById('n'),
      b = document.getElementById('b'), j = document.getElementById('journal');
t.oninput = () => n.textContent = t.value.length;
const cible = () => document.querySelector('input[name=cible]:checked').value;
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
  j.innerHTML = r.messages.map(m =>
    `<li><span class="quand">${m.quand}</span>${echapper(m.texte)}` +
    `<span class="machine">${echapper(m.machine)} — ${echapper(m.qui || '?')}</span>` +
    `<span class="etat">${echapper(m.etat)}</span></li>`).join('');
}
rafraichir(); setInterval(rafraichir, 4000);
</script>
</html>"""


def bloc_machines(printers):
    """Boutons radio des imprimantes, rendus cote serveur. Leur etat est ensuite
    rafraichi en place par la page, sans la recharger."""
    out = []
    for n, (cle, p) in enumerate(printers.items()):
        out.append(
            '  <label class="mach" data-cle="%s">\n'
            '    <input type="radio" name="cible" value="%s"%s>\n'
            '    <span class="nom">%s</span>\n'
            '    <span class="etat">…</span>\n'
            '  </label>' % (cle, cle, " checked" if n == 0 else "",
                            html.escape(p.sortie.nom)))
    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    printers = {}          # cle -> Printer
    journal = []           # liste partagee
    identifiants = None     # {utilisateur: mot_de_passe}, ou None = pas d'auth
    debit = None             # LimiteDebit, ou None = pas de limite

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
        attendu = self.identifiants.get(u)
        if attendu is not None and hmac.compare_digest(p, attendu):
            return u
        return None

    def _refuser_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Mots doux"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self._qui() is None:
            return self._refuser_auth()
        chemin = urlparse(self.path).path
        if chemin == "/":
            self._send(200, PAGE % {"max": MAX_LEN,
                                    "machines": bloc_machines(self.printers)})
        elif chemin == "/journal":
            machines = [{"cle": cle, "nom": p.sortie.nom, "etat": p.etat,
                         "prete": p.prete, "file": p.q.qsize()}
                        for cle, p in self.printers.items()]
            self._send(200, json.dumps({"machines": machines,
                                        "messages": self.journal}),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "rien ici")

    def do_POST(self):
        qui = self._qui()
        if qui is None:
            return self._refuser_auth()
        u = urlparse(self.path)
        if u.path != "/print":
            return self._send(404, "rien ici")
        cible = (parse_qs(u.query).get("cible") or [None])[0]
        if cible is None:                       # compatibilite : premiere machine
            cible = next(iter(self.printers), None)
        p = self.printers.get(cible)
        if p is None:
            return self._send(400, "imprimante inconnue : %s" % html.escape(
                str(cible)))
        if self.debit is not None and not self.debit.autorise(qui):
            return self._send(429, "trop de messages -- attends un peu avant "
                                   "d'en renvoyer un autre")
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
                    help="JSON {\"ami\": \"mot de passe\", ...} pour exiger une "
                         "authentification HTTP Basic. Fichier a garder HORS du "
                         "depot git. OBLIGATOIRE avant d'exposer via Tailscale "
                         "Funnel ou tout reseau non prive.")
    ap.add_argument("--limite-horaire", type=int, default=10,
                    help="messages max par utilisateur et par heure "
                         "(defaut 10 ; 0 = pas de limite)")
    a = ap.parse_args()

    Handler.identifiants = charger_identifiants(a.credentials)
    Handler.debit = LimiteDebit(a.limite_horaire)

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
        print("authentification : %d identifiant(s) charge(s), limite %s/h"
              % (len(Handler.identifiants), a.limite_horaire or "illimitee"))
    if a.host != "127.0.0.1":
        print("/!\\ ouvert sur le reseau (%s) — assure-toi que c'est voulu."
              % a.host)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nau revoir.")


if __name__ == "__main__":
    main()
