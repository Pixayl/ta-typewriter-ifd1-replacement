#!/usr/bin/env python3
"""
send_probe.py - Envoie la sequence "ONLINE" du protocole TA (Gabriele) en boucle,
pour trouver la ligne RxD de la machine et la reveiller.

A lancer avec le python du venv (pyserial) :
    ~/xerox575/venv/bin/python ~/xerox575/send_probe.py --port /dev/cu.XXXX

Montage : CH340 en emetteur.
    CH340 GND  -> fil marron (D)
    CH340 TX   -> 1 kOhm -> ligne candidate (Orange=A d'abord, puis F, C, H)
    Jamais B (+12V) ni E (+42V).

Pendant l'envoi : deplace le fil TX sur A, C, F, H tour a tour et regarde
la LED "Online" + le papier. Une reaction (LED qui s'allume, chariot qui bouge,
impression) = on a trouve RxD + a peu pres la bonne vitesse.

Exemples :
    ... send_probe.py --port /dev/cu.wchusbserial1420
    ... send_probe.py --port /dev/cu.wchusbserial1420 --baud 1200
    ... send_probe.py --port /dev/cu.wchusbserial1420 --offline
    ... send_probe.py --port /dev/cu.wchusbserial1420 --extra "82 1F 41"   # online + reset + 'A'
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

# Sequence d'init SE325 (tweetwronger) : clear, start, inquiry, STX(online)
ONL  = bytes([0xA0, 0x00,  0xA1, 0x00,  0xA4, 0x00,  0xA2, 0x00])
OFFL = bytes([0xA3, 0x00,  0xA0, 0x00])   # offline


def main():
    ap = argparse.ArgumentParser(description="Sonde d'envoi TA (trouver RxD / reveiller la machine).")
    ap.add_argument("--port", required=True, help="port du CH340, ex /dev/cu.wchusbserial1420")
    ap.add_argument("--baud", type=int, default=4800, help="vitesse (defaut 4800)")
    ap.add_argument("--offline", action="store_true", help="envoyer la sequence OFFLINE au lieu de ONLINE")
    ap.add_argument("--extra", default="", help="octets hex a ajouter, ex '82 1F 41'")
    ap.add_argument("--period", type=float, default=1.0, help="intervalle entre 2 envois (s)")
    ap.add_argument("--hold-low", action="store_true",
                    help="maintient TX au niveau BAS (break) pour mesurer la ligne au multimetre")
    args = ap.parse_args()

    try:
        extra = bytes(int(x, 16) for x in args.extra.split()) if args.extra else b""
    except ValueError:
        sys.exit("--extra : donne des octets hex separes par des espaces, ex '82 1F 41'")

    seq = OFFL if args.offline else ONL
    name = "OFFLINE" if args.offline else "ONLINE"
    payload = seq + extra

    try:
        ser = serial.Serial(args.port, args.baud, bytesize=serial.EIGHTBITS,
                            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                            timeout=0.2)
    except serial.SerialException as e:
        sys.exit(f"Ouverture impossible de {args.port} : {e}")

    if args.hold_low:
        ser.break_condition = True
        print(f"# {args.port} : TX MAINTENU BAS (break).")
        print("# Mesure la ligne candidate au multimetre (pointe noire sur MARRON) :")
        print("#   ~0-1 V  = pilotable  -> bonne candidate RxD")
        print("#   2-4 V   = 1k trop faible / c'est une sortie")
        print("# Ctrl-C pour relacher et passer a la couleur suivante.")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            ser.break_condition = False
            print("\n# relache")
        finally:
            ser.close()
        return

    print(f"# {args.port} @ {args.baud} bauds 8N1")
    print(f"# Envoi en boucle de la sequence {name} + extra : {payload.hex(' ')}")
    print("# Deplace le fil TX (via 1k) sur A, C, F, H et regarde la LED Online + le papier.")
    print("# Ctrl-C pour arreter.\n")
    n = 0
    try:
        while True:
            ser.write(payload)
            ser.flush()
            n += 1
            print(f"  [{n:4d}] -> {payload.hex(' ')}")
            time.sleep(args.period)
    except KeyboardInterrupt:
        print("\n# stop")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
