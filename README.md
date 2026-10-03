# School Platform

Plateforme de gestion scolaire — V1 : un établissement, architecture prête pour le multi-établissement, fonctionnement en réseau local (LAN) sans hébergement payant.

**Source de vérité :** [docs/specification/School_Master_Specification_V4.docx](docs/specification/School_Master_Specification_V4.docx).
Les écarts validés par rapport à la spec sont tracés dans [docs/adr/](docs/adr/).

## Architecture

| Composant | Technologie | Dossier |
|---|---|---|
| Backend (API REST + WebSocket) | Django 5.2 LTS, DRF, Channels | `backend/` |
| Base de données | PostgreSQL 17 | conteneur `db` |
| Temps réel / cache / limitation de débit | Redis 7 | conteneur `redis` |
| Client administrateur | Python + PySide6 (bureau) | `admin_desktop/` *(phase ultérieure)* |
| Enseignant / Parent / Gardien / Personnel | Flutter | `mobile/` *(phase ultérieure)* |
| Site public | Django Templates | `backend/` *(phase ultérieure)* |

Le backend est la seule autorité pour les permissions, les calculs, la finance et les règles métier. Les clients ne parlent jamais directement à PostgreSQL ou Redis.

## Démarrage rapide

Prérequis : Docker Desktop démarré.

```bash
cp .env.example .env        # puis remplacer les valeurs "change-me"
docker compose up --build   # API sur http://localhost:8000
```

Créer l'établissement et son premier super-administrateur (il n'existe pas d'inscription admin publique) :

```bash
docker compose exec web python manage.py bootstrap_school --code LYC-DLA --name "Lycée de Douala" --city Douala --address "Akwa" --admin-username admin --admin-email admin@example.cm --admin-first-name Jean --admin-last-name Dupont
```

Lancer les tests (sur PostgreSQL réel) :

```bash
docker compose run --rm web pytest
```

Voir [docs/runbook.md](docs/runbook.md) pour l'exploitation courante.

## État d'avancement

- [x] Phase 0 — audit de l'environnement
- [x] Phase 1 — squelette Django, Docker, utilisateur personnalisé, noyau multi-tenant, authentification, tests
- [x] Gate 0 — validation de la fondation (isolation tenant, auth, journal de sécurité, bootstrap)
- [x] Mini-gate — FK SET NULL sur SecurityEvent, détection de réutilisation des refresh tokens, `sessions/revoke-all/`, `SchoolProvisioningService`, format d'erreur `{success, error{code, message}}` + i18n fr/en
- [x] Socle métier School + Academic + People (années, périodes, niveaux, catégories, matières, compatibilité, classes, élèves, inscriptions, parents, enseignants, personnel, gardiens) — API en lecture seule, ADR 0008
- [x] Cœur académique — échelles /20 /100 /60, cours, évaluations, notes (historique immuable, période ouverte), moyennes pondérées, bulletins, évolution, clôture des périodes (ADR 0009)
- [x] Catalogue pédagogique administrable (catégories, matières) + journal d'audit (ADR 0010)
- [x] Présences + QR annuel : scans, présence journalière, retards, clôture, corrections, alertes graduées, convocations (ADR 0011)
- [x] Planning : salles, emploi du temps récurrent, séances datées, conflits garantis par PostgreSQL, disponibilités, remplacements, permutations, historique / boîte d'envoi des notifications (ADR 0012)
- [x] Finance : motifs et échéanciers, factures, paiements simulés déterministes (succès, refus, fonds insuffisants, délai, erreur fournisseur), idempotence, wallets et trésorerie en grand livre append-only, remboursements par transaction inverse, solvabilité au scan QR, tableau de bord (ADR 0013)
- [x] Paie : validation administrative des séances (check-in), taux datés, périodes, calcul déterministe programmé / acquis, paie préparée → validée → payée via Finance, double paiement impossible, corrections tracées, solvabilité QR limitée aux rôles autorisés (ADR 0014)
- [x] Communication : notifications projetées depuis les domaines (file push prête pour FCM), messagerie privée, forum / annonces, réclamations, pièces jointes privées, WebSocket temps réel (ADR 0015)
- [ ] Phases suivantes — présence par séance (fiches d'appel), envoi FCM, PDF, site public, clients PySide6 et Flutter
