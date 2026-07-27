# Journal de bord — Xerox 575 → imprimante

Format d'une entrée :
`date | montage (vérifié comment) | hypothèse départagée | attendu | observé | conclusion`

---

## État établi (au 2026-07-22) — niveau de confiance indiqué

| Fait | Confiance |
|---|---|
| Xerox 575 = Type Y92 = TA série SE (sans LCD, ~SE310/320), fonctionne en local | je sais |
| Brochage : marron=GND ; E=alim 35V (lue 42V à vide) ; B=alim 10V (lue 12V à vide) ; **orange-blanc=alim 5V régulée** (tient 4,9V sous 100Ω) | je sais (tests de charge validés) |
| **vert = DTR machine** (repose bas ; le doc SE325 décrit un pulse DTR MONTANT ~1ms → cohérent) | je pense (fort) |
| orange / bleu / vert-blanc = {DSR, RX, TX} dans un ordre inconnu | je sais (par élimination) |
| Protocole SE325 : 4800 8N1, « logically inverted », reset RTS→0x01, init A0 00/A1 00/A4 00/A2 00, codes-roue (100 positions), flux DTR pulse + DSR haut | je sais (Google Doc tweetwronger) — l'inversion physique reste « à vérifier » |
| La machine est SOURDE tant qu'elle n'est pas online ; ON LINE (touche) = zéro réaction | je sais (validé) |

## Historique condensé des essais VALIDES (stimulus prouvé délivré, capture fraîche)

| Date | Essai | Résultat |
|---|---|---|
| 2026-07-19→20 | Cartographie tensions + 2 FT232 grillés (fils volants près de B/E) | leçons de sécurité ; B=+12V, E=+42V |
| 2026-07-22 | Test charge passive 470/220/100Ω sur chaque ligne | orange-blanc = alim 5V ; les 3 autres = signaux haute impédance ; vert tenu bas |
| 2026-07-22 | Charge 100Ω sur le 5V + ON LINE (+ reboot) | pas de LED → détection « par conso » écartée |
| 2026-07-22 soir | Balayage RTS (15 pulses, ~29 transitions CONFIRMÉES sur la ligne pilotée) sur orange, bleu, vert-blanc | silence total ×3, pas de LED → un reset seul ne réveille pas la machine |

## Bugs de banc identifiés (à ne jamais reproduire)

- cap.csv périmé décodé pendant 8h (script corrigé : purge avant capture ; TOUJOURS vérifier le mtime)
- RTS qui n'atteignait pas la ligne (rangée breadboard) → vérifier le stimulus AVANT d'interpréter un négatif
- Résistance de charge en série avec le voltmètre = mesure sans effet
- Analyseur qui disparaît du bus USB (mauvais port) → `sigrok-cli --scan` doit montrer « fx2lafw Saleae Logic »

## 2026-07-23 — Ouverture machine + traçage cuivre → MAPPING COMPLET 🎯

| Étape | Résultat |
|---|---|
| Ouverture (machine débranchée), photos carte | Carte S 330638/05 « EFEA05 » : **Intel P8031AH** (µC 8051, UART intégré, socket), quartz **11,0592 MHz** (= bauds standard, 4800 exact), ROM MOSTEK MK23128 (firmware 16 Ko), RAM TMM2116, 74LS373/139/244, **2× DM74LS05N (inverseurs collecteur ouvert)**, **CD4538BE** (double monostable → pulse DTR probable) |
| Arrivée DIN = connecteur ITT 10 points (P1..P10, P1 côté CD4538). Connecteurs noirs = moteur (hors sujet) | mapping DIN→points : **P3=vert, P4=vert-blanc, P5=orange, P9=bleu, P7=GND** (10-50Ω = contact DIN oxydé, à nettoyer), P1/P2/P6 = artefacts condos/jonctions |
| Leçons banc : bip/Ω mentent sur carte peuplée (diodes de protection → pseudo-directionnel ; condos → valeur qui grimpe vers « 1 » ; contact oxydé → « effet boulon rouillé ») | mesurer en Ω, deux sens, côté carte (sans passer par la fiche) |
| Continuité points ↔ 8031 | **P4 (vert-blanc) ↔ broche 10 (RXD)** ; **P5 (orange) ↔ broche 11 (TXD)** ; P9 (bleu) ↔ aucune ; P3 (vert) ↔ broche 10 KO (cohérent DTR) |

**TABLE FINALE : orange=TX machine (0x01 ici) ; vert-blanc=RX machine ; bleu=DSR (par élimination) ; vert=DTR ; marron=GND ; orange-blanc=+5V ; B=+12V ; E=+42V.**
Chemins UART passifs + repos à 5V ⇒ polarité STANDARD (pas d'inversion) sur TX/RX (je pense).

## 2026-07-23 — 🏆 LA MACHINE A RÉPONDU

| Essai | Résultat |
|---|---|
| Câblage prouvé (RXD←orange, TXD→vert-blanc, RTS→bleu, CTS←vert, GND marron nettoyé) + handshake.py --repeat 20 + ON LINE | **`0x01` reçu au cycle 2** → init `A0 00 A1 00 A4 00 A2 00` envoyée. Cycles suivants silencieux (interprétation : déjà en ligne, plus rien à annoncer). CTS=True constant (DTR machine lu, pulses 1 ms invisibles au polling). LED non observée en continu. |

Valide d'un coup : bleu=DSR, orange=TX, 4800 8N1 **sans inversion**, protocole SE325 OK sur cette machine.
Prochain : `first_print.py` (reset unique → 0x01 → init → **82 1F reset chariot** = effet visible). ⚠️ machine ouverte = mécanique peut bouger.

## 2026-07-23 — 🖨️🏆 PREMIÈRE IMPRESSION SOUS CONTRÔLE ORDINATEUR

| Essai | Résultat |
|---|---|
| Machine rebootée + first_print.py | `82 1F` accepté (chariot déjà à l'origine) et **LED ON LINE ALLUMÉE** — première fois du projet |
| type_test.py (indices 1..30, force 25) | **La machine a TAPÉ : `. , -`** (indices 1, 2, 3) puis a calé. |

Lectures : (1) `. , -` = début IDENTIQUE à la roue SE325 → notre marguerite suit probablement le même ordre (je pense) → la table de typecontrol.py serait réutilisable telle quelle. (2) Calage après 3 frappes = régulation de flux à régler (pulse DTR 1 ms raté par le polling) → v1 : ralentir la cadence (50-100 ms/octet) ; v2 : verrou matériel type Digispark si besoin de débit.

## 2026-07-23 — Rosette essai 1 : échec instructif (désynchro de paires)

rosette.py sans reboot préalable → **aucune impression, LED de réglages interligne + pas d'écriture allumées**. Diagnostic (je pense, fort) : type_test avait calé après 3 frappes mais envoyé 54 octets de plus → nombre impair avalé → **parseur machine décalé d'un octet** → nos paires shiftées tombent sur les opcodes de réglages (0x80 = pas). Leçons : (1) jamais d'envoi à l'aveugle après calage ; (2) resynchro possible par paires A0 00 répétées ; (3) cycle secteur = reset parseur + réglages. Remède : reboot machine + relance rosette (250 ms/car).

## 2026-07-23 — 🖨️🎉 ROSETTE IMPRIMÉE : 100 caractères, roue ≈ SE325

Après re-débogage (RX du FT232 OK au loopback, contacts fiche re-nettoyés, 0x01 revient : séquence émise par la machine = `02` puis `01`). **Bug résolu : le handshake d'envoi guettait le pulse "occupé" DTR ~1ms — invisible en polling 5ms → faux timeout → crash.** Fix : ne plus guetter le pulse, attendre CTS haut + délai fixe `--gap` (0.12-0.2s). rosette.py v2 fidèle tweetwronger (reset instantané, écoute patiente 10×1s, handshake par octet).

**Impression réussie (--gap 0.2)** : lignes 3-6 parfaitement lisibles. **Roue = roue SE325 confirmée à ~95 %** : `*C"D?NIU)W_=;:M'H(K/` et `khcgnrseaiduboz` exacts. ~5 cases divergent (variante FR : `ù ò à ç` vs `¼ Δ Ω @` SE325) → table de typecontrol.py réutilisable, à corriger sur ~5 index.
Bugs restants mineurs : **retour chariot `E0 F0` trop court** (lignes 1-2 se chevauchent à gauche) → ajuster distance/direction (tester C0 vs E0). Interligne `D0 14` OK.

## 2026-07-23 soir — LEÇON DE BANC : l'analyseur laissé branché parasitait

Symptôme : impression devenue flaky (0-1/10) l'après-midi, LED de réglages qui changent (= désync par octet perdu, les octets de contrôle 0xB2 lus comme commandes de réglage). Cause : **l'analyseur logique, laissé sur les lignes après les captures, chargeait le bus.** PIRE quand débranché de l'USB mais sondes en place : les diodes de protection du chip non alimenté tirent les lignes vers 0V (rails morts) → la machine ne se connecte même plus.
RÈGLE : un instrument inutilisé → retirer ses SONDES des lignes, pas juste l'USB. Bench propre = une variable de moins. (Ce matin, impression fiable SANS analyseur sur les lignes.)
À confirmer : recette prouvée (force 40, posreset, gap 0.8, analyseur totalement retiré) → taux d'impression sur 8.

## 2026-07-23 — ✅ IMPRESSION FIABLE 8/8 (analyseur retiré)

strike_test --n 8 --gap 0.8 --force 40 --posreset, **analyseur totalement débranché** → **8/8 imprimés, LED ON LINE allumée**. CONCLUSION MAJEURE : **aucun verrou matériel nécessaire** (le mur "flux" de tweetwronger n'est pas le nôtre) — la flakiness venait de l'analyseur qui chargeait le bus. Montage final simplifié : Pi + FT232 + câble, point.
Recette fiable = pilotage TEMPS PUR (pas d'attente CTS, non fiable), online = A0/A1/A4/A2 + sleep1 + 82 0F + sleep2 (calage chariot), force 40 (ctrl 0xA8), gap ~0.6-0.8s/paire. tw.py aligné sur ça.
Prochain : `tw.py text "bonjour"` (1er mot), puis espace inter-mots (frappe-à-blanc 0x01,0x80 à valider), corriger ~5 cases FR de la table, phrase complète.

## 2026-07-23 — 🏆🖨️ TEXTE ARBITRAIRE IMPRIMÉ : « Bonjour le monde. »

tw.py text "Bonjour le monde." → imprimé proprement (majuscule + minuscules + 2 espaces + point). Espace = frappe-à-blanc (0x01,0x80) : fonctionne (fait tourner la roue inutilement, cosmétique ; optim possible via 0xC0+largeur = move pur). Fiabilité connexion améliorée : connect() répète l'impulsion reset (15×) + settle 0.6s après le 0x01 ; tip procédural = attendre la fin du boot machine (chariot posé) avant de lancer. Force 40, gap 0.6s.
**BILAN : la Xerox 575 est une imprimante pilotable, SANS matériel additionnel.** Reste : table accents FR (~zone idx 85-100), optim espace, puis but d'origine = serveur d'impression Pi + boîtier.

## 2026-07-23 nuit — Table FR + modes live/listen + cap sur le Pico

- **Table roue FR complète** dans tw.py (calibration cuivre + impression) : substitutions vs SE325 = {12:^, 13:è, 14:é, 72:ì, 74:¨(tréma), 75:◊, 80:ç, 81:ù, 82:ò, 83:à}. é è à ç ù validés à l'impression. Hommage FT232 imprimé 🎖️.
- **Retour à la ligne corrigé** : suivi de position chariot (self.col) → retour exact col×12 pas (fini le E0 fixe qui chevauchait). `crlf()` fiable (prouvé en mode live).
- **tw.py enrichi** : commandes connect/idx/text(\n)/rosette/cal/**live** (interactif, connexion maintenue = objectif #4 ✅)/**listen** (écoute clavier).
- **Terminal (#3) : NON CONCLUANT** — listen n'a rien donné MAIS le voyant ON LINE était éteint (connexion pas établie) → test invalide. À refaire sur lien fiable.
- **Fiabilité (#1)** : désyncs « sapin de Noël » = erreurs de bit physiques (breadboard + fiche DIN oxydée ~20Ω). Fix = souder. **Vitesse (#2)** actuelle ~1 car/s (gap 1.0 prudent, CTS trop capricieux pour cadencer : pulse occupé retardé/variable 0→908ms).
- **🎯 PLAN IFD-2** : **Pi Pico retrouvé** = cerveau temps-réel. Archi : Pi Zero W (réseau/RSS) → Pico (protocole IFD1 temps réel, capte le pulse 1ms → flux fiable + rapide) → Xerox. Résout #1+#2 et redonne un lien propre pour retester #3. ⚠️ Pico 3,3V vs machine 5V : Pico→machine OK (seuil TTL), machine→Pico (orange/TX, vert/DTR) = **2 diviseurs de tension requis** (4 R). Firmware MicroPython d'abord.

## 2026-07-24 — Prépa logiciel + matériel Pico (avant réception)

Matériel commandé : kit perfboards double-face + barrettes M/F + borniers à vis + entretoises M3 (bon choix). À ajouter : DIN 8 mâle capot métal, fil multibrin (blindé si possible), gaine thermo, DeoxIT.
**Câblage Pico↔machine défini** : marron=GND ; vert-blanc(RX)←GP0 via 1k ; orange(TX 5V)→GP1 via **diviseur 1k/2k** ; bleu(DSR)←GP2 via 1k ; vert(DTR 5V)→GP3 via **diviseur 1k/2k**. Pico alimenté par USB (masse commune seule). Jamais B/E.
**Firmware Pico écrit** : `~/xerox575/pico/main.py` (MicroPython, syntaxe OK, NON TESTÉ) — connect/online/print_text + table FR + suivi position. Points TODO au bring-up : polarité DSR, flux via GP3 (v2, gain vitesse), niveau 3,3V→RX. **Côté Pi** : `~/xerox575/pico/send_from_pi.py` (envoie texte au Pico /dev/ttyACM0).
Bring-up : flash MicroPython → câbler + vérifier diviseurs à 3,3V au multimètre → copier main.py → REPL: connect() puis online() puis print_text().

## 2026-07-27 — 🏆⚡ IFD-2 OPÉRATIONNEL : impression à VITESSE MAXIMUM

Montage soudé (perfboard, Pico en H1-H20/O1-O20, USB en haut) : GND rail colonne A ; 1k série sur chaque ligne ; borniers à vis pour le câble DIN. **H1=GP0 (attention : broche 1 = GP0, pas GP1)**.
**ERREUR DE CONCEPTION CORRIGÉE** : les diviseurs 1k/2k écrasaient les signaux ! Les lignes machine ont une **impédance de source ~25 kΩ** (mesuré dès le début : orange 4,85V→0,09V sous 470Ω). Un diviseur 3k ramenait GP1 à ~0,35V = toujours LOW → réception morte. **Fix : retirer les 2 kΩ**, garder juste 1k série ; la source étant faible (~48 µA max), les diodes de protection du Pico suffisent. Leçon : toujours vérifier l'impédance de source avant de dimensionner un diviseur.
**MESURE CLÉ (probe_dtr, µs)** : après CHAQUE octet reçu, **DTR monte à 1 pendant ~1 ms** = « octet reçu, envoie le suivant » (1er pulse ~2,1 ms = fin du 1er octet à 4800 bd, 2e ~4,15 ms). Quand le buffer est plein, l'accusé est RETARDÉ → **la machine impose son propre rythme**. C'était LE mur du Mac (1 ms trop bref en polling USB).
**Firmware v2** (`~/xerox575/pico/main.py`) : `send_byte()` attend l'accusé DTR → contrôle de flux réel. ⚠️ **L'accusé n'existe QUE une fois online** → `online()` reste en délai fixe (`flow=False`), le flux ne sert qu'à l'impression. `start()` = connect + **settle 600 ms** (indispensable, sinon pas de LED) + online, en une commande (évite le copier-coller multi-lignes qui casse le REPL).
**RÉSULTAT : LED ON LINE + impression à la vitesse mécanique maximale.** 🎉
Reste côté HW : remplacer la 1k de la ligne vert/GP3 par **10 kΩ** (limite le courant d'écrêtage à 140 µA au lieu de 1,4 mA) avant montage définitif.

## 2026-07-27 (soir) — ⚡ IFD-2 FIABLE : niveaux corrigés, open-drain, mise en page

**LA découverte électrique du projet** : l'entrée de la machine est **CMOS** (le CD4538 près du connecteur) → seuil VIH ≈ **3,5 V**. Une sortie push-pull 3,3 V du Pico ne suffit pas, et la résistance série modifiait involontairement le niveau haut (le pull-up machine « tire » vers 5 V à travers elle) :
| Config GP0 | Niveau BAS | Niveau HAUT | Résultat |
|---|---|---|---|
| 1 kΩ push-pull | 1,00 V | 3,64 V | marchait, avec bits 0→1 corrompus |
| 100 Ω push-pull | 0,12 V | 3,34 V | ❌ sous le seuil CMOS |
| diode seule + push-pull | — | 3,4 V | ❌ (la diode ne libère rien si la sortie force 3,3 V) |
| **open-drain + BAT85** | **0,3 V** | **5,0 V** | ✅ **les deux niveaux francs** |

**Solution finale** : GP0 (données) **et** GP2 (DSR) en **OPEN-DRAIN** — le Pico ne fait que tirer vers le bas, le pull-up 5 V de la machine fournit le niveau haut. Comme l'UART matériel est push-pull, **TX est bit-bangé en logiciel** (`_tx`, échéances cumulées, 208 µs/bit) sur GP0 ; l'UART matériel garde RX sur GP1 (TX matériel déporté sur GP12 non connecté). Bit-bang **validé** par écoute FT232 : flot de 0x55 parfait.
**Écho d'init découvert** : la machine renvoie A0/A1/A2 → `online()` vérifie l'écho de **0xA2** et **réessaie** (4×) → passage online **fiable** (fini le « une fois sur trois »).
**Mise en page** : `print_text(txt, wrap=True, end_newline=True)`, retour auto à `LINE_LEN=65` (coupe aux espaces), `offline()`, `listen()`.
**❌ TERMINAL CLAVIER : IMPOSSIBLE** — testé proprement sur lien fiable : aucune touche n'émet, la machine est **réception seule** (seuls les échos de commandes reviennent). Dossier clos.
⚠️ Réflexe obligatoire : **Ctrl-D** après chaque `mpremote fs cp` (sinon l'ancien module reste en mémoire).

## En attente / prochaines étapes (mises à jour)
1. **Bring-up Pico** : câbler Pico↔DIN (2 diviseurs sur TX/DTR), porter le handshake (0x01, init, send temps-réel avec pulse-catch) en MicroPython. Point de départ du prochain chapitre.
2. Souder le harnais (fiabilité) — ou câbler direct le Pico sur les points carte (machine ouverte).
3. Retester le terminal (#3) une fois le lien fiable.
4. Serveur d'impression : Pi Zero W + backend CUPS ASCII→codes roue, mutualisé DMP 3160 (RSS/messages).
5. Boîtier 3D « IFD-2 ».

1. **Issue GitHub postée** sur binraker/tweetwronger (2026-07-22) — questions : déclencheur online, portée du reset RTS, inversion physique, câblage exact + place du ready_latch. → surveiller les réponses.
2. **Test du switch ON LINE** (hypothèse « touche morte ») : à préparer proprement — ouverture machine hors tension, continuité sur le switch, photos avant/pendant.
3. Si réponse issue : appliquer le câblage exact → mapping DSR/RX/TX → handshake → première impression.

## 2026-07-27 (nuit) — Mise en page complète : table de commandes décodée

Isolation méthodique (strikes OK → espaces OK → newline KO) : le bug n'était ni le lien ni les frappes (`debug_send` passait 107 caractères sans faute) mais **mes commandes de mouvement**.
**Table de commandes décodée empiriquement sur CETTE machine :**
| Commande | Effet |
|---|---|
| `0x82 0x03` | **retour chariot** (posreset, drapeau chariot) — fiable, remplace le déplacement relatif `0xE0` |
| `0x82 0x0F` | reset position complet (chariot+roue+ruban) |
| `0xD0 0x10` | **interligne** (0x14 = trop large, 0x0C = plus serré) |
| `0xF0 0x14` | avance d'une ligne |
| `0xD0 0x30` | avance de plusieurs lignes |
| `0x84 0x10` | retour arrière d'un caractère |
| `0x80 <n>` | **pas d'écriture** = largeur d'un caractère en unités : **0x0F normal, 0x0A condensé**, 0x01 = tout superposé |
| `0x82 0x01` | ⚠️ à éviter (chariot n'importe où puis blocage) |
**Points clés** : les commandes de MOUVEMENT n'émettent **pas** d'accusé DTR (contrairement aux frappes) → `newline()` sans contrôle de flux, précédé de `_wait_idle()` (attend que DTR soit silencieux 400 ms = buffer d'impression vidé). Ajout de `raw(b1,b2)` pour explorer, et `set_pitch(p)` qui recalcule `LINE_LEN = LINE_UNITS // PITCH`.
**Résultat : impression multi-lignes correcte, avec pas condensé (0x0A) appliqué automatiquement à l'init.**

## 2026-07-27 — 🔑 LE VRAI SENS DU HANDSHAKE (découverte utilisateur + doc allemande)

**1. C'est la MACHINE qui appelle l'hôte, pas l'inverse.** Observation décisive de l'utilisateur : le `0x01` arrive **exactement au moment où il presse la touche ON LINE**, jamais spontanément. Notre impulsion DSR n'y est pour rien. Le manuel le disait depuis le début : « en frappant une fois sur la touche ON LINE on établit un raccord logique avec l'ordinateur personnel **connecté** ».
→ Procédure correcte : l'hôte maintient DSR asserté (présent), **l'utilisateur presse ON LINE**, la machine émet `0x01`, l'hôte répond par la séquence d'init.
→ Conséquence : tous les tests `step()`/`window_test` antérieurs (déclenchés par notre impulsion DSR) étaient **sans valeur**.

**2. La séquence d'init était fausse.** Source : *ST Computer* 8/1988, pilote Atari ST pour Gabriele 9009 :
```asm
onl_tab:  $A1, $A4, $A2, 0
```
= **quatre OCTETS SIMPLES** (A1, A4, A2, 00), un par un avec délai — **et surtout PAS de `$A0` en tête**. Or `A0` (CLEAR) est justement la commande qui verrouille le clavier puis rend la machine sourde : on commençait l'init par ce qui la bloque. Cohérent avec le seul écho réussi jamais obtenu : `a1 a4 03 01 01 51 00 01 8f 02 00 a2` — **commence par a1, aucun a0**.
Puis : `82 1F` (reset position — on utilisait `0F`), puis `80 <pas>`.

Firmware corrigé en conséquence (`online()`), en attente de test.

## 2026-07-27 — ✅ SÉQUENCE D'INIT VALIDÉE AU BANC (premier coup, sans retry)

Test du firmware corrigé (`import ifd2` puis `ifd2.start()`, appui ON LINE dans la fenêtre de 60 s) :
```
>>> PRESSE maintenant la touche ON LINE de la machine <<<
demande recue (0x01) — init dans 1200 ms...
online confirme (echo : a1 a2)
PRET (LED ON LINE allumee).
True
```
**La séquence `A1 A4 A2 00` (sans `A0`) fonctionne, du premier essai, sans aucune tentative de reprise** — alors que l'ancienne (`A0 00 A1 00 A4 00 A2 00`) ne passait qu'une fois sur trois et nécessitait les 4 retries. Le `A0` en tête était bien le coupable.
**Écho observé = `a1 a2`** : la machine réfléchit `A1` et `A2` (transitions d'état) mais **pas `A4`** — cohérent, `A4` (ENQ) appelle un bloc de statut, pas un écho, et rien d'autre n'est arrivé dans la fenêtre de lecture de 400 ms.
Autres points confirmés par ce test : `delay_ms=1200` entre le `0x01` et l'init convient (pas besoin de recalibrer), et `0x82 0x1F` (valeur du pilote ST, à la place du `0x0F` qu'on utilisait) n'a pas posé de problème de calage chariot.
**Ce que ça ferme** : le handshake est désormais déterministe. Reste à revérifier, sur cette base propre, ce qui avait été mesuré au-dessus de l'ancienne init bancale — en premier lieu une impression multi-lignes complète (`print_text`), puis la tenue de la session dans la durée (`ensure_ready`/`ping`).
**Suite immédiate : `print_text` avec wrap validé sur cette base — mise en page correcte.** La couche impression n'était donc pas contaminée par l'ancienne init.

## 2026-07-27 — 📖 SPEC PRIMAIRE RETROUVÉE : les articles ST Computer en entier

Les deux articles *ST Computer* (07 et 08/1988) sont archivés en ligne, et la partie 2 publie **le listing assembleur complet de l'émulateur IFD1**, tables comprises. Récupérés, décodés, consignés dans **[`docs/protocole-ifd1.md`](protocole-ifd1.md)** — désormais la référence normative du projet. (Le dépôt tweetwronger, lui, ne contient pas la table : son README ne fait que pointer vers ces articles.)

Ce que ça change par rapport à ce qu'on avait deviné :
- **Les codes empiriques sont confirmés un par un** : `80 <n>` pas d'écriture, `82 <drapeaux>` mise en position (bit1 chariot, bit2 marguerite, bit3 ruban → `03` = chariot seul, `0F` = tout, `01` = aucun moteur, ce qui explique le blocage constaté), `84 <n>` retour arrière. Notre `D0 10` d'interligne vaut 16/96" = **exactement 1/6"**, l'interligne normalisé : on était tombé juste.
- **Mouvement direct = distance sur 12 bits**, pas un octet : `((b1 & 0x0F) << 8) | b2`, base `C0` droite / `E0` gauche / `D0` bas / `F0` haut. Le `F0 14` noté « avance d'une ligne » est en fait un mouvement **vers le haut** — à revérifier.
- **`82 1F` n'est pas documenté** (bit 4 sans signification) ; la valeur juste est `82 0F`. Ça a marché une fois, ce n'est pas une raison.
- 🆕 **`83 <n>` = espace, et `83 00` avance d'exactement un pas d'écriture.** Notre `space()` fait une frappe à blanc (`0x01, 0x80`) qui fait tourner la marguerite pour rien → à remplacer.
- 🆕 **L'octet de force porte deux drapeaux** : bit 6 = sens de l'avance (1 = vers la gauche, impression inversée), **bit 7 = 0 supprime l'avance qui suit**. La surimpression est donc gratuite → accents composés, **gras** (double frappe décalée de 1/120") et **soulignement** sont à notre portée sans rien ajouter au protocole.
- 🆕 **La force varie par caractère dans la table d'origine : 12 à 25.** Notre `FORCE = 40` est très au-dessus de toute la plage — piste pour le bruit, l'usure du ruban et le marquage.
- 🆕 L'auteur documente le plantage qu'on a vécu : des octets incompris ne sont « pas toujours ignorés », la machine plante parfois et **seul un cycle secteur la récupère**. Notre « sapin de Noël » a un nom.

**Contradiction à trancher au banc** : le texte de l'article donne l'init en paires *avec* `A0` (`A0 00, A1 00, A4 00, A2 00`), alors que le listing du même auteur envoie `onl_tab: A1, A4, A2, 0` en 4 octets simples — la forme qui marche chez nous. Comme tout le reste du protocole est strictement en paires, l'hypothèse propre est `A1 00, A4 00, A2 00` (sans `A0`) : elle réconcilie les deux lectures et ferait réellement arriver l'ENQ, que notre forme actuelle avale en paramètre de `A1`. Ce qui expliquerait aussi pourquoi `ping()` n'a jamais rien renvoyé.

## 2026-07-27 — 🎯 L'ENQ RÉPOND : le bloc de statut est reproductible

**Contradiction tranchée, et par le listing lui-même** : la boucle qui consomme `onl_tab` **accole un `00` à chaque octet de la table** (`move.b (a1)+,d4 / senden / move.b #0,d4 / senden`). L'init réellement émise est donc `A1 00, A4 00, A2 00, 00 00` — **des paires régulières, sans `A0`**. Nos 4 octets bruts se recadraient en `(A1,A4)` + `(A2,00)` : l'ENQ partait comme *numéro de version* du START. La boucle draine aussi l'écho après chaque paire (`bsr raus`).

Firmware passé aux paires (repli automatique sur les octets bruts si pas d'écho `A2`) → **au premier essai** :
```
online confirme (echo : a1 a4 03 01 01 51 00 01 8f 02 00 a2)
```
`a1`, `a4`, puis **`03 01 01 51 00 01 8f 02 00`** (9 octets), puis `a2`. C'est la réponse à l'ENQ — et c'est mot pour mot la chaîne notée plus haut comme « le seul écho réussi jamais obtenu » : on sait enfin d'où elle venait et **comment la reproduire à volonté**. Format non documenté par l'article (qui dit seulement « la machine signale son état ») : à décoder en faisant varier l'état de la machine (papier, capot, marguerite) et en comparant.
Corollaire : `ping()` a une chance de fonctionner maintenant. Avant ce correctif il ne pouvait pas — on n'avait jamais envoyé d'ENQ valide.

**Piège de banc, à ne pas reproduire** : le fichier a été déployé en `main.py` sur le Pico au lieu de `ifd2.py`. MicroPython exécute `main.py` au démarrage → `run()` s'est lancé seul, a confisqué `stdin` puis s'est bloqué 60 s dans `start()` → **REPL inaccessible**. Récupération : Ctrl-C puis `mpremote fs rm :main.py`. L'auto-exécution (`if __name__ == "__main__"`) a été **retirée du firmware** et l'avertissement mis en tête de fichier.

**Correction épistémique** : le `em_int` cité plus haut est le code **côté hôte** (pilote Atari ST), pas côté machine — `lesen` y lit ce que la machine envoie. Il montre donc ce que l'auteur *s'attendait* à recevoir, pas ce que la machine *peut* émettre : c'est une corroboration du dossier « terminal impossible », pas une preuve. La preuve reste le test `listen()` sur lien fiable + le manuel. À noter d'ailleurs : la branche `ni_line` (ni `01` ni `02`) **répond deux octets nuls** au lieu d'ignorer — l'auteur savait que d'autres octets arrivent.

## 2026-07-27 — ⌨️ CLAVIER : les 4 états sont muets (dossier re-fermé)

`kb_hunt()` a passé en revue les états jamais explorés, 20 s de frappe clavier dans chacun :

| État | Octets reçus |
|---|---|
| 1. OFFLINE au repos (DSR asserté) | 0 |
| 2. après START `A1 00` seul (« passage préparé ») | 0 |
| 3. après ENQ `A4 00` | 0 |
| 4. ONLINE puis ETX `A3 00` (transmission interrompue) | 0 |

**Aucun état ne transmet les frappes.** L'hypothèse d'un mode saisie caché tombe : le verrouillage du clavier n'est pas propre à ONLINE, il est total. Combiné au manuel et au test `listen()`, le dossier terminal est clos pour de bon.

**Contrôle positif : fait, et concluant.** Même état 1 (OFFLINE au repos), même code, ON LINE pressée au lieu de taper des lettres → `t = 1280 ms, 0x01`. La voie de réception était donc bien vivante pendant que les lettres ne donnaient rien : **le négatif sur OFFLINE est réel**, et c'était le candidat le plus sérieux — l'état où le clavier fait son métier.

⚠️ Réserve résiduelle, assumée : les états 2-4 n'ont pas de contrôle positif, parce que `_listen_raw()` faisait un `_flush_in()` qui avalait l'écho de la commande. **Cause corrigée** : l'écho est désormais conservé par défaut (`flush=False`), il sert de contrôle positif intégré à chaque état. Si la question devait un jour se rouvrir, `kb_hunt()` rend maintenant un résultat interprétable d'emblée.

**`probe_cmd` sur A5/A6/A7** : ce ne sont pas des commandes d'état et ce ne sont pas des non-opérations — elles **font bouger le chariot ou le rouleau**. La plage `A0`–`A4` des commandes d'état est donc bien close, et au-delà on retombe dans du mouvement mécanique. À éviter.

## 2026-07-27 — ✍️ SURIMPRESSION + 💌 SERVEUR WEB « MOTS DOUX »

**Surimpression implémentée** (elle découle du bit 7 de l'octet de force, cf. [`protocole-ifd1.md`](protocole-ifd1.md)) :
- `strike(idx, advance=False)` = frappe sans avance → tout le reste en découle.
- `_move(n)` : mouvement horizontal pur — `n>0` espace (`0x83`), `n<0` retour arrière (`0x84`), `n=0` avance d'un pas d'écriture (`0x83 0x00`).
- **Gras** = deux frappes décalées de 1/120", exactement la méthode de l'IFD1 d'origine (`ESC W`). **Souligné** = trait bas surimprimé, et c'est lui qui porte l'avance. **Accents composés** : `â ê î ô û ä ë ï ö ü ÿ` reconstitués par lettre + `^`/`¨`, ce qui étend la marguerite FR sans matériel.
- `print_text(..., bold=, underline=)` + balisage inline `*gras*`. Les étoiles ne s'impriment pas et sont hors du compte pour le retour à la ligne.

**Serveur d'impression + interface web** : [`tools/serve.py`](../tools/serve.py) (bibliothèque standard + pyserial). Navigateur → serveur → USB → Pico → machine. Un seul fil parle au Pico (file d'attente) : la liaison est lente et séquentielle, deux messages entrelacés désynchroniseraient les paires d'octets. Le Pico répond `OK` par ligne imprimée, le serveur attend cet accusé avant la suivante (timeout large : la machine tape ~1 car/s). Journal des 20 derniers messages sur la page. Écoute sur `127.0.0.1` par défaut — pas d'authentification, `--host 0.0.0.0` seulement sur réseau de confiance.
`run()` (Pico) est passé au **vrai handshake** (`start()`, appui ON LINE) au lieu de l'ancien `connect()` par impulsion DSR.

Testé hors machine : page, POST, file, écriture ligne par ligne, accusé, journal, refus du message vide. **Reste à valider au banc** : le rendu du gras (le décalage de 1/120" est-il visible ?), du souligné, des accents composés, et le fait que `_move()` — commande de mouvement, donc sans accusé DTR — ne désynchronise pas le flux au milieu d'une ligne. C'est le point de risque : si ça déraille, le repli est `bold=False` (le souligné, lui, n'utilise aucun mouvement).
