# Projet IFD-2 — spécificités

La persona et les règles générales de collaboration sont dans `~/.claude/CLAUDE.md`
(niveau utilisateur, chargé automatiquement en plus de ce fichier). Ce qui suit est
spécifique à ce projet.

- **`docs/journal.md` fait autorité** pour l'état du projet : chaque essai, attendu,
  observé, conclusion. Le lire avant d'agir ; le mettre à jour après chaque jalon.
- **Préférer les tableaux aux schémas visuels** pour le câblage — confirmé plus lisible
  pour l'utilisateur que les diagrammes.
- **Sécurité électrique non négociable** : jamais les broches B (+12 V) et E (+42 V) de
  la prise DIN de la Xerox 575 sur de l'électronique logique. Câblage machine hors
  tension ; vérification à vide avant toute mise sous tension.
- Tout câblage proposé : tableau trou-par-trou + « ne PAS brancher » + une mesure de
  vérification avant le vrai test.

**Méta-règle** : si l'utilisateur dit « on tourne en rond » → alarme prioritaire : stop,
refaire le point hypothèses/plan au lieu de proposer l'essai suivant.
