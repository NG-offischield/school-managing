# ADR 0024 — Cycle de vie des comptes : activation et suspension

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - activation des comptes créés par l'administration (enseignants, personnel, tout compte métier) ;
  - suspension et réactivation ;
  - fiche enseignant du poste PySide6.
- **Hors périmètre :**
  - vérification parent (CNI, 2FA, second parent / tuteur, parrainage) : domaine Parent ;
  - applications Flutter ;
  - envoi automatique du code (e-mail, SMS) : aucune dépendance cloud.
- **Migration :** `accounts/0004_account_activation` (table `AccountActivation`, nouveaux types de SecurityEvent).

## 1. Constat (audit)

- `User` porte l'identité globale ; les mots de passe sont en Argon2.
- `SchoolMembership` et ses rôles portent le droit d'agir dans une école.
- `UserSession` : jeton d'accès signé et court, jeton de renouvellement opaque haché (SHA-256), rotation avec
  détection de réutilisation ; la session est revérifiée à chaque requête.
- `SecurityEvent` : journal séparé et durable.
- Création d'enseignant : un `User` **sans mot de passe utilisable** et une adhésion ACTIVE. Il n'existait aucun
  moyen pour la personne de définir un premier mot de passe.

**Pas de second système d'authentification :** l'activation ne fait que définir le premier mot de passe du `User`
existant. La connexion reste `/auth/login/`.

## 2. Mécanisme : code d'activation à usage unique

- **Code :** 20 caractères Crockford base32, soit environ 100 bits, groupés par 4 : `7KQ2-M9XA-4TZP-QH3W-B8NC`.
  - Saisissable à la main (application mobile, poste) ou encodable en QR plus tard.
  - Normalisé à la saisie : casse, espaces et tirets ignorés, I/L → 1, O → 0.
- **Stockage :** uniquement le **SHA-256** du code, comme pour les jetons de renouvellement. 100 bits aléatoires
  rendent un hachage lent inutile.
  - Le code est rendu **une seule fois** à l'administrateur (réponse `Cache-Control: no-store`).
  - Il n'est jamais journalisé : audit et événements de sécurité ne portent que l'id de l'activation.
- **Durée de validité :** 72 h (`ACCOUNT_ACTIVATION_LIFETIME_HOURS`).
- **Usage unique :**
  - la ligne est verrouillée (`select_for_update`) puis `used_at` est posé ;
  - une CHECK interdit à une même ligne d'être à la fois utilisée et révoquée ;
  - un index unique partiel garantit **un seul code en attente par adhésion** : en émettre un nouveau révoque
    l'ancien.
- **Révocation :** explicite par l'administration, ou automatique lors d'une suspension.
- **Historique :** les lignes ne sont jamais supprimées.
- **Remise du code :** en main propre ou imprimé, par l'établissement.

## 3. API, trois familles séparées

| Famille | Endpoints | Accès |
|---|---|---|
| Administration | `GET /admin/accounts/{membership}/` ; `POST …/activation/` (code rendu une fois) ; `POST …/activation/revoke/` ; `POST …/disable/` {motif} ; `POST …/enable/` | ADMIN / SUPER_ADMIN de l'école ; un membre d'une autre école → 404 |
| Activation par la personne | `POST /auth/activation/check/` {code} → prénom, école, identifiant, échéance ; `POST /auth/activation/complete/` {code, password} | anonyme, throttling `auth-activation` (10/min) |
| Authentification normale | `/auth/login/`, `/auth/refresh/`, `/auth/logout/` | inchangée |

L'administration n'envoie **jamais** de mot de passe : c'est la personne qui le choisit.

`complete` applique les validateurs Django (longueur, ressemblance, mots de passe courants) puis hache en Argon2.
Un mot de passe trop faible renvoie 400 VALIDATION_ERROR, et le code reste utilisable.

**Anti-énumération :** tout refus d'un code donne la même réponse, `400 INVALID_ACTIVATION_CODE`, que le code
soit inconnu, expiré, déjà utilisé ou révoqué, que le compte soit suspendu ou déjà activé. La raison est
inscrite dans `ACCOUNT_ACTIVATION_REJECTED` (journal de sécurité) uniquement.

## 4. États d'un compte

| État | Condition |
|---|---|
| `DISABLED` | adhésion non ACTIVE, utilisateur inactif ou école non active |
| `ACTIVE` | mot de passe utilisable |
| `PENDING_ACTIVATION` | un code valide attend |
| `NOT_ACTIVATED` | ni mot de passe ni code valide (jamais émis, expiré ou révoqué) |

La fiche métier (enseignant, employé) existe indépendamment de l'état du compte.

## 5. Suspension

`disable` exige un motif et refuse sa propre adhésion. Seul un SUPER_ADMIN gère un compte SUPER_ADMIN. La
suspension :

1. passe l'adhésion en SUSPENDED ;
2. rend l'utilisateur inactif s'il n'a pas d'autre école active ;
3. révoque toutes ses sessions et son code en attente.

La connexion et le renouvellement sont alors refusés **par les contrôles existants** : utilisateur inactif,
session révoquée. `enable` rétablit l'adhésion et l'utilisateur.

## 6. Audit

| Où | Événements |
|---|---|
| `AuditLog` (administratif) | ACCOUNT_ACTIVATION_ISSUED / _REVOKED, ACCOUNT_ACTIVATED, ACCOUNT_DISABLED / _ENABLED |
| `SecurityEvent` | ACCOUNT_ACTIVATION_ISSUED / _REVOKED, ACCOUNT_ACTIVATED, ACCOUNT_ACTIVATION_REJECTED (avec raison), ACCOUNT_DISABLED / _ENABLED |

## 7. Poste d'administration

La fiche enseignant affiche dans la section « Compte » :

- l'état, l'identifiant de connexion, l'échéance d'un code en attente, la date d'activation et la dernière
  connexion ;
- uniquement les actions permises par l'état : générer (ou regénérer) un code, révoquer le code, suspendre,
  réactiver.

Le code s'affiche **une fois**, dans une fenêtre dédiée avec un bouton « Copier ». Il n'apparaît ni dans les
bandeaux, ni dans les journaux, ni dans le `repr` de l'objet.

## 8. Vérifications

- `tests/test_account_activation.py` couvre : parcours complet, expiration, réutilisation, révocation, mauvais
  code, réponse identique, compte suspendu, permissions, autre école (API et service), throttling, audit,
  absence du code et de tout mot de passe en clair.
- `tools/mutation_check.py activation` passe 7/7 mutations : vérification du code, isolation école (API et
  service), usage unique, expiration, révocation, compte suspendu.
- L'E2E desktop exerce sur `db_test` le parcours enseignant complet, le refus de réutilisation et un compte
  suspendu.
