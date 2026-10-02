# ADR 0002 — Stratégie de session et de jetons

- **Statut :** accepté — 2026-10-01 (validé par le porteur du projet)
- **Contexte :** la spec définit `UserDevice` et `UserSession.refresh_token_hash` mais ne fixe pas le format des jetons.

## Décision

| Jeton | Durée | Format | Stockage serveur |
|---|---|---|---|
| Accès | 15 min | `django.core.signing` (signé avec `SECRET_KEY`, sel dédié), contient uniquement l'id de session | aucun |
| Rafraîchissement | 30 jours | 384 bits aléatoires (`secrets.token_urlsafe(48)`) | **hash SHA-256 uniquement** dans `UserSession` |

- À chaque requête, l'access token est vérifié **et** la session est relue en base : une déconnexion, une révocation ou un compte désactivé prennent effet **immédiatement**, contrairement à un JWT autonome valable jusqu'à expiration.
- Le refresh token est **renouvelé à chaque utilisation** (rotation) ; l'ancien devient invalide. `select_for_update` empêche deux rafraîchissements concurrents avec le même jeton.
- L'identifiant d'appareil envoyé par le client est stocké sous forme de **HMAC** (clé = `SECRET_KEY`).
- Changer son mot de passe révoque toutes les **autres** sessions.
- Les échecs de connexion renvoient une réponse unique (code `INVALID_CREDENTIALS`, voir ADR 0007), sans distinguer compte inexistant et mauvais mot de passe. Ils sont journalisés dans `SecurityEvent`, sans le mot de passe.
- Limitation de débit : 10 tentatives de connexion par minute et par IP, 30 rafraîchissements par minute (compteurs dans Redis).

## Réutilisation d'un refresh token — décision du 2026-10-02

**Famille de jetons = session.** Chaque rafraîchissement remplace le jeton d'une même `UserSession`. L'identifiant de session sert donc d'identifiant de famille, et aucune colonne supplémentaire n'est nécessaire sur `UserSession`.

**Historique.** Le hash du jeton remplacé est conservé dans `RotatedRefreshToken` (session, token_hash unique).

Quand un jeton déjà remplacé est présenté, quelqu'un en détient forcément une copie. Le serveur :
1. refuse la requête (401 `INVALID_REFRESH_TOKEN`, sans préciser la raison) ;
2. journalise `REFRESH_TOKEN_REUSE_DETECTED` en sévérité `CRITICAL`, avec `session_id` et `session_was_active` ;
3. considère la famille comme compromise ;
4. **révoque cette session uniquement** : le jeton le plus récent et l'access token meurent aussi ;
5. n'émet aucun jeton.

Les autres sessions de l'utilisateur ne sont **pas** touchées. Aucune politique globale n'est déclenchée automatiquement.

**Contrat transactionnel.** La révocation doit être commitée alors que la requête échoue. `RefreshView` est donc exclue d'`ATOMIC_REQUESTS` (`non_atomic_requests`), et c'est le bloc atomique du service qui commite la révocation avant que l'erreur ne soit levée.

**Compromis assumé.** Deux rafraîchissements légitimes et quasi simultanés avec le même jeton (par exemple une application qui renvoie sa requête après un timeout réseau) seront vus comme une réutilisation, et l'utilisateur devra se reconnecter. On privilégie la sécurité ; on pourra ajouter une fenêtre de grâce de quelques secondes plus tard si le besoin apparaît sur le terrain.

## Déconnexion globale — décision du 2026-10-02

`POST /api/v1/auth/sessions/revoke-all/` (authentifié) révoque **toutes** les sessions actives de l'appelant, y compris la session courante, renvoie `{"revoked_count": n}` et journalise `ALL_SESSIONS_REVOKED` avec `initiated_by: SELF`.

**Révocation administrative (prévue).** Le service `revoke_all_sessions(user, actor=...)` journalise déjà `initiated_by: ADMIN`, `actor_id` et une sévérité `WARNING`. Le futur endpoint d'administration devra exiger le rôle `ADMIN` ou `SUPER_ADMIN` **dans l'établissement de l'utilisateur ciblé**, et s'appuyer sur `scope_to_current_school`.

## Écarts assumés par rapport à la spec

- `UserSession.refresh_token_hash` est **unique et indexé** (la spec indique « Index : NO »), car chaque rafraîchissement recherche la session par ce hash.
- **Ajout** de la table `RotatedRefreshToken`, absente de la spec §4.2, pour détecter la réutilisation.
- **Ajout** de l'endpoint `sessions/revoke-all/`, absent de la spec §6.2, décidé le 2026-10-02.

## Pistes ultérieures

- Purge périodique des sessions expirées, et de leur `RotatedRefreshToken` par cascade, selon la politique de rétention (spec §10).
- MFA pour les administrateurs (`MFADevice`, `VerificationChallenge`) : modèles prévus par la spec, à livrer dans une phase dédiée.
- Rotation de `SECRET_KEY` : invalide tous les access tokens, ce qui est acceptable avec une durée de vie de 15 min.
