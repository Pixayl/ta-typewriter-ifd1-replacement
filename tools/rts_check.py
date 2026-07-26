#!/usr/bin/env python3
"""
rts_check.py - Alterne RTS et DTR toutes les 3s, pour verifier au multimetre
que ces broches du FT232 bougent bien.

Usage : ~/xerox575/venv/bin/python ~/xerox575/rts_check.py [port]
Mesure : multimetre noire sur GND, rouge sur la broche RTS (puis DTR) du FT232.
La broche doit ALTERNER entre ~0 V et ~5 V en rythme avec l'affichage.
Ctrl-C pour arreter.
"""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-A5069RR4"
s = serial.Serial(port, 4800)
print(f"# {port} : RTS et DTR alternent toutes les 3 s.")
print("# Mesure la broche RTS (puis DTR) du FT232, ref GND -> elle doit basculer ~0V <-> ~5V.")
print("# Ctrl-C pour arreter.\n")
state = False
try:
    while True:
        state = not state
        s.rts = state
        s.dtr = state
        print(f"  RTS={state}  DTR={state}   <- mesure maintenant")
        time.sleep(3)
except KeyboardInterrupt:
    s.close()
    print("\n# stop")
