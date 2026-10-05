# Applications mobiles (Flutter)

Enseignant, Parent, Gardien et Personnel. Elles parlent **uniquement** à
l'API Django (REST + WebSocket) : aucun accès PostgreSQL, aucune donnée métier locale faisant autorité,
aucune authentification locale (ADR 0025).

```
mobile/
  packages/school_core/   partagé par toutes les applications : adresse du serveur (API_URL / WS_URL),
                          permission réseau local d'Android 17 (petite couche Kotlin, android/),
                          client HTTP de l'API (enveloppe, erreurs typées, renouvellement du jeton),
                          session (connexion, refresh, déconnexion, activation), stockage sécurisé
                          du seul refresh token, temps réel (ws/v1/realtime/), thème, composants,
                          communication selon le rôle, portail QR, calendrier ; testing.dart
  apps/teacher/           application enseignant (data/, models/, presentation/)
  apps/parent/            application parent (même organisation ; ADR 0026)
  apps/guardian/          application gardien (portail QR par caméra, mes passages, notifications ; ADR 0027, 0029)
  apps/staff/             application personnel (planning, portail, messages, rémunération ; ADR 0027)
  gradle/                 school-android.gradle : niveaux Android communs aux quatre applications
  config/                 lan.example.json ; lan.json (adresse du PC, non versionné)
  tools/                  configure_lan.ps1 (réseau local) ; mutation_check.py (protections mobiles) ;
                          préparation des parcours réels (base de TEST)
```

## Versions Android supportées

Les quatre applications fonctionnent sur **Android 10 → Android 17**.

| Android | API |
|---|---|
| Android 10 | 29 |
| Android 11 | 30 |
| Android 12 | 31 / 32 |
| Android 13 | 33 |
| Android 14 | 34 |
| Android 15 | 35 |
| Android 16 | 36 |
| Android 17 | 37 |

### Configuration

```
minSdk     = 29   Android 10, le plus ancien appareil supporté
compileSdk = 37   API d'Android 17 visibles à la compilation
targetSdk  = 37   comportement actuel d'Android 17 (dont la protection du réseau local)
```

Ces valeurs sont écrites **une seule fois**, dans `mobile/gradle/school-android.gradle`. Chaque `android/app/build.gradle.kts` l'applique, et le module Android de `school_core` utilise les mêmes niveaux. Le test `packages/school_core/test/android_config_test.dart` vérifie cette cohérence, ainsi que les permissions et l'absence de HTTP en clair hors debug.

Toute API Android plus récente que l'API 29 est protégée au runtime par `Build.VERSION.SDK_INT`. Le seul code natif propre au projet est `SchoolCorePlugin.kt` (permission réseau local). La constante d'Android 17 n'y est jamais référencée à la compilation : le nom de la permission est une chaîne, et la demande est conditionnée à `SDK_INT >= 37`.

Chaîne d'outils (octobre 2026) :
- Flutter 3.47.4 / Dart 3.13.3 ;
- Android Gradle Plugin 9.1.0 ;
- Gradle 9.3.1 ;
- Kotlin 2.4.0 ;
- JDK 21 (Temurin ; bytecode Java 17) ;
- NDK 29.0.13599879 ;
- plateforme SDK `android-37.0` et build-tools 37.0.0.

Pour installer la plateforme : `sdkmanager "platforms;android-37.0" "build-tools;37.0.0"`.

### Appareil de référence : Pixel 7a

Le **Pixel 7a sous Android 17 (API 37)** est l'appareil principal de validation. Il se connecte au PC par le **Wi-Fi de la box**, pas par USB.

### Permissions

| Permission | Pourquoi | Quand |
|---|---|---|
| `INTERNET` | API REST et WebSocket | toujours (permission normale, aucune demande) |
| `ACCESS_LOCAL_NETWORK` | joindre le PC Django sur le Wi-Fi local | **Android 17 uniquement** et seulement si `API_URL` est une adresse locale ; demandée au lancement, avant toute requête |
| `CAMERA` | **gardien seulement** : lire le QR de la carte au portail | demandée à la première ouverture du scanner ; refus géré (explication, paramètres, saisie manuelle), jamais en boucle |
| `ACCESS_NETWORK_STATE` | ajoutée par ML Kit (gardien) | permission normale, aucune demande |

Aucune autre permission n'est déclarée :
- pas d'écriture de photo : le scanner ne garde que le texte du QR (`returnImage: false`) ;
- pas de stockage : les PDF sont rangés dans le dossier privé de l'application ;
- pas de notifications système : pas de FCM en V1, les notifications s'affichent dans l'application.

Ces permissions viennent des bibliothèques et sont fusionnées dans chaque APK : `school_core` pour les quatre applications, `mobile_scanner` pour le gardien seulement. Les manifestes des applications n'en déclarent aucune.

### Android 17 : `ACCESS_LOCAL_NETWORK`

Une application qui cible l'API 37 ne peut plus ouvrir de connexion vers une adresse privée (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) sans la permission runtime `ACCESS_LOCAL_NETWORK`, du groupe « Appareils à proximité ». Sans elle, la connexion échoue par **délai dépassé**. L'accès au réseau local est **obligatoire** pour nos communications en mode LAN : connexion, API, WebSocket, messages, notifications.

`LocalNetworkGate` (`school_core`) gère ce cas :
- **Android 17 + adresse locale :**
  - un écran explique le besoin, puis la fenêtre système s'affiche ;
  - en cas de refus, l'explication reste affichée avec « Autoriser » ; après un refus définitif, l'application propose « Ouvrir les paramètres » ;
  - si l'utilisateur retire l'accès dans les paramètres, l'écran réapparaît au retour dans l'application ;
  - aucune requête n'est envoyée (pas même la restauration de session) tant que l'accès n'est pas accordé.
- **Android 10 à 16 :** rien n'est demandé, `INTERNET` suffit.
- **`127.0.0.1` (`adb reverse`), HTTPS public :** rien n'est demandé.

### Debug (LAN local) et release (production)

| | debug | release |
|---|---|---|
| HTTP / WS en clair | autorisé vers une adresse **privée** ou de bouclage (`src/debug/…/network_security_config_debug.xml` ; `AppConfig` refuse les adresses publiques) | **interdit** : aucune configuration réseau dans `src/main`, donc Android par défaut, et `AppConfig` refuse `http://` |
| Adresse du serveur | `--dart-define` / `--dart-define-from-file` | idem, en `https://` |

## Réseau local (LAN)

Les téléphones joignent le PC Windows **par le Wi-Fi de la box**. Le guide complet, à suivre aussi après un changement de box ou de réseau, est [docs/mobile-lan-setup.md](../docs/mobile-lan-setup.md) ; après un simple changement de box ou d'adresse : [docs/reseau-local.md](../docs/reseau-local.md).

```
Pixel (Wi-Fi) ─► box / routeur ─► PC Windows ─► Docker ─► Django
                                  http://<IPv4 du PC>:8000/api/v1/
                                  ws://<IPv4 du PC>:8000/ws/v1/realtime/
```

1. Trouver l'IPv4 avec `ipconfig` : c'est la carte Wi-Fi ou Ethernet **qui a une passerelle par défaut**. Ignorer VirtualBox (`192.168.56.1`) et `169.254.x.x`.
2. Placer le PC et les téléphones sur le **même Wi-Fi**, pas sur le réseau invité.
3. Django écoute sur le port **8000** de toutes les interfaces (`docker-compose.yml`). L'adresse doit figurer dans `DJANGO_ALLOWED_HOSTS` (`.env`) ; `*` n'est jamais utilisé.
4. Pare-feu Windows : autoriser le port TCP 8000 en entrée, **profil Privé** et sous-réseau local seulement. Aucun port n'est ouvert vers Internet.
5. Compiler avec `API_URL` (et `WS_URL`, facultatif car déduit de `API_URL`).

Le script `mobile\tools\configure_lan.ps1 -Restart` fait les étapes 1, 3 et 5 (fichier `config/lan.json`). Pour le pare-feu, il affiche les commandes administrateur sans rien modifier.

```powershell
cd mobile\apps\guardian
flutter run --dart-define-from-file=../../config/lan.json
flutter run --dart-define=API_URL=http://192.168.1.100:8000/api/v1/ --dart-define=WS_URL=ws://192.168.1.100:8000/ws/v1/realtime/
```

Il n'y a **pas d'adresse par défaut** : sans `API_URL`, l'application affiche un écran « Configuration du serveur ». L'écran de connexion affiche en bas le serveur visé (« Serveur : 192.168.1.100:8000 »).

`localhost` / `127.0.0.1` désignent le téléphone lui-même. Ils ne servent que pour :
- `adb reverse tcp:8000 tcp:8000`, **dépannage en USB uniquement** ;
- l'émulateur, qui joint le PC par `10.0.2.2`.

Le test de référence passe par la box, sans `adb reverse`.

## Procédure de test reproductible (Pixel 7a, Android 17)

Chaque étape n'est validée qu'avec un résultat réellement observé.

1. Brancher le Pixel 7a en USB, uniquement pour installer l'APK. Activer « Débogage USB ».
2. `adb devices` : le téléphone doit apparaître en `device`.
3. `ipconfig` : relever l'IPv4 du PC sur le Wi-Fi.
4. Démarrer Docker Desktop, puis `docker compose up -d` à la racine.
5. Vérifier le port 8000 : `curl http://<IPv4>:8000/api/v1/health/` doit répondre 200, depuis le PC **et** depuis le navigateur du téléphone.
6. Connecter le PC et le téléphone au même Wi-Fi ; désactiver les données mobiles du téléphone pendant le test.
7. Configurer `API_URL` : `mobile\tools\configure_lan.ps1 -Restart`, ou `--dart-define=API_URL=http://<IPv4>:8000/api/v1/`.
8. Configurer `WS_URL` : `ws://<IPv4>:8000/ws/v1/realtime/`. C'est automatique avec `lan.json`.
9. Lancer : `flutter run --dart-define-from-file=../../config/lan.json`, ou installer l'APK debug avec `adb install -r build\app\outputs\flutter-apk\app-debug.apk`. **Pas d'`adb reverse`.**
10. Android 17 : accepter « Accès au réseau local ». Tester aussi le refus (écran d'explication), puis l'acceptation.
11. Login avec un compte activé ; vérifier « Serveur : <IPv4>:8000 » sur l'écran de connexion.
12. WebSocket : l'indicateur « En direct » passe au vert.
13. Portail QR caméra (gardien) : Accueil → « Scanner au portail » → autoriser l'appareil photo → présenter une carte ; le résultat du serveur s'affiche et l'historique se met à jour (détail : [docs/mobile-lan-setup.md](../docs/mobile-lan-setup.md) §14).
14. Notification : en envoyer une depuis le poste d'administration, elle doit arriver en direct.
15. Communication : envoyer un message (enseignant, parent, personnel) et le voir arriver sur l'autre appareil.

## Développement

```powershell
cd mobile\apps\teacher
flutter pub get
flutter analyze
flutter test                                   # tests sans réseau (faux backend)
flutter run --dart-define-from-file=../../config/lan.json            # téléphone sur le Wi-Fi
flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/v1/       # émulateur Android
```

Les règles de version Android en Kotlin ont leurs propres tests JVM : `gradlew :school_core:testDebugUnitTest`, depuis `apps/<app>/android`.

Sur cette machine, si Gradle échoue avec « Unable to establish loopback connection », donner au JDK un dossier temporaire sans espace : `JAVA_TOOL_OPTIONS="-Djdk.net.unixdomain.tmpdir=C:\gradle-tmp -Djava.io.tmpdir=C:\gradle-tmp"`.

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

Téléphone réel : par le Wi-Fi (section « Réseau local »). En dépannage USB seulement : `adb reverse tcp:8000 tcp:8000`
puis `--dart-define=API_URL=http://127.0.0.1:8000/api/v1/`.

Parcours réel sur une base de **test** :

1. Démarrer le backend de test éphémère sur le port 8001, comme pour les E2E du poste.
2. Préparer les données dans le conteneur :
   `docker exec -e E2E_USER=e2eadmin <conteneur> python manage.py shell -c "exec(open('tools/e2e_parent_fixture.py').read())"`.
   Le script affiche une ligne JSON.
3. Lancer le test :
   `PARENT_LIVE_URL=http://127.0.0.1:8001/api/v1/ PARENT_LIVE='<json>' PARENT_LIVE_ADMIN=e2eadmin PARENT_LIVE_ADMIN_PASSWORD=<généré pour l'exécution> flutter test test/live_test.dart`

Le mot de passe du parent est généré pendant le test et n'est écrit nulle part.

### Paiement mobile (ADR 0030)

Parcours : Finance → facture → « Payer » → détail → choix du portefeuille → confirmation → résultat du serveur → reçu.

- **Droits :** « Payer » n'apparaît que si le serveur répond `can_pay` pour cet enfant. Sans `can_view_financial_data`, les factures ne sont même pas demandées. L'écran de paiement redemande les droits et la facture au moment de payer.
- **Montant :** c'est le `balance_due` de la facture, exactement tel que le serveur le donne. Rien n'est saisi ni recalculé sur le téléphone, et une requête falsifiée est refusée (409 `amount_exceeds_balance`).
- **Idempotence :** une clé par intention de paiement (`PaymentFlow`).
  - **Réponse perdue** (réseau, délai, 5xx) : la clé est gardée, et « Réessayer » rejoue la même demande. Le serveur renvoie le paiement déjà fait, sans second débit.
  - **Réponse définitive** (succès, refus, fonds insuffisants, 4xx) : une nouvelle tentative utilise une nouvelle clé.
  - **Double appui :** il ne produit qu'une requête.
- **Résultats :** réussi, refusé, fonds insuffisants, délai du fournisseur, erreur du fournisseur. C'est toujours le statut enregistré par le serveur, et un échec ne débite rien. Les conflits (facture déjà réglée, montant changé, clé réutilisée) sont expliqués, avec « Recharger la facture ».
- **Reçu :** PDF officiel construit par le serveur avec l'identité et le branding de l'**établissement**, jamais le logo du logiciel. Il est enregistré dans le dossier privé de l'application, puis ouvert avec la visionneuse PDF du téléphone par `school_core` : `FileProvider` non exporté, limité à `cache/shared/`, aucune permission de stockage.

Les portefeuilles sont ouverts et alimentés par l'établissement (simulation V1). Le parent ne voit que les siens.

Parcours réel de paiement sur la base de **test** : même préparation, puis `flutter test test/payment_live_test.dart` avec les mêmes variables. Mettre l'IPv4 du PC dans `PARENT_LIVE_URL` pour passer par le réseau local.

## Applications gardien et personnel

Les comptes sont créés par l'établissement et activés par la personne avec un code (ADR 0024). Le portail
utilise le protocole QR existant : le gardien lit la carte avec l'appareil photo (lecteur QR « clavier » ou saisie en secours ; le personnel : lecteur ou saisie). Le serveur
décide de ce que chaque rôle voit :
- le gardien voit le statut de solvabilité, jamais de montant ;
- le personnel ne le voit pas.

Les gardiens n'ont pas de messagerie (spec §8). Il n'existe pas encore d'API de présence du personnel.

Parcours réels sur la base de **test** :

1. Lancer le conteneur de test sur le port 8001.
2. Préparer les données :
   `docker exec -e E2E_USER=e2eadmin <conteneur> python manage.py shell -c "exec(open('tools/e2e_field_fixture.py').read())"`.
   Le script affiche une ligne JSON.
3. Lancer `flutter test test/live_test.dart` dans `apps/guardian` puis dans `apps/staff`, avec les variables
   `FIELD_LIVE_URL`, `FIELD_LIVE` (le JSON), `FIELD_LIVE_ADMIN` et `FIELD_LIVE_ADMIN_PASSWORD`.
