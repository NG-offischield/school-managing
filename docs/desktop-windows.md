# Client d'administration Windows : installateur et build

Le poste d'administration (`desktop/`, PySide6) est distribué sous la forme d'un **installateur Windows 10 / 11 64 bits** : l'utilisateur n'installe ni Python, ni PySide6, ni aucune dépendance.

C'est le même client que `python -m school_admin`. Il ne parle qu'à l'API Django (`/api/v1/`) : pas de base locale, pas d'accès à PostgreSQL ou Redis. L'authentification et les droits sont ceux du serveur. Un compte **administrateur** est nécessaire ; les comptes de démonstration du portail (parent, enseignant, personnel, gardien) n'y ont pas accès.

## Installer

Téléchargement de la version 0.1.0 (fichier public, non signé) : <https://github.com/NG-offischield/school-managing/releases/tag/desktop-admin-v0.1.0>, SHA-256 `4cd391cb0a4113e919faebeb22eca34e5f8651f3bdd98ae2e5a310c288f21d17`.

1. Lancez `SchoolManagingAdmin-Setup-<version>-x64.exe`.
   - L'installateur **n'est pas signé** : Windows SmartScreen peut afficher « Windows a protégé votre ordinateur ». Choisissez **Informations complémentaires → Exécuter quand même** si le fichier vient bien de ce projet (comparez son empreinte SHA-256 avec celle publiée).
2. Aucun droit administrateur n'est demandé : le programme s'installe pour votre compte dans `%LOCALAPPDATA%\Programs\School Managing Admin`.
3. **Page « Serveur »** (première installation seulement) : l'adresse de l'API. Par défaut, le serveur public de démonstration `https://isbree-api.onrender.com/api/v1/`. Elle est enregistrée dans `%APPDATA%\SchoolManagingDesktop\desktop.json`, avec un délai de 75 s, car l'hébergement gratuit met environ une minute à se réveiller.
4. Raccourci dans le menu Démarrer, raccourci bureau en option, lancement proposé en fin d'installation.

**Changer de serveur plus tard** : modifiez `api_url` dans `%APPDATA%\SchoolManagingDesktop\desktop.json`, ou définissez la variable `SCHOOL_ADMIN_API_URL`, puis relancez le programme. Le serveur utilisé est affiché sous le formulaire de connexion.

**Désinstaller** : Paramètres Windows → Applications → School Managing Admin, ou l'entrée du menu Démarrer. Le programme est retiré. Votre configuration (`desktop.json`) et le journal sont **conservés** ; une réinstallation ne les écrase pas.

## Données du poste

| Quoi | Où | Contenu |
|---|---|---|
| Programme | `%LOCALAPPDATA%\Programs\School Managing Admin` | `SchoolManagingAdmin.exe` et ses bibliothèques (Python, Qt) |
| Configuration | `%APPDATA%\SchoolManagingDesktop\desktop.json` | adresse de l'API, délai, langue, thème : aucun secret |
| Session (« Rester connecté ») | Gestionnaire d'identification Windows | jetons de session, jamais dans un fichier |
| Journal | `%LOCALAPPDATA%\SchoolManagingDesktop\logs\desktop.log` | version, serveur (schéma et hôte), erreurs inattendues : ni mot de passe, ni jeton (3 fichiers de 1 Mo au plus) |

Si le serveur ne répond pas, l'écran de connexion affiche « Connexion impossible — Serveur injoignable » et le programme reste ouvert. Après une erreur inattendue, un message invite à réessayer et l'erreur est enregistrée dans le journal.

## Reconstruire l'installateur

Outils, tous gratuits :

| Outil | Version utilisée | Installation |
|---|---|---|
| Python | 3.14 (3.12 au minimum) | python.org |
| Dépendances du client | `desktop/requirements.txt` | `.venv\Scripts\python -m pip install -r requirements.txt` |
| PyInstaller | 6.22.3 | `.venv\Scripts\python -m pip install -r packaging\requirements-build.txt` |
| Inno Setup | 6 | `winget install JRSoftware.InnoSetup` |

Puis, dans `desktop/` :

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Le script :

1. lit la version dans `school_admin/__init__.py` (seule source) ;
2. génère l'icône (`packaging/make_icon.py`, monogramme ISBREE, comme les applications Android) et les informations de version Windows ;
3. empaquette le client avec PyInstaller (`packaging/school_admin.spec`) : un dossier, fenêtré, sans tests ni outils de développement ;
4. compile l'installateur avec Inno Setup (`packaging/installer.iss`) ;
5. affiche le chemin, la taille et l'empreinte SHA-256.

Sorties (générées, jamais versionnées) :

- `desktop/packaging/dist/SchoolManagingAdmin/SchoolManagingAdmin.exe` (programme empaqueté) ;
- `desktop/packaging/dist/installer/SchoolManagingAdmin-Setup-<version>-x64.exe` (installateur).

## Vérifications faites sur la version 0.1.0

Sur Windows 11, avec le poste de développement (pas sur une machine vierge) :

- installation silencieuse sans droits administrateur : programme, raccourci du menu Démarrer et entrée de désinstallation créés, `desktop.json` écrit ;
- programme installé lancé : écran de connexion affiché ;
- serveur injoignable : message « Connexion impossible — Serveur injoignable », programme toujours ouvert ;
- connexion d'un administrateur sur l'API locale : tableau de bord ISBREE chargé (4 classes, 24 élèves, séances de la semaine) ;
- désinstallation : programme, raccourci et entrée retirés ; configuration et journal conservés ; réinstallation sans écraser la configuration ;
- contenu du paquet : plugins Qt (plateforme, SVG, ICO) et icônes présents ; ni tests, ni `.env`, ni secret.

Reste à essayer sur une machine Windows **vierge** (sans Python) et contre le serveur de démonstration en ligne.

## Limites

- Installateur non signé (pas de certificat de signature de code) : avertissement SmartScreen à l'ouverture.
- x64 uniquement, Windows 10 ou plus récent.
- Le logo officiel du logiciel n'existe pas encore : dans le programme, « School Managing » s'affiche en texte (ADR 0021). Seuls le `.exe` et l'installateur portent le monogramme ISBREE.
