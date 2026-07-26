#!/usr/bin/env python3
"""
tw.py - Bibliotheque + outils de la Xerox 575 (TA SE, protocole IFD1/SE325).

Regroupe le pilote fiable (issu de rosette.py v2) et des sous-commandes :
    connect  : juste la poignee de main (verifie que tout repond)
    idx      : frappe un ou des index de roue precis (calibration table)
    text     : imprime une chaine de texte via la table roue
    rosette  : la ligne de reference 1..100

Cablage prouve : FT232 RXD<-orange | TXD->1k->vert-blanc | RTS->1k->bleu(DSR)
                 CTS<-vert(DTR) | GND->marron.  Machine : cycle secteur avant campagne.

Exemples :
    ~/xerox575/venv/bin/python ~/xerox575/tw.py connect
    ...tw.py idx 47              # frappe l'index 47 (dis-moi quel caractere sort)
    ...tw.py idx 44 45 46 47 48  # une petite serie, un par ligne
    ...tw.py text "bonjour"
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

# --- Roue Prestige Cubic FR (Xerox 575, ref 3R96686), relevee par calibration 2026-07-23 ---
# Ordre de base = SE325 ; substitutions FR observees (index 1-based) appliquees ensuite.
WHEEL = list('''.,-vlmjw²μf¥>¶+1234567890E£BFPSZV&YATL$R*C"D?NIU)W_=;:M'H(K/O!X§QJ%³G°¼¢½<Δ#txqΩ]@[ykphcgnrseaiduboz''')
_FR_SUBST = {12: '^', 13: 'è', 14: 'é', 72: 'ì', 74: '¨', 75: '◊',
             80: 'ç', 81: 'ù', 82: 'ò', 83: 'à'}   # ^ et ¨ = touches mortes (accent sans avance)
for _i, _c in _FR_SUBST.items():
    WHEEL[_i - 1] = _c


class TW:
    def __init__(self, port="/dev/cu.usbserial-A5069RR4", baud=4800, gap=0.4):
        self.ser = serial.Serial(port, baud, timeout=1)
        self.ser.rts = True
        self.gap = gap
        self.col = 0   # position chariot en pas (12 pas/caractere) -> retour a la ligne exact

    def connect(self, attempts=15):
        """Robuste : REPETE l'impulsion de reset jusqu'au 0x01 (la machine ne
        repond pas toujours a la 1ere). Chaque tentative = pulse + ecoute ~1 s."""
        print(">>> PRESSE la touche ON LINE de la machine MAINTENANT (fiabilise la connexion) <<<")
        self.ser.reset_input_buffer(); self.ser.reset_output_buffer()
        for attempt in range(attempts):
            self.ser.rts = False
            self.ser.rts = True           # impulsion instantanee
            t0 = time.time(); buf = b""
            while time.time() - t0 < 1.0:
                b = self.ser.read(1)
                if b:
                    buf += b
                    if b"\x01" in buf:
                        print(f"# connecte (0x01) a la tentative {attempt+1}")
                        return True
            print(f"# reset {attempt+1}/{attempts} (recu {buf.hex() if buf else 'rien'})")
        return False

    def send(self, *pairs):
        # TEMPS PUR (recette prouvee "Bonjour le monde"). CTS trop capricieux
        # (occupe retarde/variable) pour un cadencement serre -> on ne l'utilise pas.
        # Le gap doit couvrir le pire cas de rotation (~0,9 s mesure).
        for b1, b2 in pairs:
            self.ser.write(bytes([b1, b2])); self.ser.flush()
            time.sleep(self.gap)

    def online(self):
        self.send((0xA0, 0x00), (0xA1, 0x00), (0xA4, 0x00), (0xA2, 0x00))
        time.sleep(1)
        self.send((0x82, 0x0F))   # reset position
        time.sleep(2)             # laisse le chariot se caler (indispensable)

    def char_idx(self, idx, force=40, move=True):
        ctrl = (0x80 if move else 0) | max(0, min(63, force))
        self.send((idx, ctrl))
        if move:
            self.col += 1

    def space(self, w=None):
        # Espace = frappe a blanc (index 1, force 0) + avance. (0x83 va a gauche : evite.)
        self.send((0x01, 0x80))
        self.col += 1

    def crlf(self):
        # Retour a la ligne EXACT : on revient de la distance reellement parcourue
        # (self.col * 12), pas d'une valeur fixe -> fiable quelle que soit la longueur.
        if self.col > 0:
            d = self.col * 12
            self.send((0xE0 | ((d >> 8) & 0x0F), d & 0xFF))   # retour chariot (gauche)
            time.sleep(0.5)
        self.send((0xD0, 0x14))                                # interligne
        time.sleep(0.5)
        self.col = 0


def ensure_online(tw):
    if not tw.connect():
        sys.exit("# PAS de 0x01 -> cycle secteur machine et relance.")
    print("# connecte (0x01).")
    time.sleep(0.6)      # laisse la machine se stabiliser apres le 0x01 (sinon l'init est perdue)
    tw.online()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbserial-A5069RR4")
    ap.add_argument("--gap", type=float, default=0.4)
    ap.add_argument("--force", type=int, default=40)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("connect")
    p_idx = sub.add_parser("idx"); p_idx.add_argument("indices", type=int, nargs="+")
    p_txt = sub.add_parser("text"); p_txt.add_argument("string")
    sub.add_parser("rosette")
    p_cal = sub.add_parser("cal")   # calibration : imprime index A..B espaces, une ligne
    p_cal.add_argument("start", type=int)
    p_cal.add_argument("end", type=int)
    sub.add_parser("live")          # mode interactif : tape des lignes, elles s'impriment
    sub.add_parser("listen")        # ecoute : affiche les octets emis par le clavier machine
    a = ap.parse_args()

    tw = TW(a.port, gap=a.gap)

    if a.cmd == "connect":
        print("OK, la machine repond." if tw.connect() else "Pas de reponse (cycle secteur ?).")
        return

    ensure_online(tw)
    idx_of = {c: n + 1 for n, c in enumerate(WHEEL)}

    def print_line(text):
        """Imprime : lettres/chiffres/accents via la table, ' ' = espace, '\\n' = retour ligne."""
        for c in text:
            if c == "\n":
                tw.crlf()
            elif c == " ":
                tw.space()
            elif c in idx_of:
                tw.char_idx(idx_of[c], force=a.force)
            else:
                print(f"  (caractere {c!r} absent de la roue — ignore)")

    if a.cmd == "idx":
        for i in a.indices:
            tw.char_idx(i, force=a.force)
            se = WHEEL[i-1] if 1 <= i <= len(WHEEL) else "?"
            print(f"  index {i:3d} frappe (roue = {se!r})")
            time.sleep(0.3)
            tw.crlf()
    elif a.cmd == "text":
        print_line(a.string.replace("\\n", "\n"))   # \n litteral en ligne de commande -> vrai retour
    elif a.cmd == "live":
        print("# mode LIVE : tape une ligne + Entree -> elle s'imprime. Ligne vide = saut. Ctrl-D pour quitter.")
        while True:
            try:
                line = input("tw> ")
            except EOFError:
                print()
                break
            print_line(line)
            tw.crlf()
    elif a.cmd == "listen":
        print("# ECOUTE clavier : tape sur le clavier de la machine (essaie 'aaa', des touches variees,")
        print("#   et les boutons ON LINE/OFF LINE). Les octets recus s'affichent. Ctrl-C pour arreter.")
        tw.ser.reset_input_buffer()
        try:
            while True:
                b = tw.ser.read(1)
                if b:
                    v = b[0]
                    vis = chr(v) if 32 <= v < 127 else "."
                    print(f"  recu 0x{v:02X} ({v:3d})  {vis}")
        except KeyboardInterrupt:
            print("\n# stop")
    elif a.cmd == "rosette":
        for i in range(1, 101):
            tw.char_idx(i, force=a.force)
            if i % 20 == 0 and i < 100:
                tw.crlf()
    elif a.cmd == "cal":
        # frappe chaque index de start..end, separes d'un espace, sur UNE ligne.
        # Position n (1re, 2e...) sur le papier = index start + (n-1).
        print(f"# calibration index {a.start}..{a.end} : la 1re case = index {a.start}, etc.")
        for i in range(a.start, a.end + 1):
            tw.char_idx(i, force=a.force)
            tw.space()

    tw.ser.close()
    print("# fini.")


if __name__ == "__main__":
    main()
