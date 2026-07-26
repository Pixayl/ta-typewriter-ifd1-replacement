#!/usr/bin/env python3
"""
handshake.py - Handshake complet SE325 (tweetwronger) via un CH340 exposant RTS/CTS.

Sequence : reset via RTS -> attend 0x01 sur RX -> envoie l'init A0 A1 A4 A2 -> option char.

Cablage CH340 (a ajuster selon le mapping trouve) :
    CH340 GND  -> marron (D)
    CH340 TX   -> 1k -> ligne RxD machine (entree)
    CH340 RX   ->       ligne TxD machine (sortie, celle qui emet 0x01)
    CH340 RTS  -> 1k -> ligne "reset" machine
    CH340 CTS  <-       ligne "pret/busy" machine (optionnel)
    Jamais B (+12V) ni E (+42V).

Usage :
    ~/xerox575/venv/bin/python ~/xerox575/handshake.py --port /dev/cu.usbserial-11240
    ...handshake.py --char A          # imprime 'A' apres l'init (si table = ASCII... a verifier)
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

INIT = [bytes([0xA0, 0x00]), bytes([0xA1, 0x00]), bytes([0xA4, 0x00]), bytes([0xA2, 0x00])]


def read_for(ser, seconds):
    buf = b""
    t0 = time.time()
    while time.time() - t0 < seconds:
        b = ser.read(32)
        if b:
            buf += b
    return buf


def main():
    ap = argparse.ArgumentParser(description="Handshake SE325 via CH340 (RTS/CTS).")
    ap.add_argument("--port", default="/dev/cu.usbserial-11240")
    ap.add_argument("--baud", type=int, default=4800)
    ap.add_argument("--char", default="", help="octet(s) a envoyer apres l'init (texte)")
    ap.add_argument("--hex", default="", help="octets hex a envoyer apres l'init, ex '3D 00'")
    ap.add_argument("--repeat", type=int, default=20, help="nombre de cycles reset+ecoute (defaut 20)")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, bytesize=serial.EIGHTBITS,
                            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                            timeout=0.2)
    except serial.SerialException as e:
        sys.exit(f"Ouverture impossible de {args.port} : {e}")

    ser.dtr = True   # asserte DTR = "hote present" (pour la ligne DSR de la machine)
    print(f"# {args.port} @ {args.baud} 8N1  |  DTR asserte (= hote present)")
    print("# >>> PRESSE la touche ON LINE de la machine pendant que ca tourne <<<\n")

    for cycle in range(1, args.repeat + 1):
        # reset via RTS (pulse)
        ser.rts = True
        time.sleep(0.15)
        ser.reset_input_buffer()
        ser.rts = False
        time.sleep(0.1)
        ser.rts = True

        resp = read_for(ser, 1.5)
        mark = "   <<<<< 0x01 !!!" if b"\x01" in resp else ""
        print(f"[{cycle:2d}/{args.repeat}] reponse: {resp.hex(' ') if resp else '(rien)'}"
              f"   CTS={ser.cts} DSR={ser.dsr}{mark}")

        if resp:  # la machine a repondu -> on envoie l'init
            for cmd in INIT:
                ser.write(cmd)
                ser.flush()
                time.sleep(0.05)
            print(f"        -> init {b''.join(INIT).hex(' ')} envoyee")
        time.sleep(0.4)

    payload = b""
    if args.char:
        payload += args.char.encode("latin1")
    if args.hex:
        payload += bytes(int(x, 16) for x in args.hex.split())
    if payload:
        ser.write(payload)
        ser.flush()
        print(f"# octets test envoyes: {payload.hex(' ')}")

    ser.dtr = False
    ser.close()
    print("# termine. Regarde la LED ON LINE + le papier.")


if __name__ == "__main__":
    main()
