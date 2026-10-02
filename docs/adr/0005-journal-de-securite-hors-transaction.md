# ADR 0005 — Journal de sécurité écrit hors de la transaction métier

- **Statut :** accepté — 2026-10-02
- **Contexte :** avec `ATOMIC_REQUESTS = True`, toute écriture d'une requête est annulée si la requête lève une exception. Un événement « tentative de connexion échouée » ou « refresh token rejeté » serait alors effacé, alors que c'est précisément l'information à conserver. La première implémentation contournait le problème en faisant *retourner* une erreur par la vue au lieu de la *lever*. C'est fragile : il suffit qu'une évolution lève une exception pour perdre silencieusement le journal.

## Décision

1. **Connexion dédiée `security_log`** (`DATABASES["security_log"]`). C'est la **même base** PostgreSQL, mais une **autre connexion**, en autocommit, avec `ATOMIC_REQUESTS=False`. Le routeur `common.db_routers.SecurityLogRouter` y envoie toutes les lectures et écritures de `SecurityEvent`. Cette connexion ne fait jamais l'objet de migrations : le schéma est créé une seule fois, via `default`. C'est l'équivalent d'une « transaction autonome ».
2. **Deux moments d'écriture**, au choix de l'appelant de `record_security_event` :
   - *immédiat* (par défaut), pour les **refus et attaques** : `LOGIN_FAILED`, `REFRESH_REJECTED`, `BOOTSTRAP_REJECTED`. L'événement est commis tout de suite et survit à tout rollback ;
   - *après commit* (`after_commit=True`), pour les **succès** : `LOGIN_SUCCEEDED`, `TOKEN_REFRESHED`, `LOGOUT`, `SESSION_REVOKED`, `ALL_SESSIONS_REVOKED`, `PASSWORD_CHANGED`, `BOOTSTRAP_COMPLETED`. L'événement n'est écrit que si l'opération a réellement été validée, pour que le journal n'affirme jamais un succès qui a été annulé.
3. **`SecurityEvent.user` et `SecurityEvent.school` avec `db_constraint=False`.** L'événement est commis par une autre connexion, parfois alors que la ligne référencée n'est pas encore commise, voire sera annulée (exemple : bootstrap refusé). Une clé étrangère en base rejetterait justement l'événement à conserver. Django gère toujours la relation au niveau de l'ORM (jointures, `SET_NULL` à la suppression).

## Écart par rapport à la spec

La spec §4.2 décrit `SecurityEvent.school` et `.user` comme des FK `SET_NULL`. La relation et le comportement `SET_NULL` sont conservés ; seule la **contrainte d'intégrité en base** est retirée. **Impact :** un événement peut pointer vers un identifiant qui n'existe plus ou n'a jamais été commis. C'est acceptable, et même souhaitable, pour un journal d'audit en ajout seul. Cet écart demande une validation.

## Conséquences

- Deux connexions PostgreSQL par processus web au lieu d'une : négligeable pour un établissement en réseau local.
- Tests : l'alias est un *miroir* de la base de test. Django ne l'enveloppe pas dans le rollback par test, donc ses lignes sont réellement commises. La fixture `_isolate_security_log` les purge avant et après chaque test. Les tests d'événements « succès » utilisent la fixture `committed` pour exécuter les callbacks `on_commit`.
- Vérification par mutation : avec le routeur désactivé, 4 des 6 tests de `tests/test_security_events.py` échouent. Les tests détectent donc bien une régression.
