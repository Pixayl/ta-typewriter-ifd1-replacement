# Serveur d'impression — Pi Zero W (installation sans écran)

Chaîne complète visée : **navigateur → Pi Zero W → USB → Pico (IFD-2) → Xerox 575.**

Le Pi ne fait que le réseau et la page web ; c'est le Pico qui tient le protocole temps réel (le contrôle de flux repose sur un accusé DTR de ~1 ms, hors de portée d'un Linux non temps réel — c'est tout le sujet du journal).

## 0. À vérifier avant de commencer

- **Un adaptateur micro-USB OTG → USB-A.** C'est le point qui manque le plus souvent : le Pi Zero W n'a que deux prises micro-USB, et pour y brancher le Pico il faut passer en hôte USB. Sans cet adaptateur, rien ne se connecte.
- **Le port du milieu**, marqué `USB`, est le seul qui porte les données. Celui du bord, marqué `PWR`, n'alimente que le Pi.
- **Le Wi-Fi du Zero W est en 2,4 GHz uniquement.** Un réseau 5 GHz ne sera même pas vu. Si ta box diffuse le même nom sur les deux bandes, ça marche en général, mais c'est une cause de panne classique.

## 1. Graver la carte

Avec **Raspberry Pi Imager** : choisir **Raspberry Pi OS Lite (32 bits)**. Le Zero W est un ARMv6, donc pas de version 64 bits, et « Lite » suffit — aucun bureau n'est utile ici.

Avant d'écrire, ouvrir les **réglages du système d'exploitation** (l'engrenage / « Modifier les réglages ») et renseigner :

- nom d'hôte : `ifd2` (la page sera alors sur `http://ifd2.local:8575`)
- nom d'utilisateur et mot de passe
- **Wi-Fi** : SSID, mot de passe, et le **pays** (sans le code pays, la radio reste éteinte)
- **activer SSH**, par mot de passe ou par clé

C'est la voie recommandée aujourd'hui : les vieilles recettes à base de fichier `ssh` vide et de `wpa_supplicant.conf` déposés sur la partition de démarrage sont fragiles sur les versions récentes.

## 2. Premier contact

Insérer la carte, brancher l'alimentation sur `PWR`, laisser une bonne minute au premier démarrage.

```bash
ssh <utilisateur>@ifd2.local
```

Si `ifd2.local` ne répond pas, chercher l'adresse sur l'interface de la box, ou brancher un écran une seule fois. Puis, une fois connecté :

```bash
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

## 3. Installer le projet

```bash
sudo apt install -y git
git clone https://github.com/Pixayl/ta-typewriter-ifd1-replacement.git ~/xerox575
cd ~/xerox575 && ./deploy/install-pi.sh
```

Le script installe `python3-serial` (par apt : Bookworm refuse un `pip install` à l'échelle du système, c'est la protection PEP 668), ajoute l'utilisateur au groupe `dialout` pour l'accès au port série, puis installe et démarre le service `ifd2-web`. Il est relançable sans dommage.

Sans réseau sur le Pi, la variante sans git — depuis le Mac :

```bash
rsync -av --exclude venv --exclude .git ~/xerox575/ <utilisateur>@ifd2.local:~/xerox575/
```

## 4. Préparer le Pico en mode serveur

Depuis le Mac (ou depuis le Pi, `pip install mpremote` dans un venv) :

```bash
mpremote fs cp pico/main.py :ifd2.py
mpremote fs cp pico/server_boot.py :main.py
```

⚠️ **Le port série ne se partage pas.** Toute session `mpremote repl` ou `mpremote exec` garde le port en exclusivité et empêche le serveur de l'ouvrir. En mode serveur, le Pico démarre seul sur son `main.py` et **seul `serve.py` parle au port**. Pour revenir à la mise au point : `mpremote fs rm :main.py`.

## 5. Mise en route

1. Brancher le Pico sur le port `USB` du Pi via l'adaptateur OTG.
2. Allumer la Xerox, attendre la fin de son démarrage (chariot posé).
3. **Presser ON LINE** : c'est la machine qui appelle, le Pico répond. La LED ON LINE s'allume.
4. Ouvrir `http://ifd2.local:8575` depuis un téléphone ou un ordinateur du réseau.

Vérifications utiles :

```bash
systemctl status ifd2-web        # le service tourne-t-il
journalctl -u ifd2-web -f        # ce qu'il reçoit et envoie
ls /dev/ttyACM*                  # le Pico est-il vu
```

## Sécurité — à lire une fois

Le service écoute sur `--host 0.0.0.0`, donc sur tout le réseau local, **sans authentification ni limitation de débit**. C'est acceptable chez soi ; ça ne l'est pas sur un réseau partagé, et il ne faut surtout pas ouvrir ce port sur Internet (pas de redirection de port, pas de tunnel public). Quiconque atteint la page peut faire taper la machine.

## Notes

- L'alimentation du Pico est fournie par le port USB du Pi ; le Zero W y suffit largement (le Pico consomme quelques dizaines de mA).
- Le service redémarre tout seul (`Restart=always`) si le lien série tombe ou si le Pico est rebranché. La session avec la machine, elle, exige un nouvel appui sur ON LINE : c'est une contrainte du protocole, pas un défaut.
- Un message est mis en file d'attente, jamais imprimé en parallèle : la liaison est séquentielle et deux messages entrelacés désynchroniseraient les paires d'octets.
