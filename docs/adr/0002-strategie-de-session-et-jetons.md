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
- Les échecs de connexion renvoient un message unique (« Invalid credentials. ») sans distinguer compte inexistant et mauvais mot de passe ; ils sont journalisés dans `SecurityEvent` (sans le mot de passe).
- Limitation de débit : 10 tentatives de connexion par minute et par IP, 30 rafraîchissements par minute (compteurs dans Redis).

## Écart assumé par rapport à la spec

`UserSession.refresh_token_hash` est **unique et indexé** (la spec indique « Index : NO ») : chaque rafraîchissement recherche la session par ce hash.

## Pistes ultérieures

- Détection de réutilisation d'un refresh token déjà tourné (révocation de toute la session).
- MFA pour les administrateurs (`MFADevice`, `VerificationChallenge`) : modèles prévus par la spec, à livrer dans une phase dédiée.
- Rotation de `SECRET_KEY` : invalide tous les access tokens (acceptable : 15 min de durée de vie).
