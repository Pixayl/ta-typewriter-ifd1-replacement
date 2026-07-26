#!/usr/bin/env python3
"""
passive_listen.py - Ecoute passive du port DIN de la Xerox 575 (Triumph-Adler).

LECTURE SEULE : n'emet RIEN vers la machine.
A utiliser avec un adaptateur USB-TTL FT232 regle sur 5 V, cable ainsi :

    DIN D (masse)       ->  GND du FT232
    DIN <candidat TxD>  ->  RX  du FT232      (tester A, C, F, H tour a tour)

    /!\\ NE JAMAIS relier la broche B (+12,6 V) au FT232 : ca le detruirait.

Le protocole TA est BINAIRE (commandes de 2 octets), donc on affiche un dump
hexadecimal + ASCII avec les intervalles de temps, pas du texte brut.

Exemples :
    python3 passive_listen.py                          # /dev/ttyUSB0 a 4800 8N1
    python3 passive_listen.py --port /dev/ttyUSB0 --baud 4800
    python3 passive_listen.py --scan                   # essaie plusieurs vitesses
"""

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    sys.exit("pyserial manquant : sudo apt install python3-serial  "
             "(ou : pip3 install pyserial)")


def open_port(port, baud):
    """Ouvre le port en lecture seule, sans handshake ni flux de controle."""
    return serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.2,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False,
    )


def dump(port, baud):
    print(f"# Ecoute sur {port} a {baud} bauds 8N1 - Ctrl-C pour arreter.")
    print("# Tape sur le clavier de la machine (ou mets-la en mode interface/imprimante).")
    print("# Colonnes : heure | dt(ms) depuis l'octet precedent | HEX (dec) | ASCII\n")
    try:
        ser = open_port(port, baud)
    except serial.SerialException as e:
        sys.exit(f"Impossible d'ouvrir {port} : {e}")

    last = None
    try:
        while True:
            chunk = ser.read(64)
            now = time.time()
            for b in chunk:
                dt = "" if last is None else f"{(now - last) * 1000:7.1f}"
                ch = chr(b) if 32 <= b < 127 else "."
                print(f"{time.strftime('%H:%M:%S')} | {dt:>7} | 0x{b:02X} ({b:3d}) | {ch}")
                last = now
    except KeyboardInterrupt:
        print("\n# Arret.")
    finally:
        ser.close()


def scan(port):
    bauds = [4800, 9600, 2400, 1200, 19200, 300]
    print("# Mode SCAN. Pour chaque vitesse : appuie plusieurs fois sur la MEME touche.")
    print("# La bonne vitesse = beaucoup d'octets ET peu de valeurs distinctes,")
    print("# avec la meme sequence qui se repete a chaque appui.\n")
    for baud in bauds:
        input(f">>> Prepare-toi a taper la meme touche, puis [Entree] pour tester "
              f"{baud} bauds (6 s)...")
        try:
            ser = open_port(port, baud)
        except serial.SerialException as e:
            sys.exit(f"Impossible d'ouvrir {port} : {e}")
        ser.reset_input_buffer()
        end = time.time() + 6
        data = bytearray()
        while time.time() < end:
            data.extend(ser.read(128))
        ser.close()
        distinct = sorted(set(data))
        sample = " ".join(f"{b:02X}" for b in data[:24])
        print(f"  {baud:6d} bauds : {len(data):4d} octets, "
              f"{len(distinct):2d} valeurs distinctes | {sample}\n")
    print("# Relance ensuite en mode normal sur la vitesse retenue :")
    print("#   python3 passive_listen.py --baud <vitesse>")


def main():
    ap = argparse.ArgumentParser(description="Ecoute passive du port DIN Xerox 575.")
    ap.add_argument("--port", default="/dev/ttyUSB0", help="port serie (defaut /dev/ttyUSB0)")
    ap.add_argument("--baud", type=int, default=4800, help="vitesse (defaut 4800)")
    ap.add_argument("--scan", action="store_true", help="essaie plusieurs vitesses")
    args = ap.parse_args()

    if args.scan:
        scan(args.port)
    else:
        dump(args.port, args.baud)


if __name__ == "__main__":
    main()
