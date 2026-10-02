# ADR 0008 — Socle métier School + Academic + People

- **Statut :** proposé — 2026-10-02 (à valider avec le rapport de phase)
- **Contexte :** premier domaine métier après le Gate 0. Le périmètre couvre la structure académique et les personnes. Attendance, planning, finance, paie, communication et QR sont exclus.

## Organisation

| App | Modèles | Rôle |
|---|---|---|
| `core` | School, SchoolConfiguration, SchoolBranding | tenant racine (déjà livré au Gate 0) |
| `academics` | AcademicYear, AcademicPeriod, Level, PedagogicalCategory, Subject, SubjectCompatibilityRule, SchoolClass | structure académique |
| `people` | Student, StudentEnrollment, ParentProfile, ParentStudent, EmployeeProfile, TeacherProfile, TeacherSubjectQualification, CompatibilityOverride, StaffProfile, StaffFunction, StaffFunctionAssignment, GuardianProfile | personnes |

Sens des dépendances : `common` ← `core` ← `accounts` ← `academics` ← `people`. Il n'y a aucune dépendance inverse à l'import ; `SchoolProvisioningService` importe `academics` localement.

## Décisions

1. **Tous les modèles métier héritent de `TenantModel`.** Le champ `school` est stocké directement sur chaque ligne et filtré par `scope_to_current_school`.
2. **Cohérence « même école » garantie par PostgreSQL.** Ce sont des **clés étrangères composites** `(fk, school_id) → cible(id, school_id)`, ajoutées par l'opération de migration réutilisable `common.migration_operations.EnforceSameValue`, soit 34 contraintes. La même technique garantit qu'une classe appartient à l'année de l'inscription, et qu'une sous-période appartient à l'année de sa période parente. Coût : un index `UNIQUE (id, school_id)` supplémentaire par table cible.
3. **Contraintes d'exclusion** (extension `btree_gist`) :
   - deux années scolaires d'une même école ne se chevauchent jamais ;
   - deux périodes sœurs (même année, même parent) non plus.
4. **Règles qui couvrent plusieurs lignes** (période contenue dans son année et dans sa période parente, rôle de l'adhésion correspondant au profil) : elles sont vérifiées dans les **services**, avec des codes d'erreur stables.
5. **Les écritures passent par les services uniquement.** L'API de cette phase est en lecture seule. Les services d'administration reçoivent l'acteur et vérifient qu'il est **ADMIN ou SUPER_ADMIN dans l'école de la donnée** (`require_role(..., school=...)`).
6. **Archivage plutôt que suppression.** `Student.delete()` et `Student.objects...delete()` lèvent une exception. Toutes les FK vers `Student` sont en `PROTECT`, et une contrainte CHECK garantit que le statut `ARCHIVED` et `archived_at` sont toujours cohérents.
7. **Promotion** : le logiciel calculera une suggestion quand les notes existeront ; `decide_promotion` enregistre la **décision humaine** (acteur et date). Une décision non `PENDING` doit être datée (CHECK).
8. **Compatibilité pédagogique** (`apps/people/compatibility.py`) : la machine ne fait que **recommander**.
   - L'administrateur vérifie ou rejette.
   - Une incompatibilité est soit refusée, soit soumise à validation, selon la règle.
   - Une dérogation (`CompatibilityOverride`) est auditée : acteur, motif non vide (CHECK), date, périmètre (niveau ou tous niveaux) et expiration optionnelle (CHECK `expires_at > created_at`). Elle n'est jamais modifiée après création.

## Écarts par rapport à la Master Specification V4 (à valider)

| # | Spec | Implémentation | Raison / impact |
|---|---|---|---|
| 1 | `SchoolClass` (et `Room`) hors de la liste de la phase | `SchoolClass` **ajouté**, sans `main_room` | `StudentEnrollment.school_class` est obligatoire dans la spec. `Room` / `main_room` relèvent du planning |
| 2 | `Subject.category` NOT NULL | ~~nullable + setting~~ → **résolu le 2026-10-02** : FK **non nullable** (migration `academics.0003`), setting `subject_category_required` supprimé (`core.0003`) | décision du porteur du projet : intégrité en base, pas via un réglage runtime. Une matière = une catégorie ; l'enseignement transversal passe par les règles de compatibilité / dérogations |
| 3 | `Subject.default_grading_scale` (FK GradingScale) | **résolu** dans la phase cœur académique (ADR 0009) | — |
| 4 | `ParentStudent` = relation **vérifiée** (`verified_at` NOT NULL) | `verified_at` nullable + `identity_verified`, `verification_method`, `verification_reference`, `verified_by` | demande explicite de distinguer déclaré et vérifié. Les droits financiers exigent un lien vérifié (CHECK). `ParentStudentLinkRequest` et `IdentityVerification` restent à venir |
| 5 | `TeacherProfile.membership` + `employee_number` UNIQUE + `hire_date` | `TeacherProfile.employee` → `EmployeeProfile`. Le numéro enseignant est `employee.employee_number` ; `hire_date` est porté par `EmployeeProfile` | ADR 0003 : une seule source de vérité, sur le même modèle que `StaffProfile` |
| 6 | `employee_number`, `guardian_number`, `staff_number` UNIQUE globaux | UNIQUE **par école** | cohérence multi-tenant (ADR 0003) |
| 7 | Profils sans colonne `school` (rattachés via `membership`) | colonne `school` ajoutée + FK composite vers l'adhésion | filtrage par école et garantie en base (spec §3 l'autorise) |
| 8 | `Level` sans notion de cycle | ajout de `cycle` (texte libre : COLLEGE, LYCEE, TECHNICAL…) | demande explicite : collège / lycée / technique / futur |
| 9 | `TeacherSubjectQualification` sans résultat calculé | ajout de `computed_compatibility` | l'administrateur voit ce que la machine a recommandé |
| 10 | `StudentEnrollment.promotion_status` nullable | non nullable, défaut `PENDING` | élimine l'ambiguïté entre NULL et PENDING |
| 11 | Statuts sans valeurs listées dans la spec | listes définies (années, périodes, élèves, emplois…) et protégées par CHECK | valeurs à confirmer |

## Visibilité (lecture)

| Ressource | ADMIN / SUPER_ADMIN | TEACHER | PARENT | STAFF | autres |
|---|---|---|---|---|---|
| école, années, périodes, niveaux, catégories, matières, classes | oui | oui | oui | oui | oui (membre actif) |
| élèves, historique d'inscriptions | tous | **aucun pour l'instant** | enfants **vérifiés** | aucun | aucun |
| enseignants, qualifications | tous | soi-même | — | — | — |
| personnel | tous | — | — | soi-même | — |

Le périmètre « élèves de mes classes » pour les enseignants nécessite `Course` et `TeacherClassAssignment`, qui arrivent dans la prochaine phase académique. D'ici là, un enseignant ne voit aucun élève (fermeture par défaut).

## Exploitation

`CREATE EXTENSION btree_gist` exige un rôle PostgreSQL autorisé : c'est le cas du superutilisateur Docker. En production avec un rôle restreint, il faut créer l'extension une fois en tant qu'administrateur de la base, avant les migrations (voir le runbook).
