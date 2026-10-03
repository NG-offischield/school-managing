# ADR 0015 — Communication : notifications, messagerie, forum, réclamations, pièces jointes, temps réel

- **Statut :** accepté — 2026-10-03
- **Périmètre :** nouvelle app `communication`, consommateur WebSocket `ws/v1/realtime/`, stockage privé.
- **Hors périmètre :** envoi FCM (seule la file `NotificationDelivery` existe), PDF, PySide6, déploiement.

## 1. Notifications produites par les domaines existants, sans les modifier

Des **projecteurs** (`events.py`) relisent, **après commit**, l'état décidé par le domaine source et le transforment en notifications. Le domaine source ne connaît pas `communication`, et aucune règle métier n'est réimplémentée.

| Source | Notification | Destinataires |
|---|---|---|
| présence LATE / ABSENT | ATTENDANCE_LATE / ATTENDANCE_ABSENT | parents vérifiés de l'élève qui acceptent les notifications |
| convocation | CONVOCATION | le parent convoqué |
| `ScheduleChange` à notifier | SCHEDULE_CHANGE / SUBSTITUTION | enseignants concernés, parents de la classe |
| paiement / remboursement | PAYMENT / REFUND | le payeur |
| paie APPROVED / PAID | PAYROLL | l'employé |
| bulletin validé | REPORT_CARD | parents vérifiés de l'élève |

- **Déclencheurs :** `post_save` des modèles sources. Pour le chemin en masse de la présence (`bulk_create` / `update`, sans signal), la ligne d'audit `ATTENDANCE_DAY_FINALIZED` sert de déclencheur.
- **Idempotence :** chaque notification porte une clé d'événement unique par destinataire, UNIQUE(destinataire, `event_key`). `manage.py dispatch_notifications` rejoue donc n'importe quelle fenêtre sans doublon.
- **Après envoi :** la file `ScheduleChange` passe SENT.
- **Données internes :** les parents ne reçoivent jamais les motifs internes du planning.

Règles de livraison :
- un destinataire explicite, de la **même école** (garde du service, plus FK composite) ;
- un membre inactif ne reçoit rien ;
- préférences par type ; les types obligatoires (convocation, paie, remboursement, réclamation) restent toujours visibles dans l'application ;
- une `NotificationDelivery` PENDING est créée pour le futur FCM si le push est accepté.

L'historique est immuable : une notification ne fait que passer de non lue à lue, une seule fois (trigger), et n'est jamais supprimée.

## 2. Messagerie privée

| Type | Qui |
|---|---|
| ADMINISTRATION | un membre ↔ l'administration ; un administrateur peut ouvrir une conversation avec n'importe quel membre |
| PARENT_TEACHER | à propos d'**un** élève : un parent vérifié de cet élève et un enseignant qui a un cours actif dans sa classe |
| COMPLAINT | ouverte uniquement par le workflow de réclamation |

Les gardiens n'ont pas accès à la messagerie (spec §8).

- **Traçabilité :** l'administration de l'école lit toutes les conversations de son école. Un administrateur qui écrit rejoint la conversation de façon visible, et c'est audité.
- **Messages :** jamais modifiés. Supprimer un message (le sien uniquement) le masque, mais la ligne reste (trigger).
- **Expéditeur :** PostgreSQL impose qu'il soit participant, par la FK (conversation, expéditeur) → participant.
- **Lu / non-lu :** suivi par participant.
- **Renvois :** `client_id` déduplique un message renvoyé après une reconnexion.

## 3. Forum et annonces

`ForumSpace` est un ajout. Les membres d'un espace sont **calculés**, jamais copiés :
- **espace SCHOOL :** les rôles choisis parmi TEACHER, PARENT et STAFF ;
- **espace CLASS :** les enseignants de la classe et les parents vérifiés de ses élèves ;
- **toujours :** l'administration.

Règles :
- les annonces sont publiées par l'administration seule, en lecture seule pour les autres, et notifient tout l'espace ;
- les posts ne sont jamais modifiés ; la modération par l'administration exige un motif ;
- verrouiller ou archiver un fil exige un motif.

## 4. Réclamations

`DRAFT → OPEN → IN_PROGRESS → RESOLVED → CLOSED`, avec annulation (`CANCELLED`) et réouverture.

- **Motif obligatoire** pour : résolution, clôture, réouverture, et annulation après soumission.
- **Pas de suppression :** l'annulation est un statut.
- **Contenu figé** dès la soumission, et `CANCELLED` / `CLOSED` sont finaux (trigger).
- **Historique** `ComplaintStatusHistory` en ajout seul.
- **Brouillon :** visible par son seul auteur.

Droits :
- **parent :** réclamation sur un élève avec le droit `can_submit_complaints` du lien ;
- **enseignant :** sur un élève à qui il enseigne ;
- **personnel :** ce qui lui est assigné ;
- **administration :** toutes les réclamations soumises de son école.

À la soumission, un fil de conversation COMPLAINT s'ouvre entre l'auteur, la partie concernée et, si l'auteur l'a choisi, l'administration.

## 5. Pièces jointes

- **Stockage :** stockage Django `private`, sans aucune route publique, sous un nom aléatoire.
- **Type :** décidé par le **contenu** (signature binaire, image décodée par Pillow). Seuls PDF, PNG et JPEG sont acceptés.
- **Taille :** plafonnée par `default_attachment_limit_mb` de l'école, sous un plafond global de 25 Mo.
- **Intégrité :** empreinte SHA-256 conservée ; lignes en ajout seul.
- **Téléchargement :** uniquement par une vue qui vérifie d'abord le droit sur la conversation ou la réclamation. Sinon 404.

## 6. Temps réel

- Un seul consommateur sur la pile Channels existante.
- **Authentification :** le même jeton qu'en REST. Il passe par l'en-tête `Authorization` pour les clients natifs, ou par une première trame `auth` pour les navigateurs.
- **Revalidation :** session et adhésion sont revérifiées toutes les 30 secondes au plus ; en cas d'échec, fermeture avec le code 4401.
- **Groupes :** un groupe par membre et un par conversation. Les événements ne partent qu'après commit, et chaque événement de conversation revérifie le droit de lecture.
- **Reconnexion :** trames `sync` et `subscribe` avec un paramètre `since`, et déduplication par `client_id`.
- **Factorisation :** `session_from_access_token` et `resolve_membership` sont partagés par REST et WebSocket.

## 7. Écarts et décisions — à valider

1. **Origine WebSocket :** un `Origin` présent doit appartenir à `ALLOWED_HOSTS`. Un `Origin` absent (clients natifs, qui s'authentifient par jeton) est accepté, alors que `AllowedHostsOriginValidator` bloquait ces clients.
2. **Ajouts au modèle :**
   - `Notification.event_key` / `source_*` ;
   - `NotificationPreference` et `NotificationDelivery` ;
   - `Conversation.student` et `last_message_at` ;
   - `Message.client_id` et `deleted_by` ;
   - `ForumSpace` ;
   - `Complaint.concerned_member`, `include_administration`, `submitted_at` et `cancelled_at`.
3. **Suppression en cascade :** les CASCADE de la spec sont remplacés par PROTECT, car rien n'est jamais supprimé. La purge prévue par la politique de rétention (§10) se fera par une procédure dédiée et auditée.
4. **Pas de modification des messages ni des posts** en V1 : il n'y a donc pas d'historique de révisions.
5. **Notes :** une note isolée ne déclenche pas de notification, seul le bulletin validé en déclenche une.
