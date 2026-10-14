# Présences : état des workflows (mis à jour le 14 octobre 2026)

Audit des fonctionnalités de présence. Chaque ligne indique ce qui existe réellement et ce qui manque.

| Fonctionnalité | Modèle | API | Service | Interface | Tests | État |
|---|---|---|---|---|---|---|
| Correction d'une présence | `StudentDailyAttendance` (+ audit `ATTENDANCE_CORRECTED`) | `POST /admin/attendance/{id}/correct/` | `correct_attendance` : motif obligatoire, admin, même école, heure d'arrivée → présent ou en retard | **Desktop** : onglet « Présences du jour », bouton « Corriger… » / double-clic | backend existants ; desktop `test_attendance_page.py` | **Terminé** (desktop) |
| Codes QR annuels | `StudentQRCode` (version, révocation, audit) | `GET /admin/qr-codes/`, `issue/`, `issue-class/`, `reissue/`, `{id}/revoke/` | émission idempotente, élève inscrit, année ouverte, motif pour révoquer | **Desktop** : onglet « Codes QR » (par classe) ; la carte d'élève (Documents) imprime le code actif | backend existants ; desktop `test_attendance_page.py` | **Terminé** (desktop) |
| Présence des enseignants | `TeacherSessionCheckIn` | `POST /teacher/sessions/{id}/check-in/` (mobile) ; `POST /admin/sessions/{id}/validate/` et `reject/` | `validate_session` / `reject_session` : séance terminée, non payée, corrections tracées | Mobile enseignant : auto-déclaration (existant). **Desktop** : Planning → « Séance ▾ » → valider / séance non assurée | backend existants ; desktop `test_planning.py` | **Terminé** (desktop) |
| Convocations | `Convocation` (+ audit `CONVOCATION_CREATED/UPDATED`, notification bilingue `CONVOCATION`) | `GET/POST /admin/convocations/` (`?student=`, `?status=`), `POST …/{id}/status/`, **`GET /admin/convocations/recipients/?student=`** ; `GET /parents/convocations/` | `create_convocation` (lien actif et vérifié, motif, fin après début, niveau d'alerte enregistré), `set_convocation_status` (une seule clôture) | **Desktop** : onglet « Convocations » (liste, nouvelle convocation, clore). Parent mobile : consultation (existant) | `tests/test_convocation_admin_api.py` ; desktop `test_attendance_page.py`, `test_l10n.py` | **Terminé** (desktop), hors déclenchement automatique |
| Présence du personnel non enseignant | — | — | — | Personnel mobile : indique que la fonction n'existe pas (ADR 0027) | — | **Non défini** |

## Convocations : contrat retenu

**`GET /admin/convocations/recipients/?student=<id>`** (ADMIN / SUPER_ADMIN de l'établissement)

- **Contenu :** les parents qu'on peut convoquer à propos de l'élève, c'est-à-dire ceux dont le lien `ParentStudent` est **actif et vérifié**. Ce sont les liens que `create_convocation` accepte. Les liens déclarés, non vérifiés ou désactivés n'apparaissent jamais.
- **Ordre :** contact principal d'abord, puis par nom.
- **Champs :** `parent` (l'identifiant `ParentProfile` attendu par `POST /admin/convocations/`), `name`, `relationship_type`, `is_primary_contact`, `verified_at`, `notified`. `notified` est indicatif : il dit si le parent recevra aussi la notification (compte actif et notifications acceptées sur ce lien).
- **Jamais renvoyé :** téléphone, e-mail, adresse, pièce d'identité.
- **Erreurs :** paramètre absent ou mal formé : 400. Élève inconnu ou d'un autre établissement : 404 (même réponse). Rôle non administrateur : 403. Non authentifié : 401.

**Liste, création et clôture côté administration**

- Les réponses gardent tous les champs précédents et ajoutent `student_name`, `student_number` et `parent_name`, en lecture seule. Le filtre facultatif `?status=` répond 400 pour une valeur inconnue.
- La route des parents (`/parents/convocations/`) garde son contrat d'origine, sans ces champs.

**Notifications**

La notification `CONVOCATION` passe par le mécanisme bilingue (ADR 0031). Le motif et les notes saisis par l'administration ne sont pas recopiés dans la notification, et ne sont jamais traduits.

**Reste à décider : déclenchement automatique**

La spécification dit que « les alertes rouges peuvent créer des convocations programmées ». Le seuil, l'auteur de la convocation, le créneau proposé et le parent choisi (s'il y en a plusieurs) ne sont pas définis. Aujourd'hui, la décision reste humaine : le niveau d'alerte est seulement enregistré dans la convocation.

## Personnel non enseignant : décisions métier manquantes

**Ce qui existe :**
- `StaffProfile` et les fonctions (`StaffFunction`, `StaffFunctionAssignment`) ;
- une paie à **salaire fixe** : `StaffPayroll.gross_amount = base_salary + adjustments_amount`, avec les corrections manuelles `SalaryAdjustment`.

Aucune présence n'intervient dans cette paie.

**Ce qui n'existe pas :** aucun modèle de pointage ni endpoint pour le personnel. L'application Personnel l'indique explicitement (« Pas encore disponible… »).

La présence des élèves (portail QR, politique horaire) et celle des enseignants (séances déclarées puis vérifiées) **ne doivent pas être détournées** pour la simuler.

**Décisions à prendre avant tout développement :**
1. **Mode de pointage :** QR au portail, déclaration dans l'application Personnel, saisie par l'administration, ou une combinaison.
2. **Horaires de référence :** par fonction, par personne ou par jour ; gestion des horaires décalés et du travail le week-end.
3. **Retard et absence :** existe-t-il un seuil de retard ? Une absence est-elle automatique faute de pointage, ou toujours déclarée par l'administration ?
4. **Absences justifiées :** congés, maladie, mission ; qui les valide, et avec quelles pièces.
5. **Effet sur la paie :** aucun (salaire fixe), ou retenue, et selon quel barème. Toute retenue passerait par `SalaryAdjustment`, pour garder l'historique.
6. **Droits :** qui consulte, corrige ou exporte la présence d'un employé ; ce que l'employé voit de la sienne.
7. **Données conservées et durée de conservation** (données personnelles de travail).
