# ADR 0013 — Finance : factures, paiements simulés, portefeuilles, trésorerie, remboursements

- **Statut :** accepté — 2026-10-03
- **Périmètre :** nouvelle app `finance` avec les modèles `FeeType`, `FeeSchedule`, `Invoice`, `InvoiceLine`, `SimulationTreasury`, `Wallet`, `WalletTransaction`, `TreasuryTransaction`, `Payment`, `PaymentAllocation` et `PaymentRefund`. Elle comprend aussi un fournisseur de paiement simulé et l'indicateur de solvabilité du scan QR.
- **Hors périmètre :** paie, FCM, messagerie, PDF (reçus et factures imprimables), PySide6, vrai fournisseur mobile money et déploiement.

## 1. Argent

- Le type est `Decimal` partout (`DecimalField(18, 2)`), sans jamais de `float`. Les services refusent plus de 2 décimales.
- Dans l'API, les montants sortent en **chaînes** (`"60000.00"`), y compris dans le tableau de bord et les soldes.
- La devise est celle de l'école (XAF par défaut), contrôlée par une CHECK.

## 2. Comptabilité en grand livre (append-only)

Une seule fonction, `services._post()`, fait bouger l'argent :

1. elle verrouille la ligne du compte (`Wallet` ou `SimulationTreasury`, `SELECT … FOR UPDATE`) ;
2. elle écrit une ligne de grand livre (`WalletTransaction` / `TreasuryTransaction`) avec `balance_before` et `balance_after` ;
3. elle met à jour le solde.

PostgreSQL garantit :
- l'arithmétique `after = before ± amount` (CHECK) ;
- des soldes jamais négatifs (CHECK) ;
- l'immutabilité des grands livres, allocations et remboursements : le trigger `finance_append_only` interdit UPDATE et DELETE.

Le paiement lui-même n'est jamais supprimé. Une fois sorti de PENDING, le trigger `finance_payment_guard` ne laisse évoluer que la progression des remboursements : `refunded_amount` en hausse, et SUCCEEDED → PARTIALLY_REFUNDED → REFUNDED. Tout autre changement est refusé, même en SQL brut.

## 3. Fournisseur de paiement : interface + simulation déterministe

`providers.py` expose `charge(wallet, amount, reference) → ProviderResult(status, provider_reference, message)`.

| Fournisseur | Règle déterministe |
|---|---|
| `SIMULATION_WALLET` (méthode WALLET) | wallet BLOCKED → DECLINED ; `wallet.simulation_behavior` DECLINE / TIMEOUT / PROVIDER_ERROR → ce résultat ; solde < montant → INSUFFICIENT_FUNDS ; sinon SUCCEEDED |
| `CASH` (guichet, admin uniquement) | SUCCEEDED |

Brancher un vrai fournisseur (Orange Money, MTN MoMo) revient à ajouter une classe dans `PROVIDERS`. Avec `moves_simulated_wallet = False`, seule la trésorerie de l'école est créditée : l'argent du payeur reste chez le fournisseur. Les modèles et l'API ne changent pas. Un fournisseur **asynchrone** (callback) laissera le paiement en PENDING, ce que le modèle et le trigger acceptent déjà. Le callback et la vérification de signature arriveront avec ce fournisseur.

## 4. Statuts et résultats

- Les statuts de `Payment` sont : PENDING, SUCCEEDED, DECLINED, INSUFFICIENT_FUNDS, TIMEOUT, PROVIDER_ERROR, CANCELLED, PARTIALLY_REFUNDED et REFUNDED.
- Un échec du fournisseur est un **résultat**, pas une exception. Le paiement est enregistré (avec `completed_at` et `failure_reason`) et audité (`PAYMENT_FAILED`). L'API répond 201 avec ce statut.
- Un échec ne déplace pas d'argent et ne crée ni allocation ni ligne de grand livre.
- CANCELLED est réservé au futur fournisseur asynchrone (abandon d'un paiement PENDING).

## 5. Idempotence et double soumission

Le client génère une `idempotency_key` par intention de paiement, transmise dans l'en-tête `Idempotency-Key` ou dans le champ du corps.

| Cas | Réponse |
|---|---|
| même clé + même requête (empreinte SHA-256 de élève, montant, méthode, wallet, factures, motif) | le paiement existant, `replayed: true`, HTTP 200, **sans nouveau débit**, quel que soit son statut (un échec rejoué reste un échec ; réessayer = nouvelle clé) |
| même clé + requête différente | 409 `CONFLICT`, règle `idempotency_conflict` |
| deux soumissions simultanées | UNIQUE(school, idempotency_key) : la perdante prend une `IntegrityError`, relit et rejoue |
| deux paiements différents simultanés sur un même wallet | le wallet est verrouillé **avant** la décision du fournisseur : l'un réussit, l'autre est INSUFFICIENT_FUNDS enregistré |

Les clés sont propres à chaque école : la même clé dans deux écoles donne deux paiements.

## 6. Factures et allocations

- La numérotation est `F{aa}-{nnnnnn}` par école et par année. Le verrou sur la ligne `School` empêche deux factures d'obtenir le même numéro.
- La ligne de facture respecte la CHECK `total = round(quantité × prix, 2)`. La facture respecte `balance_due = total − amount_paid`, PAID ⇒ solde nul, et CANCELLED ⇒ rien de payé.
- Un paiement est réparti sur les factures choisies, **la plus ancienne échéance d'abord**. Le surpaiement est refusé (409 `amount_exceeds_balance`). Sans facture, un motif (`FeeType`) est obligatoire.
- `generate_invoices(classe)` facture les échéanciers actifs applicables (année, niveau ou classe) aux élèves inscrits. Elle est idempotente.
- L'annulation n'est possible que sur une facture sans paiement (409 `invoice_has_payments`). Il faut d'abord rembourser.

## 7. Remboursement = transaction inverse

`refund_payment` est réservé à l'administration, avec un motif obligatoire, pour un montant ≤ reste remboursable. Il :

1. crée `PaymentRefund`, lié au paiement, avec une `inverse_transaction_reference` ;
2. écrit les lignes inverses : DÉBIT trésorerie, et CRÉDIT wallet pour la simulation ;
3. crée des **allocations négatives** liées au remboursement, en annulant la dernière allocation d'abord, et recalcule les factures ;
4. fait progresser `refunded_amount` et le statut du paiement.

Rien n'est supprimé ni réécrit. Une FK composite garantit qu'une allocation de remboursement appartient au même paiement que son remboursement.

## 8. Droits

| Acteur | Droits |
|---|---|
| ADMIN / SUPER_ADMIN de l'école | tout : motifs, échéanciers, factures, encaissement CASH, remboursements, wallets simulés, trésorerie, tableau de bord |
| payeur | membre dont le profil parent a un lien ACTIF + VÉRIFIÉ avec `can_pay` vers l'élève ; paie uniquement avec **son propre** wallet (FK composite `(wallet, payer) → wallet(id, owner)`) |
| lecture des finances d'un enfant | lien ACTIF + VÉRIFIÉ avec `can_view_financial_data` ; un payeur sans ce droit ne voit que les paiements qu'il a faits |
| enseignant, personnel, gardien, parent non lié ou non vérifié | aucun droit financier : listes vides, 404 sur les ids |

Codes de retour :
- un enfant visible mais sans droit financier → 403 ;
- un id d'une autre école, même valide, ou hors périmètre → 404 ;
- un admin d'une autre école n'est personne ici.

## 9. Isolation

- 32 FK composites (`(fk, school) → cible(id, school)`, plus les invariants payer / wallet, élève / facture / paiement et remboursement / paiement) : 145 au total.
- Toutes les recherches de l'API passent par `scope_to_current_school`.
- La clé d'idempotence est cherchée **dans l'école**.

## 10. Audit

Les actions suivantes sont écrites dans `AuditLog`, dans la transaction métier :

| Couche | Actions |
|---|---|
| BUSINESS | `PAYMENT_SUCCEEDED`, `PAYMENT_FAILED`, `PAYMENT_REFUNDED`, `INVOICE_ISSUED`, `INVOICE_CANCELLED`, `WALLET_CREATED`, `WALLET_FUNDED`, `TREASURY_CREDITED` |
| ADMINISTRATIVE | `FEE_TYPE_CREATED`, `FEE_SCHEDULE_CREATED` |

## 11. Solvabilité au scan QR (spec §7)

La réponse du scan contient `solvency` : `UP_TO_DATE` ou `OVERDUE` (une facture échue non soldée existe). Elle ne contient jamais de montant.

## 12. Écarts par rapport à la spec — à valider

1. `Invoice.payer` est **facultatif** : tout parent vérifié avec `can_pay` peut régler la facture d'un enfant. La spec lie la facture à un payeur.
2. **`PaymentAllocation`** (paiement ↔ facture, montants signés) est ajouté pour permettre les paiements multi-factures et les remboursements partiels traçables. La spec rattache le paiement à une seule facture.
3. **`SimulationBehavior`** est un champ du wallet simulé, pour rendre les issues reproductibles. Il est sans effet pour un vrai fournisseur.
4. Les wallets simulés sont **créés et alimentés par l'administration** en V1. Il n'existe ni auto-inscription d'un wallet par le parent ni dépôt réel.
5. Les reçus PDF, les relances et les notifications de paiement sont reportés (phases PDF / communication).
