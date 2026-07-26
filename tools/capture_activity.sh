#!/usr/bin/env bash
# capture_activity.sh - Capture quelques secondes sur l'analyseur logique (fx2lafw)
# et compte les transitions par ligne => montre quelle(s) ligne(s) bougent.
#
# Cablage (cote sigrok) :
#   D0=orange(A)  D1=bleu(C)  D2=vert-blanc(F)  D3=vert(G)  D4=orange-blanc(H)
#   GND analyseur -> fil marron (D).   Jamais B ni E.
#
# Usage :  ./capture_activity.sh [duree_en_secondes]   (defaut 5)

set -e
DUR=${1:-5}
SR=250000                      # 250 kHz : large pour du 4800..9600 baud
SAMPLES=$(( SR * DUR ))
CSV="$HOME/xerox575/cap.csv"

echo "############################################################"
echo "#  Capture de ${DUR}s.  DES QUE 'Acquisition' demarre :"
echo "#    1) appuie sur le bouton ONLINE"
echo "#    2) tape plusieurs fois la meme touche (ex: e e e)"
echo "############################################################"
sleep 1

rm -f "$CSV"   # purge l'ancienne capture : si la nouvelle echoue, on le VOIT
ERR=$(sigrok-cli --driver fx2lafw --config samplerate=${SR} --samples ${SAMPLES} \
  --channels D0,D1,D2,D3,D4 -O csv -o "$CSV" 2>&1)

if [ ! -s "$CSV" ]; then
  echo
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "!! ERREUR : aucune donnee capturee."
  echo "!! L'analyseur logique n'est PAS detecte."
  echo "!! Message sigrok : $ERR"
  echo "!! -> Rebranche l'analyseur (bon port USB !), puis verifie :"
  echo "!!      sigrok-cli --scan   (doit montrer 'Saleae Logic')"
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  exit 1
fi

echo
echo "=== Activite par ligne (nb de transitions pendant la capture) ==="
awk -F, '
BEGIN{
  lbl[1]="D0  orange        (A)"
  lbl[2]="D1  bleu          (C)"
  lbl[3]="D2  vert-blanc    (F)"
  lbl[4]="D3  vert          (G)"
  lbl[5]="D4  orange-blanc  (H)"
}
!/^;/ && !/logic/ {
  if(started){ for(i=1;i<=NF;i++) if($i!=prev[i]) cnt[i]++ }
  else        { for(i=1;i<=NF;i++) first[i]=$i }
  for(i=1;i<=NF;i++) prev[i]=$i
  started=1; ncol=NF; rows++
}
END{
  printf "(%d echantillons analyses)\n", rows
  for(i=1;i<=ncol;i++){
    tag = (cnt[i]>0) ? "  <-- BOUGE" : ""
    printf "  %-28s repos=%s  transitions=%6d%s\n", lbl[i], first[i], cnt[i], tag
  }
}' "$CSV"

echo
echo "CSV brut conserve : $CSV"
