# ADR 0025 — Socle mobile Flutter et application enseignant

- **Statut :** accepté — 2026-10-05
- **Périmètre :** `mobile/packages/school_core` (socle partagé) et `mobile/apps/teacher` (première verticale).
- **Hors périmètre :**
  - applications Parent, Gardien et Personnel ;
  - paiement mobile, fonctions médicales ;
  - pièces jointes depuis le téléphone ;
  - packaging de release.
- **Backend :** aucune modification. Uniquement les API existantes.

## 1. Structure

```
mobile/packages/school_core   client HTTP, erreurs, session, stockage du jeton, temps réel, thème, composants
mobile/apps/teacher           data/ (dépôt d'accès à l'API), models/ (lecture), presentation/ (écrans)
```

- Les futures applications Parent, Gardien et Personnel dépendront de `school_core` (dépendance `path`)
  au lieu de dupliquer l'infrastructure.
- Pas de monorepo outillé ni de générateur de code : `provider` pour l'état, navigation Material simple.
- Le métier reste dans Django.

## 2. Authentification : pas de seconde authentification

- **Connexion :** `POST /auth/login/` (identifiant, mot de passe, appareil).
  - Le jeton d'accès reste **en mémoire**.
  - Seul le **refresh token** est stocké, dans `flutter_secure_storage` (Android Keystore).
  - Le mot de passe n'est jamais conservé ; les champs sont vidés après envoi.
- **Requêtes :** sur un 401, un seul `POST /auth/refresh/` (rotation du jeton, partagé par les requêtes
  simultanées), puis la requête est rejouée une fois. Un refresh refusé (session révoquée, compte suspendu)
  ramène à l'écran de connexion avec un message.
- **Activation (ADR 0024) :** `check` (code) → mot de passe + confirmation → `complete` → retour à la
  connexion normale.
  - La force du mot de passe est jugée **par le serveur** (validateurs Django) et ses messages sont affichés.
  - Le code n'est plus affiché après usage.
- **Rôle :** l'application enseignant refuse un compte sans rôle TEACHER ; la session ouverte est
  aussitôt fermée côté serveur.

## 3. Écrans

| Écran | API |
|---|---|
| Accueil | `/auth/me/`, `/courses/` (mes cours), `/teacher/sessions/` (aujourd'hui → J+14), `/notifications/unread-count/`, `/teacher/payroll/` (ma rémunération du mois, masquée si refusée) |
| Planning | `/teacher/sessions/?date_from=&date_to=` (jour ou semaine ; remplacements « Vous remplacez X » / « Remplacé par Y ») |
| Séance | `/sessions/{id}/`, `/planning/changes/?session=`, `POST /teacher/sessions/{id}/check-in/` (présence auto-déclarée, validée ensuite par l'administration) |
| Communication | notifications (lecture, tout lire), conversations et messages (envoi avec `client_id` réutilisé en cas de coupure), réclamations visibles |
| Profil | identité, établissement, déconnexion, « À propos » |

- **Isolation :**
  - l'application n'envoie **jamais** d'identifiant d'enseignant pour choisir les données lues ;
  - elle n'utilise que les endpoints « moi » et la visibilité du serveur ;
  - la séance d'un autre enseignant renvoie 404.
- **Temps réel :** `RealtimeClient` (`school_core`) sur l'endpoint Channels existant.
  - Notifications et messages arrivent en direct ; le badge des non-lus est mis à jour.
  - Reconnexion automatique, et au retour de l'application au premier plan.
  - La resynchronisation porte sur ce qui a été manqué.
  - Une fermeture 4401 déclenche un refresh, sinon la session est expirée.

## 4. Identité visuelle

- Les jetons de couleur sont ceux du poste : marine `#0F2747`, bleu `#1D4ED8`, contrastes WCAG.
- Boutons d'au moins 48 dp, mises en page défilantes (clavier, petits écrans), états chargement / vide /
  erreur avec « Réessayer », message hors ligne explicite.
- **Identité du logiciel :** le nom « School Managing » apparaît sur l'écran de démarrage, la connexion et
  le profil.
  - Le fichier officiel du logo (concept 5) n'est pas encore dans le dépôt : **aucun logo n'est fabriqué**,
    le nom est en texte.
  - Les documents de l'école gardent l'identité de l'établissement.

## 5. Android

- `INTERNET` ; `allowBackup=false`.
- HTTP en clair **uniquement dans la build debug**, vers `10.0.2.2`, `127.0.0.1` et `localhost`. La release
  reste en HTTPS.
- L'URL de l'API est donnée à la compilation (`--dart-define=API_URL=…`).
- NDK `29.0.13599879` : seul NDK complet sur la machine de développement.

## 6. Tests

- **`school_core` (10 tests) :**
  - client HTTP (erreurs, hors ligne) ;
  - session : seul le refresh est stocké, refresh unique, refresh refusé → expirée, restauration,
    déconnexion, compte suspendu, mauvais rôle ;
  - activation ;
  - WebSocket avec un faux canal (authentification, resynchronisation, 4401 → refresh puis expiration).
- **Application (7 tests de widgets)**, contre un faux backend à deux enseignants :
  - isolation A/B ;
  - connexion et ses erreurs ;
  - activation complète ;
  - planning et séance (présence refusée avant le début, puis acceptée) ;
  - notifications ;
  - session révoquée, hors ligne puis « Réessayer », déconnexion ;
  - session reprise au démarrage sur petit écran.
- **Parcours réel** (`test/live_test.dart`, opt-in) sur une base de test préparée par
  `mobile/tools/prepare_live_teacher.py` :
  1. activation, connexion ;
  2. mes cours et mes séances seulement ;
  3. remplacement, présence déclarée, changements ;
  4. séance de B → 404 ;
  5. notifications ;
  6. WebSocket réel ;
  7. déconnexion, ancien jeton refusé, reconnexion et refresh ;
  8. code non réutilisable.
