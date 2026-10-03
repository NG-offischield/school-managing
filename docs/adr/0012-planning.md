# ADR 0012 — Planning : emploi du temps, séances, disponibilités, remplacements

- **Statut :** accepté — 2026-10-03
- **Périmètre :**
  - `Room` et `SchoolClass.main_room` (app `academics`) ;
  - nouvelle app `scheduling` : `ScheduleSlot`, `TeachingSession`, `TeacherAvailability`, `TeacherAvailabilityException`, `SchoolBreak`, `ScheduleChange` ;
  - point d'intégration `GuardianScan.teaching_session` (app `attendance`).

## 1. `Course` reste la relation pédagogique de référence

`Course` porte déjà « matière + enseignant + classe + année » (ADR 0009) et sert au périmètre des enseignants, aux notes et aux bulletins. Le planning **programme** ce cours dans le temps et ne crée aucune table parallèle d'affectation enseignant ↔ classe. `TeacherClassAssignment` reste reporté.

`ScheduleSlot` et `TeachingSession` portent des **copies** de la classe, de l'enseignant (prévu), de la matière et de l'année du cours. Ce sont elles qui permettent à PostgreSQL d'interdire les chevauchements, et des FK composites `(course, x) → course(id, x)` garantissent qu'elles ne divergent jamais du cours. Pour la séance, cela inclut `planned_teacher` = `course.teacher`, grâce au nouveau paramètre `target_field` de `EnforceSameValue`.

## 2. Planning théorique et séances réelles sont séparés

| | `ScheduleSlot` (récurrent) | `TeachingSession` (daté) |
|---|---|---|
| Exemple | lundi 08:00–10:00, 3e A, maths, X, R12 | 2026-10-12 08:00–10:00 |
| Modifié comment | jamais sur place : fin (`effective_to`) ou archivage, puis nouveau créneau (`reschedule`) | annulation, déplacement, changement de salle, remplacement, permutation |
| Statuts | PUBLISHED / ARCHIVED | SCHEDULED / COMPLETED / CANCELLED |

Pour éviter de multiplier les statuts, les autres situations sont des **faits** portés par la séance :
- *remplacée* : `teacher` ≠ `planned_teacher`, les deux étant conservés ;
- *déplacée* ou *fin exceptionnelle* : `original_start` et `original_end` contiennent la **première** heure initiale ;
- *séance exceptionnelle* (rattrapage) : `schedule_slot` est NULL.

La génération (`generate_sessions`) est idempotente grâce à UNIQUE(slot, date). Elle saute les `SchoolBreak` et rattache chaque séance à la **période feuille** qui la contient (séquence ou semestre).

## 3. Conflits

| Conflit | Service (message clair) | PostgreSQL (filet de sécurité) |
|---|---|---|
| même classe, même enseignant ou même salle au même moment | `find_slot_conflicts` / `find_session_conflicts` → 409 `planning_conflict` avec `details.context.conflicts` | 6 contraintes d'exclusion (btree_gist) : créneaux PUBLISHED (jour × plage horaire `[)` × plage de dates) et séances SCHEDULED (`tstzrange`) |
| capacité de salle < effectif | 409 `room_capacity_exceeded` | — |
| cours, matière, catégorie, enseignant, classe ou salle inactifs ; année close | 400 (`course_inactive`, `room_inactive`…) | — |
| hors de l'année scolaire | 400 `outside_year` | — |
| mélange d'écoles ou d'années, copie divergente du cours | 404 côté API (ids résolus dans l'école) | 34 FK composites |

Les exclusions sont **DEFERRABLE**, car une permutation crée un chevauchement transitoire. Chaque service force la vérification (`SET CONSTRAINTS … IMMEDIATE`) avant de rendre la main : une violation remonte dans le service (409), jamais au commit final.

Les plages sont semi-ouvertes : 08:00–10:00 et 10:00–12:00 ne sont pas en conflit.

Le contrôle à blanc `POST /admin/schedules/check/` alimente l'écran « Conflits » du client PySide6 sans rien écrire.

## 4. Disponibilité des enseignants

- **Récurrente** (`TeacherAvailability`) : déclarée par l'enseignant (ou par l'admin), retirée et jamais supprimée. Créer un créneau sur une indisponibilité déclarée est refusé (`teacher_unavailable`), sauf si l'admin force **avec un motif** ; ce forçage est audité.
- **Datée** (`TeacherAvailabilityException`) :
  - soumise en PENDING par l'enseignant (ou saisie par l'admin) ;
  - décidée par un **admin qui n'est pas l'enseignant concerné** (pas d'auto-approbation, même pour un enseignant qui a aussi le rôle ADMIN) : APPROVED, REJECTED ou CHANGES_REQUESTED, avec un commentaire obligatoire sauf en cas d'approbation ;
  - l'enseignant peut retirer sa demande tant qu'elle n'est pas décidée ;
  - une approbation **n'annule rien en silence** : elle renvoie les séances impactées, que l'administration remplace, permute ou annule.

  Une indisponibilité approuvée bloque le déplacement d'une séance sur ce créneau et le choix de cet enseignant comme remplaçant.

## 5. Remplacements et permutations

- **Remplacement** (`substitute_teacher`) : il réutilise strictement la compatibilité de la phase people (`evaluate`), c'est-à-dire qualifications, catégorie, `SubjectCompatibilityRule` et dérogations.
  - Seuls COMPATIBLE ou OVERRIDDEN sont acceptés. Si une dérogation est nécessaire, une `CompatibilityOverride` auditée doit **déjà exister** ; sinon le refus `teacher_incompatible` indique le résultat calculé.
  - Le remplaçant doit aussi être actif, disponible et libre à ce moment.
  - `restore_teacher` rend la séance à l'enseignant prévu.
- **Permutation** (`swap_sessions`) : les deux séances échangent leurs horaires, chacune gardant son cours, son enseignant et sa salle. Les conflits sont vérifiés avant l'échange (en ignorant les deux séances concernées), puis par PostgreSQL. Les heures initiales sont conservées.
- **Traçabilité** : chaque opération exige un motif et un auteur, et écrit un `ScheduleChange` (anciennes et nouvelles valeurs).

## 6. Historique et préparation des notifications

`ScheduleChange` est à la fois l'historique et la **boîte d'envoi** des notifications :
- les changements qui comptent pour les familles et les enseignants (annulation, déplacement, salle, remplacement, permutation, fin de créneau) sont créés en `notification_status = PENDING`, avec la classe et les enseignants concernés ;
- le futur dispatcher (FCM) lira `GET /admin/planning/changes/?notification_status=PENDING` et passera seulement PENDING → SENT ;
- un trigger refuse toute autre modification et toute suppression.

Il généralise le `ScheduleChange` de la spec, qui ne concernait que les créneaux.

## 7. Vers la présence par séance

- `TeachingSession` est l'unité sur laquelle reposeront les feuilles d'appel (`StudentSessionAttendance`) et le pointage des enseignants (`TeacherSessionCheckIn`, champs `actual_start` / `actual_end` déjà présents).
- `GuardianScan.teaching_session` (nullable, même école garantie par FK composite) permettra de rattacher un scan à une séance précise.
- Les scans du portail laissent ce champ à NULL : la présence journalière et le QR annuel (ADR 0011) sont **inchangés**.

## 8. Visibilité

| | ADMIN / SUPER_ADMIN | STAFF | TEACHER | PARENT (lien vérifié) |
|---|---|---|---|---|
| salles | gestion | lecture | lecture | — |
| créneaux, séances | tout + gestion | lecture | les siens (enseignés ou prévus) | classes de ses enfants, sans données internes (`ParentSessionSerializer`) |
| changements | tout | notifiables | ceux qui le concernent | notifiables des classes de ses enfants, **sans motif ni auteur** |
| disponibilités | tout + décision | — | les siennes (déclaration, retrait) | — |

## Écarts par rapport à la spec

| Spec | Implémentation | Raison |
|---|---|---|
| `TeachingSession.schedule_slot` NOT NULL | nullable + `course` explicite | séances exceptionnelles (rattrapage) |
| `TeachingSession` | ajout de `planned_teacher` / `teacher`, `original_start` / `original_end`, `room`, `academic_period`, copies du cours | remplacement et déplacement tracés, filtres, présence par séance |
| `execution_status`, `absence_status`, `payable_status` | `status` (SCHEDULED / COMPLETED / CANCELLED) ; le reste est reporté | `absence_status` relève de la présence enseignant ; `payable_status` relève de la paie |
| `ScheduleChange` (créneau uniquement) | créneau ou séance, `change_type`, ancien/nouveau, champs de notification | historique unique et boîte d'envoi |
| `TeacherAvailabilityException.status` | statuts PENDING, APPROVED, REJECTED, CHANGES_REQUESTED, CANCELLED, plus auteur, décideur, date et commentaire | workflow de décision demandé |
| `PATCH /schedules/{id}/` | `.../end/` et `.../reschedule/` | jamais de modification sur place d'un créneau |
| `ClassAvailability`, `RoomAvailability` | **reportés** | les conflits de salle et de classe sont déjà garantis ; à ajouter si un générateur automatique est développé |
