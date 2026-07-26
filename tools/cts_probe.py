#!/usr/bin/env python3
"""
cts_probe.py - Sonde le comportement de CTS (= DTR machine) pendant une frappe.

Objectif : voir si/quand CTS passe "occupe" apres l'envoi d'un caractere,
et combien de temps, pour regler correctement le handshake (au lieu de deviner).

Frappe 3x la lettre 'e', en echantillonnant CTS toutes les ~1 ms, et affiche
toutes les transitions horodatees.

Usage : ~/xerox575/venv/bin/python ~/xerox575/cts_probe.py
"""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

WHEEL = '''.,-vlmjw²μf¥>¶+1234567890E£BFPSZV&YATL$R*C"D?NIU)W_=;:M'H(K/O!X§QJ%³G°¼¢½<Δ#txqΩ]@[ykphcgnrseaiduboz'''
IDX_E = WHEEL.index('e') + 1
CTRL = 0x80 | 40  # frappe + auto-avance, force 40

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-A5069RR4"
s = serial.Serial(port, 4800, timeout=1)
s.rts = True

# connexion
s.reset_input_buffer(); s.reset_output_buffer()
s.rts = False; s.rts = True
ok = False
for _ in range(10):
    if s.read(1) == b"\x01":
        ok = True; break
print(f"# connect : {'OK' if ok else 'ECHEC (cycle secteur ?)'}")
if not ok:
    s.close(); sys.exit(1)

# online
for pair in [(0xA0, 0), (0xA1, 0), (0xA4, 0), (0xA2, 0)]:
    t0 = time.time()
    while not s.cts and time.time() - t0 < 2:
        time.sleep(0.005)
    s.write(bytes(pair)); s.flush(); time.sleep(0.15)
time.sleep(1)
s.write(bytes([0x82, 0x0F])); s.flush()
time.sleep(1.5)   # laisse le chariot se caler

print(f"# frappe 'e' (index {IDX_E}) x3, echantillonnage CTS a ~1 ms\n")

for k in range(3):
    print(f"--- frappe {k+1} : CTS avant = {s.cts} ---")
    s.write(bytes([IDX_E, CTRL])); s.flush()
    t0 = time.time()
    last = s.cts
    trans = [(0.0, last)]
    while time.time() - t0 < 1.2:
        c = s.cts
        if c != last:
            trans.append((time.time() - t0, c))
            last = c
        time.sleep(0.001)
    if len(trans) == 1:
        print(f"    CTS n'a PAS bouge (reste {trans[0][1]}) pendant 1.2 s")
    else:
        for t, c in trans:
            print(f"    t={t*1000:7.1f} ms  CTS -> {c}")
    print()

s.close()
print("# fini.")
