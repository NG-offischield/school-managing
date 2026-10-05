# Applications mobiles (Flutter)

Enseignant aujourd'hui ; Parent/Tuteur, Gardien et Personnel ensuite. Elles parlent **uniquement** à
l'API Django (REST + WebSocket) : aucun accès PostgreSQL, aucune donnée métier locale faisant autorité,
aucune authentification locale (ADR 0025).

```
mobile/
  packages/school_core/   partagé par toutes les applications : client HTTP de l'API (enveloppe,
                          erreurs typées, renouvellement du jeton), session (connexion, refresh,
                          déconnexion, activation), stockage sécurisé du seul refresh token,
                          temps réel (ws/v1/realtime/), thème et composants
  apps/teacher/           application enseignant (data/, models/, presentation/)
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
