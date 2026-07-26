#!/usr/bin/env python3
"""
rts_toggle.py - Pulse la ligne RTS du CH340 pendant N secondes.

Sert a declencher le "reset" de la machine (methode tweetwronger) : a chaque
front, la machine doit repondre un 0x01 sur sa ligne TxD. On lance ca en tache
de fond pendant qu'on capture a l'analyseur, pour voir QUELLE ligne repond.

Cablage : CH340 GND -> marron (D) ; CH340 RTS -> 1k -> ligne candidate.

Usage :
    ~/xerox575/venv/bin/python ~/xerox575/rts_toggle.py --seconds 10
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")


def main():
    ap = argparse.ArgumentParser(description="Pulse RTS du CH340.")
    ap.add_argument("--port", default="/dev/cu.usbserial-11240")
    ap.add_argument("--baud", type=int, default=4800)
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--period", type=float, default=0.4, help="periode d'un cycle bas/haut (s)")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
    except serial.SerialException as e:
        sys.exit(f"Ouverture impossible de {args.port} : {e}")

    print(f"# Pulse RTS sur {args.port} pendant {args.seconds}s (periode {args.period}s)...")
    t0 = time.time()
    n = 0
    while time.time() - t0 < args.seconds:
        ser.rts = False
        time.sleep(args.period / 2)
        ser.rts = True
        time.sleep(args.period / 2)
        n += 1
    ser.rts = True
    ser.close()
    print(f"# fini ({n} impulsions RTS)")


if __name__ == "__main__":
    main()
