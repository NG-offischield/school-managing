# school_core

Infrastructure partagée des applications mobiles School Managing. Aucune règle métier : l'API Django
reste la source de vérité.

- `ApiClient` : enveloppe `{success, data, meta}`, erreurs typées (401/403/404/409/400/429/5xx, réseau),
  un seul renouvellement du jeton sur 401 (partagé par les requêtes simultanées).
- `AuthService` : connexion, refresh, déconnexion, restauration au démarrage, activation de compte
  (ADR 0024), contrôle du rôle de l'application. Seul le refresh token est conservé (`SecureTokenStore`,
  Android Keystore) ; le mot de passe n'est jamais stocké.
- `RealtimeClient` : WebSocket existant `ws/v1/realtime/` (en-tête Bearer, resynchronisation, ping,
  reconnexion, fermeture 4401 → un refresh puis session expirée).
- `buildAppTheme()` / `Tokens` : mêmes couleurs que le poste d'administration ; composants communs
  (`SoftwareBrand`, `AsyncBody`, `MessageBanner`, `StatusChip`).
