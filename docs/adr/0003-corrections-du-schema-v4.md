# ADR 0003 — Corrections du schéma de la spec V4

- **Statut :** accepté — 2026-10-01 (validé par le porteur du projet)
- **Contexte :** incohérences relevées lors de l'audit Phase 0.

## 1. `employee_number` uniquement sur `EmployeeProfile`

La spec déclare `employee_number` (unique) à la fois sur `TeacherProfile` et sur `EmployeeProfile`, alors que `EmployeeProfile` est le « profil employé commun aux enseignants et au personnel ». Deux sources de vérité finiraient par diverger.

**Décision :** le matricule n'existe que sur `EmployeeProfile`. `TeacherProfile` sera relié à son `EmployeeProfile` (phase Profils).

## 2. `Student.student_number` unique **par établissement**

La spec marque `student_number` comme unique globalement **et** déclare la contrainte `UNIQUE(school, student_number)`. L'unicité globale empêcherait deux établissements d'utiliser la même numérotation, ce qui contredit l'objectif multi-tenant.

**Décision :** seule la contrainte `UNIQUE(school, student_number)` est retenue (idem pour `registration_number`). À appliquer dans la phase Scolarité.

## 3. Stratégie de jetons

Voir [ADR 0002](0002-strategie-de-session-et-jetons.md).

## Ajouts mineurs (non contradictoires avec la spec)

- Unicité **insensible à la casse** de `User.username` et `User.email` (empêche `Admin` / `admin`).
- Un utilisateur a **au plus une** adhésion `is_primary_school=True` (sinon la résolution du tenant serait ambiguë).
- Contraintes CHECK sur les statuts (`School.status`, `SchoolMembership.status`) et sur l'ordre des seuils d'alerte (jaune ≤ orange ≤ rouge).
- `User.is_staff` ajouté, requis uniquement par le Django admin de développement.
