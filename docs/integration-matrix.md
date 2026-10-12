# Matrice d'intégration des clients

État au **9 octobre 2026**, après la phase de finalisation : forum mobile, notifications du forum, conversations enseignant → parent, E2E inter-applications.

**Règle de lecture.** Une case n'est **PASS** que si un test réel l'a exercée. Le type de test est toujours indiqué :

| Type | Ce que c'est |
|---|---|
| backend | pytest |
| widget | Flutter, faux serveur |
| desktop | pytest Qt hors affichage, faux serveur |
| **réseau** | `e2e/cross_app.mjs`, `e2e/desktop_forum.py` ou `e2e/desktop_payment.py` contre le vrai backend, par l'IP LAN |

Dernier passage réseau, le 09/10/2026 sur le backend de **test** (`db_test`), joint par l'IP LAN du PC (192.168.1.102 ce jour-là, lue au lancement) :

- **`cross_app.mjs` : 52 contrôles, 52 PASS, 0 FAIL, 0 GAP** ;
- **`desktop_forum.py` : 8/8 PASS** ;
- **`desktop_payment.py` : 10/10 PASS**.

Ces chiffres sont ceux du dernier passage, après l'ajout de la notification administrative des paiements. L'IP était alors 192.168.1.113 : le bail DHCP était revenu à cette adresse pendant la journée. Le passage précédent, avant cet ajout, donnait 49 PASS et 1 GAP sur 50 contrôles.

Procédure : [e2e/README.md](../e2e/README.md).

## 1. Architecture

```
Admin PySide6 ─┐                          ┌─ PostgreSQL (db)   jamais exposé
Parent        ─┤  HTTP  /api/v1/…         │
Teacher       ─┼─────────────► Django ────┤
Staff         ─┤  WS    /ws/v1/realtime/  │
Guardian      ─┘  (Bearer, même jeton)    └─ Redis (canaux, cache)   jamais exposé
```

- **Isolation :** aucun client n'accède à PostgreSQL ou à Redis. Une donnée créée par un client n'atteint un autre client qu'en passant par l'API et ses services, puis :
  - en direct, par le WebSocket ;
  - plus tard, par `GET` ou par la trame `sync` à la reconnexion.
- **Une école à la fois :** chaque compte agit dans **son** établissement. L'administrateur `admin` (école `TEST01`) ne voit **rien** de l'école `DEMO`, dont l'administrateur est `demo.admin`. C'est voulu : 404 pour tout objet d'une autre école. Voir [desktop/README.md](../desktop/README.md).
- **Un seul chemin par fonction :**
  - un seul forum (`apps/communication/forum.py`) ;
  - un seul service de notifications (`notify` / `notify_many`), idempotent, qui respecte les préférences, refuse un destinataire d'une autre école et pousse après commit ;
  - une seule règle « qui peut parler à qui » (`apps/communication/access.py`).

  Les clients affichent ; le serveur décide.

## 2. Clients

| Client | API | WebSocket | Jetons | 401 / expiration | Reconnexion / resync |
|---|---|---|---|---|---|
| Admin PySide6 (`desktop/`) | `SCHOOL_ADMIN_API_URL`, sinon `%APPDATA%\SchoolManagingDesktop\desktop.json`, sinon `http://127.0.0.1:8000/api/v1/` | déduit de l'API (`ws://…/ws/v1/realtime/`), QWebSocket | accès en mémoire, refresh dans le trousseau Windows (keyring) | un seul refresh partagé, puis rejeu ; 4401 → refresh, sinon retour à la connexion | backoff de 1 à 30 s ; `sync` + `subscribe(since)` |
| Parent, Enseignant, Gardien, Personnel (`mobile/`, `school_core`) | `--dart-define=API_URL` ou `--dart-define-from-file=mobile/config/lan.json`, sans valeur par défaut ; HTTP en clair seulement vers une IP privée, en debug | `WS_URL`, ou déduit de `API_URL` (même hôte imposé) | accès en mémoire, refresh dans `flutter_secure_storage` | idem ; 4401 → refresh, sinon session expirée | idem (`RealtimeClient`) |

- **Erreurs typées des deux côtés :**
  - 403 : `ForbiddenException` ;
  - 404 : `NotFoundException` ;
  - 409 : `ConflictException`, règle expliquée. Par exemple `thread_locked` : l'écran recharge la discussion.
- **Pas de copie locale :** aucune base locale et aucun cache faisant autorité ; tout est relu sur l'API.
- **Aucune IP en dur dans les sources.** `mobile/config/lan.json` et `.env` sont ignorés par Git, et l'E2E lit l'adresse dans `E2E_API_URL`. Les seules adresses écrites dans le dépôt sont des constats datés dans la documentation, comme [pixel-lan-test-checklist.md](pixel-lan-test-checklist.md).

## 3. Authentification et sessions

- Le même jeton sert pour REST et pour le WebSocket :
  - `Authorization: Bearer` pour les clients natifs ;
  - première trame `{"type":"auth","token"}` pour un navigateur ou pour Node.
- **Vérifié par le réseau le 09/10 :**
  - connexion de l'administrateur, d'un parent, d'un enseignant, d'un gardien, d'un agent et de l'administrateur de `TEST01` ;
  - 6 connexions en direct ;
  - jeton invalide : fermeture en 4401 ;
  - refresh : nouveau jeton d'accès ;
  - logout : la connexion en direct est fermée en 4401 (le serveur revérifie la session toutes les 30 s), et l'ancien jeton est refusé (401).
- Toutes les permissions sont revérifiées par le serveur, en REST comme dans le consumer WebSocket.

## 4. Communication : trois domaines distincts

| Domaine | Qui | Règles (serveur) |
|---|---|---|
| **Forum** | admin, parent, enseignant, personnel ; **pas le gardien** | Voir le détail sous ce tableau. |
| **Messagerie privée** | admin, parent, enseignant, personnel ; **pas le gardien** (403) | Voir le détail sous ce tableau. |
| **Réclamations** | parent (sur **son** enfant, droit `can_submit_complaints`), enseignant (élève enseigné, ou sans élève), admin | Workflow avec historique. Soumission : notification de l'administration et conversation `COMPLAINT`. |

**Forum, règles du serveur :**

- **Espaces :**
  - école, ouverts par rôles ;
  - classe : les enseignants de la classe et les parents **vérifiés** de ses élèves, calculés.
- **Annonces :** réservées à l'administration, en lecture seule pour les membres. Notification `ANNOUNCEMENT` à tout l'espace.
- **Nouveau sujet :** notification `FORUM` aux membres de l'espace, sauf l'auteur.
- **Réponse :** notification `FORUM` aux seuls participants : l'auteur du sujet et les membres qui y ont écrit (message non retiré). Jamais toute l'école.
- **Modération :** par l'administration, avec motif. Un message n'est jamais modifié ; un message retiré est masqué.
- **Verrouillage :** une réponse est alors refusée en 409 `thread_locked`.

**Messagerie privée, règles du serveur :**

- **`ADMINISTRATION` :** un membre ↔ l'administration.
- **`PARENT_TEACHER` :** au sujet d'**un** élève, entre un parent vérifié de cet élève et un enseignant qui l'a **actuellement** en cours.
  - **Côté enseignant :** `GET /teacher/contacts/` donne seulement les élèves de ses cours actifs et leurs parents vérifiés et actifs : identifiant, nom, lien. Pas d'e-mail, pas de téléphone, pas de recherche dans les parents de l'école. Le serveur revérifie à l'envoi : 403, ou 404 pour une autre école.
  - **Côté parent :** `GET /parents/children/{id}/teachers/`.

Les notifications des autres domaines viennent de `communication/events.py` :

- **Vie scolaire :** retard ou absence, convocation, changement de planning ou remplacement (enseignants et parents de la classe), bulletin validé.
- **Argent :** paiement et remboursement (payeur), paie (employé).

Le type `FORUM` est **désactivable** dans les préférences, comme les autres types non obligatoires.

## 5. Matrice par client

| | API | WS | AUTH | PERM | UI | E2E réseau |
|---|---|---|---|---|---|---|
| Admin | PASS (réseau) | PASS (réseau, QWebSocket du poste) | PASS (réseau) | PASS (backend + réseau) | PASS (desktop : notifications, conversations, forum + modération, réclamations, élèves, parents, finance, planning, documents ; libellé « Forum ») | PASS forum : `desktop_forum.py` 8/8 ; paiements : `desktop_payment.py` 10/10, le 09/10. Parcours complet `test_live.py` : non relancé dans cette phase. |
| Parent | PASS (réseau) | PASS (réseau) | PASS (réseau) | PASS (backend + réseau) | PASS (widget, dont le **forum**) | PASS (réseau 09/10, par l'API). Application réelle sur téléphone : **à faire** (Pixel, § 8). |
| Personnel | PASS (réseau) | PASS (réseau) | PASS (réseau) | PASS (backend + réseau) | PASS (widget, dont le **forum**) | PASS (réseau 09/10, par l'API) |
| Enseignant | PASS (réseau) | PASS (réseau) | PASS (réseau) | PASS (backend + réseau) | PASS (widget, dont le **forum** et **« Nouveau message » → Parent d'élève**) | PASS (réseau 09/10, par l'API) |
| Gardien | PASS (réseau) | PASS (réseau) | PASS (réseau) | PASS (pas de forum, pas de messagerie : backend + réseau) | PASS (widget : l'onglet Forum n'existe pas et rien n'est demandé au serveur) | PASS (réseau 09/10) |

Pour les quatre applications mobiles, **E2E réseau** veut dire : le chemin réseau qu'elles empruntent (mêmes requêtes, même WebSocket, même IP LAN), joué par `cross_app.mjs`. Leurs écrans, eux, sont testés en widget contre un faux serveur. L'exécution de leurs **écrans** contre le vrai backend relève des tests `live_test.dart` (rejoués le 05/10, pas dans cette phase) et du test sur Pixel (§ 8).

## 6. Matrice par fonctionnalité

| | ADMIN | PARENT | STAFF | TEACHER | GUARDIAN |
|---|---|---|---|---|---|
| Notifications | PASS | PASS | PASS (seulement ce qui le concerne, réseau S6) | PASS | PASS (aucune notification de forum ni de messagerie, réseau S7) |
| Forum | PASS (desktop + réseau : publication, lecture, notification, modération, verrou) | PASS (widget + réseau : lecture, réponse, annonce en lecture seule) | PASS (widget + réseau : annonce et nouveau sujet de l'espace école seulement) | PASS (widget + réseau : sujet dans l'espace de **sa** classe ; autre classe refusée) | N/A (exclu, vérifié) |
| Notifications du forum | PASS (auteur notifié d'une réponse, en direct ; libellé « Forum ») | PASS (nouveau sujet, en direct) | PASS (nouveau sujet de son espace ; pas les réponses ni la classe) | PASS (backend : périmètre de l'espace) | N/A |
| Messaging | PASS | PASS (dont les réponses à un enseignant) | PASS | PASS (vers l'administration ; **vers un parent de ses élèves** : backend + widget + réseau) | N/A (403 vérifié) |
| Complaints | PASS | PASS | N/A (le personnel n'en dépose pas) | PARTIAL (autorisé et testé en backend, pas joué par le réseau) | N/A |
| Planning | PASS | PASS (en direct et hors ligne) | PASS (aucune notification de planning de classe, par conception) | PASS | N/A (fermetures seulement) |
| Finance | PASS (paiement et facture PAYÉE vus ; **notifiée** d'un paiement de parent confirmé, une fois, en direct et par `GET` : backend + réseau + poste) | PASS (paiement, notification) | N/A (sa paie : PASS le 05/10) | N/A (sa paie) | N/A (statut sans montant) |
| Documents | PARTIAL (desktop ; non joué par le réseau dans cette phase) | PASS (reçu PDF, 05/10) | PARTIAL | PARTIAL | N/A |
| Plans de l'établissement | PASS (desktop : import, aperçu, versions, publication, retrait, diffusion ; réseau : `e2e/school_plans.mjs` 28/28, le 12/10) | PASS (widget + réseau : liste, téléchargement, notification `PLAN` en direct, accès fermé au retrait ou hors public) | N/A (jamais destinataire, vérifié par le réseau) | PASS (widget + réseau ; perd l'accès aussitôt hors public) | N/A (jamais destinataire, vérifié par le réseau) |

## 7. Scénarios E2E (réseau, le 09/10)

| # | Scénario | Résultat |
|---|---|---|
| 1 | Annonce → parent | **PASS** : en direct pour le parent, l'enseignant et l'agent ; parent hors ligne : `GET /notifications/` |
| 2 | Le parent lit le forum et répond | **PASS** : notification `FORUM` du nouveau sujet ; liste, lecture ; annonce en lecture seule (403) ; réponse (201) |
| 3 | L'administration voit la réponse | **PASS** : l'auteur est notifié en direct ; lecture par `GET` comme le fait le poste ; modération avec motif (le message apparaît retiré pour les membres) ; verrouillage → 409 `thread_locked`. Poste réel : `desktop_forum.py` 8/8. |
| 4 | Périmètre enseignant | **PASS** : `teacher/contacts` = élèves de 6e A (S1 oui, S4 de 3e B non) ; refusé à un parent (403) ; sujet dans l'espace 6e A, parent notifié en direct ; espace 3e B : 404 |
| 5 | L'enseignant contacte un parent | **PASS** : conversation `PARENT_TEACHER` au sujet de S1, notifications en direct des deux côtés ; au sujet de S4 (élève non enseigné) : 403 |
| 6 | L'agent ne reçoit que ce qui le concerne | **PASS** : annonce et nouveau sujet de l'espace école ; aucune réponse, classe, message, paiement ni planning |
| 7 | Pas de forum pour le gardien | **PASS** : espaces et sujets vides ; écriture 404 ; messagerie 403 ; aucune notification |
| 8 | Paiement → Finance → administration | **PASS** : paiement SUCCEEDED, notification au parent, facture PAYÉE vue par l'administration ; administration notifiée en direct (« Paiement confirmé — facture F26-… — 75 000 XAF »), retrouvée une fois par `GET` ; fonds insuffisants : rien. |
| 9 | Changement de planning | **PASS** : séance annulée ; parent de 6e A et enseignant notifiés en direct ; parent hors ligne : `GET` |
| 10 | Reconnexion | **PASS** : notification manquée rendue par `sync`, message manqué par `subscribe(since)` |
| 11 | Pas de fuite DEMO ↔ TEST01 | **PASS** : aucune conversation ni aucun sujet visible ; élève DEMO = 404 ; écriture vers un parent DEMO = 404 ; aucun événement DEMO sur la connexion en direct de TEST01 |

Le premier passage du 09/10 a révélé deux écarts. Le passage suivant les montre corrigés.

1. **Une réponse à un sujet verrouillé reçoit 409, pas 400 :** `thread_locked` fait partie de `CONFLICT_RULES`.
   - L'application mobile ne rechargeait pas la discussion sur un 409, et son faux serveur répondait 400.
   - Corrigé : l'écran recharge aussi sur un 409, et le faux serveur suit le contrat. Un test de mutation confirme qu'il détecte la régression.
2. **L'attente du test sur l'agent était fausse.** Un agent membre de l'espace école est bien notifié d'un **nouveau sujet** de cet espace : c'est la règle validée. Le contrôle vérifie désormais exactement cela, et l'absence de tout le reste.

## 8. Réseau local, pare-feu, Pixel

### Adresse et `ALLOWED_HOSTS`

- **Django** écoute sur `0.0.0.0:8000` (`docker-compose.yml`). `DJANGO_ALLOWED_HOSTS` contient l'IP courante, **jamais `*`**. Un `Host` non listé reçoit 400.
- **L'IP change** (bail DHCP, autre box) : 192.168.1.113 le 07/10, 192.168.1.102 le 09/10.
  - On la lit à chaque fois (`ipconfig`, ou `Get-NetIPAddress`) ; on ne l'écrit dans aucune source.
  - Puis `mobile/tools/configure_lan.ps1 -Restart` met à jour `.env` et `mobile/config/lan.json`, tous deux ignorés par Git, et l'APK est reconstruit. Voir [reseau-local.md](reseau-local.md).
  - **Constat du 09/10 :** `.env` et `lan.json` désignent encore `.113`. Il faut lancer `configure_lan.ps1` et reconstruire l'APK avant le test sur Pixel. Rien n'a été modifié automatiquement.
- **Poste d'administration :** `127.0.0.1` sur le PC lui-même. Depuis un autre PC du réseau : `SCHOOL_ADMIN_API_URL` ou `desktop.json`.

### Pare-feu Windows

Aucun réglage n'a été changé. Recommandation :

1. le Wi-Fi de confiance en profil **Privé** ;
2. une règle entrante **TCP 8000**, profil **Privé uniquement**, depuis le **sous-réseau local** uniquement ;
3. aucune redirection de port sur la box.

Les commandes à lancer par l'administrateur du poste (PowerShell administrateur) sont dans [reseau-local.md](reseau-local.md#pare-feu-windows-et-profil-réseau).

Constat **en lecture seule** du 09/10 :

| Élément | État |
|---|---|
| Profil réseau du Wi-Fi « Wi-Fi 3 » | **Public** |
| Règle « School Managing API (LAN) » | **absente** |
| Règles « Docker Desktop Backend » | 2 règles entrantes **Allow** sur le profil **Public** |

C'est grâce aux règles Docker que le port publié est joignable depuis le téléphone, et il le serait aussi sur un Wi-Fi public. À régulariser par l'administrateur du poste :

- passer le Wi-Fi de confiance en Privé ;
- créer la règle limitée au profil Privé ;
- restreindre les règles Docker au profil Privé.

### Test sur Pixel 7a, par le Wi-Fi, sans `adb reverse`

Checklist : [pixel-lan-test-checklist.md](pixel-lan-test-checklist.md). Elle couvre :

- connexion, API, WebSocket (« Connecté en direct ») ;
- notifications et forum (annonce publiée depuis le poste, réponse vue sur le poste) ;
- paiement et reçu.

**Pas encore exécuté dans cette phase :** il demande le téléphone en main. Seul l'accès réseau du Pixel au port 8000 a été constaté, le 05/10. L'émulateur Android 17 plante sur ce GPU, et le test réel reste donc à faire sur l'appareil.

## 9. Écarts et suites

| Écart | État |
|---|---|
| L'administration n'était pas notifiée d'un paiement | **résolu** : notification `PAYMENT` aux administrateurs de l'école pour un paiement de parent confirmé (projecteur après commit, idempotent). Le paiement lui-même est inchangé. |
| Écrans mobiles contre le vrai backend | `live_test.dart` à rejouer, puis test sur Pixel (§ 8) |
| Parcours complet du poste (`test_live.py`) | non relancé dans cette phase (il ne couvre pas le forum, couvert par `desktop_forum.py`) |
| Pare-feu / profil réseau | à régulariser par l'administrateur du poste (§ 8) |
| Réclamation d'enseignant par le réseau | testée en backend seulement |
