# ADR 0027 — Applications Flutter Gardien et Personnel, socle mobile commun

- **Statut :** accepté — 2026-10-05.
- **Périmètre :** `mobile/apps/guardian`, `mobile/apps/staff`, mise en commun dans `mobile/packages/school_core`.
- **Hors périmètre :** paiement mobile, packaging Windows, release finale, scan par caméra.
- **Backend :** aucune nouvelle API métier. Ajouts :
  - un champ en lecture : `function_labels` (nom des fonctions) dans `GET /staff/` ;
  - un fichier de tests de sécurité ;
  - une suite de mutations `field` ;
  - un fixture E2E (base de test uniquement).

## 1. Audit des API existantes

**Gardien :**
- `POST /qr/scans/` : le protocole QR existant, non modifié.
  - Le serveur rend le résultat, l'arrivée de l'élève et le statut de solvabilité (UP_TO_DATE / OVERDUE).
  - Le statut de solvabilité est réservé au gardien et à l'administration (ADR 0014), sans jamais de montant.
- `GET /guardians/scans/?date=` : les scans **de l'appelant**, filtrés par le serveur.
- Notifications et temps réel ; `GET /school-breaks/` (fermetures).
- **Pas de messagerie :** les gardiens en sont exclus par la spec (§8, `MESSAGING_ROLES`).
- **Pas de réclamations :** elles sont réservées aux parents (pour leur enfant) et aux enseignants.
- Aucun dossier d'élève, note, finance, paie ni liste du personnel.

**Personnel :**
- `GET /staff/` : sa propre fiche et ses fonctions.
- `GET /sessions/` et `/planning/changes/` : le planning de l'école, que le personnel peut lire.
- `GET /payroll/me/` : ses paies validées ou payées seulement.
- Scan autorisé, **sans** solvabilité.
- Messagerie vers l'administration autorisée ; réclamations non autorisées.
- **Présence du personnel :** aucune API n'existe. L'application l'indique au lieu d'en inventer une.

## 2. Mise en commun (sans changer d'architecture)

Quatre applications partageaient ou allaient copier les mêmes écrans. Ils vivent maintenant dans
`school_core` :
- `SignInScreen` + `SignInAlternative`, avec deux chemins :
  - activation d'un compte créé par l'école ;
  - inscription d'un parent.
- `ActivationScreen`, auparavant dans l'application enseignant.
- `LiveState`, état temps réel du shell : branchement de `RealtimeClient`, reconnexion au retour au
  premier plan, expiration de session.
- `openAbove()` : ouvre un écran au-dessus du shell en lui redonnant ses providers.
- `CommunicationScreen` (notifications, messages, réclamations, **selon le rôle**), `ConversationScreen`,
  `AdminMessageScreen`, `ComplaintComposer`.
- Module Portail (`GateRepository`, `ScanScreen`, `MyScansScreen`) : le protocole QR existant,
  partagé par le gardien et le personnel.
  - Le jeton est saisi ou envoyé par un lecteur QR « clavier ».
  - Le scan par caméra demanderait un plugin natif : hors de cette phase.
- `upcomingBreaks()` (calendrier), formats de dates, `showMessage`.
- `package:school_core/testing.dart` : `FakeChannel` pour les tests WebSocket.

Les applications enseignant et parent utilisent désormais ces composants ; leurs copies locales ont été
supprimées.

## 3. Régressions communes corrigées

1. **Historique des passages figé :** il n'était pas rechargé après un scan, car l'onglet reste construit
   dans l'`IndexedStack`. `GateRepository.scans` notifie chaque scan et l'historique se recharge.
2. **Libellé parasite** dans les réclamations enseignant (« ne vous concerne ») : le libellé est commun,
   et le test est mis à jour.

## 4. Sécurité vérifiée

**Backend** (`tests/test_guardian_staff_api.py`) :
- scans propres seulement (gardien A, gardien B, personnel, autre école) ;
- solvabilité selon le rôle, sans montant ;
- aucun dossier d'élève, finance, paie ni administration pour un gardien ;
- gardien inactif ; comptes suspendus ; jeton invalide ;
- communication propre à chaque rôle ;
- personnel :
  - sa seule fiche avec les noms des fonctions ;
  - ses seules paies (celle d'un collègue renvoie 404) ;
  - le planning de son école, jamais d'une autre ;
  - aucun droit d'administration.

**Mutations** (`tools/mutation_check.py field`, 8) :
- isolation : scans, liste du personnel, paie, filtrage par école ;
- permission : solvabilité, droit de scanner, gardien inactif, messagerie des gardiens.

**Mobile :** faux backends au contrat du serveur, tests d'interface et de sécurité, parcours réels sur
db_test (`backend/tools/e2e_field_fixture.py`, puis `test/live_test.dart` dans chaque application).
