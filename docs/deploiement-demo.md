# Démo publique ISBREE : publication GitHub et hébergement à 0 FCFA

Objectif : une **préproduction de démonstration** pour le portfolio, avec des données **fictives** uniquement. Ce n'est **pas** l'ouverture officielle aux familles : voir `docs/isbree-web.md` §5 pour ce qui manque avant une vraie mise en production.

Les décisions sont dans l'[ADR 0033](adr/0033-demo-publique-gratuite.md). Ce guide liste les actions, dans l'ordre. Les étapes marquées 👤 demandent une connexion de votre part : ne communiquez jamais vos mots de passe ou jetons, ni à une IA, ni dans un fichier du dépôt.

## Règle absolue : aucune carte bancaire

Si un fournisseur demande une carte, **arrêtez-vous à cette étape**. C'est aussi le cas pour une « vérification », un essai gratuit ou un « simple contrôle à 1 $ ». N'entrez aucune donnée de paiement, puis reportez-vous à la section « Plan B ». Les plans gratuits retenus ne facturent rien sans moyen de paiement enregistré : au-delà des limites, le service est suspendu, pas facturé.

## Étape 1 — Publier le dépôt sur GitHub 👤

L'audit du dépôt et de **tout** son historique a été fait avant publication : aucun secret, dump, APK, clé ou donnée de famille. Le détail est dans l'ADR 0033 §2.

1. Ouvrez un terminal dans le dossier du projet et lancez la commande ci-dessous. Répondez : `GitHub.com` → `HTTPS` → `Login with a web browser`. Copiez le code à 8 caractères, validez-le dans le navigateur, puis autorisez **GitHub CLI**.

   ```bash
   gh auth login
   ```

2. Vérifiez la connexion :

   ```bash
   gh auth status
   ```

3. Créez le dépôt **public** et poussez `main` avec tout son historique. Cette commande ne force rien et ne réécrit rien :

   ```bash
   gh repo create school-managing --public --source . --remote origin --push --description "School Managing : gestion scolaire (Django, PostgreSQL, PySide6, Flutter, Next.js) et démonstration ISBREE"
   ```

4. Publiez le tag existant, dont le contenu est contrôlé : c'est un point de l'historique de `main`.

   ```bash
   git push origin pre-i18n-phase
   ```

5. Vérifiez sur GitHub que le dépôt est **Public**, que les commits `4396539`, `c772f7f` et `24d1cff` apparaissent, et qu'aucun fichier `.env` n'est présent.

Adresse de commit : `git config user.email` vaut `ngoudagabriel180@gmail.com`. Si cette adresse n'est pas associée au compte GitHub (*Settings → Emails*), les commits ne seront pas reliés au profil. Ajoutez-la dans GitHub plutôt que de réécrire l'historique.

## Étape 2 — Base PostgreSQL de démo (Neon, gratuit sans carte) 👤

1. Sur <https://neon.com>, choisissez **Sign up**, de préférence **Continue with GitHub**, et gardez le plan **Free**.
2. Créez un projet nommé `isbree-demo`, en choisissant la région la plus proche (Europe, par exemple Frankfurt).
3. Créez la base `isbree_demo` (ou gardez `neondb`). C'est une base **neuve et vide** : n'y importez jamais la base `school` de développement.
4. Dans **Connect**, notez séparément l'hôte, la base, l'utilisateur et le mot de passe. Ils seront saisis à l'étape 3 dans le tableau de bord Render, nulle part ailleurs.

Limites du plan gratuit (relevées le 15/10/2026) :

- 1 Go de stockage par projet ;
- 100 h de calcul par mois et par projet ;
- mise en veille après 5 minutes d'inactivité ;
- 6 h d'historique de restauration ;
- pas d'expiration annoncée.

Ce n'est **pas** une sauvegarde durable : voir l'étape 6.

## Étape 3 — Services sur Render (offre Free) 👤

Le fichier [`render.yaml`](../render.yaml) décrit quatre services. Aucun secret n'y figure.

- `isbree-api` : Django, en image Docker. Au démarrage, il applique les migrations et charge les données de démo fictives.
- `isbree-redis` : Key Value gratuit, en mémoire seulement.
- `isbree-portal` : l'Espace ISBREE.
- `isbree-public` : le site public.

1. Sur <https://render.com>, choisissez **Get Started**, puis **GitHub**. **Si une carte est demandée : arrêtez** (voir le plan B).
2. Allez dans **New → Blueprint**, choisissez le dépôt `school-managing`, puis la branche `main`. Render lit `render.yaml`.
3. Remplissez les valeurs demandées, marquées `sync: false` dans `render.yaml` :

   | Service | Variable | Valeur |
   |---|---|---|
   | isbree-api | `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | valeurs Neon (étape 2) |
   | isbree-api | `ISBREE_DEMO_PASSWORD` | un mot de passe **nouveau**, ≥ 10 caractères, qui sera **publié** (comptes de démonstration en lecture seule) |
   | isbree-api | `ISBREE_ADMIN_PASSWORD` | un **autre** mot de passe long, **jamais publié** (compte `isbree.admin`). Le seed refuse de démarrer s'il est absent ou identique |
   | isbree-api | `ISBREE_CONTACT_EMAIL` | l'adresse de contact publique |
   | isbree-api | `ISBREE_PORTAL_URL` | URL du portail, par exemple `https://isbree-portal.onrender.com` (lue dans Render après création) |
   | portail et site | `DJANGO_INTERNAL_API_URL` | `https://<url de isbree-api>/api/v1` |
   | portail et site | `ISBREE_PUBLIC_URL`, `ISBREE_PORTAL_URL` | les deux URL Render |
   | isbree-portal | `ISBREE_DEMO_SHARED_PASSWORD` | **la même** valeur que `ISBREE_DEMO_PASSWORD`, affichée sur la page de connexion |

   `DJANGO_SECRET_KEY`, `WEB_BFF_TOKEN` et `PORTAL_SESSION_SECRET` sont **générés par Render**. Ils sont distincts de ceux du poste de développement et n'apparaissent dans aucun fichier.
4. Appliquez le Blueprint. Une fois les URL connues, complétez les variables d'URL, puis relancez chaque service (**Manual Deploy → Deploy latest commit**).

Limites de l'offre Free (relevées le 15/10/2026) :

- **Mise en veille :** chaque service s'endort après 15 minutes sans visite ; le premier accès prend environ une minute.
- **Heures partagées :** 750 heures d'instance par mois pour tout l'espace de travail. Au-delà, les services sont suspendus jusqu'au mois suivant, sans facturation en l'absence de moyen de paiement.
- **Pas de disque persistant :** les fichiers téléversés disparaissent au redémarrage. La démo n'utilise donc pas d'images téléversées : la galerie affiche « aucune image ».
- **Key Value en mémoire :** les compteurs de limitation de débit repartent à zéro à chaque redémarrage.
- **Usage :** Render indique que ces instances ne sont pas destinées à la production.

## Étape 4 — Vérifications en ligne (à faire après déploiement)

Ne déclarez pas la démo opérationnelle tant que ces points ne sont pas vérifiés sur les URL réelles.

| Contrôle | Attendu |
|---|---|
| `GET https://<api>/api/v1/health/` | 200 `{"status":"ok"}` |
| Logs `isbree-api` | migrations appliquées, seed « rien de nouveau » au 2e démarrage |
| Site public : accueil, À propos, Formations, Actualités, FAQ, Galerie, Contact, menu mobile | pages affichées, bandeau « Version de démonstration » |
| Préinscription | encadré « Démonstration », référence `PRE-…` reçue avec des données fictives |
| Portail sans session | `/espace/parent` → page de connexion ; en-têtes `X-Robots-Tag: noindex` et `Cache-Control: no-store` |
| Connexion `parent.demo@isbree.test` | espace Parent, enfant « Léa Démo », déconnexion |
| `/espace/enseignant` avec le compte Parent | « Espace non accessible » |
| Compte démo : toute écriture (ex. changer de mot de passe dans une application mobile) | refusée : 403 `DEMO_READ_ONLY` |
| Applications mobiles | « pas encore disponible » (aucun APK publié, aucun faux lien) |
| Adresse visiteur | une préinscription crée un événement de sécurité avec l'IP du visiteur et non celle de Render ; sinon ajuster `ISBREE_TRUSTED_PROXY_HOPS` |
| Contrôle de santé Render | si le service reste « unhealthy » alors que `/health/` répond, vérifier l'hôte utilisé par le contrôle (`DJANGO_ALLOWED_HOSTS`) |

## Étape 5 — Ajouter les liens réels dans le README

Seulement après l'étape 4 : complétez la section « Démonstration » du `README.md` avec les **vraies** URL (site, portail, dépôt, vidéo) et commitez. N'y mettez jamais un lien non vérifié.

## Étape 6 — Sauvegardes

| Quoi | Comment | Où |
|---|---|---|
| Code et historique | `git bundle create "C:\Users\<vous>\Documents\school-backups\SchoolManaging-AAAAMMJJ.bundle" --all` (déjà fait le 15/10/2026, vérifié). Restauration : `git clone SchoolManaging-AAAAMMJJ.bundle school-managing` | hors du dépôt |
| Base de démo (Neon) | `pg_dump "postgresql://USER:MOT_DE_PASSE@HÔTE/BASE?sslmode=require" -Fc -f isbree-demo-AAAAMMJJ.dump`, en tapant la chaîne dans votre terminal uniquement | hors du dépôt, jamais sur GitHub |
| Restauration de la démo | `pg_restore --no-owner --clean --if-exists -d "postgresql://…" isbree-demo-AAAAMMJJ.dump`, ou relancer simplement le service : le seed recrée les données fictives | — |
| Base de développement `school` | runbook existant (`docs/database-runbook.md`) | hors du dépôt |
| Fichiers téléversés | `backend/private-media/` en local (ignoré par Git) ; aucun en démo | hors du dépôt |

Ne doivent **jamais** entrer dans Git : `.env`, `.env.local`, `.env.isbree.local`, les dumps, `private-media/`, `media/`, les APK, les keystores, les vidéos.

La démo gratuite n'a pas de sauvegarde automatique au-delà des 6 h d'historique Neon. Ce n'est **pas** un stockage pour de vrais dossiers familiaux.

## Plan B (si une carte est demandée)

- **Site public seul :** sur Vercel Hobby (gratuit, sans carte, usage personnel non commercial), importez le dépôt avec *Root Directory* `web/isbree-public` et les mêmes variables que ci-dessus.
- **API Django et portail :** il faut un hébergeur gratuit **sans carte** qui accepte un conteneur, ce qui reste à trouver au moment voulu. À défaut, présentez le portail par la **vidéo** (`docs/video-demo.md`), sans exposer le poste local sur Internet.
- **Base :** même sans hébergeur d'application, ne réutilisez jamais la base `school` de développement.
