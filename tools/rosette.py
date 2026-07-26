#!/usr/bin/env python3
"""
rosette.py v2 - Ligne de Rosette, implementation FIDELE a tweetwronger (typecontrol.py).

Differences cles vs v1 (qui echouait) :
  - reset RTS INSTANTANE (rts=False; rts=True, sans sleep), UNE impulsion
  - ecoute patiente : jusqu'a 10 lectures bloquantes de 1 s, octets parasites jetes
  - envoi avec handshake CTS 3 phases PAR OCTET (pret -> ecrit -> occupe -> pret)
  - REGLE D'OR conservee : pas de 0x01 = pas d'impression

Usage :
    ~/xerox575/venv/bin/python ~/xerox575/rosette.py
    ...rosette.py --force 40 --start 1 --end 30
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial manquant : utilise ~/xerox575/venv/bin/python")

WHEEL = '''.,-vlmjw²μf¥>¶+1234567890E£BFPSZV&YATL$R*C"D?NIU)W_=;:M'H(K/O!X§QJ%³G°¼¢½<Δ#txqΩ]@[ykphcgnrseaiduboz'''


class TW:
    def __init__(self, portname, baud, bytegap=0.12):
        self.ser = serial.Serial(portname, baud, timeout=1)  # lectures bloquantes 1 s, comme eux
        self.ser.rts = True
        self.errors = 0
        self.bytegap = bytegap

    def _wait_cts(self, want, nudge=False, label=""):
        """Attend cts==want (5 ms de pas, 3 s max, pichenette RTS optionnelle comme tweetwronger)."""
        n = 600
        while self.ser.cts != want:
            time.sleep(0.005)
            n -= 1
            if n < 0:
                self.errors += 1
                print(f"  !! timeout CTS ({label}) — on continue ({self.errors} erreurs)")
                if self.errors >= 5:
                    raise RuntimeError("Trop de timeouts CTS : la machine ne suit pas. STOP propre.")
                return False
            if nudge:
                self.ser.rts = False
                self.ser.rts = True
        return True

    def send(self, data):
        """Envoi octet par octet. On attend seulement que la machine soit PRETE
        (CTS haut) puis on ajoute un delai fixe : le pulse 'occupe' de ~1 ms est
        trop bref pour etre vu en polling, on ne le guette donc PAS."""
        for byte in bytes(data):
            self._wait_cts(True, label="pret avant octet")
            self.ser.write(bytes([byte]))
            self.ser.flush()
            time.sleep(self.bytegap)   # laisse la mecanique digerer (regle par --gap)

    def connect(self):
        """Fidele a TWconnect : buffers, UNE impulsion instantanee, ecoute patiente."""
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.ser.rts = False
        self.ser.rts = True          # impulsion instantanee, sans sleep
        for t in range(10):          # 10 lectures bloquantes de 1 s
            b = self.ser.read(1)
            if b == b"\x01":
                print(f"# 0x01 recu (lecture {t + 1}) — machine connectee !")
                return True
            print(f"# attente... ({t + 1}/10, recu: {b.hex() if b else 'rien'})")
        return False

    def init_online(self):
        for pair in ([0xA0, 0x00], [0xA1, 0x00], [0xA4, 0x00], [0xA2, 0x00]):
            self.send(pair)
        time.sleep(1)                # comme tweetwronger
        self.send([0x82, 0x0F])      # posreset chariot+roue+ruban
        print("# init envoyee (CLEAR/START/ENQ/STX + posreset)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbserial-A5069RR4")
    ap.add_argument("--baud", type=int, default=4800)
    ap.add_argument("--force", type=int, default=40)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=100)
    ap.add_argument("--per-line", type=int, default=20, dest="per_line")
    ap.add_argument("--attend-boot", action="store_true", dest="attend_boot",
                    help="ouvre le port (hote present), attend que TU redemarres la machine, puis connecte")
    ap.add_argument("--gap", type=float, default=0.12,
                    help="delai fixe apres chaque octet (s) — augmente si la machine cale (defaut 0.12)")
    a = ap.parse_args()

    tw = TW(a.port, a.baud, bytegap=a.gap)
    print(f"# Rosette {a.start}..{a.end}, force {a.force} — implementation fidele tweetwronger")

    if a.attend_boot:
        print("# Port ouvert, ligne DSR tenue a l'etat 'hote present'.")
        input("# >>> CYCLE SECTEUR la machine MAINTENANT, attends la fin de son init, puis [Entree] <<< ")
        time.sleep(2)

    if not tw.connect():
        tw.ser.close()
        sys.exit("# PAS de 0x01 -> ABANDON (regle d'or). Cycle secteur machine et relance.")

    tw.init_online()

    ctrl = 0x80 | max(0, min(63, a.force))
    count = 0
    try:
        for idx in range(a.start, a.end + 1):
            tw.send([idx, ctrl])
            ch = WHEEL[idx - 1] if idx - 1 < len(WHEEL) else "?"
            print(f"  idx {idx:3d} frappe (SE325 dirait {ch!r})")
            count += 1
            if count >= a.per_line and idx < a.end:
                dist = a.per_line * 12
                tw.send([0xE0 | ((dist >> 8) & 0x0F), dist & 0xFF])   # retour chariot
                tw.send([0xD0, 0x14])                                  # interligne
                print("  -- nouvelle ligne --")
                count = 0
    except (KeyboardInterrupt, RuntimeError) as e:
        print(f"\n# arret : {e}")
    tw.ser.close()
    print("# fini — photographie le resultat !")


if __name__ == "__main__":
    main()
