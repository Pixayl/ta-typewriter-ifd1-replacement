#!/usr/bin/env python3
"""
send_from_pi.py - Cote Pi (ou PC) : envoie du texte au Pico (IFD-2) par USB serie.

Le Pico apparait comme /dev/ttyACM0 (Pi/Linux) ou /dev/cu.usbmodemXXXX (Mac).
Le Pico, lui, imprime chaque ligne recue sur la Xerox.

Usage :
    ./send_from_pi.py "Bonjour le monde"          # une ligne
    echo "salut" | ./send_from_pi.py -            # depuis un pipe (RSS, etc.)
    ./send_from_pi.py --port /dev/ttyACM0 "..."
"""
import argparse
import sys

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : pip install pyserial")

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/ttyACM0", help="port du Pico (defaut /dev/ttyACM0)")
ap.add_argument("--baud", type=int, default=115200, help="debit USB CDC (peu importe la valeur)")
ap.add_argument("text", help="texte a imprimer, ou '-' pour lire stdin")
a = ap.parse_args()

data = sys.stdin.read() if a.text == "-" else a.text
if not data.endswith("\n"):
    data += "\n"

with serial.Serial(a.port, a.baud, timeout=2) as s:
    s.write(data.encode("utf-8", errors="replace"))
    s.flush()
print(f"# envoye ({len(data)} car) au Pico sur {a.port}")
