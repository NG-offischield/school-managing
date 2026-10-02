# ADR 0006 — Bootstrap de l'installation et provisionnement des établissements

- **Statut :** accepté — 2026-10-02 (décision du porteur du projet)

## Décision

### `SchoolProvisioningService` (apps/core/services.py)

C'est le **seul chemin de code** qui crée un établissement complet et prêt à l'emploi, en une transaction atomique :
- `School` ;
- `SchoolConfiguration` ;
- `SchoolBranding` ;
- le premier compte : `User`, adhésion `ACTIVE`, rôle `SUPER_ADMIN`. Le flag « école principale » n'est posé que si l'utilisateur n'en a pas déjà une.

Le mot de passe est validé (`AUTH_PASSWORD_VALIDATORS`) **avant** toute écriture, puis haché en Argon2.

Le service ne vérifie **aucune autorisation**. C'est à l'appelant de le faire : accès shell aujourd'hui, permissions du *control plane* demain (`SchoolInstallation`, spec §4, hors V1). Le service est lui-même prêt pour le multi-établissement : il sait créer un deuxième établissement, ce que les tests vérifient.

**Il n'existe aucune API HTTP qui l'expose.** Créer un établissement est une opération de plateforme, pas une action d'établissement.

### `manage.py bootstrap_school`

La commande initialise uniquement une installation **vide**. C'est la **seule** règle « premier établissement uniquement », et elle est propre au bootstrap.
- Elle s'exécute depuis un shell sur le serveur. Aucune route HTTP équivalente n'existe ; un test parcourt toutes les URL pour le vérifier.
- Elle délègue la création à `SchoolProvisioningService`.
- Mot de passe : saisie masquée et confirmée, ou variable `BOOTSTRAP_ADMIN_PASSWORD` pour l'automatisation. Il n'est jamais accepté en argument, jamais affiché, jamais journalisé. Sans terminal et sans la variable, la commande échoue au lieu de rester bloquée.
- Journalisation : `BOOTSTRAP_COMPLETED` après commit ; `BOOTSTRAP_REJECTED` immédiatement, avec `ALREADY_BOOTSTRAPPED` ou `ADMIN_ALREADY_EXISTS`. Ce dernier survit au rollback.
- **Second lancement** : la commande refuse, ne modifie rien et sort en erreur.

**Variable d'environnement** : `BOOTSTRAP_ADMIN_PASSWORD` peut être visible via `docker inspect` ou `/proc`. Il faut la retirer après usage ; la saisie interactive reste la méthode recommandée.
