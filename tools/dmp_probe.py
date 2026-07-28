#!/usr/bin/env python3
r"""
dmp_probe.py — trouver quelles sequences de controle la matricielle honore.

Contexte : avec ESC E / ESC F (le gras "emphasized" d'Epson), la DMP 3160 n'a
RIEN imprime du tout — elle n'a pas ignore la sequence, elle a attendu une suite
qui ne venait pas et a avale la ligne. Plutot que de deviner, on essaie une
famille de sequences a la fois, chacune sur sa propre ligne etiquetee.

Usage :
    sudo ./tools/dmp_probe.py                    # tout, une ligne par essai
    sudo ./tools/dmp_probe.py --seulement gras   # une categorie
    sudo ./tools/dmp_probe.py --device /dev/usb/lp0

METHODE : chaque ligne s'imprime en DEUX temps — d'abord son etiquette en clair,
puis l'essai. Donc :
  - etiquette visible + essai visible  -> la sequence est comprise
  - etiquette visible + essai absent   -> la sequence a avale la suite (le cas
                                          d'ESC E ici)
  - etiquette absente                  -> l'essai precedent a tout casse ;
                                          eteindre/rallumer l'imprimante
Un `ESC @` (reinitialisation) est envoye entre chaque essai pour limiter la
contagion, mais si l'imprimante se bloque, un cycle secteur la remet d'aplomb.
"""
import argparse
import glob
import sys
import time

ESSAIS = [
    # (categorie, etiquette, avant, texte, apres)
    ("base", "texte simple", b'', b'ABCdef 123', b''),
    ("gras", "ESC E / ESC F  (Epson emphasized)", b'\x1bE', b'GRAS', b'\x1bF'),
    ("gras", "ESC G / ESC H  (Epson double-strike)", b'\x1bG', b'GRAS', b'\x1bH'),
    ("gras", "ESC ! 8        (Epson master select)", b'\x1b!\x08', b'GRAS', b'\x1b!\x00'),
    ("gras", "SO / DC4       (mode elargi)", b'\x0e', b'LARGE', b'\x14'),
    ("souligne", "ESC - 1 / ESC - 0", b'\x1b-\x01', b'SOULIGNE', b'\x1b-\x00'),
    ("pas", "ESC M  (elite 12 cpi)", b'\x1bM', b'elite 12 cpi', b'\x1bP'),
    ("pas", "SI     (condense)", b'\x0f', b'condense', b'\x12'),
    ("accents", "cp437 direct", b'', 'e a c: \x82 \x85 \x87'.encode('latin-1'), b''),
    ("accents", "ASCII translitere", b'', b'e a c: e a c', b''),
]


def trouver():
    for motif in ("/dev/usb/lp*", "/dev/usblp*", "/dev/lp*"):
        t = sorted(glob.glob(motif))
        if t:
            return t[0]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="peripherique (detecte si omis)")
    ap.add_argument("--seulement", help="une categorie : base, gras, souligne, "
                                        "pas, accents")
    ap.add_argument("--pause", type=float, default=0.4,
                    help="secondes entre deux essais (defaut 0,4)")
    a = ap.parse_args()

    dev = a.device or trouver()
    if not dev:
        raise SystemExit("aucune imprimante trouvee (/dev/usb/lp0 ?). "
                         "Verifier `dmesg | tail` et `lsusb`.")

    essais = [e for e in ESSAIS if not a.seulement or e[0] == a.seulement]
    if not essais:
        raise SystemExit("categorie inconnue : %s" % a.seulement)

    print("peripherique : %s" % dev)
    print("%d essai(s) — regarde le papier, pas cet ecran.\n" % len(essais))

    with open(dev, "wb", buffering=0) as f:
        f.write(b'\x1b@')                      # reinitialisation
        time.sleep(a.pause)
        f.write(b'--- dmp_probe ---\r\n')
        for n, (cat, etiquette, avant, texte, apres) in enumerate(essais, 1):
            # l'etiquette part SEULE et en clair : si elle sort mais pas
            # l'essai, on sait que la sequence a avale la suite.
            f.write(("%2d. %-38s " % (n, etiquette)).encode("ascii", "replace"))
            time.sleep(a.pause)
            f.write(avant + texte + apres + b'\r\n')
            time.sleep(a.pause)
            f.write(b'\x1b@')                  # remise a zero entre essais
            time.sleep(a.pause)
            print("  %2d. %s" % (n, etiquette))
        f.write(b'\r\n\r\n')

    print("\nLire le papier :")
    print("  etiquette + essai visibles  -> sequence comprise")
    print("  etiquette seule             -> la sequence a avale la suite")
    print("  etiquette manquante         -> essai precedent bloquant "
          "(cycle secteur)")
    print("\nPuis lancer serve.py avec le gras qui marche, par exemple :")
    print("  ./tools/serve.py --gras double")


if __name__ == "__main__":
    main()
