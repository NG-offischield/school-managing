# ADR 0005 — Journal de sécurité écrit hors de la transaction métier

- **Statut :** accepté — 2026-10-02, révisé le même jour (FK rétablies sur décision du porteur du projet)
- **Contexte :** avec `ATOMIC_REQUESTS = True`, toute écriture d'une requête est annulée si la requête lève une exception. Un événement comme « tentative de connexion échouée » ou « refresh token rejeté » serait alors effacé, alors que c'est précisément l'information à conserver.

## Décision

1. **Connexion dédiée `security_log`** (`DATABASES["security_log"]`). C'est la même base PostgreSQL, mais une **autre connexion**, en autocommit, sans `ATOMIC_REQUESTS`. Le routeur `common.db_routers.SecurityLogRouter` y envoie toutes les lectures et écritures de `SecurityEvent`. Aucune migration ne passe par cet alias. C'est l'équivalent d'une « transaction autonome ».
2. **Deux moments d'écriture** dans `record_security_event` :
   - *immédiat* (par défaut), pour les **refus et attaques** : `LOGIN_FAILED`, `REFRESH_REJECTED`, `REFRESH_TOKEN_REUSE_DETECTED`, `BOOTSTRAP_REJECTED`. L'événement survit à tout rollback ;
   - *après commit* (`after_commit=True`), pour les **succès**. L'événement n'est écrit que si l'opération a réellement été validée.
3. **Intégrité référentielle** :
   - `user` et `school` sont de **vraies clés étrangères PostgreSQL**, nullables, en `ON DELETE SET NULL` **au niveau de la base**. Django 5.2 ne sait pas l'exprimer : la migration `accounts.0003` réécrit les contraintes via `RunSQL`, et un test vérifie `confdeltype = 'n'` pour détecter une régression. Un événement survit ainsi à la suppression de son utilisateur ou de son école, même par SQL brut. Lorsqu'une référence existe, elle pointe toujours vers une ligne réelle.
   - **Cas limite.** Un événement immédiat peut référencer une ligne non encore commise par la transaction métier, invisible pour la connexion `security_log`. La FK est alors rejetée. Plutôt que de perdre l'événement, `record_security_event` le réécrit sans le lien et conserve l'identifiant dans `metadata["unresolved_refs"]`. Ce cas ne se produit pas dans les flux actuels (les refus portent sur des lignes déjà commises), mais il est couvert et testé.
   - **`lock_timeout = 2 s`** sur la connexion `security_log`. La vérification de FK pose un verrou `KEY SHARE` sur la ligne référencée. Si la transaction métier de la même requête détenait cette ligne `FOR UPDATE`, l'attente serait un auto-interblocage, puisque les deux connexions servent la même requête. Au bout de 2 s, on bascule sur le cas limite ci-dessus.

## Conséquences

- Deux connexions PostgreSQL par processus web : négligeable pour un établissement en réseau local.
- **Tests transactionnels.** Toute la suite tourne avec `django_db(transaction=True)` : les données sont réellement commitées, comme en production, sinon la connexion `security_log` ne les verrait pas et les FK ne pourraient pas être testées honnêtement. La base est vidée (TRUNCATE) après chaque test, et les rôles système sont ré-injectés avant chaque test par la même fonction que la migration (`sync_system_roles`). Coût : suite environ 2 fois plus lente (≈ 45 s pour 106 tests).
- **Vérifications par mutation** : routeur désactivé → 4 tests sur 6 échouent ; historique de rotation désactivé → les 2 tests de réutilisation échouent ; `set_rollback()` retiré → le test 500 échoue.
