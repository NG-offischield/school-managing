# ADR 0028 — Compatibilité Android 10 → 17 et accès au réseau local

- **Statut :** accepté — 2026-10-05
- **Périmètre :**
  - niveaux Android communs aux quatre applications Flutter (enseignant, parent, gardien, personnel) ;
  - adresse du serveur configurable ;
  - permission réseau local d'Android 17 ;
  - séparation du HTTP en clair entre debug et release.
- **Hors périmètre :** QR par caméra, paiement mobile, packaging Windows, release signée.

## 1. Niveaux

| | Valeur | Raison |
|---|---|---|
| `minSdk` | 29 (Android 10) | parc d'appareils visé ; toutes les dépendances l'acceptent (secure storage : 19, path_provider : JNI sans code natif) |
| `targetSdk` | 37 (Android 17) | comportement actuel, dont la protection du réseau local |
| `compileSdk` | 37 | plateforme `android-37.0` |

Les valeurs sont écrites une seule fois dans `mobile/gradle/school-android.gradle`, que chaque `app/build.gradle.kts` applique. Le module Android de `school_core` utilise les mêmes niveaux.

`packages/school_core/test/android_config_test.dart` vérifie :
- la cohérence des niveaux ;
- les permissions ;
- l'absence de HTTP en clair hors debug ;
- l'absence d'adresse IP dans les sources.

## 2. Adresse du serveur

`school_core` `AppConfig` lit `API_URL` (obligatoire) et `WS_URL` (facultatif, déduit de l'API) au moment de la compilation, avec `--dart-define` ou `--dart-define-from-file=mobile/config/lan.json`.

Règles :
- **Aucune valeur par défaut :** sans adresse, l'application affiche un écran « Configuration du serveur ». L'ancienne valeur par défaut `10.0.2.2` pointait silencieusement vers l'émulateur.
- **HTTP/WS en clair :** acceptés seulement vers une adresse privée (RFC 1918), de bouclage ou `.local`, et jamais en release.
- **Même hôte :** le WebSocket vise obligatoirement le même hôte que l'API, puisque le jeton y est envoyé.

L'écran de connexion affiche le serveur visé.

`mobile/tools/configure_lan.ps1` prépare un changement de réseau :
- il détecte l'IPv4 du PC ;
- il écrit `DJANGO_ALLOWED_HOSTS` (jamais `*`) et `lan.json` ;
- il vérifie `/health/` ;
- il affiche les commandes de pare-feu et de profil réseau sans les exécuter.

Le guide pour l'utilisateur est `docs/reseau-local.md`.

## 3. Android 17 : `ACCESS_LOCAL_NETWORK`

Une application qui cible l'API 37 a besoin de cette permission runtime (groupe `NEARBY_DEVICES`) pour se connecter à une adresse privée. Sans elle, la connexion TCP expire.

- **Couche native :** `school_core` devient un plugin Flutter, avec une petite couche Kotlin, `SchoolCorePlugin`, et le canal `school_core/local_network` (status, request, openSettings).
  - La demande n'est faite que si `SDK_INT >= 37`.
  - Le nom de la permission est une chaîne : aucune constante de l'API 37 n'est chargée sur Android 10.
  - La règle de version, `LocalNetworkPolicy`, est testée en JUnit.
- **Écran de garde :** `LocalNetworkGate` entoure chaque application.
  - Si l'API est sur le réseau local et la permission manque, il explique le besoin puis demande l'accès.
  - Après un refus, il redemande ; après un refus définitif, il ouvre les paramètres.
  - Au retour au premier plan, il vérifie de nouveau (révocation).
  - La restauration de session n'est lancée qu'une fois l'accès obtenu.
- **Android 10 à 16 :** rien n'est demandé.

## 4. Permissions

Toutes les permissions viennent du manifeste de `school_core`, fusionné dans chaque APK :
- `INTERNET` ;
- `ACCESS_LOCAL_NETWORK`.

Aucune caméra, aucun stockage, aucune notification système. AndroidX ajoute lui-même `DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` (signature, propre à l'application).

## 5. HTTP en clair

| Build | HTTP en clair |
|---|---|
| debug | `base-config cleartextTrafficPermitted` dans `src/debug` seulement : Android ne sait pas exprimer une plage d'adresses, et l'adresse du PC change avec la box. `AppConfig` limite le clair aux adresses privées. |
| release | aucune configuration réseau : HTTPS seulement par défaut, et `AppConfig` refuse `http://` |

## Conséquences

- Changer de réseau oblige à recompiler les APK, puisque l'adresse est figée à la compilation, et à relancer `configure_lan.ps1`.
- Le jour où le QR caméra arrivera, son plugin devra accepter minSdk 29 et ajouter la permission `CAMERA`, déclarée dans le manifeste du seul gardien.
