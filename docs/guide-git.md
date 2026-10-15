# Git et GitHub : fiche pratique

Cette fiche sert à travailler seul sur ses projets, sans assistant. Les exemples se tapent dans un terminal ouvert dans le dossier du projet.

## 1. Les notions

| Terme | Ce que c'est |
|---|---|
| **Dépôt local** | Le dossier du projet plus son historique, dans le sous-dossier caché `.git`. Tout fonctionne sans Internet. |
| **Commit** | Une photo enregistrée de l'état du projet, avec un message, un auteur et une date. L'historique est une suite de commits. |
| **Branche** | Une ligne de travail : un nom qui pointe vers un commit et avance à chaque nouveau commit (`main`, `feature/contact`…). |
| **Remote** | Un dépôt distant connu de votre dépôt local, en général `origin` sur GitHub. |
| **Push** | Envoyer vos commits locaux vers le remote. |
| **Pull** | Récupérer les commits du remote et les intégrer à votre branche (*fetch* puis *merge*). |
| **GitHub public** | Le dépôt distant est visible par tout le monde, avec **tout l'historique** : un secret commité une fois reste lisible, même s'il est effacé ensuite. |
| **Déploiement** | Faire tourner l'application sur un serveur (Render, Vercel…). C'est différent de GitHub : GitHub garde le **code**, l'hébergeur **exécute** l'application. |

## 2. Les commandes essentielles

```bash
git status                     # où j'en suis : fichiers modifiés, ajoutés, non suivis
git diff                       # ce qui a changé et n'est pas encore ajouté
git diff --staged              # ce qui partira dans le prochain commit
git log --oneline --graph --all  # l'historique en arbre, toutes branches
git add chemin/fichier.py      # ajouter UN fichier au prochain commit (préférer à « git add . »)
git commit -m "feat: page contact"   # enregistrer le commit
git push                       # envoyer vers GitHub (la 1re fois : git push -u origin main)
git pull                       # récupérer le travail distant
git branch                     # lister les branches ; git branch nom = en créer une
git switch nom-branche         # changer de branche (git switch -c nom = créer et y aller)
git merge nom-branche          # intégrer une branche dans la branche courante
git restore fichier.py         # annuler MES modifications non commitées d'un fichier (irréversible)
git restore --staged fichier.py  # retirer un fichier du prochain commit (garde les modifications)
git stash push -m "essai"      # mettre de côté des modifications ; git stash pop pour les reprendre
git remote -v                  # voir les dépôts distants
```

Une journée type :

1. `git switch -c feature/x` pour créer une branche de travail ;
2. vous codez ;
3. `git status`, puis `git diff`, pour relire ;
4. `git add fichiers`, puis `git commit -m "…"` ;
5. `git push -u origin feature/x`, puis une *pull request* sur GitHub, ou `git switch main` suivi de `git merge feature/x` ;
6. enfin `git push`.

## 3. Ne jamais publier de secret

- Les secrets (mots de passe, clés, jetons, chaînes de connexion) vont dans des fichiers **`.env` ignorés** (`.gitignore`), jamais dans le code. On versionne seulement un **`.env.example`** avec des valeurs vides.
- Avant chaque commit, lancez `git status` puis `git diff --staged`. Un `.env`, un `.dump`, un `.apk`, une clé `.jks` ou `.pem` ne doivent jamais apparaître.
- Évitez `git add .` tant que `git status` n'a pas été relu.
- Si un secret a été commité :
  1. considérez-le **compromis** et changez-le chez le fournisseur (révocation) ;
  2. ensuite seulement, demandez-vous s'il faut nettoyer l'historique (`git filter-repo`). Supprimer le fichier dans un nouveau commit ne suffit pas.
- GitHub ne doit pas servir de sauvegarde de base de données ou de fichiers privés.

## 4. Dépanner sans risque

- **« Je ne sais plus où j'en suis »** : `git status` et `git log --oneline -5`.
- **Annuler le dernier commit en gardant le travail** : `git reset --soft HEAD~1`. Uniquement s'il n'a **pas** été poussé.
- **Conflit au merge ou au pull** : ouvrez les fichiers marqués, gardez la bonne version entre `<<<<<<<` et `>>>>>>>`, puis `git add` et `git commit`.
- **À éviter sans être sûr de soi :** `git reset --hard`, `git clean -fd` et `git push --force`. Ils effacent du travail ou réécrivent l'historique des autres.
- **Sauvegarder tout le dépôt dans un fichier :** `git bundle create ..\sauvegarde.bundle --all`. Pour le restaurer : `git clone sauvegarde.bundle projet`.
