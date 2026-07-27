#!/usr/bin/env python3
"""
serve.py — petite interface web pour envoyer des mots doux a la Xerox 575.

Architecture :   navigateur  ->  ce serveur  ->  USB  ->  Pico (IFD-2)  ->  machine

Cote Pico, ifd2.run() doit tourner : il lit une ligne sur l'USB et l'imprime.
    mpremote fs cp pico/main.py :ifd2.py soft-reset exec "import ifd2; ifd2.run()"
puis presser ON LINE sur la machine quand run() le demande.

Puis, ici :
    ./tools/serve.py --port /dev/tty.usbmodem1101
    ./tools/serve.py --port /dev/ttyACM0 --host 0.0.0.0     # visible sur le reseau local

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

try:
    import serial
except ImportError:
    import os
    import sys as _sys
    _venv = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "venv", "bin", "python")
    _msg = ["pyserial manquant pour CET interpreteur :", "    %s" % _sys.executable,
            "", "Attention : `pip` et `python3` ne pointent pas forcement sur le",
            "meme Python. Installer avec l'interpreteur qui execute le script :",
            "    %s -m pip install pyserial" % _sys.executable]
    if os.path.exists(_venv):
        _msg += ["", "Ou plus simple, le venv du projet l'a deja :",
                 "    %s %s" % (_venv, os.path.abspath(__file__))]
    raise SystemExit("\n".join(_msg))

MAX_LEN = 500          # garde-fou : la machine tape ~1 caractere/seconde


def trouver_port():
    """Cherche le Pico sur le bus. Sur Mac les ports sont /dev/cu.usbmodemXXXX
    (numero variable selon la prise !), sur Linux /dev/ttyACM0."""
    import glob
    for motif in ("/dev/cu.usbmodem*", "/dev/ttyACM*", "/dev/cu.usbserial*"):
        trouves = sorted(glob.glob(motif))
        if trouves:
            return trouves[0]
    return None


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

    def __init__(self, port=None, baud=115200):
        super().__init__()
        self.q = queue.Queue()
        self.port, self.baud = port, baud
        self.fixe = port is not None       # port impose ou detecte a chaud
        self.log = []                      # derniers messages, pour la page
        self.ser = None
        self.etat = "imprimante : recherche..."

    def submit(self, text):
        self.q.put(text)
        return self.q.qsize()

    def _ouvrir(self):
        """Ouvre le port, en le redetectant si besoin (le numero change d'une
        prise a l'autre, et le Pico peut avoir ete rebranche)."""
        if self.ser is not None:
            return True
        port = self.port if self.fixe else trouver_port()
        if not port:
            self.etat = "imprimante absente (aucun Pico sur le bus USB)"
            return False
        self.ser = serial.Serial(port, self.baud, timeout=5)
        self.port = port
        time.sleep(0.5)
        self.etat = "imprimante prete (%s)" % port
        return True

    def veiller(self):
        """Tient l'etat a jour meme quand personne n'imprime, pour que la page
        dise la verite au lieu de rester sur un vieux message."""
        while True:
            if self.ser is None and not self.fixe and trouver_port() is None:
                self.etat = "imprimante absente (aucun Pico sur le bus USB)"
            time.sleep(5)

    def run(self):
        threading.Thread(target=self.veiller, daemon=True).start()
        while True:
            text = self.q.get()
            for essai in range(1, self.ESSAIS + 1):
                try:
                    if not self._ouvrir():
                        raise IOError("aucun Pico detecte")
                    for line in text.split('\n'):
                        self.ser.write((line + '\n').encode('utf-8', 'replace'))
                        self.ser.flush()
                        # le Pico repond "OK" quand la ligne est sur le papier
                        self._wait_ok()
                    self._note(text, "imprime")
                    break
                except Exception as e:                  # lien coupe, Pico absent
                    self._fermer()
                    self.etat = "imprimante injoignable : %s" % e
                    if essai == self.ESSAIS:
                        self._note(text, "ECHEC : %s" % e)
                    else:
                        time.sleep(self.ATTENTE)

    def _fermer(self):
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def _wait_ok(self, timeout=180):
        """Attend l'accuse du Pico. La machine tape lentement : large timeout."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.ser.readline()
            if not line:
                continue
            if line.strip() == b'OK':
                return True
        return False

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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="port serie du Pico (detecte tout seul "
                                   "si omis)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 (defaut) ou 0.0.0.0 pour le reseau local")
    ap.add_argument("--http-port", type=int, default=8575)
    a = ap.parse_args()

    # On NE sort PAS si le Pico est absent : la page doit rester accessible,
    # c'est justement la qu'on en a besoin pour comprendre pourquoi.
    detecte = a.port or trouver_port()
    if detecte:
        print("Pico : %s" % detecte)
    else:
        print("Pico : absent pour l'instant — la page fonctionne, l'impression")
        print("       reprendra des qu'il sera branche. Verifier que :")
        print("       - il est sur le port USB de donnees (celui du MILIEU sur un Zero W)")
        print("       - aucune session mpremote ne tient le port (exclusivite)")

    Handler.printer = Printer(a.port, a.baud)
    Handler.printer.start()

    srv = ThreadingHTTPServer((a.host, a.http_port), Handler)
    print("Mots doux : http://%s:%d/   (Pico sur %s)"
          % ("localhost" if a.host == "127.0.0.1" else a.host,
             a.http_port, a.port))
    if a.host != "127.0.0.1":
        print("/!\\ ouvert sur le reseau : aucune authentification, "
              "reseau de confiance uniquement.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nau revoir.")


if __name__ == "__main__":
    main()
