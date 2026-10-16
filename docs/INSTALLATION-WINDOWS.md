# Installation sur un PC Windows

Ce guide installe **Gestion Stockage Camping-Cars** sur un seul PC Windows 10 ou 11.
L'application fonctionne entièrement sur ce PC : pas de serveur, pas de nom de domaine.
On l'ouvre dans le navigateur à l'adresse **http://localhost:8000**.

Compter environ 30 minutes. Les étapes 1 à 3 ne se font qu'une fois.

> **À savoir**
> - Le PC doit être **allumé et la session ouverte** pour que les rappels partent (tous les
>   jours à 8 h). S'il était éteint, les rappels manqués partent au démarrage suivant.
> - Une **connexion internet** est nécessaire pour envoyer les emails ; tout le reste fonctionne
>   sans internet.
> - Toutes les données sont dans le dossier de l'application : les **sauvegardes quotidiennes**
>   (étape 7) sont indispensables.

---

## 1. Installer Python

1. Télécharger **Python 3.12** (ou plus récent) sur <https://www.python.org/downloads/windows/>
   (« Windows installer (64-bit) »).
2. Lancer l'installateur et **cocher « Add python.exe to PATH »** en bas de la première fenêtre,
   puis « Install Now ».

## 2. Installer les bibliothèques des factures PDF (MSYS2)

Les factures PDF sont produites par WeasyPrint, qui a besoin des bibliothèques « Pango ».
Sous Windows, elles s'installent avec MSYS2 :

1. Télécharger l'installateur sur <https://www.msys2.org/> et l'installer **dans le dossier
   proposé, `C:\msys64`**.
2. À la fin, une fenêtre noire « MSYS2 » s'ouvre (sinon : menu Démarrer → « MSYS2 MSYS »).
   Y taper la commande suivante, puis Entrée, et répondre `O` (ou `Y`) si une question est posée :

   ```
   pacman -S mingw-w64-x86_64-pango
   ```
3. Fermer la fenêtre MSYS2.

## 3. Copier l'application sur le PC

Créer le dossier **`C:\GestionStockage`** et y mettre les fichiers de l'application :

- **Sans Git** : sur la page GitHub du projet, bouton **Code → Download ZIP**, puis extraire le
  contenu du zip dans `C:\GestionStockage` (le fichier `manage.py` doit se trouver directement
  dans `C:\GestionStockage`).
- **Avec Git** : `git clone <adresse du dépôt> C:\GestionStockage`

> **Ne pas placer ce dossier dans OneDrive, Google Drive ou Dropbox.** La synchronisation d'une
> base de données en cours d'utilisation peut l'abîmer. Seules les *sauvegardes* vont dans le
> cloud (étape 7).

## 4. Lancer l'installation

1. Ouvrir le dossier `C:\GestionStockage` dans l'Explorateur, cliquer dans la barre d'adresse,
   taper `powershell` puis Entrée : une fenêtre PowerShell s'ouvre dans ce dossier.
2. Taper :

   ```
   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
   ```
3. Le script :
   - vérifie Python et installe les composants nécessaires ;
   - demande le **dossier des sauvegardes** (Entrée pour accepter la proposition, par exemple
     `OneDrive\Sauvegardes Stockage`) ;
   - crée la base de données et demande de créer le **premier utilisateur** (nom, email, mot de
     passe : c'est le compte qui servira à se connecter) ;
   - enregistre trois **tâches planifiées** Windows :
     | Tâche | Quand | Rôle |
     |---|---|---|
     | Stockage - application | à chaque ouverture de session | démarre l'application |
     | Stockage - rappels | tous les jours à 8 h | envoie les rappels de fin de stockage |
     | Stockage - sauvegarde | tous les jours à 19 h | sauvegarde les données |
   - crée le raccourci **« Gestion Stockage »** sur le bureau et ouvre l'application.

Le script peut être relancé sans risque : il ne refait que ce qui manque.

## 5. Configurer l'envoi des emails

Ouvrir le fichier `C:\GestionStockage\.env` avec le Bloc-notes et compléter la partie
« Envoi des emails » avec les informations de la boîte mail de la société :

| Fournisseur | `EMAIL_HOST` | `EMAIL_PORT` | Remarque |
|---|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` | `587` | utiliser un **mot de passe d'application** (compte Google → Sécurité) |
| Outlook / Microsoft 365 | `smtp.office365.com` | `587` | l'envoi SMTP doit être autorisé sur le compte |
| Autre (Brevo, OVH, Combell…) | voir le fournisseur | `587` | |

```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=contact@ma-societe.be
EMAIL_HOST_PASSWORD=le-mot-de-passe-d-application
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=contact@ma-societe.be
```

Enregistrer, puis **redémarrer le PC** (ou fermer et rouvrir la session) pour que l'application
relise la configuration. Dans l'application : **Paramètres → Envoyer un email de test**.

> Utiliser la même adresse dans `EMAIL_HOST_USER`, `DEFAULT_FROM_EMAIL` et dans
> Paramètres → Société → Email : la plupart des fournisseurs refusent un expéditeur différent.

## 6. Premiers réglages dans l'application

Dans **Paramètres** :
1. **Société** : dénomination, adresse, TVA, BCE, IBAN… (obligatoires pour émettre des factures).
2. **Tarifs & TVA** : prix par période.
3. **Rappels** : emails des administrateurs, texte de l'email aux clients.
4. **Rangées** : « Créer les rangées ».

## 7. Sauvegardes

Chaque soir à 19 h, une sauvegarde complète (base de données + factures PDF + logo) est créée
dans le dossier choisi à l'étape 4 : `sauvegarde-AAAAMMJJ-HHMMSS.zip`. Les 30 derniers jours sont
conservés. Si le dossier est dans OneDrive (ou Google Drive, Dropbox), une copie part
automatiquement dans le cloud.

- **Vérifier de temps en temps** que des fichiers récents arrivent dans ce dossier.
- Sauvegarde manuelle, à tout moment : dans PowerShell, dans `C:\GestionStockage` :
  ```
  .venv\Scripts\python.exe manage.py backup_data
  ```

### Restaurer une sauvegarde

1. Arrêter l'application : dans PowerShell, `Stop-ScheduledTask "Stockage - application"`.
2. Dans `C:\GestionStockage` :
   ```
   .venv\Scripts\python.exe manage.py restore_backup "C:\...\sauvegarde-20270310-190000.zip"
   ```
   et taper `OUI`. Les données actuelles sont d'abord copiées (`avant-restauration-….zip`, dans
   le même dossier), ce qui permet d'annuler une restauration.
3. Redémarrer l'application : `Start-ScheduledTask "Stockage - application"` (ou redémarrer le PC).

**Sur un nouveau PC** (panne, vol) : refaire les étapes 1 à 4, puis restaurer la dernière
sauvegarde comme ci-dessus.

## 8. Mettre à jour l'application

1. Remplacer les fichiers de l'application par la nouvelle version :
   - avec Git : rien à faire, le script s'en charge ;
   - avec un ZIP : extraire la nouvelle version **par-dessus** `C:\GestionStockage`, sans
     supprimer `.env`, `db.sqlite3`, `media\`, `logs\` ni `.venv\`.
2. Dans PowerShell, dans `C:\GestionStockage` :
   ```
   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
   ```
   Le script fait une sauvegarde, arrête l'application, met à jour la base et la redémarre.

## 9. Dépannage

| Problème | Que faire |
|---|---|
| La page http://localhost:8000 ne s'ouvre pas | Redémarrer le PC. Sinon, ouvrir le « Planificateur de tâches » et vérifier la tâche « Stockage - application ». Voir `logs\app.log`. |
| « Accès refusé » lors de l'installation des tâches | Relancer PowerShell **en tant qu'administrateur** puis l'étape 4. (À défaut, le script démarre l'application via le dossier Démarrage de Windows.) |
| Les scripts refusent de s'exécuter | Toujours les lancer avec `powershell -ExecutionPolicy Bypass -File …` |
| Erreur à la création d'un PDF | Refaire l'étape 2, vérifier que `.env` contient `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin`, redémarrer le PC. |
| Les rappels ne partent pas | Tableau de bord (encadré rouge) et **Historique des rappels** ; fichier `logs\send_reminders.log` ; « Envoyer un email de test » dans Paramètres. |
| La sauvegarde échoue | `logs\backup_data.log` ; vérifier que OneDrive (ou autre) est bien installé et connecté. |
| Le port 8000 est déjà utilisé | Mettre par exemple `APP_PORT=8010` dans `.env`, relancer l'étape 4 (le raccourci est mis à jour). |

## 10. Données de démonstration (présentation uniquement)

Pour présenter l'application sur un PC **qui ne contient pas encore de vraies données** :

```
.venv\Scripts\python.exe manage.py seed_demo --force
```

Cela crée des rangées, clients, réservations et factures fictifs (environ 20 secondes).
**Ne jamais le faire sur l'installation réelle** : avant la mise en service, repartir d'une
installation propre : arrêter l'application (`Stop-ScheduledTask "Stockage - application"`),
supprimer `db.sqlite3` et `media\`, puis relancer l'étape 4.

## 11. Désinstaller

```
powershell -ExecutionPolicy Bypass -File deploy\windows\uninstall.ps1
```

Retire les tâches planifiées et le raccourci. Les données et les sauvegardes sont conservées.
