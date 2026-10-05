# ADR 0029 — QR par caméra dans l'application gardien

- **Statut :** accepté — 2026-10-05
- **Périmètre :** lecture des cartes au portail par l'appareil photo (application gardien), protections partagées du portail (`school_core`), tests WebSocket sur le réseau local.
- **Hors périmètre :** nouveau format QR, paiement mobile, packaging.

## 1. Bibliothèque

`mobile_scanner` ^7.4.2 :
- maintenu : version du 10 septembre 2026, score pub.dev 160/160 ;
- CameraX 1.6.1 et modèle ML Kit **embarqué** (barcode-scanning 17.3.0), donc lecture hors ligne et sans Play Services ;
- minSdk 23, compatible avec notre minSdk 29 ; build validé en compileSdk et targetSdk 37.

Cette dépendance n'est ajoutée **qu'à l'application gardien**, et un test le vérifie. Elle apporte `CAMERA`, `android.hardware.camera` (non obligatoire) et `ACCESS_NETWORK_STATE` (permission normale, ajoutée par ML Kit).

## 2. Protocole : inchangé

La caméra lit le texte du QR de la carte, c'est-à-dire le jeton existant (`secrets.token_urlsafe(32)`, encodé tel quel par `documents/rendering.py`). Ce jeton part vers `POST /qr/scans/ {token}`, comme avec le lecteur clavier. Le serveur reste seul juge :
- jeton inconnu ou d'une autre école : `UNKNOWN_TOKEN` ;
- jeton révoqué : `REVOKED_TOKEN` ;
- jeton d'une autre année : `EXPIRED_TOKEN` ;
- élève non inscrit : `STUDENT_NOT_ENROLLED` ;
- solvabilité visible pour le seul rôle gardien, sans montant.

**Aucune image** n'est conservée ni envoyée : `returnImage: false`, format QR uniquement, et seul le texte décodé sort de `qr_camera.dart`.

## 3. Côté téléphone

- **Filtre de format** (`looksLikeQrToken`, `school_core`) : un contenu qui n'a pas la forme d'un jeton (URL, code Wi-Fi, vCard…) n'est **jamais envoyé**. C'est une protection de la vie privée, pas une décision métier.
- **Double scan :** l'écran caméra ne retient que la première lecture valide (verrou, vibration, fermeture). `ScanGuard` (`school_core`) n'accepte qu'un envoi à la fois et ne renvoie pas une carte déjà traitée par le serveur dans les 5 dernières secondes. Un envoi qui n'a pas atteint le serveur (réseau absent) peut être retenté tout de suite.
- **Permission caméra :**
  - elle est demandée à l'ouverture du scanner ;
  - en cas de refus, un panneau explique pourquoi et propose de redemander, d'ouvrir les paramètres (canal natif de `school_core`) ou de passer en saisie manuelle ;
  - le cycle de vie n'est suivi que lorsque la caméra tourne.

  Ce dernier point corrige une boucle observée sur Android 10 : le dialogue système rendait l'application inactive, et elle redemandait la permission à chaque retour.
- **Arrière-plan :** la caméra est libérée, puis relancée au retour. Une permission retirée entre-temps fait apparaître le panneau « refusé ».
- **Délai :** sans lecture pendant 45 s, la caméra est arrêtée et un bouton « Réessayer » s'affiche.
- **Réseau absent ou délai dépassé :** le message dit explicitement que le passage n'est pas enregistré, avec un bouton « Réessayer l'envoi ».
- **Le lecteur USB/Bluetooth et la saisie** restent disponibles en secours. Le personnel garde ce mode seul.

## 4. Vérification

- **Tests Flutter** avec une caméra simulée (`test/camera_test.dart`) : 16 cas.
- **Tests de mutation :**
  - `backend/tools/mutation_check.py gate` (contrôle QR, isolation, permission) : 7/7 tuées ;
  - `mobile/tools/mutation_check.py` (format, double scan, permissions réseau et caméra, configuration réseau) : 11/11 tuées.
- **Tests réels sur l'IP LAN du PC :** QR révoqué après réémission ; WebSocket avec message et notification poussés, resynchronisation et session révoquée (fermeture 4401 en 30 s au plus, `REVALIDATE_SECONDS`).
- **Émulateurs Android 10 et 16 :** permission, refus sans boucle, aperçu, arrière-plan.
- **Non vérifié sur appareil :** la lecture d'un vrai QR par la caméra (la scène virtuelle de l'émulateur ne s'oriente pas en ligne de commande) et Android 17 / Pixel 7a.
