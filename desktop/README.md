# Poste d'administration (PySide6)

Client desktop officiel de l'administration de l'école. Il consomme **uniquement l'API Django** (`/api/v1/`) : il n'accède pas à PostgreSQL, n'a pas de base locale et ne duplique aucune règle métier.

## Installation (Windows, PowerShell)

```powershell
cd desktop
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Python 3.12 ou plus récent. Les dépendances sont PySide6, httpx et keyring ; pytest et ruff pour le développement.

## Configuration de l'URL du backend

L'URL est cherchée dans cet ordre :

1. la variable d'environnement `SCHOOL_ADMIN_API_URL`, par exemple `http://127.0.0.1:8000/api/v1/` ;
2. `api_url` dans `%APPDATA%\SchoolManagingDesktop\desktop.json` :
   ```json
   {"api_url": "https://ecole.lan/api/v1/", "timeout": 10}
   ```
3. par défaut, `http://127.0.0.1:8000/api/v1/` (backend de développement `docker compose up`).

En HTTP vers une autre machine, l'écran de connexion affiche un avertissement : utilisez HTTPS en production.

## Lancement en développement

```powershell
docker compose up -d            # à la racine du dépôt : backend sur http://127.0.0.1:8000
cd desktop
.venv\Scripts\python -m school_admin
```

## Compte de test

Utilisez le SUPER_ADMIN créé par `manage.py bootstrap_school` (sur la base de développement actuelle : identifiant `admin`, école `TEST01`). Son mot de passe est celui saisi lors du bootstrap. **Il n'est écrit nulle part dans le dépôt.**

## Tests

```powershell
.venv\Scripts\python -m pytest            # client API, authentification, services, écrans (hors affichage)
.venv\Scripts\python -m ruff check .
```

Le test de bout en bout contre un vrai backend est optionnel. Il crée :

- une catégorie et une matière ;
- une année lointaine (rendue courante, puis l'ancienne courante est rétablie et l'année de test clôturée) ;
- un niveau et une classe ;
- un élève (inscrit, avec photo), qui change de classe, est retiré puis archivé ;
- un enseignant (compte sans mot de passe) avec une matière ajoutée puis validée, désactivé puis réactivé.

À lancer contre un backend de **test** :

```powershell
$env:SCHOOL_ADMIN_E2E_URL = "http://127.0.0.1:8000/api/v1/"
$env:SCHOOL_ADMIN_E2E_USER = "admin"
$env:SCHOOL_ADMIN_E2E_PASSWORD = Read-Host -AsSecureString | ConvertFrom-SecureString -AsPlainText
.venv\Scripts\python -m pytest -m live
```

## Architecture

```
school_admin/
  config.py            URL du backend, délai réseau (aucun secret)
  api/                 client HTTP : enveloppe {success,data,meta}, pagination,
                       401 -> rafraîchissement du jeton puis reconnexion,
                       erreurs typées 400/401/403/404/409/429/5xx, hors ligne, délai dépassé
  auth/                connexion / rafraîchissement / déconnexion via /auth/* (jetons du backend),
                       identifiant d'installation, coffre du système pour « rester connecté »
  models.py            objets de données (Identity, Category, Subject, AcademicYear, Level, SchoolClass,
                       Metric, ChartData…)
  services/            catalogue (catégories, matières), années et niveaux (structure.py), classes et
                       listes de référence, élèves (students.py : fiche, inscription, photo),
                       enseignants (teachers.py : fiche, qualifications, verdicts du serveur),
                       tableau de bord (indicateurs et séries réels de l'API)
  ui/                  écran de connexion, shell (barre latérale, en-tête), pages, dialogues,
                       exécution des appels hors du fil d'affichage, messages d'erreur uniformes
```

## Interface (thème unique)

`school_admin/ui/theme.py` est la seule source des couleurs et de la typographie (jetons `TOKENS` et `TYPE`). Le thème :

- impose le style Fusion et une palette claire, quel que soit le mode sombre de Windows ;
- vérifie les contrastes WCAG 2.1 par des tests (`tests/test_theme_dialogs.py`) : 4,5:1 pour les textes, 3:1 pour les bordures et le focus.

Rôles de boutons : `primary` (Ajouter, Enregistrer), `secondary` (Annuler, Actualiser, Modifier), `danger` (Désactiver).

Composants partagés dans `ui/widgets.py` : `button()`, `FormDialog`, `ConfirmDialog`, `Banner`. Graphiques du tableau de bord dans `ui/charts.py` (QPainter, couleurs du thème) :

- `LineChart` et `BarChart` ;
- `ChartCard`, avec quatre états : chargement, données, aucune donnée, erreur ;
- `ActivityCard`.

### Règle obligatoire : dialogues et petits écrans

Aucun dialogue ne doit sortir de l'écran. L'application reste utilisable en 1366×768, en 1280×720 et en 1024×768. Tout dialogue passe par `FormDialog` (ADR 0017 §5) :

- **Structure :** en-tête fixe, formulaire **défilant**, pied fixe (« * champ obligatoire », raison d'un bouton désactivé, Annuler / Enregistrer toujours visibles).
- **Champs :** `add_field(..., width="short" | "medium" | "long", beside=True)`. La largeur dépend de la donnée. Les champs côte à côte repassent sur une colonne quand le dialogue est étroit.
- **Clavier :** Tab parcourt les champs et fait défiler le formulaire ; Entrée enregistre ; Échap ferme.

Avant tout nouveau dialogue, posez-vous la question : « Peut-il être entièrement utilisé sur un écran 1280×720 ? ». Le test `tests/test_responsive.py` doit couvrir chaque nouveau dialogue.

Captures des vrais écrans contre un backend (revue visuelle) :

```powershell
$env:QT_QPA_FONTDIR = "C:/Windows/Fonts"
.venv\Scripts\python tools\capture_screens.py C:\temp\captures 1366x768 1920x1080
```

L'outil utilise les mêmes variables `SCHOOL_ADMIN_E2E_*` que le test de bout en bout. Il crée une catégorie, une matière et une classe ; les années, les niveaux et le tableau de bord sont seulement affichés.

## Sécurité

- **Mot de passe :** il n'est jamais stocké ; le champ est vidé dès l'envoi de la requête.
- **Jeton d'accès :** gardé en mémoire uniquement.
- **Jeton de rafraîchissement :** conservé seulement si « rester connecté » est coché, dans le coffre du système (Gestionnaire d'identifiants Windows), jamais dans un fichier. Il est révoqué côté serveur à la déconnexion.
- **Permissions :** le serveur décide. Le poste refuse seulement d'ouvrir le shell à un compte sans rôle ADMIN ou SUPER_ADMIN.
