# Intégration inter-applications (E2E réseau)

`cross_app.mjs` rejoue les 11 scénarios de [docs/integration-matrix.md](../docs/integration-matrix.md) **par le vrai réseau**. Il passe par le même chemin que les téléphones et le poste d'administration :

- REST ;
- WebSocket `ws/v1/realtime/` ;
- l'adresse IP **locale (LAN)** du PC.

Il ne parle qu'au backend : aucun accès direct à PostgreSQL ou à Redis, et aucune communication directe entre applications.

| | |
|---|---|
| Cible | un backend **de TEST** (`config.settings.test`, base `db_test`), jamais la base de développement |
| Données | le jeu DEMO (`seed_demo`) + `backend/tools/e2e_cross_app_fixture.py` |
| Prérequis | Docker Desktop, Node.js ≥ 22 (`fetch` et `WebSocket` intégrés, aucune dépendance) ; pour `desktop_forum.py` et `desktop_payment.py`, l'environnement virtuel du poste (`desktop\.venv`) |
| Résultat | une ligne par vérification (`PASS` / `FAIL` / `GAP`), code de sortie 1 au premier `FAIL` |

`GAP` signale un comportement que le produit n'offre pas aujourd'hui. Il est affiché et compté, jamais masqué.

## Ce que la fixture ajoute à DEMO

- Un enseignant ayant un cours en `6e A`, avec une séance **demain**. Une modification de planning concerne alors les parents A, B, C et D (classe `6e A`), mais pas S4 (`3e B`).
- Un gardien et un agent (STAFF) de DEMO.
- Une seconde école `TEST01` avec son administrateur `test01.e2e.admin` : elle sert à vérifier l'isolation DEMO ↔ TEST01.

Les comptes créés reçoivent le mot de passe de `DEMO_PASSWORD`. Ce mot de passe n'est passé que par l'environnement : jamais dans le dépôt, jamais affiché.

## Lancer (PowerShell, depuis la racine du dépôt)

**1. L'adresse IP du PC.** Elle change selon le réseau (DHCP), donc on la lit à chaque fois et on ne l'écrit jamais dans les sources :

```powershell
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq 'Dhcp' } | Select-Object -First 1).IPAddress
```

**2. Une base de TEST vide.** `db_test` est en mémoire (`tmpfs`) : la redémarrer la vide. La base de développement n'est pas touchée.

```powershell
docker compose restart db_test
```

**3. Le backend de TEST, sur le port 8001, accessible par le LAN :**

```powershell
docker compose run -d --rm --no-deps -p 8001:8000 -e DJANGO_SETTINGS_MODULE=config.settings.test -e "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,$ip" --name school-e2e web sh -c "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"
```

Attendre que `http://<ip>:8001/api/v1/health/` réponde 200.

**4. Les données.** Le mot de passe est saisi, jamais écrit :

```powershell
$env:DEMO_PASSWORD = Read-Host "Mot de passe des comptes de test"
docker exec -e DEMO_PASSWORD school-e2e python manage.py seed_demo
docker exec -e DEMO_PASSWORD school-e2e python manage.py shell -c "exec(open('tools/e2e_cross_app_fixture.py').read())" > $env:TEMP\e2e_fixture.json
```

**5. Le scénario :**

```powershell
$env:E2E_API_URL = "http://${ip}:8001"
$env:E2E_FIXTURE = "$env:TEMP\e2e_fixture.json"
node e2e/cross_app.mjs
desktop\.venv\Scripts\python e2e\desktop_forum.py
desktop\.venv\Scripts\python e2e\desktop_payment.py
```

`desktop_forum.py` fait tourner le **code du poste d'administration lui-même** contre ce backend, par le réseau : `ApiClient`, `CommunicationService` et le `RealtimeClient` Qt (sans affichage). Il vérifie :

- la publication d'une discussion ;
- la notification « Forum » reçue en direct quand un parent répond, puis retrouvée par `GET` ;
- la lecture de la réponse ;
- la modération avec motif ;
- le verrouillage (la réponse suivante du parent reçoit 409).

`desktop_payment.py` fait tourner le même code du poste pour un **paiement de parent**. Il vérifie :

- qu'un paiement refusé pour fonds insuffisants (parent B) ne notifie rien ;
- qu'un paiement confirmé (parent D) arrive en direct avec le type « Paiement » et le titre « Paiement confirmé — facture <n°> — <montant> XAF » ;
- que le compteur de non-lus augmente ;
- que la notification se retrouve par `GET` ;
- que la facture apparaît PAYÉE ;
- qu'un rejeu avec la même clé d'idempotence n'ajoute aucune notification.

**6. Nettoyage :**

```powershell
docker rm -f school-e2e
Remove-Item Env:DEMO_PASSWORD, Env:E2E_API_URL, Env:E2E_FIXTURE
Remove-Item $env:TEMP\e2e_fixture.json
```

Un second passage exige une base vide : reprendre à l'étape 2, car les factures DEMO sont alors déjà payées et la séance déjà annulée.

Si l'adresse LAN ne répond pas alors que `127.0.0.1:8001` répond, c'est le pare-feu. Voir « Réseau local et pare-feu » dans [docs/integration-matrix.md](../docs/integration-matrix.md). Une adresse `127.0.0.1` fonctionne aussi, mais le script prévient qu'elle ne teste pas le chemin des téléphones.

## Scénarios couverts

| | Scénario | Vérifié par le réseau |
|---|---|---|
| S1 | annonce → parent | notification en direct (parent, enseignant, agent) ; parent hors ligne : `GET /notifications/` |
| S2 | parent lit le forum et répond | notification FORUM du nouveau sujet ; liste, lecture ; annonce en lecture seule (403) ; réponse |
| S3 | l'administration voit la réponse | notification FORUM à l'auteur ; lecture ; modération avec motif ; verrouillage (409 `thread_locked`) |
| S4 | périmètre enseignant | `GET /teacher/contacts/` limité à ses classes ; refusé aux parents ; espace de classe : parents notifiés ; autre classe refusée |
| S5 | l'enseignant contacte un parent | conversation parent–enseignant, notifications des deux côtés ; élève non enseigné : 403 |
| S6 | l'agent ne reçoit que ce qui le concerne | annonce et nouveau sujet de l'espace école ; aucune réponse, classe, message, paiement ni planning |
| S7 | pas de forum pour le gardien | espaces et sujets vides ; écriture refusée ; aucune notification |
| S8 | paiement → Finance → administration | paiement réussi, notification au parent, facture PAYÉE vue par l'administration ; administration notifiée en direct (« Paiement confirmé — facture … ») et une seule fois par `GET` ; fonds insuffisants (parent B) : aucune notification |
| S9 | changement de planning | annulation : parent et enseignant notifiés en direct ; parent hors ligne : `GET` |
| S10 | reconnexion | trame `sync` (notifications manquées) et `subscribe(since)` (messages manqués) |
| S11 | pas de fuite DEMO ↔ TEST01 | conversations, élève (404), écriture, forum, flux en direct |

S'y ajoutent l'authentification (6 connexions en direct, jeton invalide refusé en 4401, rafraîchissement) et la déconnexion, qui ferme le flux en direct (4401) et révoque le jeton.
