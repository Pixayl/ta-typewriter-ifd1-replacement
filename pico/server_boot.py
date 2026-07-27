# -*- coding: utf-8 -*-
# IFD-2 — mode SERVEUR D'IMPRESSION.
#
# A deployer sous le nom main.py pour que le Pico demarre tout seul en serveur :
#     mpremote fs cp pico/main.py :ifd2.py
#     mpremote fs cp pico/server_boot.py :main.py
#     (debrancher / rebrancher, ou mpremote soft-reset puis LACHER le port)
#
# Le Pico attend alors l'appui sur ON LINE, puis imprime chaque ligne recue sur
# l'USB. C'est tools/serve.py (interface web) qui parle a ce port.
#
# POURQUOI ce fichier existe : mpremote garde le port serie en EXCLUSIVITE.
# Lancer run() par `mpremote exec` empeche serve.py d'ouvrir le meme port.
# En mode serveur, le Pico doit donc demarrer seul et personne d'autre que
# serve.py ne doit tenir le port.
#
# POUR REVENIR EN MODE MISE AU POINT (REPL) :
#     mpremote fs rm :main.py        (Ctrl-C d'abord si le REPL ne repond pas)
# ... et on retrouve `import ifd2` a la main.

import ifd2

ifd2.run()
