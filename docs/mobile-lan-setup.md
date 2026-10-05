# Mobiles sur le réseau local : procédure complète

Ce guide décrit comment faire fonctionner les quatre applications Android (enseignant, parent, gardien, personnel) avec le serveur Django du PC, **par le Wi-Fi de la box**, sans Internet ni serveur cloud.

Pour un simple changement de box ou d'adresse, le guide court est [reseau-local.md](reseau-local.md).

```
Téléphone Android ── Wi-Fi ──► box / routeur ──► PC Windows ──► Docker ──► Django :8000
                                                  REST       http://<IPv4 du PC>:8000/api/v1/
                                                  WebSocket  ws://<IPv4 du PC>:8000/ws/v1/realtime/
```

Le même jeton (`Authorization: Bearer`) sert pour l'API REST et pour le WebSocket. Il n'y a ni cookie ni second système d'authentification.

## Arborescence

```
mobile/
├── packages/school_core/     code partagé par les 4 applications
│   ├── lib/src/config/       app_config.dart (API_URL / WS_URL), local_network.dart (Android 17)
│   ├── lib/src/ui/gate.dart  portail QR : contrôle du format, anti-double scan, envoi, résultat
│   └── android/              couche Kotlin : permission ACCESS_LOCAL_NETWORK (Android 17)
├── apps/teacher/             application enseignant
├── apps/parent/              application parent
├── apps/guardian/            application gardien (caméra : lib/presentation/camera/)
├── apps/staff/               application personnel
├── gradle/school-android.gradle   minSdk 29 / compileSdk 37 / targetSdk 37 (une seule fois)
├── config/                   lan.example.json ; lan.json = adresse du PC (non versionné)
└── tools/                    configure_lan.ps1, mutation_check.py, préparation des E2E
```

### Assets du logiciel

Le logo officiel « concept 5 » **n'est pas encore intégré**, et aucun logo n'a été fabriqué.

| Où | Aujourd'hui | Quand le logo officiel arrivera |
|---|---|---|
| Poste d'administration | `desktop/school_admin/ui/assets/brand/` (README) | fichiers listés dans ce README, chargés par `ui/branding.py` |
| Mobiles, écrans de démarrage et de connexion | texte « School Managing » (`school_core` `SoftwareBrand`, `widgets.dart`) | `SoftwareBrand` est le seul endroit à modifier |
| Icônes Android | icônes Flutter par défaut : `apps/<app>/android/app/src/main/res/mipmap-*` | remplacer dans chaque application, avec le même outil pour les 4 |

Le logo du logiciel n'apparaît **jamais** sur les documents scolaires (bulletins, cartes, reçus…). Ceux-ci gardent le branding de l'établissement (`SchoolBranding`).

## 1. Trouver l'adresse du PC : `ipconfig`

```powershell
ipconfig
```

## 2. Choisir la bonne IPv4

Prendre la carte **reliée à la box** : « Carte réseau sans fil Wi-Fi » ou « Ethernet », celle qui a une **Passerelle par défaut** IPv4, par exemple `192.168.1.1`. Relever son **Adresse IPv4**, par exemple `192.168.1.100`.

Ignorer :
- `VirtualBox Host-Only` (`192.168.56.1`) ;
- `vEthernet (WSL / Hyper-V)` (`172.x.x.x`) ;
- les adresses `169.254.x.x`.

Le script `mobile\tools\configure_lan.ps1` fait ce choix automatiquement.

## 3. Démarrer Docker et Django

Démarrer Docker Desktop, puis, à la racine du dépôt :

```powershell
docker compose up -d
```

Django écoute sur `0.0.0.0:8000` : toutes les interfaces du PC.

## 4. Vérifier le port 8000

```powershell
curl http://<IPv4>:8000/api/v1/health/
```

La réponse attendue est HTTP 200 `{"status":"ok"}`. Faire le même test depuis le **navigateur du téléphone** : c'est la meilleure vérification du pare-feu.

## 5. `ALLOWED_HOSTS`

Django refuse (HTTP 400) toute requête dont l'en-tête `Host` n'est pas autorisé. Dans `.env` :

```
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.100
```

Le joker `*` n'est **jamais** utilisé. `configure_lan.ps1 -Restart` met cette ligne à jour (ancienne adresse retirée) et redémarre `web`.

## 6. Pare-feu Windows

Le port 8000 n'est ouvert que pour le **réseau privé** et le **sous-réseau local**. Ne faire **aucune** ouverture vers Internet et **aucune** redirection de port sur la box.

Commandes à lancer une fois, en PowerShell administrateur :

```powershell
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi 3" -NetworkCategory Private
New-NetFirewallRule -DisplayName "School Managing API (LAN)" -Direction Inbound -Protocol TCP `
    -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet -Action Allow
```

Le nom exact de l'interface se lit avec `Get-NetConnectionProfile`.

## 7. Même Wi-Fi

Le PC et les téléphones doivent être sur **le même réseau** :
- pas sur le réseau « invité » de la box ;
- pas avec l'« isolation des clients » activée.

Pendant le test, couper les données mobiles du téléphone.

## 8. `API_URL`

L'adresse est fixée **à la compilation**, sans aucune adresse par défaut ni IP écrite dans les sources :

```powershell
flutter run --dart-define=API_URL=http://192.168.1.100:8000/api/v1/
# ou, après configure_lan.ps1 :
flutter run --dart-define-from-file=../../config/lan.json
```

En build debug, le HTTP en clair n'est accepté que vers une adresse privée. La release exige HTTPS.

## 9. `WS_URL`

```
--dart-define=WS_URL=ws://192.168.1.100:8000/ws/v1/realtime/
```

`WS_URL` est facultatif : il est déduit de `API_URL` (même hôte, même port). Un `WS_URL` vers un autre hôte est refusé, puisque le jeton y serait envoyé.

## 10. Android 17 : permission « réseau local »

Sur Android 17 (API 37), avec une adresse locale, l'application montre d'abord un écran « Accès au réseau local », puis la fenêtre système « Appareils à proximité ».
- **Accepter :** sans cet accès, la connexion au PC expire.
- **En cas de refus :** l'application propose de redemander, puis les paramètres.
- **Retrait plus tard :** l'écran revient au retour dans l'application.

Android 10 à 16 n'affichent rien : `INTERNET` suffit.

## 11. Installer l'APK

```powershell
adb devices                                    # le téléphone doit être « device »
cd mobile\apps\guardian
flutter build apk --debug --dart-define-from-file=../../config/lan.json
adb install -r build\app\outputs\flutter-apk\app-debug.apk
```

L'USB sert **uniquement** à installer. Ne **pas** utiliser `adb reverse` pour la validation : avec `127.0.0.1`, le trafic passe par le câble et non par la box. `adb reverse tcp:8000 tcp:8000` reste une méthode de dépannage USB.

## 12. Connexion

L'écran de connexion affiche en bas « Serveur : 192.168.1.100:8000 ». Vérifier cette adresse, puis se connecter (ou activer le compte avec le code remis par l'école).

## 13. WebSocket

En haut à droite, l'icône « Connecté en direct » indique que le WebSocket est ouvert par le Wi-Fi.
- **Coupure (Wi-Fi coupé, PC éteint) :** « Hors ligne : reconnexion automatique ».
- **Retour du réseau :** l'application se reconnecte et récupère ce qui a été manqué (resynchronisation).
- **Session expirée ou révoquée :** le serveur ferme la socket (code 4401) dans les 30 s et l'application revient à la connexion.

## 14. QR caméra (gardien)

**Parcours :** Accueil → « Scanner au portail ». La caméra s'ouvre directement.
- **Premier usage :** Android demande l'appareil photo.
  - Android 10 propose « Allow / Deny » ;
  - Android 11 et plus proposent « Pendant l'utilisation / Cette fois uniquement / Refuser ».
- **Lecture :** placer le QR de la carte dans le cadre. À la première lecture valide, le téléphone vibre légèrement, la caméra se ferme et le jeton part vers l'endpoint existant `POST /qr/scans/`. Le résultat du serveur s'affiche, puis « Scanner la carte suivante ».

| Situation | Comportement |
|---|---|
| QR qui n'est pas une carte (URL, Wi-Fi…) | message dans le scanner ; **rien n'est envoyé** ; la lecture continue |
| QR révoqué | « QR révoqué » (réponse du serveur) |
| QR d'une autre école | « QR inconnu » (le serveur ne cherche que dans son école) |
| même carte relue | une seule lecture par ouverture ; même carte dans les 5 s : pas renvoyée |
| permission refusée | explication, « Autoriser l'appareil photo », « Ouvrir les paramètres », saisie manuelle ; aucune redemande en boucle |
| permission retirée pendant l'arrière-plan | au retour : panneau « refusé » |
| pas de caméra | saisie manuelle / lecteur QR |
| 45 s sans carte | caméra arrêtée (batterie), « Réessayer » |
| arrière-plan | caméra libérée, relancée au retour |
| réseau absent / serveur muet | « le passage n'est PAS enregistré », bouton « Réessayer l'envoi » |
| faible luminosité | bouton lampe |

Aucune image n'est enregistrée ni envoyée : seul le texte du QR est lu (`returnImage: false`, format QR uniquement). Le lecteur USB/Bluetooth et la saisie au clavier restent disponibles sous « Lecteur USB / Bluetooth ou saisie du code ».

## 15. Notifications

Depuis le poste d'administration, publier ou envoyer quelque chose au compte. La notification arrive en direct, avec un badge sur « Alertes ». Celles reçues hors ligne arrivent à la reconnexion.

## 16. Communication

Envoyer un message, par exemple personnel ou parent vers l'administration, ou enseignant vers parent. Il arrive en direct sur l'autre appareil et sur le poste. Le gardien n'a pas de messagerie (spec §8) : notifications seulement.

## 17. Problèmes réseau

| Symptôme | Cause probable | Remède |
|---|---|---|
| « Le serveur ne répond pas » | pare-feu / profil Public, autre Wi-Fi, permission Android 17 refusée | §6, §7, §10 |
| HTTP 400 | IP absente de `DJANGO_ALLOWED_HOSTS` | §5 |
| marche depuis le PC, pas depuis le téléphone | réseau invité / isolation AP, pare-feu | §6, §7 |
| « Configuration du serveur » au lancement | APK compilé sans `API_URL`, ou adresse publique en HTTP | §8 |
| ancienne adresse sur l'écran de connexion | APK compilé avant un changement de réseau | recompiler |

## 18. Changement d'IP (nouvelle box, autre réseau, bail DHCP)

```powershell
powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -Restart
```

Puis recompiler et réinstaller les APK, puisque l'adresse est figée dans l'APK. Pour éviter les changements, réserver une adresse fixe pour le PC dans la box (réservation DHCP).

## Ce qui a été vérifié, et sur quoi

| Vérification | Moyen |
|---|---|
| API, WebSocket (message et notification poussés, resynchronisation, session révoquée en 4401), isolation, QR révoqué, 4 parcours complets | tests réels Dart contre le backend de test, **via l'IP LAN du PC** (`192.168.1.100`), lancés depuis le PC |
| permission caméra (refus sans boucle, autorisation), aperçu caméra, lampe, arrière-plan et retour | émulateurs Android 10 et Android 16 |
| lecture d'un vrai QR par la caméra | **non vérifiée sur appareil** : tests avec caméra simulée seulement |
| Android 17, Pixel 7a, trajet réel par la box | **à faire** : aucun téléphone n'était branché, et l'émulateur Android 17 plante sur ce PC (GPU) |
