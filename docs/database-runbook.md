# Runbook PostgreSQL

Ce runbook décrit l'administration **technique** de la base de ce dépôt : consulter, sauvegarder, restaurer.

Les valeurs ci-dessous sont celles réellement lues dans `docker-compose.yml`, `.env` et `backend/config/settings/base.py`. **Aucun mot de passe n'y figure** : il vit uniquement dans `.env`, non versionné, et les conteneurs le lisent dans leur environnement (`$POSTGRES_PASSWORD`).

## 1. Architecture

```
PC Windows
  │  http://<IPv4 ou 127.0.0.1>:8000   (seul port publié)
  ▼
Docker Compose « school-platform »
  ├── web      Django (runserver/daphne)  ── réseau Docker interne ──┐
  ├── db       PostgreSQL 17 (données de travail, volume pg_data)  ◄──┤
  ├── db_test  PostgreSQL 17 (tests, données en RAM / tmpfs)       ◄──┤
  └── redis    cache, limites, canaux WebSocket                    ◄──┘
```

- **Seul `web` publie un port** (8000). `db` et `db_test` ne sont **pas** exposés au PC ni au réseau local : les clients (poste d'administration, mobiles) ne parlent jamais à PostgreSQL directement (spec §9).
- **Deux connexions Django vers la même base** : `default` pour le métier, avec chaque requête HTTP dans une transaction, et `security_log` pour le journal de sécurité en autocommit (ADR 0005).

| Paramètre | Valeur réelle | Source |
|---|---|---|
| Service PostgreSQL (données) | `db` (conteneur `school-platform-db-1`) | `docker-compose.yml` |
| Image | `postgres:17-alpine` (PostgreSQL 17.11 au 5 oct. 2026) | `docker-compose.yml`, `SELECT version()` |
| Base | `school` | `.env` → `POSTGRES_DB` |
| Utilisateur | `school` (propriétaire de la base, superutilisateur du conteneur) | `.env` → `POSTGRES_USER` |
| Mot de passe | **non documenté** : `.env` → `POSTGRES_PASSWORD` | `.env` |
| Hôte vu par Django | `db` | `.env` → `POSTGRES_HOST` |
| Port | `5432`, **interne au réseau Docker** | `.env` → `POSTGRES_PORT` |
| Volume des données | `pg_data` (`/var/lib/postgresql/data`) | `docker-compose.yml` |
| Base de test | service `db_test`, mêmes identifiants, données en RAM (`tmpfs`) | `docker-compose.yml`, `config/settings/test.py` |

## 2. Se connecter

### Depuis le conteneur : méthode recommandée

Le client `psql` est déjà dans l'image `db`. Il n'y a rien à installer sur le PC, et le mot de passe n'est jamais tapé : l'accès local au conteneur est de confiance.

```powershell
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Pour une seule requête, sans session interactive :

```powershell
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM people_student"'
```

Pour la base de **test** (`db_test`), même commande avec `db_test` à la place de `db`.

### Depuis le PC

Le port 5432 n'est pas publié, et PostgreSQL n'est pas installé sur le PC de développement. Passer par `docker compose exec`, comme ci-dessus.

### pgAdmin (facultatif, développement uniquement)

pgAdmin a besoin d'un port joignable. `docker-compose.yml` prévoit déjà, en commentaire dans le service `db`, une publication **limitée à la machine** :

```yaml
# ports: ["127.0.0.1:5432:5432"]
```

Pour l'utiliser, il faut décommenter cette ligne **localement**, sans la committer, puis lancer `docker compose up -d db`. pgAdmin se connecte alors à `127.0.0.1:5432`, base `school`, utilisateur `school`, mot de passe de `.env`.
- Ne jamais publier en `0.0.0.0` ni ouvrir 5432 dans le pare-feu : la base doit rester invisible du réseau local.
- Remettre le commentaire après usage.

## 3. Opérations métier et administration technique

| | Outils | Pour |
|---|---|---|
| **A. Opérations métier** | poste d'administration PySide6, applications mobiles, API, services Django (`manage.py`) | **toute** création ou modification : élèves, inscriptions, parents et rattachements, factures, paiements, remboursements, wallets, paie, notes, présences… |
| **B. Administration technique** | `psql`, pgAdmin, `pg_dump` / `pg_restore` | **lecture**, diagnostic, sauvegarde, restauration |

**Ne jamais modifier les données métier en SQL.** Ce serait contourner ce que seuls les services garantissent :

- **Permissions et isolation :** droits par rôle et par école (`require_role`, `scope_to_current_school`), droits du lien parent (`can_pay`, `can_view_financial_data`).
- **Audit :** chaque opération métier écrit un `AuditLog` (créations d'élèves, factures, paiements, wallets…). Un `UPDATE` SQL ne laisse aucune trace.
- **Argent :** un mouvement d'argent passe **uniquement** par `finance.services._post`. Ce service verrouille la ligne, écrit une ligne de grand livre avant/après et met à jour le solde. Modifier `finance_wallet.balance` à la main désynchronise le solde de son grand livre. Les grands livres, allocations et remboursements sont de plus protégés par les triggers `finance_<table>_append_only` (UPDATE et DELETE interdits), et un paiement terminé par `finance_payment_guard`.
- **Règles métier :** numérotation des factures, recalcul `balance_due`, idempotence des paiements, une inscription par année, capacité des classes, rattachement parent par le parcours vérifié (ADR 0026).
- **Comptes :** mots de passe hachés en Argon2, sessions et jetons révocables. Ne jamais toucher `accounts_user.password` ni les sessions en SQL.

Pour **recharger un wallet**, utiliser `seed_demo --refill-wallets` (démonstration) ou `POST /admin/finance/wallets/{id}/fund/`. Pour **corriger** un paiement, faire un remboursement par le poste d'administration. Jamais d'`UPDATE`.

## 4. Lire la base : requêtes sûres

Toutes les requêtes ci-dessous sont des `SELECT`. Elles ont été vérifiées sur la base de test avec le jeu de démonstration (section 6). Pour qu'une écriture accidentelle soit refusée (« read-only transaction »), commencer la session par :

```sql
SET default_transaction_read_only = on;
```

### Bases, tables, structure

```sql
\l                      -- bases : postgres, school, template0, template1
\dt                     -- tables du schéma public
\dt finance_*           -- tables Finance
\d+ people_student      -- colonnes, index, contraintes, triggers d'une table
\d finance_wallettransaction
```

Tables utiles :
- **Établissement et comptes :** `core_school`, `accounts_user`, `accounts_schoolmembership`.
- **Scolarité :** `people_student`, `people_studentenrollment`, `academics_schoolclass`, `academics_academicyear`.
- **Parents :** `people_parentprofile`, `people_parentstudent` (lien et droits), `people_parentstudentlinkrequest`, `people_registrationrequest`.
- **Finance :** `finance_feetype`, `finance_invoice`, `finance_invoiceline`, `finance_payment`, `finance_paymentallocation`, `finance_paymentrefund`, `finance_wallet`, `finance_wallettransaction`, `finance_simulationtreasury`, `finance_treasurytransaction`.
- **Audit :** `audit_auditlog`.

### Rechercher un élève

```sql
SELECT s.student_number, s.first_name, s.last_name, s.date_of_birth, s.sex, s.status, sc.code AS ecole
FROM people_student s JOIN core_school sc ON sc.id = s.school_id
WHERE s.student_number = 'DEMO-2026-001' OR s.last_name ILIKE '%nkoulou%';
```

Sa classe et son année :

```sql
SELECT s.student_number, c.name AS classe, y.name AS annee, e.status, e.enrollment_date
FROM people_studentenrollment e
JOIN people_student s ON s.id = e.student_id
JOIN academics_schoolclass c ON c.id = e.school_class_id
JOIN academics_academicyear y ON y.id = e.academic_year_id
WHERE s.student_number = 'DEMO-2026-004';
```

### Rechercher un parent

```sql
SELECT u.email, u.first_name, u.last_name, m.status AS adhesion, sc.code AS ecole, p.id AS parent_profile
FROM accounts_user u
JOIN accounts_schoolmembership m ON m.user_id = u.id
JOIN core_school sc ON sc.id = m.school_id
LEFT JOIN people_parentprofile p ON p.membership_id = m.id
WHERE u.email ILIKE 'parent.%@demo-ecole.test';
```

### Relations parent ↔ enfant (et droits)

```sql
SELECT u.email AS parent, s.student_number, ps.relationship_type, ps.identity_verified, ps.active,
       ps.can_view_financial_data, ps.can_pay
FROM people_parentstudent ps
JOIN people_parentprofile p ON p.id = ps.parent_id
JOIN accounts_schoolmembership m ON m.id = p.membership_id
JOIN accounts_user u ON u.id = m.user_id
JOIN people_student s ON s.id = ps.student_id
ORDER BY u.email, s.student_number;
```

Un lien n'ouvre de droits que s'il est `identity_verified` **et** `active`.

### Consulter une facture

```sql
SELECT i.invoice_number, s.student_number, i.status, i.total_amount, i.amount_paid, i.balance_due, i.currency, i.due_date
FROM finance_invoice i JOIN people_student s ON s.id = i.student_id
WHERE i.invoice_number = 'F26-000005';

SELECT l.description, l.quantity, l.unit_price, l.total
FROM finance_invoiceline l JOIN finance_invoice i ON i.id = l.invoice_id
WHERE i.invoice_number = 'F26-000005';
```

### Consulter un wallet

```sql
SELECT w.provider_code, w.wallet_identifier, w.balance, w.currency, w.status, u.email AS proprietaire
FROM finance_wallet w
JOIN accounts_schoolmembership m ON m.id = w.owner_id
JOIN accounts_user u ON u.id = m.user_id
ORDER BY u.email;
```

### Consulter un paiement et son affectation

```sql
SELECT p.payment_reference, s.student_number, p.payment_method, p.status, p.amount, p.refunded_amount,
       p.idempotency_key, p.failure_reason, p.initiated_at, p.completed_at
FROM finance_payment p JOIN people_student s ON s.id = p.student_id
ORDER BY p.initiated_at DESC LIMIT 20;

SELECT p.payment_reference, i.invoice_number, a.amount, a.refund_id IS NOT NULL AS remboursement
FROM finance_paymentallocation a
JOIN finance_payment p ON p.id = a.payment_id
JOIN finance_invoice i ON i.id = a.invoice_id
ORDER BY a.allocated_at DESC LIMIT 20;
```

### Écritures du grand livre

Grand livre d'un wallet :

```sql
SELECT t.created_at, t.transaction_type, t.direction, t.amount, t.balance_before, t.balance_after, t.reference
FROM finance_wallettransaction t JOIN finance_wallet w ON w.id = t.wallet_id
WHERE w.wallet_identifier = '670000404'
ORDER BY t.created_at;
```

Trésorerie de l'école (solde et écritures) :

```sql
SELECT sc.code, tr.balance FROM finance_simulationtreasury tr JOIN core_school sc ON sc.id = tr.school_id;

SELECT t.created_at, t.transaction_type, t.direction, t.amount, t.balance_before, t.balance_after, t.reference
FROM finance_treasurytransaction t JOIN core_school sc ON sc.id = t.school_id
WHERE sc.code = 'DEMO' ORDER BY t.created_at;
```

Contrôle de cohérence : le solde d'un compte est égal au `balance_after` de sa dernière écriture. Le `reference` d'une écriture `PAYMENT` est le `payment_reference` du paiement.

## 5. Sauvegarde et restauration

### Dump

Le format personnalisé (`-Fc`) est compressé et restaurable table par table. Le fichier est écrit **dans le conteneur**, puis copié sur le PC : il ne faut pas rediriger avec `>` sous PowerShell 5.1, qui réencode la sortie en UTF-16 et rend le dump illisible.

```powershell
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/school.dump'
docker compose cp db:/tmp/school.dump ".\school-$(Get-Date -Format yyyyMMdd-HHmm).dump"
docker compose exec -T db rm /tmp/school.dump
```

Le dump contient des données personnelles (élèves, parents) : il faut le ranger hors du dépôt et ne jamais le committer.

### Vérifier un dump

```powershell
docker compose cp ".\school-AAAAMMJJ-HHMM.dump" db:/tmp/check.dump
docker compose exec -T db sh -c 'pg_restore --list /tmp/check.dump | grep -c "TABLE DATA"'
```

Le résultat est un nombre de tables non nul : 100 au 5 octobre 2026. Une erreur signale un fichier corrompu ou tronqué.

### Restaurer (sans écraser la base en service)

On restaure dans une **nouvelle** base, puis on vérifie. Ces commandes ne touchent pas à la base `school` :

```powershell
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" school_restore'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d school_restore --no-owner /tmp/check.dump'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d school_restore -c "SELECT count(*) FROM people_student"'
```

Pour **utiliser** la base restaurée :
1. arrêter `web` ;
2. mettre `POSTGRES_DB=school_restore` dans `.env` ;
3. `docker compose up -d web`.

Pour revenir en arrière, remettre `POSTGRES_DB=school`. L'ancienne base reste intacte.

Procédure vérifiée le 5 octobre 2026 sur `db_test` :
- dump de 806 Ko, 100 tables de données et 40 triggers listés ;
- restauration dans une base neuve, avec des comptes identiques (élèves, paiements, écritures, total des soldes).

## 6. Jeu de démonstration

Référence complète : [demo-data.md](demo-data.md).

- **`seed_demo`** (`backend/apps/demo/management/commands/seed_demo.py`) crée ou complète l'établissement `DEMO` en passant **uniquement par les services**. Il est idempotent : une seconde exécution ne duplique rien, et les paiements du seed sont rejoués par leurs clés d'idempotence fixes.
- **`backend/apps/demo/dataset.py`** est le seul endroit où le jeu est défini :
  - `STUDENTS` : les élèves, avec les champs du modèle, plus leur classe ;
  - `PARENTS` : les parents et leurs enfants (`children`), rattachés par le parcours vérifié ;
  - `INVOICES` : une facture par élève et motif, avec une échéance relative ;
  - `CASH_PAYMENTS` : les paiements au guichet du seed ;
  - `WALLETS` : les wallets simulés et leurs soldes cibles ;
  - `TREASURY_FUNDING` : les fonds de départ de l'école.
- **Mot de passe des comptes de démonstration :** fourni par la variable `DEMO_PASSWORD` au premier chargement. Il n'est jamais écrit ni affiché.

```powershell
docker compose exec -e DEMO_PASSWORD web python manage.py seed_demo
```

(Après avoir défini `$env:DEMO_PASSWORD` dans la session ; voir demo-data.md.)

- **`--refill-wallets`** remet chaque wallet de démonstration à son solde cible, par des écritures `FUNDING` tracées. Les paiements et factures restent tels quels.

```powershell
docker compose exec web python manage.py seed_demo --refill-wallets
```

Pour vérifier en SQL après un chargement, utiliser les requêtes de la section 4 : elles visent les données `DEMO`.
