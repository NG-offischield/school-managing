# ADR 0009 — Cœur académique : notes, moyennes, bulletins

- **Statut :** accepté — 2026-10-02
- **Périmètre :** GradingScale, Course, Assessment, Grade, GradeChangeLog, ReportCard, ReportCardLine (nouvelle app `gradebook` ; `GradingScale` dans `academics`).

## Décisions

1. **App `gradebook` distincte.** `Course` référence `TeacherProfile` (`people`), qui référence déjà `academics` : placer `Course` dans `academics` créerait une dépendance circulaire.
2. **Aucune échelle codée en dur.**
   - Une note est d'abord une fraction `score / max_score` de son évaluation.
   - Les moyennes de matière s'expriment dans l'échelle du cours : celle du cours, sinon celle par défaut de la matière, sinon celle de l'école.
   - Les bulletins s'expriment dans l'échelle **par défaut** de l'école (`GradingScale.is_default`, une seule par école grâce à un index unique partiel).
   - Échelles initiales : /20 (par défaut), /100 et /60.
3. **Calcul.**
   - Période feuille : moyenne pondérée des fractions. Le poids est `coefficient_override`, sinon `assessment.weight`.
   - Période parente (trimestre) : moyenne simple des périodes enfants (séquences) qui ont une moyenne.
   - Un semestre universitaire sans enfant est une feuille : le même code sert les deux organisations.
   - Moyenne générale : `Σ(moyenne × coefficient) / Σ coefficient`.
   - Rang : classement « compétition » (1, 2, 2, 4) parmi les élèves de la classe qui ont une moyenne.
   - Absence de note : pas de moyenne (et non zéro).
   - Arrondi : `ROUND_HALF_UP`, au plus 2 décimales.
4. **Les évaluations se rattachent uniquement à une période feuille, ouverte, de la même année que le cours.**
5. **Garanties PostgreSQL.**
   - 22 FK composites (même école, même année).
   - Note ≤ barème : `Grade.max_score` est une copie de `Assessment.max_score`, maintenue par une FK composite `ON UPDATE CASCADE`, plus un `CHECK score <= max_score`. Baisser le barème d'une évaluation sous une note existante est donc refusé.
   - **Trigger** : aucune écriture (INSERT, UPDATE ou DELETE) sur `gradebook_grade` si l'évaluation ou sa période n'est pas `OPEN`.
   - **Trigger** : `GradeChangeLog` est en ajout seul ; UPDATE et DELETE sont refusés.
   - `CHECK weighted_average = ROUND(average × coefficient, 2)` sur les lignes de bulletin.
6. **Permissions.**
   - L'administrateur de l'école peut tout faire.
   - L'enseignant n'agit que sur ses cours, et seulement en période ouverte.
   - Le parent lit les notes de ses enfants **vérifiés**, et uniquement leurs bulletins **validés**.
   - Les enseignants voient désormais les élèves inscrits dans les classes où ils ont un cours actif.
7. **Correction de note** : un motif est obligatoire, la ligne est verrouillée (`SELECT … FOR UPDATE`) et un `GradeChangeLog` est écrit dans la même transaction. Le contrôle optimiste `expected_score` renvoie 409 `CONFLICT` si la note a changé entre-temps (spec §6, concurrence).
8. **Clôture des périodes.**
   - `close_period` ferme la période, ses descendantes et leurs évaluations.
   - `reopen_period` est refusé si un bulletin validé existe pour la période ou l'une de ses ancêtres.
   - Un bulletin ne se valide que si sa période est close ; une fois validé, il n'est plus jamais recalculé.
9. **Erreurs API** : une règle métier violée renvoie 400 `BUSINESS_RULE_VIOLATION` avec `details.rule` (code stable) ; un refus de la base renvoie 409 `CONFLICT`.

## Écarts / ajouts par rapport à la spec

| Spec | Implémentation | Raison |
|---|---|---|
| `GradingScale` sans notion d'échelle de référence | `is_default` (une par école) | échelle des bulletins sans setting codé en dur |
| `Assessment` sans `academic_year` | colonne ajoutée | permet de garantir en base que période et cours sont de la même année |
| `Grade` sans `max_score` | copie maintenue par la base | rend `score <= max_score` vérifiable par un CHECK |
| `ReportCard` | ajout de `validated_at`, `scale_max_score` (instantané de l'échelle) et `class_size` (pour « rang x / y ») | bulletin figé lisible même si les échelles changent |
| `coefficient_override` (sémantique non précisée) | remplace le poids de l'évaluation pour cette note | interprétation retenue |
| API 6.6 | ajout de `POST /report-cards/generate/` et `GET /report-cards/`, `GET /report-cards/{id}/` ; le PDF (`GET /report-cards/{id}/pdf/`) relève de la phase Reports | génération nécessaire pour valider |
| `ClassPrincipalAssignment` + `GET /classes/{id}/dashboard/` | **livrés** (bloc suivant, même phase) | un seul professeur principal actif par classe (index unique partiel), historique conservé ; tableau de bord en lecture seule pour l'admin et le professeur principal, calculé par la même fonction que les bulletins (`compute_class_results`) |
| `TeacherClassAssignment` | **reporté** | ferait doublon avec `Course` pour le périmètre enseignant ; à introduire si un besoin d'affectation sans matière apparaît |
| `SchoolConfiguration.low_average_threshold` | interprété dans l'échelle **par défaut** de l'école | le tableau de bord signale les élèves sous ce seuil |
