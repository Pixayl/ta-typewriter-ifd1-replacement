#!/usr/bin/env python3
"""
type_test.py - Premiere impression : init puis frappe des index de roue 1..N.

La machine va taper une ligne de caracteres (sa "pierre de Rosette") :
photographier le resultat pour construire NOTRE table index->caractere.

/!\\ PAPIER CHARGE. Machine ouverte = le chariot VA bouger. Mains a l'ecart.

Usage :
    ~/xerox575/venv/bin/python ~/xerox575/type_test.py               # index 1..30, force 25
    ...type_test.py --n 30 --force 35                                # plus fort si trop pale
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
    ap.add_argument("--n", type=int, default=30, help="nb d'index a frapper (1..N, defaut 30)")
    ap.add_argument("--force", type=int, default=25, help="force de frappe 0-63 (defaut 25)")
    a = ap.parse_args()

    ser = serial.Serial(a.port, a.baud, bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                        timeout=0.2)

    def wait_ready(timeout=3.0):
        """Attend que la machine soit prete (CTS = DTR machine), comme tweetwronger."""
        t0 = time.time()
        while not ser.cts:
            if time.time() - t0 > timeout:
                return False
            time.sleep(0.005)
        return True

    def send2(b1, b2, label=""):
        if not wait_ready():
            print(f"  !! machine pas prete (CTS bas) avant {b1:02X} {b2:02X} — on envoie quand meme")
        ser.write(bytes([b1, b2]))
        ser.flush()
        time.sleep(0.03)
        if label:
            print(f"  -> {b1:02X} {b2:02X}  ({label})")

    print(f"# {a.port} @ {a.baud} 8N1 — frappe des index 1..{a.n}, force {a.force}")

    # 1) reset DSR + attente 0x01 (si deja en ligne : pas grave)
    ser.rts = True
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.rts = False
    time.sleep(0.1)
    ser.rts = True
    t0 = time.time()
    got = b""
    while time.time() - t0 < 3:
        got += ser.read(8)
        if b"\x01" in got:
            break
    print(f"# poignee de main : {got.hex(' ') if got else '(rien — deja en ligne ?)'}")

    # 2) init
    for b1, b2, lab in [(0xA0, 0x00, "CLEAR"), (0xA1, 0x00, "START"),
                        (0xA4, 0x00, "ENQ"), (0xA2, 0x00, "STX/online")]:
        send2(b1, b2, lab)

    # 3) reset position (chariot+roue+ruban)
    send2(0x82, 0x0F, "reset position")

    # 4) LA ligne de Rosette : index 1..N, avance auto (bit 128)
    ctrl = 0x80 | max(0, min(63, a.force))
    print(f"# >>> FRAPPE ! octet de controle = {ctrl:02X} <<<")
    for idx in range(1, a.n + 1):
        send2(idx, ctrl)
        print(f"  index {idx:3d} envoye")

    # 5) retour eventuel
    tail = ser.read(64)
    if tail:
        print(f"# retour machine : {tail.hex(' ')}")
    ser.rts = True
    ser.close()
    print("# fini. Photographie la ligne imprimee !")


if __name__ == "__main__":
    main()
