# ADR 0006 — Bootstrap de l'installation et ajout futur d'établissements

- **Statut :** proposé — 2026-10-02 (à valider)

## Décision

`manage.py bootstrap_school` initialise uniquement une installation **vide** :

- Il s'exécute seulement depuis un shell sur le serveur (environnement contrôlé). Il n'existe **aucune route HTTP équivalente**, et un test le vérifie en parcourant toutes les URL.
- Il crée l'établissement, sa `SchoolConfiguration` et sa `SchoolBranding` de façon atomique, puis le premier compte : adhésion `ACTIVE`, école principale, rôle `SUPER_ADMIN`.
- Mot de passe : saisie masquée et confirmée, ou variable `BOOTSTRAP_ADMIN_PASSWORD` pour l'automatisation. Il n'est **jamais** accepté en argument, validé par `AUTH_PASSWORD_VALIDATORS`, haché en Argon2, jamais affiché ni journalisé. Sans terminal et sans la variable, la commande échoue au lieu de rester bloquée.
- Journalisation : `BOOTSTRAP_COMPLETED` après commit ; `BOOTSTRAP_REJECTED` immédiatement, qui survit donc au rollback.
- **Second lancement** : si un établissement existe déjà, la commande refuse, ne modifie rien, sort en erreur et journalise `ALREADY_BOOTSTRAPPED`. Même comportement si le nom d'utilisateur ou l'e-mail admin existe déjà.

## Point à arbitrer

La spec veut un fonctionnement **mono-établissement en V1** mais **prêt pour le multi-établissement**. Le bootstrap refuse volontairement de créer un deuxième établissement. Cela ne remet pas en cause le modèle : un deuxième `School` reste une simple insertion de données, comme le démontrent les tests de `test_tenancy_permissions.py`. En revanche, la création d'un établissement supplémentaire relève du futur *control plane* (`SchoolInstallation`, hors V1 selon la spec §4). Elle devra faire l'objet d'une opération dédiée, conçue explicitement plutôt que dérivée du bootstrap.

**Variable d'environnement** : `BOOTSTRAP_ADMIN_PASSWORD` peut être visible via `docker inspect` ou `/proc`. Il faut la retirer de l'environnement après usage. La saisie interactive reste la méthode recommandée.
