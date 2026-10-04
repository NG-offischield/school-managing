# ADR 0022 — Finance et paie sur le poste d'administration

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - pages PySide6 « Gestion → Finance » et « Gestion → Paie » ;
  - accès en lecture seule à la rémunération depuis la fiche enseignant ;
  - tableau de bord : un indicateur et un graphique financiers réels.
- **Hors périmètre :** communication desktop, Flutter, activation des comptes, packaging Windows.
- **Migrations :** aucune. Aucun nouveau modèle métier, aucun second mécanisme de paiement.

## 1. Clients minces des domaines existants

Le poste réutilise **strictement** Finance (ADR 0013) et Paie (ADR 0014). `services/finance.py` et
`services/payroll.py` vérifient seulement que les champs obligatoires sont remplis et qu'un montant est un
nombre ; tout le reste est décidé par le serveur :

- qui peut payer, l'issue du fournisseur, les imputations ;
- ce qui reste remboursable, l'idempotence ;
- le calcul de la paie, sa conformité avant approbation (409 `payroll_stale`), le paiement unique par la trésorerie.

## 2. Argent : Decimal, jamais float

Les montants arrivent en chaînes (`"60000.00"`) et sont lus en `Decimal` (`school_admin/money.py`).
`to_decimal(0.1)` lève une erreur : un float ne transporte jamais un montant. L'affichage se fait en
`1 250 000 XAF` (espace fine insécable). Les graphiques comptent des paiements ou des paies, pas des montants.

## 3. Finance

| Onglet | API |
|---|---|
| Vue d'ensemble | `GET admin/finance/dashboard/`, `GET admin/finance/treasury/` |
| Paiements | `GET finance/payments/` (paginé : statut, mode, période, recherche) ; `POST finance/payments/` ; `POST admin/finance/payments/{id}/refund/` |
| Factures | `GET finance/invoices/` ; `POST admin/finance/invoices/` ; `…/{id}/cancel/` ; `GET finance/students/{id}/obligations/` |
| Remboursements | `GET admin/finance/refunds/` (nouveau, lecture) |
| Wallets | `GET admin/finance/wallets/` (lecture seule, identifiants masqués `•••• 0001`) |
| Motifs | `GET/POST admin/finance/fee-types/` |

- **Paiement :**
  - en espèces au guichet, ou avec un wallet simulé **de l'administrateur connecté** : le serveur refuse tout autre wallet ;
  - l'issue est affichée telle que le serveur l'enregistre : réussi, refusé, fonds insuffisants, délai dépassé, erreur fournisseur ;
  - un échec est un résultat, pas une erreur.
- **Clé d'idempotence par intention de paiement :**
  - si le réseau échoue et que l'issue est inconnue, la nouvelle tentative réutilise la même clé ;
  - le serveur rejoue alors le premier envoi (200, `replayed`), sans second débit.
- **Remboursement :** transaction inverse ; le paiement d'origine reste dans l'historique.

## 4. Paie

Parcours : Période → Calculer → Préparer → Vérifier → Approuver → Payer.

| Onglet | API |
|---|---|
| Périodes | `GET/POST admin/payroll/periods/`, `POST admin/payroll/calculate/`, `…/periods/{id}/close/` |
| Paies | `GET admin/payroll/` (période, statut, type, employé), `GET admin/payroll/{id}/` (toutes les versions de lignes), `…/approve/`, `…/pay/`, `…/cancel/` |
| Corrections | `GET/POST admin/payroll/adjustments/` |

- **Versement :** en espèces / hors système, ou sur le wallet de l'employé. Le poste ne propose que les wallets
  au nom de l'employé ; le serveur l'impose de toute façon (403 sinon).
- **Second paiement :** refusé par le serveur (409 `payroll_already_paid`), et ce refus est affiché.

## 5. Fiche enseignant

Le bouton « Rémunération et paies… » ouvre une fenêtre en lecture seule. Elle montre, pour l'année courante :

- la rémunération programmée, acquise et payée (`admin/payroll/remuneration/`) ;
- les paies de l'enseignant ;
- le nombre de séances validées.

Elle n'offre aucune action. Les permissions de l'API Paie s'appliquent : un refus est affiché, jamais contourné.

## 6. Ajouts backend (lecture seule, sans migration)

- filtres `search`, `date_from`, `date_to` et `payment_method` sur `finance/payments/` et `finance/invoices/` ;
  ils restreignent seulement ce que l'appelant voit déjà ;
- `GET admin/finance/refunds/` (ADMIN) : remboursement avec son paiement d'origine ;
- `owner_name` sur les wallets ;
- `employee` (id du profil employé) sur la fiche enseignant ;
- `?employee=` sur `admin/payroll/` et `?teacher=` sur `admin/payroll/check-ins/`.

## 7. Tableau de bord

- Indicateur « Paies versées » : somme `Decimal` des montants approuvés des paies payées.
- Carte « Finances » : paiements par résultat et paies par étape, en nombres.
- Aucun chiffre n'est inventé.

## 8. Écran

- Toutes les fenêtres sont des `FormDialog` (couvertes par `test_responsive.py`).
- Sur une page étroite (1024×768), les colonnes secondaires se masquent (`narrow_hidden`) ; le détail reste
  accessible.
- Les filtres ont des libellés courts : « Statut : tous », « Période : toutes ».

## 9. Identité

Les reçus et les bulletins de paie restent aux couleurs de l'**école** (`SchoolBranding`), jamais de School
Managing : l'E2E vérifie un reçu PDF réel.
