# ADR 0031 — Notifications système dans la langue du lecteur

- **Statut :** accepté — 2026-10-13
- **Périmètre :** titres et messages des notifications **système** (présences, convocations, planning, paiements, remboursements, paie, bulletins, réclamations, forum, messagerie, plans), en français ou en anglais.
- **Hors périmètre :** traduction de ce que les personnes écrivent ; notifications push (aucun envoi n'existe : voir §5) ; préférence de langue côté serveur.

## 1. Le problème

Les projecteurs (`communication/events.py` et les services qui appellent `notify()`) écrivaient le titre et le message **en français**, figés dans la ligne `Notification`. L'interface des cinq clients est bilingue, mais une notification restait en français pour un lecteur en anglais.

Défaut trouvé au passage : les types de changement de planning n'avaient pas de libellé. Le titre en français affichait donc « Planning : Session Cancelled ».

## 2. Décision : décrire le texte, le rendre à la lecture

- Une notification système porte, dans une nouvelle colonne `Notification.text` (JSON), la **description** de son texte : une clé de `communication/texts.py` et ses paramètres. Exemple : `{"title": {"key": "attendance.late.title", "params": {"student": "Awa Ndiaye"}}}`.
- Le texte est rendu **à la lecture**, dans la langue demandée :
  - **REST :** l'en-tête `Accept-Language`, via `LocaleMiddleware` (ADR 0007) ;
  - **WebSocket :** la langue de la connexion. C'est `Accept-Language` à l'ouverture (clients natifs), ou `"language"` dans la trame `auth` (navigateurs). Les trames `notification` et `sync` sont rendues par chaque connexion.
- Les chaînes source sont en anglais (convention Django, ADR 0007). Le français est dans `locale/fr/LC_MESSAGES/django.po`, et le `.mo` reste versionné.
- Les libellés de statut utilisés dans une phrase passent par `pgettext` avec un contexte. Exemple : « Annulée » pour une convocation, « Annulé » pour un paiement.

## 3. Ce qui ne change pas

- **Les colonnes `title` / `message` restent remplies** avec le rendu français fait à la création. Les lignes antérieures (`text = {}`) et tout lecteur direct de la base les affichent comme avant. Le contrat d'API garde exactement les mêmes champs (`title`, `message`, `payload`…) : seule la langue du texte suit la demande.
- **Le `payload` (faits métier) est inchangé.** Il n'accueille pas la description du texte, car c'est un contrat que des tests vérifient à l'identique.
- **Les données métier sont insérées telles quelles :**
  - noms, références, montants (chaîne exacte du `Decimal`) ;
  - dates au format jj/mm/aaaa dans les deux langues ;
  - noms de plans, de périodes et de motifs de frais.
- **Ce que les personnes écrivent n'est jamais traduit :**
  - corps de message ;
  - sujet, description et commentaire d'une réclamation ;
  - titre et texte d'une annonce ou d'un sujet de forum.

  Ces textes sont passés à `notify()` en chaîne simple. Seul le préfixe système (« Message de », « Nouveau sujet : ») est traduit.
- **Immuabilité :** le déclencheur `comm_notification_guard` compare toute la ligne (`to_jsonb`). La nouvelle colonne est donc aussi figée que les autres (test).

## 4. Pourquoi une colonne plutôt qu'une préférence serveur

La langue est un **choix local de l'appareil** : une même personne peut utiliser deux appareils dans deux langues, et un appareil peut servir à plusieurs comptes. Stocker la langue sur le compte imposerait une seule langue à tous ses appareils. Rendre le texte à la lecture respecte chaque appareil sans rien stocker de plus sur la personne.

Migration : `communication.0005_notification_text`, un ajout de colonne avec `{}` par défaut, sans réécriture de données.

## 5. Notifications push : non couvertes

`notify()` alimente une file `NotificationDelivery` (`PENDING`) destinée à un futur service FCM, mais **aucun envoi push n'existe**. Il n'y a ni Firebase côté client, ni travailleur côté serveur. Les notifications ne sont donc bilingues que dans l'application (REST et temps réel).

Le futur service devra :
- connaître la langue de **chaque appareil**, enregistrée avec son jeton FCM ;
- rendre `texts.render(notification.text[...], langue)` au moment de l'envoi ;
- garder le rendu stocké en repli.

## 6. Clients

- **Desktop et mobile :** ils annoncent la langue de l'interface à l'ouverture du WebSocket. Changer de langue reconnecte la session temps réel si elle est ouverte ; une session fermée (déconnexion) n'est pas rouverte.
- **Mobile :** la liste des notifications est rechargée dans la nouvelle langue.
- **Desktop :** les pages sont reconstruites au changement de langue, ce qui les recharge.
