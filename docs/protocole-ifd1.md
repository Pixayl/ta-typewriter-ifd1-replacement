# Protocole IFD1 — spécification bit à bit (source primaire)

Décodé le 2026-07-27 depuis les deux articles de *ST Computer* (archivés sur stcarchiv.de) :
- Partie 1, 07/1988 — <https://www.stcarchiv.de/st-computer/1988/07/gabriele-9009-1> : liaison, états, **table des commandes bit par bit**.
- Partie 2, 08/1988 — <https://www.stcarchiv.de/st-computer/1988/08/gabriele-9009-2> : émulateur IFD1, **listing assembleur complet** (tables `onl_tab`, `offl_tab`, jeu de caractères).

Le dépôt [binraker/tweetwronger](https://github.com/binraker/tweetwronger) ne contient **pas** la table : son README renvoie à ces deux articles (et à un Google Doc non accessible sans compte). `typecontrol.py` n'en applique qu'un sous-ensemble.

Cette page est la **référence normative**. Le journal reste le récit de ce qui a été vérifié sur NOTRE machine ; en cas de divergence, c'est la mesure qui gagne — les divergences connues sont notées ici.

## Liaison

4800 bauds, 1 start / 8 données / 1 stop, sans parité. Niveaux TTL (0 V / +5 V) sortis sur la DIN 8 points, **sans circuit de transmission** — d'où l'adaptation obligatoire côté hôte. L'article ne mentionne que +5 V, +10 V et +35 V sur la prise (nous mesurons +12 V et +42 V : variante de modèle).

La liaison doit être **bidirectionnelle** : la machine doit pouvoir signaler des évènements, en premier lieu « la touche ON LINE a été pressée ».

## États et transitions

Toutes les commandes font **exactement deux octets** : le premier définit la commande, **le second est un numéro de version, normalement `00H`**.

| Code | Nom | Effet |
|---|---|---|
| `A0 00` | CLEAR | retour OFFLINE, la machine redevient machine à écrire |
| `A1 00` | START | prépare le passage à ONLINE |
| `A2 00` | STX | passage ONLINE : la machine devient imprimante, les commandes d'impression peuvent commencer |
| `A3 00` | ETX | interrompt la transmission, attend la reprise |
| `A4 00` | ENQ | demande à la machine de signaler son état |

**OFFLINE → ONLINE : `A0 00`, `A1 00`, `A4 00`, `A2 00`** — l'ordre est imposé, pas arbitraire.
**ONLINE → OFFLINE : `A3 00`, `A0 00`.**

> ⚠️ **Divergence source/source.** Le texte de l'article donne la séquence ci-dessus *avec* `A0` en tête. Mais le listing du même auteur, en partie 2, envoie :
> ```asm
> onl_tab:   dc.b $A1, $A4, $A2, 0        ; 4 octets, envoyés tels quels
> offl_tab:  dc.b $A3, 0, $A0, 0          ; 2 paires régulières
> ```
> `onl_tab` n'est donc **pas** une suite de paires (ce serait `A1 A4` puis `A2 00`), contrairement à `offl_tab`. C'est cette forme-là — 4 octets simples, sans `A0` — qui passe **du premier coup sur notre machine**, là où la séquence en paires avec `A0` ne passait qu'une fois sur trois. Voir le journal, entrée du 2026-07-27.
> Reste à tester : les paires propres `A1 00`, `A4 00`, `A2 00` (sans `A0`), qui réconcilieraient les deux lectures — et qui, elles, feraient réellement parvenir l'ENQ.

En ONLINE, les réglages faits au clavier de la machine (interligne, pas, force de frappe) et affichés par ses LED **sont sans effet** : tout vient de l'hôte.

## Machine → hôte

`01H` = **code de la touche ONL**. C'est l'unique déclencheur : la machine l'émet quand l'utilisateur presse ON LINE, et c'est à l'hôte de répondre par la séquence d'init. La machine « ne réagit par principe qu'à des instructions venues de l'extérieur » — d'où le sens du handshake établi dans le journal.

Le retour OFFLINE depuis le clavier existe aussi, par combinaison de touches variable selon le modèle (`CE` sur SE 325).

## Commandes d'impression

### Frappe d'un caractère — `<rayon> <force>`

| Octet | Bits | Rôle |
|---|---|---|
| 1 | 0-6 | code du typenrad = **numéro de rayon** de la marguerite |
| 1 | 7 | **`0`** (c'est ce qui distingue une frappe d'une commande) |
| 2 | 0-5 | **force de frappe** (0-63) |
| 2 | 6 | `0` = avance à droite après la frappe, `1` = à gauche |
| 2 | 7 | `0` = **supprime** l'avance qui suit, `1` = l'exécute |

→ `bit7 = 0` donne la **surimpression** (frappe sans avancer) : c'est le mécanisme des accents composés et du soulignement.
→ `bit6 = 1` permet l'impression de droite à gauche. L'auteur l'a délibérément écartée : la 9009 en est capable mais fait « un curieux mouvement de secousse » après chaque pas à gauche, ce qui annule le gain du bidirectionnel.

### Commandes (bit 7 du premier octet = 1)

| Code | Nom | Second octet |
|---|---|---|
| `80 <n>` | **pas d'écriture** | nombre de pas de 1/120" exécutés automatiquement après chaque frappe (0-255) |
| `82 <f>` | **course de mise en position** (Grundstellung) | drapeaux, voir ci-dessous |
| `83 <n>` | **espace** (vers la droite) | pas de 1/120" ; **`n = 0` → avance d'un pas d'écriture** |
| `84 <n>` | **retour arrière** (vers la gauche) | pas de 1/120" |

Drapeaux du `82` : bit 0 = `1` (toujours), bit 1 = moteur du chariot, bit 2 = moteur de la marguerite, bit 3 = moteur du ruban.
→ `82 03` = chariot seul (= notre retour chariot), `82 0F` = les trois moteurs (reset complet), `82 01` = aucun moteur — cohérent avec le blocage constaté au journal. **`82 1F` n'est pas documenté** (bit 4 sans signification) ; utilisé une fois sans dommage, mais `0F` est la valeur juste.

Pas d'écriture usuels : `120 / n` = caractères par pouce. `n = 12` → 10 cpi (Elite), `n = 10` → 12 cpi (Pica), `n = 8` → 15 cpi.

### Mouvement direct (chariot ou rouleau)

Deux octets qui portent ensemble une distance sur 12 bits.

Premier octet : bits 6 et 7 à `1` (code de commande) ; **bit 4** = `0` horizontal / `1` vertical ; **bit 5** = `0` droite ou avant / `1` gauche ou arrière ; bits 0-3 = **quartet de poids fort** de la distance.
Second octet : **octet de poids faible** de la distance.

| Base | Direction | Unité |
|---|---|---|
| `C0` | horizontal, **droite** | 1/120" |
| `E0` | horizontal, **gauche** | 1/120" |
| `D0` | vertical, **vers le bas** | 1/96" |
| `F0` | vertical, **vers le haut** | 1/96" |

`distance = ((octet1 & 0x0F) << 8) | octet2`, soit 0 à 4095 pas.

→ `D0 10` = 16/96" = **exactement 1/6"**, l'interligne normalisé : notre `LF_CMD` empirique tombait juste.
→ ⚠️ Le journal note `F0 14` comme « avance d'une ligne » : d'après la spec c'est un mouvement **vers le haut** de 20/96". À revérifier.

L'hôte doit **tenir lui-même la position du chariot** : la machine n'a d'autonomie que pour l'avance après frappe (`80 <n>`). C'est ce que fait notre suivi de `self.col`.

## Force de frappe : elle varie selon le caractère

Le listing donne, pour chaque caractère, le couple `<rayon> <force>`. Les forces employées vont de **`0x0C` (12) à `0x19` (25)** — un `l` ou un `.` frappe doucement, un `M`, un `W` ou un `&` frappe fort. Extraits :

```asm
dc.b $02,$8E   ; ,      (force 14)
dc.b $05,$92   ; l      (force 18)
dc.b $37,$99   ; M      (force 25)
dc.b $5E,$94   ; a      (force 20)
dc.b $83,0     ; caractère absent de la marguerite -> simple espace
```

Le `$80` de poids fort est le bit « exécuter l'avance ». **Notre `FORCE = 40` (`0x28`) est très au-dessus de toute la plage d'origine** — piste pour réduire le bruit, l'usure du ruban et le marquage du papier, voire pour une table de force par caractère.

Autre détail réutilisable : un caractère absent de la marguerite est rendu par **`83 00`** (un espace d'un pas), jamais ignoré silencieusement.

## Couche ESC (interface IFD1, pas le fil)

⚠️ Ces séquences sont ce que la **boîte IFD1** acceptait de l'ordinateur ; elle les traduisait vers les commandes ci-dessus. Elles ne circulent **pas** sur notre liaison — mais elles décrivent bien le jeu de fonctions à offrir côté API, et comment les réaliser.

| Séquence | Fonction | Réalisation |
|---|---|---|
| `ESC 9` | marge gauche | fixée à la position courante du chariot |
| `ESC D` / `ESC U` | exposant / indice | demi-interligne arrière / avant |
| `ESC LF` | interligne inverse | une ligne en arrière |
| `ESC W` / `ESC &` | gras on/off | **chaque caractère frappé deux fois**, avec 1/120" de décalage entre les deux |
| `ESC E` / `ESC R` | soulignement on/off | un trait de soulignement frappé en plus du caractère |
| `ESC US <x>` | pas d'écriture | `x+1` pas (10 cpi → x=13, 12 → 11, 15 → 9, 6 → 23) |
| `ESC RS <x>` | interligne | `x+1` pas de 1/96" (ligne normalisée : x=17) |

Le gras et le soulignement se ramènent donc, chez nous, à la surimpression (`bit7 = 0` sur l'octet de force) — implémentables sans rien de nouveau côté protocole.

Non réalisés par l'auteur, et pour de bonnes raisons : impression bidirectionnelle (secousse mécanique) et proportionnelle (exige une marguerite spéciale).

## Avertissement de l'auteur, qu'on a vérifié à nos dépens

> Si la machine reçoit des caractères dont elle ne peut rien faire, elle ne les ignore pas toujours : il lui arrive de **planter**, et seul un cycle secteur la récupère.

C'est exactement le « sapin de Noël » du journal (désynchronisation par octet perdu). D'où sa recommandation : n'allumer la machine qu'une fois l'hôte stabilisé.
