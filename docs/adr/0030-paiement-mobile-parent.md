# ADR 0030 — Paiement mobile du parent

- **Statut :** accepté — 2026-10-05
- **Périmètre :** paiement d'une facture depuis l'application parent, sur l'API Finance existante (ADR 0013), et ouverture du reçu PDF.
- **Hors périmètre :** nouveau système financier, vrai fournisseur de mobile money, dépôt sur le portefeuille par le parent, packaging.

## 1. Rien de nouveau côté serveur

L'application n'utilise que les routes existantes :

| Besoin | Route |
|---|---|
| droits + factures ouvertes | `GET /finance/students/{id}/obligations/` (`can_pay`, `balance_due`) |
| détail d'une facture | `GET /finance/invoices/{id}/` |
| portefeuilles du payeur | `GET /finance/wallets/` (les siens uniquement) |
| paiement | `POST /finance/payments/` (`WALLET`, `idempotency_key`) |
| historique | `GET /finance/payments/?student=` |
| reçu | `GET /payments/{id}/receipt.pdf/` |

Aucune migration ni nouvel endpoint : le paiement, l'idempotence, les droits, l'isolation et les remboursements restent ceux de l'ADR 0013.

## 2. Le téléphone ne décide de rien

- **Montant :** le paiement porte sur **une** facture. Le montant envoyé est sa chaîne `balance_due`, telle que le serveur l'a donnée. Il n'y a aucun champ de saisie. Le serveur refuse un montant falsifié (409 `amount_exceeds_balance`).
- **Droit de payer :** c'est la réponse `can_pay` du serveur, redemandée à l'ouverture de l'écran de paiement. Sans ce droit, les montants restent visibles, sans action de paiement.
- **Résultat :** c'est le statut enregistré par le serveur (`SUCCEEDED`, `DECLINED`, `INSUFFICIENT_FUNDS`, `TIMEOUT`, `PROVIDER_ERROR`), affiché tel quel avec le motif du fournisseur. Un échec ne déplace pas d'argent (ADR 0013 §4).
- **Codes d'erreur :**
  - élève d'une autre école ou inconnu, facture d'une autre famille : 404 ;
  - élève de l'école sans droit de payer : 403 (`can_pay`) ;
  - facture réglée, montant changé, clé réutilisée : 409, avec la règle expliquée.

## 3. Idempotence (`PaymentFlow`)

Une **intention** de paiement porte une clé `mob-<128 bits aléatoires>`, créée une seule fois.

| Situation | Clé | Effet |
|---|---|---|
| réponse perdue : réseau, délai client, 5xx | **gardée** | « Réessayer » rejoue la même demande ; le serveur renvoie le paiement existant (`replayed`), sans second débit |
| réponse définitive : succès, échec enregistré, 4xx | abandonnée | une nouvelle tentative est une nouvelle intention, avec une nouvelle clé |
| double appui, deuxième envoi pendant le premier | — | ignoré : une seule requête |
| changement de portefeuille pendant une intention non résolue | — | interdit, car même clé avec une autre requête = 409 |

Pendant le paiement, l'écran ne peut pas être quitté.

## 4. Reçu

Le PDF est celui du serveur : identité et branding de l'**établissement** (`school_block`, `SchoolBranding`). Le module documents interdit déjà le nom du logiciel (test `test_planning_breaks_branding`).

Le fichier est enregistré dans le dossier privé de l'application, puis ouvert par `school_core` (`openDocument`). La couche Kotlin le copie dans `cache/shared/`, seul dossier exposé par un `FileProvider` propre au projet (non exporté, droits de lecture temporaires), et lance `ACTION_VIEW`. Sans visionneuse, le reçu reste enregistré et l'application le dit.

`open_file` 4.0.0 a été écarté : son `FileProvider` expose la racine du système de fichiers (`root-path ""`) et il force `requestLegacyExternalStorage`.

## 5. Vérification

- **Tests Flutter :** 17 tests de paiement (services, écrans, sécurité, idempotence, réseau, reçu, petit écran). Le faux backend reproduit les règles du serveur.
- **Test réel** (`payment_live_test.dart`) contre la base de test, **via l'IP LAN du PC** :
  - montant falsifié : 409 ;
  - portefeuille vide : `INSUFFICIENT_FUNDS` sans débit ;
  - même clé rejouée : un seul paiement, un seul débit ;
  - reçu PDF et historique ;
  - double paiement : 409 ;
  - élève non rattaché : 404 et 403.
- **Non vérifié :** le parcours sur le Pixel 7a (aucun appareil branché).
