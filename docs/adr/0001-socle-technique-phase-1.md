# ADR 0001 — Socle technique de la Phase 1

- **Statut :** accepté — 2026-10-01
- **Contexte :** Phase 0 (audit) puis Phase 1 de la spec V4 (§13, §14).

## Décisions

1. **Dépôt indépendant** `school-platform/` en monorepo : `backend/`, `admin_desktop/`, `mobile/`, `docs/`. Aucun lien avec le dépôt Hospito.
2. **Django 5.2 LTS** (support sécurité jusqu'en avril 2028) plutôt que Django 6.x (non-LTS).
3. **Python 3.13 dans les conteneurs**, Python 3.14 en local (venv pour l'outillage et le futur client PySide6). L'écosystème (psycopg, channels, PySide6) est plus éprouvé sur 3.13 en production.
4. **PostgreSQL 17 + Redis 7 via Docker Compose.** Seul le service `web` publie un port ; `db` et `redis` restent sur le réseau Docker interne (spec §9 : aucun client ne se connecte directement à PostgreSQL ou Redis).
5. **Settings séparés** `base / development / production / test`, secrets lus dans l'environnement (`django-environ`). Le démarrage échoue si `DJANGO_SECRET_KEY` est absent.
6. **`ATOMIC_REQUESTS = True`** : chaque requête HTTP est une transaction. Les événements de sécurité qui doivent survivre à un rollback passent par une connexion dédiée (voir [ADR 0005](0005-journal-de-securite-hors-transaction.md)).
7. **Enveloppe de réponse unique** `{success, data, message, meta|errors}` (spec §6) appliquée par un renderer et un exception handler DRF.
8. **Clés primaires UUID** sur tous les modèles métier (`common.models.BaseModel`).
9. **Argon2** comme hacheur de mots de passe ; aucun hacheur MD5 configuré.
10. **Tests pytest-django sur PostgreSQL réel** (jamais SQLite) ; cache et channel layer en mémoire pour l'isolation.

## Conséquences

- Les phases suivantes ajoutent leurs apps dans `backend/apps/` et réutilisent `BaseModel`, `TenantModel`, `scope_to_current_school`, `IsSchoolMember`, `HasSchoolRole`.
- Le Django admin (`/django-admin/`) est un outil de développement ; le vrai client d'administration est l'application PySide6.
