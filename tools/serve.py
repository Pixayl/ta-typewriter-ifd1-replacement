#!/usr/bin/env python3
"""
serve.py — petite interface web pour envoyer des mots doux, sur deux imprimantes.

DEUX SORTIES, une seule page web (file d'attente, journal et interface communs) :

  --backend pico        Xerox 575 via le Pico (IFD-2), protocole IFD1
      navigateur -> ce serveur -> USB -> Pico -> machine a ecrire
      Cote Pico, ifd2.run() doit tourner (deploye en main.py, voir
      pico/server_boot.py), et il faut presser ON LINE sur la machine.
      /!\ le port serie ne se partage pas : aucune session mpremote en cours.

  --backend centronics  Amstrad DMP 3160 sur adaptateur USB <-> Centronics
      navigateur -> ce serveur -> /dev/usblp0 -> matricielle
      Beaucoup plus simple : de l'ASCII brut, ni protocole a deux octets, ni
      accuse DTR, ni index de marguerite. Utile aussi pour tester toute la
      chaine (page, file, service) sans la Xerox ni le Pico.

Exemples :
    ./tools/serve.py                                   # Xerox, port detecte
    ./tools/serve.py --backend centronics              # DMP, /dev/usblp0 detecte
    ./tools/serve.py --backend centronics --sans-esc   # si le gras sort en charabia
    ./tools/serve.py --host 0.0.0.0                    # visible sur le reseau local

Le serveur n'ecoute que sur 127.0.0.1 par defaut : il n'y a ni authentification
ni limitation de debit, donc ne l'ouvrir au reseau que sur un reseau de confiance,
et jamais sur Internet.
"""
import argparse
import html
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
    USB <-> Centronics, qui se presente en classe imprimante : /dev/usblp0.

    Bien plus simple que la Xerox : ni protocole a deux octets, ni accuse DTR,
    ni index de marguerite — la matricielle avale de l'ASCII."""

    nom = "DMP 3160 (Centronics)"

    # Sequences ESC de la famille Epson, dont la DMP 3160 se reclame.
    # NON VERIFIE sur cette imprimante : si le gras sort en charabia, lancer
    # avec --sans-esc et le balisage sera simplement ignore.
    GRAS_ON, GRAS_OFF = b'\x1bE', b'\x1bF'

    def __init__(self, device=None, encodage="cp437", fin_ligne="\r\n",
                 fin_message="\n\n\n", esc=True):
        self.device = device
        self.encodage = encodage
        self.fin_ligne = fin_ligne
        self.fin_message = fin_message
        self.esc = esc
        self.f = None

    def disponible(self):
        if self.device:
            return self.device if os.path.exists(self.device) else None
        for motif in ("/dev/usblp*", "/dev/lp*"):
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
                          % (self.device or "/dev/usblp0"))
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
        sortie = bytearray()
        for ligne in texte.split('\n'):
            if self.esc:
                # meme balisage que la Xerox : *entoure d'etoiles* = gras
                for n, morceau in enumerate(ligne.split('*')):
                    if n % 2:
                        sortie += self.GRAS_ON + self._octets(morceau) + self.GRAS_OFF
                    else:
                        sortie += self._octets(morceau)
            else:
                sortie += self._octets(ligne.replace('*', ''))
            sortie += self._octets(self.fin_ligne)
        sortie += self._octets(self.fin_message)
        self.f.write(bytes(sortie))
        self.f.flush()

    def absente(self):
        return ("imprimante absente (%s introuvable — adaptateur branche ? "
                "module usblp charge ?)" % (self.device or "/dev/usblp0"))


# --------------------------------------------------------------- file d'attente
class Printer(threading.Thread):
    """Un seul fil parle au Pico : la liaison est sequentielle et lente, et deux
    messages entrelaces desynchroniseraient le protocole (paires d'octets).

    Le serveur web ne depend PAS de la presence du Pico : sans lui la page
    s'affiche quand meme et annonce l'imprimante absente. Sortir en erreur
    quand le Pico n'est pas branche rendrait la page inaccessible au moment
    precis ou on en a besoin pour diagnostiquer."""

    daemon = True
    ESSAIS = 3             # tentatives d'ouverture du port par message
    ATTENTE = 3            # secondes entre deux tentatives

    def __init__(self, sortie):
        super().__init__()
        self.q = queue.Queue()
        self.sortie = sortie
        self.log = []                      # derniers messages, pour la page
        self.etat = "imprimante : recherche..."

    def submit(self, text):
        self.q.put(text)
        return self.q.qsize()

    def _dire(self, msg):
        self.etat = msg

    def veiller(self):
        """Tient l'etat a jour meme quand personne n'imprime, pour que la page
        dise la verite au lieu de rester sur un vieux message."""
        while True:
            if self.sortie.disponible() is None:
                self.sortie.fermer()
                self.etat = self.sortie.absente()
            time.sleep(5)

    def run(self):
        threading.Thread(target=self.veiller, daemon=True).start()
        while True:
            text = self.q.get()
            for essai in range(1, self.ESSAIS + 1):
                try:
                    ou = self.sortie.ouvrir()
                    self.sortie.imprimer(text, self._dire)
                    self._note(text, "imprime")
                    self.etat = "%s prete (%s)" % (self.sortie.nom, ou)
                    break
                except Exception as e:                  # lien coupe, absente
                    self.sortie.fermer()
                    self.etat = "imprimante injoignable : %s" % e
                    if essai == self.ESSAIS:
                        self._note(text, "ECHEC : %s" % e)
                    else:
                        time.sleep(self.ATTENTE)

    def _note(self, text, etat):
        self.log.insert(0, {"quand": time.strftime("%H:%M:%S"),
                            "texte": text, "etat": etat})
        del self.log[20:]


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
  textarea { width: 100%%; min-height: 8rem; font: inherit; padding: .8rem;
             border: 1px solid currentColor; border-radius: 6px;
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
  #machine { font-size: .85rem; padding: .5rem .8rem; border-radius: 6px;
             margin-bottom: 1rem;
             border: 1px solid color-mix(in srgb, currentColor 25%%, transparent); }
  #machine.absente { border-style: dashed; opacity: .75; }
</style>
<h1>Mots doux</h1>
<p class="sub">Ça sort sur la Xerox 575, à la vitesse d'une machine à écrire.
Entourez un mot d'<code>*étoiles*</code> pour le mettre en gras.</p>
<div id="machine">état…</div>
<form id="f">
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
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  if (!t.value.trim()) return;
  b.disabled = true; b.textContent = 'Envoi…';
  await fetch('/print', {method: 'POST', body: t.value});
  t.value = ''; n.textContent = '0';
  b.disabled = false; b.textContent = 'Imprimer';
  rafraichir();
};
const mach = document.getElementById('machine');
async function rafraichir() {
  const r = await (await fetch('/journal')).json();
  mach.textContent = r.etat;
  mach.className = /absente|injoignable/.test(r.etat) ? 'absente' : '';
  j.innerHTML = r.messages.map(m =>
    `<li><span class="quand">${m.quand}</span>${m.texte.replace(/[<&]/g, c =>
      ({'<':'&lt;','&':'&amp;'}[c]))}<span class="etat">${m.etat}</span></li>`).join('');
}
rafraichir(); setInterval(rafraichir, 4000);
</script>
</html>"""


class Handler(BaseHTTPRequestHandler):
    printer = None

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE % {"max": MAX_LEN})
        elif self.path == "/journal":
            self._send(200, json.dumps({"etat": self.printer.etat,
                                        "messages": self.printer.log}),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "rien ici")

    def do_POST(self):
        if self.path != "/print":
            return self._send(404, "rien ici")
        n = int(self.headers.get("Content-Length", 0))
        texte = self.rfile.read(n).decode("utf-8", "replace")[:MAX_LEN].strip()
        if not texte:
            return self._send(400, "message vide")
        rang = self.printer.submit(texte)
        print("  -> en file (%d) : %s" % (rang, texte.replace("\n", " / ")))
        self._send(200, html.escape(texte))

    def log_message(self, *a):        # pas de log HTTP par requete
        pass


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("pico", "centronics"), default="pico",
                    help="pico = Xerox 575 via le Pico (defaut) ; "
                         "centronics = matricielle DMP 3160 sur port parallele")
    ap.add_argument("--port", help="sortie pico : port serie du Pico "
                                   "(detecte tout seul si omis)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--device", help="sortie centronics : peripherique "
                                    "(detecte /dev/usblp* si omis)")
    ap.add_argument("--encodage", default="cp437",
                    help="sortie centronics : jeu de caracteres de "
                         "l'imprimante (defaut cp437 ; repli en ASCII "
                         "translitere si l'encodage echoue)")
    ap.add_argument("--sans-esc", action="store_true",
                    help="sortie centronics : n'envoyer aucune sequence ESC "
                         "(a utiliser si le gras sort en charabia)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 (defaut) ou 0.0.0.0 pour le reseau local")
    ap.add_argument("--http-port", type=int, default=8575)
    a = ap.parse_args()

    if a.backend == "centronics":
        sortie = SortieCentronics(a.device, encodage=a.encodage,
                                  esc=not a.sans_esc)
    else:
        sortie = SortiePico(a.port, a.baud)

    # On NE sort PAS si l'imprimante est absente : la page doit rester
    # accessible, c'est justement la qu'on en a besoin pour comprendre pourquoi.
    detecte = sortie.disponible()
    if detecte:
        print("%s : %s" % (sortie.nom, detecte))
    else:
        print("%s : absente pour l'instant — la page fonctionne, l'impression"
              % sortie.nom)
        print("    reprendra des qu'elle sera branchee. Verifier que :")
        if a.backend == "pico":
            print("    - le Pico est sur le port USB de donnees "
                  "(celui du MILIEU sur un Zero W)")
            print("    - aucune session mpremote ne tient le port (exclusivite)")
        else:
            print("    - l'adaptateur USB<->Centronics est branche")
            print("    - /dev/usblp0 existe (`lsusb`, `dmesg | tail`, "
                  "`sudo modprobe usblp`)")
            print("    - l'utilisateur a le droit d'y ecrire (groupe lp)")

    Handler.printer = Printer(sortie)
    Handler.printer.start()

    srv = ThreadingHTTPServer((a.host, a.http_port), Handler)
    print("Mots doux : http://%s:%d/   (sortie : %s)"
          % ("localhost" if a.host == "127.0.0.1" else a.host,
             a.http_port, sortie.nom))
    if a.host != "127.0.0.1":
        print("/!\\ ouvert sur le reseau : aucune authentification, "
              "reseau de confiance uniquement.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nau revoir.")


if __name__ == "__main__":
    main()
