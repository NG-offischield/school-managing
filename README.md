# School Managing

Plateforme de gestion scolaire complète : API Django, poste d'administration Windows (PySide6), quatre applications mobiles Flutter (Parent, Enseignant, Personnel, Gardien), et pour l'établissement ISBREE (Yaoundé, Etoug-Ebe) un site public et un portail web par rôle en Next.js.

Le backend est la **seule autorité** pour les permissions, les calculs, la finance et les règles métier. Aucun client ne parle directement à PostgreSQL ou à Redis.

## Démonstration

> Démonstration avec des **données fictives** (préproduction gratuite). Ce n'est pas le système officiel d'ISBREE. Les services gratuits se mettent en veille : la première visite peut prendre environ une minute.

| Lien | Adresse |
|---|---|
| Site public ISBREE | *à compléter après déploiement vérifié* |
| Espace ISBREE (portail) | *à compléter après déploiement vérifié* |
| Vidéo de démonstration | *à compléter après publication* |
| Dépôt GitHub | *à compléter après publication* |

Comptes de démonstration du portail (fictifs, **consultation seule**) : `parent.demo@isbree.test`, `enseignant.demo@isbree.test`, `personnel.demo@isbree.test`, `gardien.demo@isbree.test`. Le mot de passe commun est affiché sur la page de connexion de la démo.

## Architecture

| Composant | Technologie | Dossier |
|---|---|---|
| API REST + WebSocket | Django 5.2 LTS, DRF, Channels (ASGI, Daphne) | `backend/` |
| Base de données | PostgreSQL 17 | conteneur `db` |
| Temps réel, cache, limitation de débit | Redis 7 | conteneur `redis` |
| Poste d'administration | Python + PySide6, français et anglais | `desktop/` |
| Applications mobiles | Flutter, socle partagé `school_core` | `mobile/` (parent, enseignant, personnel, gardien) |
| Site public ISBREE | Next.js 16 (rendu serveur, cache, CSP) | `web/isbree-public/` |
| Espace ISBREE | Next.js 16 en BFF : jetons dans un cookie chiffré HttpOnly, rôle revérifié par l'API | `web/isbree-portal/` |

Les décisions d'architecture sont tracées dans [docs/adr/](docs/adr/), de 0001 à 0033. La source fonctionnelle est [docs/specification/School_Master_Specification_V4.docx](docs/specification/School_Master_Specification_V4.docx).

## Fonctionnalités

- **Socle :**
  - multi-établissement ;
  - authentification par jetons révocables (rotation et détection de réutilisation) ;
  - journal de sécurité ;
  - codes d'activation à usage unique ;
  - messages en français et en anglais.
- **Scolarité :**
  - années, périodes, niveaux, matières, classes, élèves ;
  - notes avec historique immuable, bulletins ;
  - présences par QR annuel, retards et convocations ;
  - planning avec conflits garantis par PostgreSQL et remplacements.
- **Gestion :**
  - finance avec paiements simulés, idempotence et grand livre append-only ;
  - paie ;
  - communication temps réel : notifications, messagerie, forum, réclamations ;
  - documents PDF officiels versionnés aux couleurs de l'école.
- **Parents :** inscription validée par l'école et rattachement parent-enfant vérifié.
- **ISBREE web :**
  - site public : formations réelles, actualités, galerie, FAQ, préinscription avec pot de miel et limitation de débit ;
  - portail par rôle ;
  - invitation des familles par lien d'activation valable 48 h ;
  - téléchargement des seuls APK Release signés ;
  - administration dans le poste (module « Site ISBREE »).

Le détail par phase est dans la section « État d'avancement » ci-dessous.

## Démarrage local

Prérequis : Docker Desktop. Pour le web : Node.js 24. Pour le poste : Python 3.13.

1. Créez le fichier de configuration :

   ```bash
   cp .env.example .env
   ```

   Remplacez ensuite les valeurs « change-me ».

2. Démarrez l'API, sur <http://localhost:8000> :

   ```bash
   docker compose up --build
   ```

3. Créez l'établissement et son premier super-administrateur (il n'existe pas d'inscription d'administrateur publique) :

   ```bash
   docker compose exec web python manage.py bootstrap_school --code LYC-DLA --name "Lycée de Douala" --city Douala --address "Akwa" --admin-username admin --admin-email admin@example.cm --admin-first-name Jean --admin-last-name Dupont
   ```

Le site et le portail ISBREE, leurs variables et leurs comptes de démonstration sont décrits dans [docs/isbree-web.md](docs/isbree-web.md).

## Tests

| Suite | Commande |
|---|---|
| Backend (PostgreSQL réel) | `docker compose run --rm web pytest` |
| Poste PySide6 | `desktop/.venv/Scripts/python -m pytest` (dans `desktop/`) |
| Web : unitaires, types, lint | `npm test`, `npm run typecheck`, `npm run lint` (dans chaque application web) |
| Web : bout en bout et accessibilité (Playwright + axe) | `npm run test:e2e` (API démarrée, données de démonstration) |

Derniers passages complets (14 et 15/10/2026, poste de développement) :

- backend : 948 tests réussis, dont 4 pour les garde-fous de la démo ;
- poste : 709 tests réussis ;
- site public : 10 tests unitaires et 36 tests Playwright réussis ;
- portail : 12 tests unitaires et 16 tests Playwright réussis.

## Documentation

- [Exploitation](docs/runbook.md) et [base de données](docs/database-runbook.md)
- [Site et portail ISBREE](docs/isbree-web.md)
- [Démo publique gratuite](docs/deploiement-demo.md) et [ADR 0033](docs/adr/0033-demo-publique-gratuite.md)
- [Script de la vidéo de démonstration](docs/video-demo.md)
- [Fiche Git et GitHub](docs/guide-git.md)
- Réseau local et applications mobiles : [docs/reseau-local.md](docs/reseau-local.md), [mobile/README.md](mobile/README.md)

## Limites connues

- **ISBREE :**
  - les textes de l'établissement sont **provisoires**, à valider ;
  - le logo est provisoire ;
  - l'adresse n'est pas confirmée ;
  - les images de démonstration sont des illustrations.
- **Applications mobiles :** aucune version Release signée n'est publiée. Il faut d'abord le keystore de l'établissement.
- **Démo en ligne :** hébergement gratuit, mise en veille, aucune sauvegarde automatique durable. Elle ne doit **pas** recevoir de vraies données familiales.
- **Ressources ISBREE :** on ne peut pas encore les limiter à une fonction du personnel depuis le poste : l'API ne fournit pas la liste des fonctions.
- **Hors périmètre actuel :** notifications push (FCM), paiement en ligne réel, mise en production.

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
- [x] Documents officiels PDF : bulletins, reçus, bulletins de paie, relevés et registres de présence, carte d'élève (QR annuel existant), emploi du temps ; officiel / provisoire, versions, branding de l'école, stockage privé, traces (ADR 0016)
- [x] Poste d'administration PySide6 : connexion, shell, tableau de bord avec graphiques, années scolaires, niveaux, catégories pédagogiques, matières, classes, élèves, enseignants, cours, planning, finance, paie, communication, documents (`desktop/`, voir desktop/README.md, ADR 0017 à 0023)
- [x] Cycle de vie des comptes : codes d'activation à usage unique (hachés, expirants, révocables), premier mot de passe choisi par la personne, suspension / réactivation (ADR 0024)
- [x] Mobile Flutter : socle partagé `school_core` et application enseignant (activation, connexion, tableau de bord, planning, séance, communication ; `mobile/`, ADR 0025)
- [x] Parents : inscription validée par l'école, rattachement vérifié (pièce d'identité contrôlée à l'école — empreinte HMAC seulement —, désignation par l'élève, parrainage d'un second parent par code à usage unique), page Parents du poste, application Flutter parent (accueil, présences, planning, finance selon les droits, bulletins, messages ; ADR 0026)
- [x] Gardien et Personnel : applications Flutter (portail QR existant, mes passages, notifications, planning, messages vers l'administration, rémunération) sur un socle `school_core` commun aux quatre applications (connexion, activation, temps réel, communication selon le rôle, portail ; ADR 0027)
- [x] Site ISBREE et Espace ISBREE : site public (formations réelles, actualités, galerie, FAQ, contact, préinscription), portail par rôle (Parent, Enseignant, Personnel, Gardien), invitation par lien d'activation, téléchargement des APK Release signés, administration dans le poste (module « Site ISBREE ») — non mis en production (ADR 0032, docs/isbree-web.md)
- [x] Démo publique préparée : réglages `demo`, comptes de démonstration en lecture seule, mot de passe administrateur distinct, `render.yaml` (ADR 0033) — déploiement à faire (comptes hébergeurs)
- [ ] Phases suivantes — autres écrans du poste d'administration, présence par séance (fiches d'appel), envoi FCM, mise en production du site
