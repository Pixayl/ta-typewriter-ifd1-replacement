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
    messages entrelaces desynchroniseraient le protocole (paires d'octets)."""

    daemon = True

    def __init__(self, port, baud=115200):
        super().__init__()
        self.q = queue.Queue()
        self.port, self.baud = port, baud
        self.log = []                      # derniers messages, pour la page
        self.ser = None

    def submit(self, text):
        self.q.put(text)
        return self.q.qsize()

    def run(self):
        while True:
            text = self.q.get()
            try:
                if self.ser is None:
                    self.ser = serial.Serial(self.port, self.baud, timeout=5)
                    time.sleep(0.5)
                for line in text.split('\n'):
                    self.ser.write((line + '\n').encode('utf-8', 'replace'))
                    self.ser.flush()
                    # le Pico repond "OK" quand la ligne est sortie sur le papier
                    self._wait_ok()
                self._note(text, "imprime")
            except Exception as e:                      # lien coupe, Pico reboote
                self.ser = None
                self._note(text, "ECHEC : %s" % e)

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
</style>
<h1>Mots doux</h1>
<p class="sub">Ça sort sur la Xerox 575, à la vitesse d'une machine à écrire.
Entourez un mot d'<code>*étoiles*</code> pour le mettre en gras.</p>
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
async function rafraichir() {
  const r = await (await fetch('/journal')).json();
  j.innerHTML = r.map(m =>
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
            self._send(200, json.dumps(self.printer.log),
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

    if not a.port:
        a.port = trouver_port()
        if not a.port:
            raise SystemExit(
                "Aucun Pico trouve sur le bus USB.\n"
                "  - est-il branche ? (verifier le cable, essayer une autre prise)\n"
                "  - `mpremote devs` doit le lister\n"
                "  - et surtout : AUCUN autre programme ne doit tenir le port.\n"
                "    mpremote le garde en exclusivite — quitter toute session\n"
                "    `mpremote repl` ou `mpremote exec` avant de lancer serve.py.")
        print("Pico detecte sur %s" % a.port)

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
