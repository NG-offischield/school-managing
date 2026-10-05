# ADR 0026 — Compte parent, rattachement vérifié et application Flutter parent

- **Statut :** accepté pour la fondation — 2026-10-05.
  Les choix marqués **[à valider]** attendent la décision métier de l'utilisateur.
- **Périmètre :**
  - backend : inscription d'un parent, demande de rattachement, vérification d'identité, parrainage
    d'un second parent ;
  - poste d'administration : page Parents ;
  - mobile : `mobile/apps/parent`, sur le socle `mobile/packages/school_core`.
- **Hors périmètre :**
  - applications Gardien et Personnel ;
  - packaging Windows ;
  - paiement mobile (aucun paiement n'est lancé depuis l'application parent) ;
  - ouverture des PDF dans une visionneuse native.

## 1. Audit : ce qui existait, ce qui manquait

**Spécification V4 :**
- §6.3 : `POST /registrations/parent/` et file de validation administrative.
- §6.5 : `/parents/link-requests/`, `…/student-approve/`, `…/sponsor/`, `…/2fa/verify/`,
  `/admin/link-requests/{id}/approve/`, `/parents/children/`.
- Tables `RegistrationRequest`, `IdentityVerification`, `ParentStudentLinkRequest`, `VerificationChallenge`.
- §9 : « un rattachement est un workflow vérifié, pas une correspondance de nom ».

**Déjà en place avant cette phase :**
- `ParentStudent` (DÉCLARÉ / VÉRIFIÉ) avec ses droits par lien (`can_pay`, `can_view_financial_data`,
  `can_receive_notifications`, `can_submit_complaints`).
- La vérification administrative par service (`verify_parent_link`).
- La lecture parent, toujours limitée aux liens **vérifiés** :
  - `GET /parents/children/`, `GET /parents/convocations/` ;
  - `students/{id}/attendance|scans|timetable|sessions/` (le scan ne dit jamais qui a scanné) ;
  - `finance/students/{id}/obligations/` (403 si le lien n'ouvre pas la finance), factures et paiements ;
  - `report-cards/` (bulletins VALIDÉS seulement pour un parent), PDF, `documents/verify/` ;
  - notifications, conversations, réclamations, WebSocket.

**Manquait :** toute l'inscription, les demandes de rattachement, la vérification d'identité, le parrainage
et le 2FA. Aucune API ne permettait non plus à un parent de savoir à quel enseignant écrire.

Ces API ont été **construites**. Aucune autre API métier n'a été ajoutée : l'application parent lit
uniquement les API existantes.

## 2. Le parcours (le serveur décide de tout)

```
Créer mon compte ──► compte EN ATTENTE ──► l'école valide ──► parent (rôle PARENT, profil)
        │                                      (ou refuse : compte désactivé)
        ▼
« C'est mon enfant » : matricule + date de naissance + pièce d'identité (type + numéro)
        │
        ├── l'école compare la pièce ORIGINALE présentée au guichet ──► identité VÉRIFIÉE
        │     (ou : un parent déjà vérifié de l'élève a remis un code ──► identité SPONSOR_2FA)
        ├── l'élève désigne son parent (réponse saisie par l'école) ou « non requise »
        └── l'école valide en choisissant les droits ──► ParentStudent VÉRIFIÉ ──► accès
```

### Inscription — §6.3
- `POST /registrations/parent/` est public et limité à 5 requêtes par minute.
- Le parent choisit son mot de passe :
  - validé par les validateurs Django, avant toute recherche ;
  - haché en Argon2.
- Le compte est créé avec un membership **PENDING**, sans rôle.
- **Pas d'énumération :** la réponse est toujours `202 RECEIVED`, même si l'e-mail est déjà utilisé ou
  l'école inconnue.
  - Un doublon est tracé en événement de sécurité.
  - Le hachage est aussi calculé quand rien n'est créé, pour que le temps de réponse ne trahisse rien.
- Un compte PENDING **peut se connecter**, mais ne lit que `GET /registrations/me/`. Toute donnée de
  l'école répond 403 `NO_ACTIVE_MEMBERSHIP`.
- Validation par l'école : membership ACTIVE, rôle PARENT, `ParentProfile`.
- Refus : membership LEFT, et le compte est désactivé s'il n'a pas d'autre école active.

### Demande de rattachement — §6.5
- **Identification de l'élève :** le matricule **et** la date de naissance doivent correspondre.
  - Une erreur, un élève inconnu ou un élève d'une autre école donnent tous la même réponse
    (`student_not_found`).
  - Un parent ne peut donc pas parcourir les élèves.
- **Pièce d'identité :** le numéro n'est **jamais stocké**.
  - Seul un HMAC-SHA256 (clé `SECRET_KEY`) du numéro normalisé est conservé : majuscules, sans
    espaces ni tirets.
  - Aucune API ne renvoie ni le numéro ni son empreinte, pas même l'administration.
  - Aucune image n'est conservée.
- **Contrôle à l'école :** l'administration saisit le numéro de la pièce **originale** ; le serveur
  compare les empreintes.
  - Le type de pièce doit aussi correspondre.
  - Après 3 écarts, l'identité est REFUSÉE.
  - Les écarts restent comptés même en cas d'erreur : vue non atomique, ce qui est validé.
- **Validation finale :** elle exige une identité VÉRIFIÉE et la désignation de l'élève (APPROVED ou
  NOT_REQUIRED).
  - Elle crée ou active le `ParentStudent` vérifié, par le service existant (`verify_parent_link`,
    méthode ID_DOCUMENT ou SPONSOR_2FA).
  - Elle fixe les droits. Les droits financiers ne sont **jamais** accordés par défaut.

### Second parent : parrainage + code à usage unique (« 2FA »)
- Un parent **vérifié** de l'élève génère un code dans son application :
  - `POST /parents/children/{id}/sponsor-codes/` ;
  - 8 caractères lisibles (XXXX-XXXX), valable 10 minutes ;
  - seul son hachage est stocké, et il est affiché une seule fois (`Cache-Control: no-store`).
- Il le remet **en main propre** au second parent, qui le saisit dans sa demande :
  - `POST /parents/link-requests/{id}/sponsor/` ;
  - au plus 5 tentatives par code, comptées même en cas d'échec ;
  - un nouveau code annule le précédent.
- Le code remplace la pièce : l'identité devient SPONSOR_2FA / VÉRIFIÉE.
- La désignation par l'élève et la **validation de l'école restent obligatoires**.
- Le parent parrainé n'a **jamais plus de droits financiers que son parrain** (`rights_exceed_sponsor`).
  Si le parrain n'est plus vérifié, la validation est refusée (`sponsor_not_verified`).

## 3. Décisions à valider, et écarts à la spécification

1. **[à valider] Mot de passe choisi à l'inscription** (spec §6.3 muette).
   - Alternative : inscription sans mot de passe, puis code d'activation (ADR 0024) remis par l'école.
   - Le choix retenu évite un passage au guichet de plus. Le compte ne voit rien tant que l'école n'a pas
     validé.
2. **[à valider] Désignation par l'élève saisie par l'administration** (`/admin/link-requests/{id}/student-approval/`).
   - La spec prévoit `…/{id}/student-approve/` côté élève, mais les élèves n'ont pas de compte en V1.
   - « Non requise » est possible : élève trop jeune, ou lien établi par un document officiel.
3. **[à valider] 2FA = code remis en main propre** (canal IN_APP), au lieu d'un SMS ou d'un e-mail :
   aucun fournisseur n'est intégré (pas de dépendance cloud).
   - `/sponsor/` et `/2fa/verify/` de la spec sont réunis en un seul appel : le code **est** la preuve
     du parrainage.
4. `VerificationChallenge` porte `school` (multi-école) et `target_id` (l'élève concerné). Il reste
   générique pour d'autres usages.
5. `IdentityVerification` : `document_reference_hash` est un **HMAC** (et non un simple hachage, qu'un
   dictionnaire de numéros pourrait inverser).
   - `failed_checks` a été ajouté.
   - `legacy_reference` n'est pas repris (aucune reprise de données en V1).
6. Ajout de `GET /parents/children/{id}/teachers/` : les enseignants des cours actifs d'un enfant vérifié.
   Sans lui, l'échange parent–enseignant de la spec était inaccessible, car la création de conversation
   exige l'identifiant de l'enseignant.
7. `GET /parents/children/` renvoie aussi la scolarité de l'année courante : classe, année, statut.

## 4. Modèle et contraintes PostgreSQL

- `people.RegistrationRequest`, `people.IdentityVerification`, `people.ParentStudentLinkRequest`
  (migration `people 0003`) et `accounts.VerificationChallenge` (migration `accounts 0005`).
- **CHECK :**
  - valeurs des statuts ;
  - revue cohérente avec le statut ;
  - refus avec motif ;
  - VÉRIFIÉE ⇒ date ;
  - pièce ⇒ empreinte ;
  - APPROUVÉE ⇒ lien et date ;
  - parrainage ⇒ parrain.
- **UNIQUE partielle :** une seule demande EN COURS par couple (parent, élève).
- **Même école** (`people 0004`, `EnforceSameValue`) : clés étrangères composites sur le membership,
  le parent, l'élève, l'identité, le parrain et le lien.
- **Journalisation :**
  - chaque décision est enregistrée dans l'audit (couche ADMINISTRATIVE) ;
  - inscriptions, doublons, écarts d'identité, codes émis et codes refusés sont des événements de
    sécurité.

## 5. Poste d'administration : Gestion académique → Parents

- **Onglet Rattachements** (en cours par défaut). La fiche d'une demande propose les actions selon son état :
  - Vérifier l'identité… : type et numéro de la pièce originale ;
  - Désignation par l'élève… ;
  - Valider le rattachement… : droits, financiers décochés ;
  - Refuser… : motif.
- **Onglet Inscriptions :** Valider, ou Refuser… avec un motif.
- Les refus du serveur sont expliqués dans le bandeau (`school_admin/messages.py`).
- Les dialogues `FormDialog` sont couverts par `tests/test_responsive.py`.

## 6. Application Flutter parent

**Socle partagé**, sans duplication de l'authentification. `school_core` gagne :
- **`AuthStatus.pending`**, activé par `allowPending`, et `reloadIdentity()`.
  - Un compte en attente garde sa session et ne voit que l'état de son inscription.
  - L'application enseignant traite ce statut comme une déconnexion.
- **`ApiClient.download()`** : PDF, avec le même jeton, le même rafraîchissement et les mêmes erreurs.
- **`CommunicationRepository`** et les modèles communs : notifications, conversations, messages,
  réclamations, `formatMoney`.
  - Ils viennent de l'application enseignant, dont le dépôt hérite désormais au lieu d'en avoir une copie.

**Écrans :**
- Connexion, Créer mon compte, compte en attente.
- Accueil : enfants visibles (classe, année, scolarité), notifications, convocations, raccourcis, avec
  un sélecteur d'enfant.
- Présences : bilan calculé par le serveur, convocations, passages au portail, historique.
- Planning : jour ou semaine, enseignant, salle ; cours annulé, déplacé ou remplaçant.
- Scolarité et paiements :
  - sans `can_view_financial_data`, les obligations ne sont **même pas demandées** (le serveur
    répondrait 403) ; seuls mes paiements de payeur sont listés ;
  - « peut payer » est **la réponse du serveur**, jamais une déduction ;
  - les montants sont des chaînes du serveur ;
  - les reçus sont téléchargeables ;
  - aucun paiement n'est lancé.
- Bulletins officiels (le serveur ne donne jamais un bulletin provisoire), avec le PDF à la marque de
  l'**école** et la vérification d'un code imprimé.
- Messages :
  - écrire à l'administration ou à un enseignant de l'enfant ;
  - réclamations ;
  - temps réel `ws/v1/realtime/` : reconnexion, resynchronisation ; 4401 déclenche un rafraîchissement,
    puis la reconnexion.
- Rattachements : demande, code de parrainage reçu, génération d'un code ; profil.

**Identité visuelle :** le nom du logiciel n'apparaît que sur le splash, la connexion et le profil. Le
logo officiel n'est toujours pas fourni : rien n'est fabriqué. Les documents scolaires gardent la marque
de l'école.

**Défauts latents corrigés dans l'application enseignant**, révélés par le parcours parent :
1. Une conversation ouverte au-dessus du shell n'avait pas accès à l'état temps réel
   (`ProviderNotFoundException`).
2. `setState(() => _future = …)` renvoyait un `Future`, assertion Flutter dans les onglets Messages et
   Réclamations.
3. `dispose()` lisait un provider via le `context`.

Un test de non-régression a été ajouté côté enseignant.

## 7. Vérification

- **Backend :** `tests/test_parent_workflow.py` couvre :
  - l'inscription (réponse générique, doublon, mot de passe faible, compte en attente) ;
  - la validation et le refus ;
  - le matricule et la date de naissance, l'empreinte jamais exposée, les 3 écarts ;
  - la désignation, le parrainage (code unique, expiré, tentatives, droits du parrain) ;
  - l'isolation : parent A / B, autre école, lien non vérifié, compte suspendu, finance 403, scan sans
    scanneur.
- **Mutations :** `tools/mutation_check.py parents`, 15 mutations : filtre parent/enfant, contrôles de
  vérification, isolation école.
- **Poste :** `tests/test_parents_admin.py`, plus les dialogues dans `test_responsive.py`.
- **Mobile :**
  - `school_core` ;
  - application parent : faux backend reproduisant le contrat ;
  - application enseignant : non-régression.
- **E2E réel** : `backend/tools/e2e_parent_fixture.py` sur le conteneur de test (base db_test), puis
  `flutter test test/live_test.dart` sur le parcours complet :
  - création, attente, validation ;
  - demande, écart puis concordance de la pièce, désignation, validation ;
  - accueil, présence, planning, finance ;
  - bulletin provisoire caché puis validé avec son PDF ;
  - notification REPORT_CARD, messages ;
  - isolation, WebSocket, déconnexion.
