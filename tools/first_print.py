#!/usr/bin/env python3
"""
first_print.py - Premiere prise de controle : reset -> 0x01 -> init -> reset chariot.

Cablage (prouve au cuivre, 2026-07-23) :
    FT232 GND -> marron | RXD <- orange (TX machine) | TXD ->1k-> vert-blanc (RX machine)
    RTS ->1k-> bleu (DSR) | CTS <- vert (DTR)

/!\\ La machine peut BOUGER (chariot). Mains et outils hors du mecanisme.

Usage :
    ~/xerox575/venv/bin/python ~/xerox575/first_print.py
    ...first_print.py --extra "83 0C"     # octets test en plus (paires hex)
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbserial-A5069RR4")
    ap.add_argument("--baud", type=int, default=4800)
    ap.add_argument("--extra", default="", help="octets hex en plus apres le test, ex '83 0C'")
    a = ap.parse_args()

    ser = serial.Serial(a.port, a.baud, bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                        timeout=0.2)

    def send2(b1, b2, label):
        ser.write(bytes([b1, b2]))
        ser.flush()
        time.sleep(0.05)  # laisse la machine digerer (pulse DTR ~1ms trop bref a poller)
        print(f"  -> {b1:02X} {b2:02X}  ({label})")

    print(f"# {a.port} @ {a.baud} 8N1")

    # 1) UN reset via RTS, puis DSR maintenu HAUT
    ser.rts = True
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.rts = False
    time.sleep(0.1)
    ser.rts = True
    print("# reset envoye, attente du 0x01 (3 s max)...")
    t0 = time.time()
    got = b""
    while time.time() - t0 < 3:
        got += ser.read(8)
        if b"\x01" in got:
            break
    print(f"# recu : {got.hex(' ') if got else '(rien)'}")
    if b"\x01" not in got:
        print("# pas de 0x01 — la machine est peut-etre DEJA en ligne, on continue.")

    # 2) init
    for b1, b2, lab in [(0xA0, 0x00, "CLEAR"), (0xA1, 0x00, "START"),
                        (0xA4, 0x00, "ENQ"), (0xA2, 0x00, "STX/online")]:
        send2(b1, b2, lab)

    # 3) effet visible : reset position chariot
    print("# >>> REGARDE : chariot + LED ON LINE + clavier <<<")
    send2(0x82, 0x1F, "reset position chariot")

    # 4) octets additionnels eventuels
    if a.extra:
        xs = [int(x, 16) for x in a.extra.split()]
        for i in range(0, len(xs) - 1, 2):
            send2(xs[i], xs[i + 1], "extra")

    # 5) retour machine ?
    tail = ser.read(64)
    if tail:
        print(f"# retour machine : {tail.hex(' ')}")
    ser.rts = True  # DSR reste haut (hote toujours present)
    ser.close()
    print("# fini. La LED ? Le chariot a bouge ? Le clavier est muet (signe online) ?")


if __name__ == "__main__":
    main()
