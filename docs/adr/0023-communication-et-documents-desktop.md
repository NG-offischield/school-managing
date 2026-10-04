# ADR 0023 — Communication et documents sur le poste d'administration

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - pages PySide6 « Gestion → Communication » et « Gestion → Documents » ;
  - client temps réel sur l'endpoint existant `ws/v1/realtime/` ;
  - deux indicateurs du tableau de bord.
- **Hors périmètre :** FCM, Flutter, activation des comptes, packaging Windows.
- **Migrations :** aucune. Aucun nouveau modèle, aucune logique PDF côté poste.

## 1. Clients minces

Le poste réutilise **strictement** Communication (ADR 0015) et le registre `Document` (ADR 0016). Tout est
décidé par le serveur :

- la visibilité : ce qu'on ne peut pas voir répond 404, comme ce qui n'existe pas ;
- les transitions d'une réclamation, avec un motif exigé pour résoudre, clôturer ou rouvrir ;
- la modération ;
- le contrôle des pièces jointes : PDF, PNG ou JPEG, **contenu réel** vérifié, taille limitée, stockage privé ;
- la construction des PDF et le statut des documents (provisoire, officiel, remplacé).

## 2. Communication

| Onglet | API |
|---|---|
| Notifications | `GET notifications/` (lu / non lu, type ; paginé), `…/unread-count/`, `…/{id}/read/`, `…/read-all/` |
| Messagerie | `GET/POST conversations/` (multipart pour les pièces jointes), `…/{id}/messages/`, `…/read/`, `…/participants/`, `DELETE messages/{id}/` (masqué, conservé) |
| Forum | `GET forum/spaces/`, `POST admin/forum/spaces/`, `GET/POST forum/threads/`, `…/posts/`, `DELETE forum/posts/{id}/` {motif}, `POST admin/forum/threads/{id}/status/` |
| Réclamations | `GET complaints/`, `…/{id}/`, `…/cancel/`, `…/attachments/`, `POST admin/complaints/{id}/status/` {statut, motif, assignation} |

- **Rien n'est supprimé :**
  - un message ou un post est masqué, avec son motif, et reste lisible par l'administration ;
  - une réclamation est annulée ; son historique est affiché.
- **Pièces jointes :**
  - seuls le **nom nu** et les octets quittent le poste (multipart), jamais un chemin local ;
  - le téléchargement passe par `attachments/{message|complaint}/{id}/download/` après contrôle des droits ;
  - aucun chemin serveur n'est jamais exposé.
- **Renvoi après coupure réseau :** il réutilise le même `client_id`, donc pas de doublon (même principe que
  l'idempotence des paiements, ADR 0022).

## 3. Temps réel (`school_admin/realtime.py`)

`QWebSocket` de Qt (aucune nouvelle dépendance) sur **l'infrastructure Channels existante** :

- **Connexion :** handshake avec `Authorization: Bearer <access>`, le même jeton que REST et jamais dans
  l'URL ; le serveur répond `auth.ok` (non-lus).
- **Resynchronisation** après chaque (re)connexion : `sync` depuis la dernière notification vue, puis
  `subscribe` (avec `since`) pour les conversations ouvertes.
- **Maintien :** `ping` toutes les 25 s ; reconnexion avec attente croissante (1 → 30 s).
- **Fermeture 4401** (jeton expiré, session révoquée, membre suspendu) : un seul rafraîchissement du jeton par
  le client REST, puis reconnexion ; en cas d'échec, retour à la connexion (« session expirée »).
- **Désactivation :** l'`AppController` ne crée le client que si une fabrique est fournie. L'application
  réelle en fournit une ; les tests unitaires, non, ou un faux socket.

## 4. Documents

Il y a six onglets : Bulletins, Cartes élèves, Emplois du temps, Reçus, Bulletins de paie, Relevés de présence
(relevé d'un élève ou registre d'une classe). Chaque onglet offre :

- une liste paginée avec recherche (titre ou code de vérification, ajout lecture seule) et filtre de statut ;
- le détail du document ;
- la génération : on choisit la source, le serveur construit le PDF et réutilise un document déjà à jour ;
- le téléchargement : `documents/{id}/download/`, contrôlé et tracé par le serveur ;
- la regénération d'un document provisoire : l'ancien est conservé ;
- la vérification d'un code imprimé.

Bulletins : « Calculer les bulletins… » appelle l'API existante `report-cards/generate/`.

## 5. Identité — règle absolue

- Les documents scolaires portent **exclusivement** l'identité de l'établissement (`SchoolBranding`).
- Le registre Documents n'a pas été modifié.
- Les écrans Documents n'importent rien de l'identité du logiciel (`ui/branding.py`) ; un test le vérifie.
- L'E2E télécharge un bulletin, un reçu et une carte réels : chacun contient le nom de l'école et jamais
  « School Managing ».

## 6. Ajouts backend (lecture seule, sans migration)

- `GET admin/communication/members/?search=&role=` (ADMIN) : annuaire des membres actifs (id, nom, rôles ;
  ni e-mail, ni téléphone). Il sert à choisir les participants d'une conversation et l'assigné d'une
  réclamation.
- `?search=` sur `documents/` : titre ou code de vérification, dans ce que l'appelant voit déjà.

## 7. Tableau de bord

- Indicateur « Communication » : notifications non lues ; messages non lus et réclamations ouvertes en complément.
- Indicateur « Documents » : nombre de documents et dernier généré.

## 8. E2E

`backend/tools/e2e_documents_fixture.py` (base de **test** uniquement, idempotent) prépare une année « 2199-2200 »
avec une période, une classe et un élève. Il n'existe aucune API de création de périodes : elles sont établies
avec l'école.

Le poste calcule ensuite les bulletins et génère leur PDF par les API existantes.
