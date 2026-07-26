#!/usr/bin/env bash
# find_txd.sh - Capture l'allumage de la machine, puis decode l'UART sur chaque
# ligne a plusieurs vitesses pour identifier TxD (la ligne qui emet un octet propre).
#
# Cablage analyseur : D0=orange(A) D1=bleu(C) D2=vert-blanc(F) D3=vert(G) D4=orange-blanc(H)
#                     GND -> marron (D).  Jamais B/E.
#
# Usage :  ./find_txd.sh [duree_s]        (defaut 12)

SR=250000
DUR="${1:-12}"
SAMPLES=$(( SR * DUR ))
SR_FILE="$HOME/xerox575/poweron.sr"
BAUDS="4800 9600 2400 1200 19200 300 600"

name_of() {
  case "$1" in
    D0) echo "orange (A)";;
    D1) echo "bleu (C)";;
    D2) echo "vert-blanc (F)";;
    D3) echo "vert (G)";;
    D4) echo "orange-blanc (H)";;
  esac
}

echo "############################################################"
echo "#  Capture ${DUR}s.  DES QUE ca demarre :"
echo "#    eteins la machine, attends 2 s, RALLUME-la (repete 1-2x)."
echo "############################################################"
sleep 1

sigrok-cli --driver fx2lafw --config samplerate=${SR} --samples ${SAMPLES} \
  --channels D0,D1,D2,D3,D4 -o "$SR_FILE" 2>/dev/null

echo
echo "Capture faite : $SR_FILE"
echo "Decodage (une ligne 'propre' avec peu d'octets, souvent 01, = TxD + bonne vitesse) :"
echo

for BAUD in $BAUDS; do
  echo "==================== ${BAUD} baud ===================="
  for CH in D0 D1 D2 D3 D4; do
    OUT=$(sigrok-cli -i "$SR_FILE" -P uart:baudrate=${BAUD}:rx=${CH}:format=hex \
          -A uart=rx-data 2>/dev/null | sed 's/^uart-1: //')
    N=$(printf '%s\n' "$OUT" | grep -cE '^[0-9A-Fa-f]{2}$')
    BYTES=$(printf '%s' "$OUT" | tr '\n' ' ' | cut -c1-70)
    printf "  %-3s %-16s : %4s octets | %s\n" "$CH" "$(name_of $CH)" "$N" "$BYTES"
  done
  echo
done

echo "Astuce : le CSV/sr brut est garde ($SR_FILE) ; on pourra re-decoder autrement au besoin."
