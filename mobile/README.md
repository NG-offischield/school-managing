# Applications mobiles (Flutter)

Enseignant et Parent aujourd'hui ; Gardien et Personnel ensuite. Elles parlent **uniquement** à
l'API Django (REST + WebSocket) : aucun accès PostgreSQL, aucune donnée métier locale faisant autorité,
aucune authentification locale (ADR 0025).

```
mobile/
  packages/school_core/   partagé par toutes les applications : client HTTP de l'API (enveloppe,
                          erreurs typées, renouvellement du jeton), session (connexion, refresh,
                          déconnexion, activation), stockage sécurisé du seul refresh token,
                          temps réel (ws/v1/realtime/), thème, composants et module de
                          communication commun (notifications, conversations, réclamations)
  apps/teacher/           application enseignant (data/, models/, presentation/)
  apps/parent/            application parent (même organisation ; ADR 0026)
  tools/                  préparation d'un parcours réel sur une base de TEST
```

## Développement

```powershell
cd mobile\apps\teacher
flutter pub get
flutter analyze
flutter test                                   # tests sans réseau (faux backend)
flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/v1/   # émulateur Android
```

Téléphone réel (USB) : `adb reverse tcp:8000 tcp:8000` puis `--dart-define=API_URL=http://127.0.0.1:8000/api/v1/`.
Le HTTP en clair n'est autorisé que dans la build **debug**, vers `10.0.2.2`, `127.0.0.1` et `localhost` ;
la release reste en HTTPS.

Sur cette machine, si Gradle échoue avec « Unable to establish loopback connection », donner au JDK un
dossier temporaire sans espace : `JAVA_TOOL_OPTIONS="-Djdk.net.unixdomain.tmpdir=C:\gradle-tmp"`.

## Parcours réel (base de test)

1. Lancer un backend de **test** (comme l'E2E du poste) et préparer les données :
   `desktop\.venv\Scripts\python mobile\tools\prepare_live_teacher.py`
   (variables `SCHOOL_ADMIN_E2E_URL / _USER / _PASSWORD`). Le script affiche une ligne JSON
   (code d'activation à usage unique, identifiants des séances).
2. `TEACHER_LIVE_URL=... TEACHER_LIVE='<json>' flutter test test/live_test.dart`

Aucun mot de passe n'est écrit dans le dépôt : celui de l'enseignant est généré pendant le test.

## Application parent

Le parent crée son compte depuis l'application ; l'établissement le valide. Le parent demande ensuite le
rattachement de son enfant :
- l'école vérifie sa pièce d'identité, ou un parent déjà vérifié le parraine avec un code à usage unique ;
- l'élève le désigne ;
- l'école valide et choisit ses droits.

Le serveur reste l'autorité : l'application n'affiche que les enfants et les droits qu'il renvoie
(ADR 0026).

Téléphone réel (Pixel en USB, backend de développement sur le port 8000) :

```powershell
adb devices
adb reverse tcp:8000 tcp:8000
cd mobile\apps\parent
flutter run --dart-define=API_URL=http://127.0.0.1:8000/api/v1/
```

Parcours réel sur une base de **test** :

1. Démarrer le backend de test éphémère sur le port 8001, comme pour les E2E du poste.
2. Préparer les données dans le conteneur :
   `docker exec -e E2E_USER=e2eadmin <conteneur> python manage.py shell -c "exec(open('tools/e2e_parent_fixture.py').read())"`.
   Le script affiche une ligne JSON.
3. Lancer le test :
   `PARENT_LIVE_URL=http://127.0.0.1:8001/api/v1/ PARENT_LIVE='<json>' PARENT_LIVE_ADMIN=e2eadmin PARENT_LIVE_ADMIN_PASSWORD=<généré pour l'exécution> flutter test test/live_test.dart`

Le mot de passe du parent est généré pendant le test et n'est écrit nulle part.
