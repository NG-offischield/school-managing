# ADR 0011 — Présences élèves et QR annuel

- **Statut :** accepté — 2026-10-03
- **Périmètre :** nouvelle app `attendance` avec `AttendancePolicy`, `StudentQRCode`, `GuardianScan`, `StudentDailyAttendance` et `Convocation`.

## Hors périmètre (dépend du planning)

- Les feuilles d'appel par séance (`StudentSessionAttendance`) et la présence des enseignants (`TeacherSessionCheckIn`, `TeacherAttendanceDay`) dépendent de `TeachingSession`, elle-même rattachée à `ScheduleSlot`. Elles arriveront avec le planning.
- L'envoi effectif des alertes aux parents relève de la phase communication. Ici, le niveau est **calculé** (`parent_notification_due`).

## Décisions

1. **QR persistant pour l'année** (pas regénéré à la connexion).
   - Token : `secrets.token_urlsafe(32)`, soit 43 caractères et 256 bits.
   - Un **CHECK PostgreSQL** impose ce format exact : le token ne peut contenir ni nom, ni matricule, ni UUID. C'est la traduction en base du « token does not contain PII » de la spec.
   - Un seul QR **actif** par élève et par année (index unique partiel). Une réémission révoque la version n et crée la version n+1. Les versions révoquées restent en base, et un token révoqué ne peut jamais revenir (UNIQUE).
2. **Scan.**
   - Le token est recherché **dans l'école du scanneur uniquement** : celui d'une autre école est traité comme inconnu, sans fuite d'information.
   - Les refus sont **renvoyés et journalisés**, jamais levés : `UNKNOWN_TOKEN`, `REVOKED_TOKEN`, `EXPIRED_TOKEN` (QR d'une autre année que l'année courante) et `STUDENT_NOT_ENROLLED`.
   - Le journal `GuardianScan` est **append-only** (trigger), y compris pour les refus. Il ne stocke jamais le token présenté, seulement un préfixe de hash.
   - Peuvent scanner : GUARDIAN (profil actif), STAFF, ADMIN et SUPER_ADMIN.
   - La réponse est minimale : nom, classe et statut d'arrivée. Le champ « solvabilité » sera ajouté par la phase finance.
3. **Présence journalière.**
   - Le premier scan accepté donne PRESENT, ou LATE avec les minutes de retard calculées par rapport à `late_after_time` du jour, dans le fuseau de l'école.
   - Une arrivée tardive après la clôture transforme l'ABSENT en LATE.
   - `finalize_day` marque ABSENT les élèves inscrits sans arrivée, si la règle du jour est `NO_ARRIVAL`. Il est idempotent et refuse les jours futurs ou hors année.
   - Une correction administrative exige un motif et est auditée (avant/après).
   - Un CHECK PostgreSQL garantit la cohérence entre statut, heure d'arrivée, minutes de retard et heures d'absence.
4. **Alertes graduées.**
   - Les heures d'absence **non justifiées** de l'année sont comparées aux seuils jaune, orange et rouge de `SchoolConfiguration` (10, 20 et 30 h par défaut).
   - Les absences justifiées (EXCUSED) sont comptées à part et ne font jamais monter le niveau.
   - La convocation reste une **décision de l'admin**. Elle exige un lien parent **vérifié** et enregistre le niveau d'alerte du moment.
5. **Isolation.** 17 FK composites garantissent l'appartenance à la même école et :
   - qu'un scan accepté porte sur le QR de **cet** élève (`(qr_code, student)`) ;
   - que ce QR est celui de **cette** année (`(qr_code, academic_year)`).

   Les présences portent `academic_year` (même école). L'inscription de l'élève et l'appartenance de la date à l'année sont vérifiées par les services.
6. **Audit.** Émission, révocation et réémission de QR, règles des jours, clôture de journée, corrections et convocations écrivent un `AuditLog` dans la transaction. Les scans constituent leur propre journal immuable.
7. **API** (spec §6.7) : scan (Flutter), « mes scans », présences et scans d'un enfant (parent vérifié), et toutes les opérations d'administration sous `/admin/...` (PySide6, ADMIN uniquement). Le token n'est renvoyé que par les endpoints admin des QR, pour l'impression des cartes. Le scan est limité à 240 requêtes par minute par utilisateur.

## Écarts par rapport à la spec

| Spec | Implémentation | Raison |
|---|---|---|
| `AttendancePolicy.school` en OneToOne + UNIQUE(school, day_of_week) | ForeignKey | incohérence de la spec : un OneToOne n'autoriserait qu'un seul jour |
| — | `AttendancePolicy.absence_hours` | sans emploi du temps, le poids horaire d'une absence d'une journée doit être configuré |
| `StudentQRCode` UNIQUE(student, academic_year) | UNIQUE partiel sur les QR ACTIVE + UNIQUE(student, year, version) + `revoked_by`, `revocation_reason` | conserver l'historique des QR révoqués |
| `GuardianScan.guardian` NOT NULL | `scanned_by` (adhésion) NOT NULL + `guardian` nullable ; `student`, `qr_code` nullables pour les refus ; ajout de `academic_year` | la matrice §8 autorise STAFF et ADMIN à scanner ; les refus sont journalisés |
| `StudentDailyAttendance` | ajout de `academic_year` et `note` | isolation par année ; motif des corrections |
| `Convocation` | ajout de `alert_level` | trace du niveau ayant motivé la convocation |
