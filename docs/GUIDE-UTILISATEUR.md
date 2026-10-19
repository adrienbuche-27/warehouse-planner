# Guide d'utilisation

Ce guide explique comment utiliser l'application au quotidien, étape par étape. Il s'adresse
aux personnes qui gèrent l'entrepôt : réservations, placement des véhicules, facturation et
suivi. L'installation est décrite dans [INSTALLATION-WINDOWS.md](INSTALLATION-WINDOWS.md).

## Sommaire

1. [Vue d'ensemble](#1-vue-densemble)
2. [Premiers réglages](#2-premiers-réglages-une-seule-fois)
3. [Prendre une réservation](#3-prendre-une-réservation)
4. [Vérifier les documents](#4-vérifier-la-pièce-didentité-et-lassurance)
5. [Facturer et suivre les paiements](#5-facturer-et-suivre-les-paiements)
6. [Entrée du véhicule](#6-entrée-du-véhicule)
7. [Fin du stockage : prolonger ou sortir](#7-fin-du-stockage--prolonger-ou-sortir)
8. [Corriger une erreur](#8-corriger-une-erreur)
9. [Gérer l'espace](#9-gérer-lespace)
10. [Le suivi quotidien : tableau de bord](#10-le-suivi-quotidien--le-tableau-de-bord)
11. [Ce que l'application fait toute seule](#11-ce-que-lapplication-fait-toute-seule)
12. [Vocabulaire](#12-vocabulaire)

## 1. Vue d'ensemble

L'application s'ouvre dans le navigateur à l'adresse `http://localhost:8000` (raccourci
« Gestion Stockage » sur le bureau). Il faut se connecter avec son identifiant ; en cas
d'oubli, « Mot de passe oublié ? » envoie un lien par email.

Le menu en haut de chaque page donne accès à tout :

| Menu | À quoi ça sert |
|---|---|
| **Tableau de bord** | Ce qu'il faut faire aujourd'hui et dans les 14 prochains jours, les chiffres clés |
| **Planning** | L'occupation des rangées sur 6 mois, et le **Plan de l'entrepôt** |
| **Réservations** | La liste des réservations, **+ Nouvelle réservation** et **Trouver un emplacement** |
| **Clients** / **Véhicules** | Les fiches des clients et de leurs véhicules |
| **Factures** | Les factures et notes de crédit, payées ou non |
| **Paramètres** | Tarifs, informations de la société, textes des emails, rangées |

Le cycle d'un stockage, du premier contact à la sortie :

```
Réservation ──► Documents vérifiés ──► Facture émise ──► Entrée du véhicule
     (3)               (4)                  (5)                 (6)
                                                                 │
                     Sortie du véhicule ◄── Rappel de fin ◄──────┘
                      ou prolongation       (automatique)
                           (7)                  (11)
```

## 2. Premiers réglages (une seule fois)

Dans **Paramètres** :

1. **Entrepôt** : longueur d'une rangée (16 m par défaut), espace de sécurité entre deux
   véhicules (0,50 m) et durée d'une période (14 jours, à ne pas changer).
2. **Tarifs & TVA** : taille d'une tranche (2 m) et **prix par tranche et par période**.
   Exemple : 12,00 € par tranche de 2 m ; un camping-car de 7,40 m compte 4 tranches (une
   tranche entamée compte entière), soit 48,00 € HTVA par période. Puis le régime de TVA et le
   délai de paiement des factures.
3. **Société (mentions sur factures)** : dénomination, adresse, numéro de TVA, BCE, IBAN… Ces
   informations sont obligatoires pour émettre une facture.
4. **Rappels** : adresses email des administrateurs, délai du rappel (14 jours avant la fin),
   objet et texte de l'email envoyé aux clients.
5. Cliquer **Enregistrer les paramètres**, puis **Envoyer un email de test** pour vérifier
   que les emails partent bien.
6. **Rangées** (en bas de la page) : indiquer le nombre de rangées et cliquer **Créer les
   rangées** (R01, R02…). Une rangée plus courte ou plus longue que les autres se règle dans
   le tableau (**Modifier**).

Modifier un tarif plus tard ne change jamais les réservations ni les factures déjà faites.

## 3. Prendre une réservation

### Étape 1 – Trouver un emplacement (conseillé)

**Réservations → Trouver un emplacement** :

1. Indiquer la **date d'entrée**, le **nombre de périodes** (de 14 jours) et la **longueur du
   véhicule** (ou choisir un véhicule déjà enregistré).
2. Cliquer **Chercher**. L'application affiche :
   - les **5 meilleurs emplacements**, avec l'occupation de la rangée et les véhicules
     éventuellement à déplacer ;
   - le **plan de l'entrepôt** sur la période : chaque rangée est marquée ✓ (le véhicule y
     tient), ★ (parmi les meilleures propositions), ⚠ (il y tient mais des véhicules devront
     être déplacés : le détail est sous la rangée) ou ✗ (pas assez de place).
3. Cliquer **Réserver ici** (ou sur une rangée du plan) : le formulaire de réservation s'ouvre
   avec la rangée, la position et les dates déjà remplies.

Les meilleurs emplacements sont ceux où personne ne doit être déplacé, puis ceux qui laissent
le moins de place perdue. Les véhicules qui partent plus tard sont placés plus au fond.

### Étape 2 – Le formulaire de réservation

**Réservations → + Nouvelle réservation** (ou depuis l'étape 1) :

1. **Client** : le choisir dans la liste. S'il n'existe pas encore, cliquer **+ Nouveau
   client**, remplir la fiche (adresse et téléphone obligatoires ; numéro de TVA pour une
   entreprise) et l'ajouter : il est sélectionné et le formulaire du véhicule s'ouvre.
2. **Véhicule** : le choisir, ou **+ Nouveau véhicule** (plaque et longueur obligatoires).
3. **Dates** : date d'entrée et nombre de périodes. La date de fin, le nombre de tranches et
   le prix (HTVA, TVA, TVAC) s'affichent tout de suite.
4. **Emplacement** : déjà rempli si vous venez de l'étape 1. Sinon, cliquer sur une rangée du
   plan affiché sous le formulaire, ou sur **Proposer un emplacement**. Position 1 = la plus
   proche de l'allée.
5. Cliquer **Créer la réservation**.

L'application refuse un emplacement où le véhicule ne tient pas. Si l'emplacement oblige à
déplacer d'autres véhicules à l'entrée ou à la sortie, elle affiche le plan de déplacement et
demande de cocher « Je confirme » avant d'enregistrer.

## 4. Vérifier la pièce d'identité et l'assurance

À faire **pour chaque réservation**, même pour un client ou un véhicule déjà connu. Les copies
papier sont classées dans le dossier : l'application n'enregistre que le résultat.

Sur la page de la réservation, bloc **Documents** :

1. Pour la **Pièce d'identité** puis l'**Assurance** (valable pour toute la période), cliquer
   **✓ Valide**, **✗ Invalide** ou **Manquant**.
2. Une remarque peut être ajoutée avant de cliquer (exemple : « attestation au nom du
   conjoint »).
3. L'application note qui a vérifié et quand.

Une nouvelle réservation commence avec les deux documents « Manquant ». Les réservations à
compléter sont listées sur le tableau de bord et dans **Réservations**, filtre « Documents à
compléter ».

## 5. Facturer et suivre les paiements

1. Sur la page de la réservation, cliquer **Créer la facture**. Un **brouillon** est créé,
   avec une ligne détaillée (exemple : « Stockage camping-car AB-123-CD – 7,40 m, soit
   4 tranches de 2 m × 12,00 € – du 01/03/2027 au 11/04/2027 – 3 périodes de 14 jours »).
2. Vérifier le brouillon ; **Modifier** permet de corriger les lignes. Un brouillon n'a pas
   encore de numéro et peut être supprimé.
3. Cliquer **Émettre** : la facture reçoit son numéro définitif (2027-0001, 2027-0002…), le PDF
   est créé et la facture **ne peut plus être modifiée ni supprimée**. L'application refuse
   d'émettre tant que les informations de la société (Paramètres) ou l'adresse du client
   manquent, et indique quoi compléter.
4. **Télécharger le PDF** ou **Envoyer par email** au client.
5. À réception du paiement : **Marquer payée** (date, mode : virement, espèces ou autre).
   **Annuler le paiement** corrige une erreur de saisie.

**Factures** liste toutes les factures, avec des filtres (payées, en retard…) et les totaux.
**+ Facture manuelle** sert pour une facture qui n'est pas liée à une réservation.

## 6. Entrée du véhicule

Le jour où le véhicule arrive, sur la page de la réservation :

1. Vérifier que les documents sont « Valide » (voir 4).
2. Si l'entrée est bloquée (⚠ en haut de la page), suivre le plan de déplacement : déplacer
   d'abord les véhicules indiqués, dans l'ordre, puis les replacer dans l'ordre inverse.
3. Cliquer **Marquer en stock** avec la date d'entrée effective. La réservation passe de
   « Réservée » à « En stock ».

## 7. Fin du stockage : prolonger ou sortir

Environ 14 jours avant la fin, un **rappel** part automatiquement : un email au client (lui
demandant de confirmer la sortie ou de prolonger) et un email aux administrateurs, avec le
plan de déplacement si le véhicule est bloqué (voir 11).

**Le client prolonge** :

1. Sur la réservation, **Prolonger** : indiquer le nombre de périodes à ajouter. Si la
   prolongation oblige à déplacer des véhicules, cocher « Je confirme la prolongation ».
2. Cliquer **Facturer N période(s) non facturée(s)** pour créer la facture complémentaire,
   puis l'émettre comme d'habitude (voir 5). Le prix par période reste celui de la réservation.

**Le client reprend son véhicule** :

1. Si la sortie est bloquée, suivre le plan de déplacement affiché sur la réservation.
2. Cliquer **Marquer sortie** avec la date de sortie effective. La réservation passe à
   « Terminée » et la place est libérée.

Une réservation qui n'a pas encore commencé peut être annulée : **Annuler la réservation**.

## 8. Corriger une erreur

| Situation | Que faire |
|---|---|
| Mauvaise date, rangée ou position (avant l'entrée ou pendant le stockage) | Réservation → **Modifier** |
| Longueur du véhicule erronée | Véhicules → **Modifier** la longueur. Si la réservation n'est pas encore facturée, le prix est recalculé automatiquement (un message l'indique). Si le véhicule plus long ne tient plus dans sa rangée, l'application le signale et demande **Enregistrer quand même** : déplacez ensuite la réservation |
| Erreur sur un **brouillon** de facture | **Modifier** ou **Supprimer le brouillon**, puis **Créer la facture** à nouveau |
| Erreur sur une facture **émise** | Ouvrir la facture → **Créer une note de crédit** (indiquer le motif), vérifier ses lignes (on peut ne créditer qu'une partie) et l'**Émettre**. Si elle couvre toute la facture, celle-ci passe à « Annulée ». Créer ensuite une nouvelle facture correcte |
| Client ou véhicule à retirer | **Archiver** (il disparaît des listes ; **Restaurer** le fait revenir). La suppression est refusée dès qu'il a des réservations ou des factures |

Une facture émise ne se modifie jamais : c'est une obligation légale. La correction passe
toujours par une note de crédit.

## 9. Gérer l'espace

**Planning** montre chaque rangée sur 13 périodes de 2 semaines (environ 6 mois) :

- chaque case donne l'occupation maximale de la rangée sur la période (ex. `13,5 / 16 m`), en
  vert (moins de 70 %), orange (70 à 95 %) ou rouge (plus de 95 %) ;
- ⚠ signale un véhicule bloqué à l'entrée ou à la sortie pendant cette période ;
- un clic sur une case affiche les véhicules de la rangée, leurs dates et les plans de
  déplacement, avec **Nouvelle réservation ici** ;
- « Espace libre min. » ne garde que les rangées où il reste au moins autant de place (utile
  pour un grand véhicule).

**Planning → Plan de l'entrepôt** dessine l'entrepôt vu de dessus : une bande par rangée,
l'allée à gauche, chaque véhicule à sa position et à sa taille.

- Choisir un jour, ou une période « du … au … » pour voir tous les véhicules présents à un
  moment (les véhicules présents seulement une partie du temps sont en clair).
- Les véhicules bloqués à l'entrée ou à la sortie sont marqués ⚠ ; le détail des déplacements
  est sous la rangée.
- Clic sur un véhicule : sa réservation. Clic sur la place libre d'une rangée : une nouvelle
  réservation à cet endroit.
- **Imprimer** donne une version papier du plan (par exemple pour l'entrepôt).

Le Plan de l'entrepôt sert à **gérer l'espace** ; pour **placer un nouveau véhicule**,
utiliser **Trouver un emplacement** (voir 3).

## 10. Le suivi quotidien : le tableau de bord

À ouvrir chaque matin. Il montre :

- **les chiffres du jour** : occupation de l'entrepôt, mètres libres, réservations en cours,
  factures impayées et factures en retard ;
- **Fin de stockage dans les 14 prochains jours** : les véhicules qui vont sortir, si le
  rappel a été envoyé, et ⚠ si la sortie est bloquée ;
- **Prochaines entrées** : les véhicules attendus, avec ⚠ si l'entrée est bloquée ;
- **Documents à compléter** : les véhicules en stock ou attendus dont la pièce d'identité ou
  l'assurance n'est pas « Valide » ;
- **les rappels en échec** (email non parti), à vérifier ;
- deux graphiques : l'occupation prévue et le chiffre d'affaires mensuel.

**Réservations → Historique des rappels** liste tous les emails de rappel envoyés ou tentés.

## 11. Ce que l'application fait toute seule

Quand le PC est allumé, trois tâches tournent sans intervention :

| Quand | Quoi |
|---|---|
| À l'ouverture de la session Windows | L'application démarre |
| Chaque jour à 08:00 | Les **rappels de fin de stockage** : email au client et aux administrateurs, une seule fois par réservation. Si le PC était éteint, les rappels en retard partent dès qu'il est rallumé. Les administrateurs reçoivent aussi un résumé quand une entrée prochaine est bloquée |
| Chaque jour à 19:00 | La **sauvegarde** de toutes les données (dans le dossier de sauvegarde, gardée 30 jours) |

La restauration d'une sauvegarde est décrite dans
[INSTALLATION-WINDOWS.md](INSTALLATION-WINDOWS.md).

## 12. Vocabulaire

| Terme | Signification |
|---|---|
| **Période** | 14 jours. Une réservation dure un nombre entier de périodes |
| **Tranche** | Part de la longueur du véhicule (2 m par défaut) servant au prix. Une tranche entamée compte entière : 7,40 m = 4 tranches |
| **Rangée** | Une bande de l'entrepôt où les véhicules se garent l'un derrière l'autre, accessible d'un seul côté (l'allée) |
| **Position** | Place dans la rangée : 1 = la plus proche de l'allée |
| **Bloqué** (⚠) | Un véhicule ne peut pas entrer ou sortir sans déplacer d'abord ceux placés devant lui |
| **Plan de déplacement** | Les véhicules à déplacer, dans l'ordre, puis à replacer dans l'ordre inverse |
| **Brouillon** | Facture pas encore émise : sans numéro, modifiable, supprimable |
| **Note de crédit** | Document qui annule tout ou partie d'une facture émise |
