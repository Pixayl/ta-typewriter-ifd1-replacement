#!/usr/bin/env bash
# Installe l'interface web "mots doux" en service au demarrage, sur le Pi.
# A lancer DEPUIS LE REPO, sur le Pi :   ./deploy/install-pi.sh
# Relancable sans dommage (idempotent).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=/etc/systemd/system/ifd2-web.service
USER_NAME="${SUDO_USER:-$USER}"

echo "== IFD-2 : installation du service web =="
echo "   repo        : $REPO"
echo "   utilisateur : $USER_NAME"

# --- pyserial ---------------------------------------------------------------
# Bookworm applique PEP 668 (« externally managed environment ») : `pip install`
# a l'echelle du systeme est refuse. Le paquet Debian est la bonne voie.
if ! python3 -c 'import serial' 2>/dev/null; then
    echo "-- installation de python3-serial"
    sudo apt-get update -qq
    sudo apt-get install -y python3-serial
else
    echo "-- pyserial deja present"
fi

# --- droits sur le port serie ----------------------------------------------
# dialout = port serie du Pico ; lp = port parallele de la matricielle.
for GRP in dialout lp; do
    if ! id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx "$GRP"; then
        echo "-- ajout de $USER_NAME au groupe $GRP"
        sudo usermod -aG "$GRP" "$USER_NAME"
        echo "   (prend effet a la prochaine session ; le service, lui, l'a deja)"
    else
        echo "-- $USER_NAME est deja dans $GRP"
    fi
done

# --- service ----------------------------------------------------------------
echo "-- ecriture de $UNIT"
sed -e "s|__REPO__|$REPO|g" -e "s|__USER__|$USER_NAME|g" \
    "$REPO/deploy/ifd2-web.service" | sudo tee "$UNIT" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now ifd2-web.service

echo
echo "== Termine =="
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "   page   : http://$(hostname).local:8575/   (ou http://${IP:-?}:8575/)"
echo "   etat   : systemctl status ifd2-web"
echo "   logs   : journalctl -u ifd2-web -f"
echo
echo "   /!\\ Pas d'authentification : reseau local de confiance uniquement."
echo "   /!\\ Le Pico doit etre branche sur le port USB du MILIEU (marque 'USB'),"
echo "       pas celui marque 'PWR', et demarrer sur son main.py (server_boot.py)."
