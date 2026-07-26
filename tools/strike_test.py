#!/usr/bin/env python3
"""
strike_test.py - Frappe la lettre 'e' N fois, pilotage TEMPS PUR (CTS ignore, car bloque a True).
But : mesurer le taux de reussite. Compte combien de 'e' s'impriment sur N.

  Beaucoup ratent quel que soit le delai -> la machine exige la synchro sur son
  pulse 'pret' 1 ms -> il faut un verrou materiel (Digispark/ATtiny facon tweetwronger).
  Tout s'imprime des que le delai est assez grand -> pilotage temps pur suffit.

Usage :
    ~/xerox575/venv/bin/python ~/xerox575/strike_test.py                 # 10 'e', gap 0.5s
    ...strike_test.py --n 10 --gap 1.0 --force 50 --posreset
"""
import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

WHEEL = '''.,-vlmjw²μf¥>¶+1234567890E£BFPSZV&YATL$R*C"D?NIU)W_=;:M'H(K/O!X§QJ%³G°¼¢½<Δ#txqΩ]@[ykphcgnrseaiduboz'''
IDX_E = WHEEL.index('e') + 1

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="/dev/cu.usbserial-A5069RR4")
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--gap", type=float, default=0.5)
ap.add_argument("--force", type=int, default=45)
ap.add_argument("--posreset", action="store_true", help="envoyer 82 0F (reset chariot) avant")
a = ap.parse_args()

s = serial.Serial(a.port, 4800, timeout=1)
s.rts = True

s.reset_input_buffer(); s.reset_output_buffer()
s.rts = False; s.rts = True
if not any(s.read(1) == b"\x01" for _ in range(10)):
    s.close(); sys.exit("# connect ECHEC — cycle secteur et relance.")
print("# connect OK")

for pair in [(0xA0, 0), (0xA1, 0), (0xA4, 0), (0xA2, 0)]:
    s.write(bytes(pair)); s.flush(); time.sleep(0.15)
time.sleep(1)
if a.posreset:
    s.write(bytes([0x82, 0x0F])); s.flush(); time.sleep(2.0)

ctrl = 0x80 | max(0, min(63, a.force))
print(f"# frappe 'e' (index {IDX_E}) x{a.n}, gap {a.gap}s, force {a.force}, posreset={a.posreset}")
for k in range(a.n):
    s.write(bytes([IDX_E, ctrl])); s.flush()
    print(f"  envoi {k+1}/{a.n}")
    time.sleep(a.gap)

s.close()
print(f"# fini. COMPTE combien de 'e' sont imprimes sur {a.n}.")
