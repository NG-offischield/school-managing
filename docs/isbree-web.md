# Site ISBREE et Espace ISBREE — guide d'exploitation

L'architecture et les décisions de sécurité sont dans l'[ADR 0032](adr/0032-site-isbree-et-espace-isbree.md). Ce guide couvre la configuration, le lancement local, les tests et les procédures d'administration.

| Application | Dossier | Port local | Rôle |
|---|---|---|---|
| Site public | `web/isbree-public` | 3000 | présentation, formations, actualités, préinscription |
| Espace ISBREE | `web/isbree-portal` | 3001 | portail authentifié Parent / Enseignant / Personnel / Gardien |
| API | `backend` (Docker) | 8000 | `public/…`, `portal/…`, `admin/website/…`, `admin/pre-enrollments/…` |
| Administration | `desktop` (PySide6) | — | module **Gestion → Site ISBREE** |

## 1. Configuration

### Backend (`.env` à la racine, voir `.env.example`)

| Variable | Rôle |
|---|---|
| `WEB_BFF_TOKEN` | secret partagé avec les deux serveurs Next. Vide = Django ignore l'adresse visiteur qu'ils transmettent |
| `ISBREE_PORTAL_URL` | base des liens d'invitation `…/activation#code=…` |
| `PORTAL_INVITATION_LIFETIME_HOURS` | 48 par défaut |
| `PRE_ENROLLMENT_CONSENT_VERSION` | à changer quand le texte de confidentialité change |

### Site public (`web/isbree-public/.env.local`, voir `.env.example`)

`ISBREE_SCHOOL_CODE`, `DJANGO_INTERNAL_API_URL`, `ISBREE_PUBLIC_URL`, `ISBREE_PORTAL_URL`, `ISBREE_DEMO_MODE`, `WEB_BFF_TOKEN`, `ISBREE_TRUSTED_PROXY_HOPS`.

### Portail (`web/isbree-portal/.env.local`)

Les mêmes variables, plus `PORTAL_SESSION_SECRET` : au moins 32 caractères aléatoires. Le changer déconnecte tout le monde.

Les fichiers `.env*` réels ne sont **jamais** versionnés (seuls les `.env.example` le sont).

## 2. Lancement local

```bash
docker compose up -d                       # backend, base, redis
```

Données ISBREE : textes provisoires, plus `--demo` (comptes et lieux fictifs) et `--images` (illustrations). La commande est idempotente et refusée en production.

```bash
docker compose run --rm -e ISBREE_DEMO_PASSWORD=… -e ISBREE_CONTACT_EMAIL=… web python manage.py seed_isbree --demo --images /app/private-media/seed-images
```

```bash
cd web/isbree-public && npm install && npm run dev   # http://localhost:3000
```

```bash
cd web/isbree-portal && npm install && npm run dev   # http://localhost:3001
```

Comptes de démonstration (`--demo`) :

- `parent.demo@isbree.test` : enfant « Léa Démo », lien vérifié ;
- `enseignant.demo@isbree.test`, `personnel.demo@isbree.test`, `gardien.demo@isbree.test`.

Le mot de passe est celui passé dans `ISBREE_DEMO_PASSWORD`. En local, il est conservé dans `.env.isbree.local`, qui est ignoré par git.

## 3. Tests

| Suite | Commande | Prérequis |
|---|---|---|
| Backend | `docker compose run --rm web pytest` | base de test `db_test` |
| Unitaires web | `npm test` (dans chaque app) | — |
| Types / lint | `npm run typecheck && npm run lint` | — |
| E2E + accessibilité (axe) | `npm run test:e2e` | backend démarré, données `--demo`, Microsoft Edge installé (`E2E_BROWSER_CHANNEL` pour en changer) |
| Desktop | `.venv/Scripts/python -m pytest` dans `desktop` | — |
| Build | `npm run build` | backend joignable pour pré-rendre (sinon pages « indisponible » rafraîchies en quelques secondes) |

Tests E2E optionnels. Ils écrivent **réellement** dans la base de développement, donc ils sont désactivés par défaut :

- `E2E_SUBMIT=1 npx playwright test -g "receives a reference"` (site public) crée une préinscription `@e2e.isbree.test` ;
- `E2E_INVITE_LINK=… E2E_INVITE_LOGIN=… npx playwright test -g "family activates"` (portail) parcourt l'activation, puis la connexion de la famille. Il faut un lien d'invitation **neuf**, puisqu'il est à usage unique.

## 4. Procédures d'administration (desktop → Site ISBREE)

1. **Préinscriptions :**
   - « Changer le statut… » ne propose que les étapes permises ;
   - un motif est exigé pour refuser ou demander des informations ;
   - le message à la famille s'affiche dans son espace ;
   - « Inviter la famille… » n'est possible que sur une demande **acceptée**. Il crée le compte Parent sans enfant et affiche **une seule fois** le lien, valable 48 h. Le logiciel n'envoie **aucun e-mail** : remettez le lien vous-même ;
   - ensuite, inscrivez l'élève (« Élèves ») et validez le rattachement parent-enfant (« Parents »).
2. **Contenus (Pages, FAQ, Actualités, Ressources, Lieux) :**
   - « Ajouter » / « Modifier », puis « Publier » ; « Archiver » retire de l'affichage sans supprimer ;
   - laissez « Contenu provisoire » coché tant que l'établissement n'a pas validé le texte ;
   - une ressource peut être limitée à un niveau, une classe ou une année, et recevoir un PDF (« Joindre un PDF… »).
3. **Images :** « Ajouter » importe le fichier. Le texte alternatif est obligatoire. Cochez « Image d'illustration » pour toute image qui ne montre pas ISBREE.
4. **Applications :**
   - « Importer un APK… » n'accepte qu'un **APK de production signé** ;
   - un APK debug ou non signé est refusé par le serveur ;
   - publiez la version pour qu'elle apparaisse dans l'Espace ISBREE.
5. **Profil et publication :**
   - accroche, présentation, valeurs, horaires ;
   - cochez « adresse confirmée » seulement quand l'adresse est vérifiée ;
   - la liste « Avant l'ouverture » reprend `python manage.py isbree_readiness --school ISBREE`.

## 5. Avant une mise en production (non faite)

- Faire valider tous les textes par l'établissement : identité légale, directeur, frais, règlement, documents à fournir. Aucun n'a été inventé : les champs « [à compléter par l'établissement] » restent à remplir. Décocher ensuite « provisoire ».
- Dépublier ou archiver toutes les données de démonstration, et mettre `ISBREE_DEMO_MODE=false`.
- Remplacer les images d'illustration par de vraies photos autorisées, et le logo provisoire par le logo officiel.
- Signer les applications avec le keystore de l'établissement. Celui-ci est à créer et à conserver par l'établissement, jamais dans le dépôt. Puis publier les APK Release.
- HTTPS, domaines, et reverse proxy qui ajoute `X-Forwarded-For` (`ISBREE_TRUSTED_PROXY_HOPS=1`). Un seul processus Next pour le portail (voir ADR §1.5).
- Secrets `WEB_BFF_TOKEN` et `PORTAL_SESSION_SECRET` générés pour la production.
- `isbree_readiness` sans point bloquant.
