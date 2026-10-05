# Réseau local : changer de box, de routeur ou de Wi-Fi

Ce guide explique comment rebrancher les téléphones sur le serveur Django quand le réseau change : nouvelle box, autre routeur, autre Wi-Fi, ou simple changement d'adresse du PC.

## Le principe

```
Téléphone Android ── Wi-Fi ──► box / routeur ──► PC Windows (Docker + Django)
                                                  http://<IPv4 du PC>:8000/api/v1/
                                                  ws://<IPv4 du PC>:8000/ws/v1/realtime/
```

Aucun serveur sur Internet n'est utilisé. Les téléphones joignent le PC par son **adresse IPv4 sur le réseau local**, par exemple `192.168.1.100`.

C'est la box qui attribue cette adresse. Elle **change donc avec le réseau**, et parfois même sur le même réseau après un redémarrage de la box.

Trois éléments dépendent de cette adresse :

| Élément | Où | Qui l'utilise |
|---|---|---|
| `DJANGO_ALLOWED_HOSTS` | fichier `.env` à la racine du dépôt (jamais commité) | Django refuse toute requête dont l'en-tête `Host` n'y figure pas (réponse 400) |
| `API_URL` / `WS_URL` | `mobile/config/lan.json` (jamais commité), ou `--dart-define` | les applications Flutter, fixé à la compilation |
| pare-feu Windows | règle « School Managing API (LAN) » | laisse entrer le port 8000 depuis le réseau local, profil Privé uniquement |

`localhost` et `127.0.0.1` désignent **l'appareil lui-même**. Sur un téléphone, ils visent donc le téléphone, pas le PC. Ils ne servent qu'à deux cas :
- le développement sur le PC ;
- un téléphone en USB avec `adb reverse tcp:8000 tcp:8000` (dépannage).

L'émulateur Android joint le PC par `10.0.2.2`.

## Procédure rapide (après chaque changement de réseau)

1. Connecter le PC au nouveau Wi-Fi, ou au câble de la box.
2. Démarrer Docker Desktop.
3. Dans PowerShell, à la racine du dépôt, lancer :

   ```powershell
   powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -Restart
   ```

   Le script :
   - trouve l'IPv4 du PC sur le réseau de la box (interface qui a une passerelle). Les adaptateurs VirtualBox, Hyper-V et les adresses `169.254.x.x` sont ignorés ;
   - met à jour `DJANGO_ALLOWED_HOSTS` dans `.env` : il garde `localhost` et `127.0.0.1`, retire l'ancienne adresse LAN et ajoute la nouvelle. Il n'utilise jamais `*` ;
   - écrit `mobile/config/lan.json` ;
   - redémarre le conteneur `web` (`-Restart`) pour que Django relise `.env` ;
   - vérifie `http://<IP>:8000/api/v1/health/` ;
   - affiche le profil réseau Windows et l'état du pare-feu, avec les commandes administrateur à lancer si besoin. **Il ne modifie aucun réglage système.**

   Pour imposer une adresse : `... configure_lan.ps1 -Ip 192.168.0.42 -Restart`.

4. Reconstruire et réinstaller chaque application. L'adresse est figée dans l'APK à la compilation :

   ```powershell
   cd mobile\apps\guardian
   flutter run --dart-define-from-file=../../config/lan.json
   # ou : flutter build apk --debug --dart-define-from-file=../../config/lan.json
   ```

5. Sur le téléphone, l'écran de connexion affiche en bas **« Serveur : 192.168.x.x:8000 »**. Vérifier que c'est la bonne adresse.

## Procédure manuelle (sans le script)

1. Trouver l'adresse du PC :

   ```powershell
   ipconfig
   ```

   Prendre la carte **reliée à la box**, en général « Carte réseau sans fil Wi-Fi » ou « Ethernet », celle qui a une **Passerelle par défaut** IPv4, par exemple `192.168.1.1`. Relever sa ligne **Adresse IPv4**, par exemple `192.168.1.100`.

   Ignorer :
   - `VirtualBox Host-Only` (`192.168.56.1`) ;
   - `vEthernet (WSL/Hyper-V)` ;
   - les adresses `169.254.x.x`.

2. Dans `.env`, ajouter l'adresse sans retirer `localhost,127.0.0.1` :

   ```
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.100
   ```

   Enregistrer le fichier en **UTF-8 sans BOM** : Bloc-notes « UTF-8 », pas « UTF-8 avec BOM ».

3. Redémarrer Django : `docker compose up -d web` à la racine du dépôt.
4. Vérifier depuis le PC : `curl http://192.168.1.100:8000/api/v1/health/`. La réponse attendue est un HTTP 200.
5. Compiler les applications avec :

   ```
   --dart-define=API_URL=http://192.168.1.100:8000/api/v1/
   --dart-define=WS_URL=ws://192.168.1.100:8000/ws/v1/realtime/
   ```

   `WS_URL` est facultatif. Par défaut, il se déduit de `API_URL` : même hôte, même port.

## Pare-feu Windows et profil réseau

Le port 8000 ne doit être ouvert que **sur le réseau local de confiance**, jamais vers Internet. Aucune redirection de port sur la box n'est nécessaire, et il ne faut pas en créer.

Commandes à lancer une fois, dans **PowerShell administrateur** :

```powershell
# Le Wi-Fi de l'école ou de la maison est un réseau de confiance : profil « Privé ».
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi 3" -NetworkCategory Private

# Port 8000 entrant, profil Privé seulement, depuis le sous-réseau local seulement.
New-NetFirewallRule -DisplayName "School Managing API (LAN)" -Direction Inbound -Protocol TCP `
    -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet -Action Allow
```

`Wi-Fi 3` est le nom de l'interface sur le PC de développement. Le nom exact se lit avec `Get-NetConnectionProfile`.

Sur un nouveau réseau, Windows le classe souvent en **Public** : il faut repasser ce réseau en Privé. La règle du pare-feu n'a pas à être recréée.

> Constat sur le PC de développement (5 octobre 2026) :
> - le Wi-Fi « Wi-Fi 3 » est en profil **Public** ;
> - Docker Desktop a installé des règles « Docker Desktop Backend » qui autorisent l'entrée **sur le profil Public**. Le port publié par Docker peut donc être joignable même sur un Wi-Fi public.
>
> À revoir par l'administrateur du poste : passer le Wi-Fi de confiance en Privé et restreindre les règles Docker. Aucun réglage n'a été modifié automatiquement.

## Android 17 : permission « réseau local »

Pour les applications qui ciblent l'API 37 (c'est notre cas), Android 17 bloque l'accès au réseau local tant que l'utilisateur ne l'a pas autorisé : la permission runtime `ACCESS_LOCAL_NETWORK` appartient au groupe « Appareils à proximité ». Sans elle, la connexion au PC échoue par **délai dépassé**, sans message explicite.

Les applications gèrent ce cas, via `school_core` (`LocalNetworkGate`) :
- **Android 17 avec une adresse locale** (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, `10.0.2.2`) : au premier lancement, un écran explique le besoin, puis la fenêtre système s'affiche.
  - **Refus :** l'application reste sur l'écran d'explication et propose « Autoriser » à nouveau. Après un refus définitif, elle propose « Ouvrir les paramètres ».
  - **Retrait plus tard dans les paramètres :** au retour dans l'application, l'écran réapparaît.
- **Android 10 à 16 :** rien n'est demandé, la permission `INTERNET` suffit.
- **`adb reverse` (`127.0.0.1`), HTTPS public :** rien n'est demandé.

Aucune requête n'est envoyée au serveur, pas même la restauration de session, tant que l'accès n'est pas accordé.

## HTTP en clair : débogage seulement

| Build | Trafic autorisé |
|---|---|
| **debug** (`flutter run`, `build apk --debug`) | HTTP/WS en clair vers une adresse **privée** ou de bouclage. `school_core` (`AppConfig`) refuse toute adresse publique en clair et affiche un écran d'erreur. |
| **release** | HTTPS/WSS uniquement : Android par défaut (aucune configuration réseau dans `src/main`) et `AppConfig` refuse `http://`. |

## Problèmes fréquents

| Symptôme | Cause probable | Remède |
|---|---|---|
| « Le serveur ne répond pas » depuis le téléphone | pare-feu, profil Public, autre Wi-Fi, permission Android 17 refusée | profil Privé + règle du pare-feu ; même Wi-Fi (pas le réseau invité de la box) ; autoriser « Appareils à proximité » |
| HTTP 400 « Bad Request » | adresse absente de `DJANGO_ALLOWED_HOSTS` | relancer `configure_lan.ps1 -Restart` |
| L'écran de connexion affiche une ancienne adresse | APK compilé avant le changement | recompiler avec le nouveau `lan.json` |
| Ça marche avec le PC mais pas avec le téléphone | réseau invité ou « isolation des clients » activée sur la box | utiliser le Wi-Fi principal, désactiver l'isolation AP dans la box |
| L'adresse change à chaque redémarrage de la box | bail DHCP | réserver une adresse fixe pour le PC dans la box (réservation DHCP par adresse MAC) |
