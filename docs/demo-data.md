# Jeu de données de démonstration

Ce document décrit le jeu de démonstration : un établissement fictif complet pour tester et présenter School Managing (administration, applications parent, paiement mobile).

- **Source de vérité :** `backend/apps/demo/dataset.py`, des données déclaratives.
- **Création :** `backend/apps/demo/seed.py`, qui n'appelle que les **services du domaine**, sans SQL ni fixture JSON.
- **Commande :** `manage.py seed_demo`.
- **Tests :** `backend/tests/test_demo_seed.py`.

> **Aucun vrai mot de passe ici.** Tous les comptes de démonstration reçoivent le mot de passe passé dans la variable `DEMO_PASSWORD` **au moment où le seed les crée**. Il n'est ni stocké dans le dépôt, ni affiché, ni journalisé. Les adresses utilisent le domaine réservé `.test`.

## Charger, compléter, recharger

```powershell
# Première fois : choisir localement un mot de passe de démonstration (validé par les règles du serveur).
$env:DEMO_PASSWORD = Read-Host "Mot de passe des comptes de démonstration"
docker compose exec -e DEMO_PASSWORD web python manage.py seed_demo
Remove-Item Env:DEMO_PASSWORD

# Relancer à tout moment : complète ce qui manque, ne duplique rien.
docker compose exec web python manage.py seed_demo

# Après une démonstration : remettre les wallets à leurs soldes de départ.
docker compose exec web python manage.py seed_demo --refill-wallets
```

- **Idempotence (upsert) :** chaque objet est d'abord cherché par sa clé naturelle stable :
  - code d'établissement, e-mail, matricule ;
  - identifiant de wallet ;
  - code de motif, et (élève, motif) pour une facture.

  Les paiements du seed ont des **clés d'idempotence fixes** : une seconde exécution les rejoue sans nouveau débit.
- **Tout ou rien :** le seed tourne dans une seule transaction.
- **Pas de « reset » :** les tables Finance sont en ajout seul (trigger `finance_append_only`, ADR 0013). Rien n'est supprimé ni réécrit. Pour repartir de zéro, il faut utiliser une base vide, par exemple `db_test`.
- **Recharge :** `--refill-wallets` crédite chaque wallet de la différence avec son solde cible, par une écriture `FUNDING` normale, donc tracée. Un wallet au-dessus de sa cible n'est pas modifié : Finance n'a pas de retrait.
- **Production :** refusé avec `config.settings.production`.
- **Établissement séparé :** le seed crée l'établissement `DEMO` à côté des autres. Il ne touche à aucune autre école, ce qui permet de le charger aussi sur une base de développement.

## Comment l'argent entre dans un wallet aujourd'hui

1. **Ouverture :** l'administration ouvre le wallet simulé du parent avec `finance.create_wallet`, ou `POST /admin/finance/wallets/`. Le propriétaire est l'adhésion du parent dans l'école.
2. **Alimentation :** elle l'alimente avec `finance.fund_wallet`, ou `POST /admin/finance/wallets/{id}/fund/ {amount}`. Le service passe par `_post` :
   - verrou de la ligne ;
   - écriture `WalletTransaction` `FUNDING`/`CREDIT` avec `balance_before` et `balance_after` ;
   - mise à jour du solde.

   PostgreSQL vérifie l'arithmétique et interdit un solde négatif.
3. **Paiement réussi :**
   - `DEBIT` du wallet (`PAYMENT`) ;
   - `CREDIT` de la trésorerie de l'école (`SimulationTreasury`, une par école, ledger `TreasuryTransaction`) ;
   - `PaymentAllocation` vers la facture, qui est recalculée.

   Un échec (refus, fonds insuffisants…) est enregistré sans aucun mouvement.
4. **Fonds de départ de l'école :** `finance.credit_treasury` (`FUNDING`).

Le « wallet de l'établissement » est donc la **trésorerie simulée** existante : pas de second système.

## Établissement et administration

| | Valeur |
|---|---|
| Code | `DEMO` |
| Nom | Collège de Démonstration Les Manguiers (Douala) |
| Administrateur (SUPER_ADMIN) | identifiant `demo.admin`, e-mail `admin@demo-ecole.test`, Clarisse Ngo Bassa |
| Année | l'année scolaire en cours (1er sept. → 31 juil.), courante |
| Classes | `6e A` (niveau 6E), `3e B` (niveau 3E) |
| Trésorerie | 2 000 000 XAF de fonds de départ, plus les encaissements |

## Élèves

Les champs sont ceux du modèle `people.Student`, rien d'autre.

| Clé | Matricule | N° d'inscription | Élève | Sexe | Naissance | Lieu | Classe | Statut |
|---|---|---|---|---|---|---|---|---|
| S1 | DEMO-2026-001 | INS-DEMO-001 | Léa Mbarga | F | 12/03/2014 | Douala | 6e A | ACTIVE |
| S2 | DEMO-2026-002 | INS-DEMO-002 | Junior Ekotto | M | 03/07/2014 | Yaoundé | 6e A | ACTIVE |
| S3 | DEMO-2026-003 | INS-DEMO-003 | Aïcha Bello | F | 21/11/2013 | Garoua | 6e A | ACTIVE |
| S4 | DEMO-2026-004 | INS-DEMO-004 | Paul Nkoulou | M | 30/01/2011 | Douala | 3e B | ACTIVE |
| S5 | DEMO-2026-005 | INS-DEMO-005 | Inès Nkoulou | F | 08/09/2014 | Douala | 6e A | ACTIVE |

## Parents, enfants et droits

Chaque lien passe par le vrai parcours (ADR 0026) :
1. inscription, puis validation par l'école ;
2. demande de rattachement (matricule + date de naissance + pièce fictive) ;
3. contrôle de la pièce, puis désignation par l'élève ;
4. validation avec les droits.

| Parent | Compte | Enfant(s) | Lien | Droits |
|---|---|---|---|---|
| A — Awa Mbarga | `parent.a@demo-ecole.test` | S1 | mère | voir les finances, payer, notifications, réclamations |
| B — Samuel Ekotto | `parent.b@demo-ecole.test` | S2 | père | idem |
| C — Mariam Bello | `parent.c@demo-ecole.test` | S3 | mère | idem |
| D — Roger Nkoulou | `parent.d@demo-ecole.test` | S4, S5 | père | idem |

## Factures (XAF)

| Clé | Élève | Motif | Montant | Échéance | État après le seed |
|---|---|---|---|---|---|
| F-S1-TUITION | S1 | Frais de scolarité | 75 000 | J+20 | à payer |
| F-S2-TUITION | S2 | Frais de scolarité | 75 000 | J+20 | à payer |
| F-S3-CANTEEN | S3 | Cantine | 25 000 | J+15 | à payer |
| F-S4-EXAM | S4 | Frais d'examen | 15 000 | J−10 | **payée** (espèces au guichet, payeur D) : reçu disponible |
| F-S4-TRANSPORT | S4 | Transport scolaire | 30 000 | J−5 | **partiellement payée** (10 000 au guichet, reste 20 000) : échéance dépassée |
| F-S5-TUITION | S5 | Frais de scolarité | 75 000 | J+45 | à payer |

J = jour du premier chargement. Les numéros de facture (`F26-000001`…) sont attribués par Finance.

## Wallets (Finance `Wallet`, simulation)

| Parent | Fournisseur : identifiant | Solde de départ |
|---|---|---|
| A | FAKE_ORANGE : 690000101 | 100 000 |
| B | FAKE_MTN : 670000202 | 1 000 |
| C | FAKE_ORANGE : 690000303 | 25 000 (exactement la facture F-S3-CANTEEN) |
| D | FAKE_MTN : 670000404 | 500 000 |

## Scénarios et résultats attendus

Ils se jouent depuis l'application parent (Finance → facture → « Payer ») ou par l'API `POST /finance/payments/`. Chacun est vérifié par `tests/test_demo_seed.py`.

| | Action | Résultat attendu |
|---|---|---|
| **A** | Parent A paie F-S1-TUITION (75 000) | `SUCCEEDED` ; wallet A 100 000 → 25 000 ; trésorerie +75 000 ; facture **PAID** ; reçu PDF disponible |
| **B** | Parent B paie F-S2-TUITION (75 000) avec 1 000 | `INSUFFICIENT_FUNDS` enregistré ; wallet B reste 1 000 ; trésorerie inchangée ; facture toujours à payer ; aucun paiement réussi |
| **C** | Parent C paie F-S3-CANTEEN (25 000) avec 25 000 | `SUCCEEDED` ; wallet C = **0** ; facture PAID |
| **D** | Parent A renvoie **la même requête avec la même clé d'idempotence** | réponse 200 `replayed: true` avec le paiement d'origine ; une seule transaction, un seul débit, un seul encaissement |
| **E** | Parent A tente de payer pour S2 (même école, pas son enfant) | **403** |
| **E bis** | … pour un élève d'une **autre école** (ou un identifiant inconnu) | **404** |

Après la démonstration, `seed_demo --refill-wallets` remet A à 100 000 et C à 25 000. Les factures payées le restent : l'historique est immuable.

## Créer soi-même un élève : la méthode canonique

Le seul chemin est le service **`people.services.admin_create_student`**. Il contrôle les champs obligatoires, l'unicité des numéros et la classe, enregistre l'audit `STUDENT_CREATED`, et inscrit l'élève dans la même transaction. Trois façons de l'appeler :

1. **Poste d'administration (PySide6)** : écran Élèves → « Nouvel élève ».
2. **API** : `POST /api/v1/students/` (administrateur de l'école) :

   ```json
   {
     "student_number": "DEMO-2026-006", "registration_number": "INS-DEMO-006",
     "first_name": "Nadia", "last_name": "Fouda", "date_of_birth": "2014-05-02", "sex": "F",
     "birth_place": "Kribi", "enrollment": {"school_class": "<id de la classe 6e A>"}
   }
   ```
3. **Jeu de démonstration** : ajouter une entrée dans `STUDENTS` de `apps/demo/dataset.py`, puis relancer `seed_demo`. Seul le nouvel élève est créé.

D'où viennent les rattachements :

1. **Données :** `dataset.STUDENTS`, ou le formulaire / le JSON ci-dessus.
2. **Injection :** `admin_create_student(school, actor=admin, enrollment=…, **champs)`.
3. **Classe :** `enrollment={"school_class": …}` crée la `StudentEnrollment` de l'année de la classe (`admin_enroll_student`). Sans cela, on inscrit plus tard avec `POST /students/{id}/enrollments/`.
4. **Établissement :** c'est celui de l'administrateur appelant. L'API résout l'école de la session, et les numéros sont uniques **par école**.
5. **Lien parent :** le parent s'inscrit dans l'application, l'école valide, le parent demande le rattachement (matricule + date de naissance + pièce), l'école contrôle la pièce, l'élève confirme, puis l'école approuve avec les droits (`can_pay`, `can_view_financial_data`…). Pour le seed, il suffit d'ajouter l'enfant dans `children` du parent dans `dataset.PARENTS`.
6. **Facture :** `finance.issue_invoice(élève, lignes, échéance)`, ou `POST /admin/finance/invoices/`, ou par échéancier de classe (`generate_invoices`). Pour le seed, il suffit d'ajouter une entrée dans `dataset.INVOICES`.

## Recharger un wallet à la main (hors seed)

`POST /admin/finance/wallets/{id}/fund/ {"amount": "50000"}`, en administrateur, ou `finance.fund_wallet(wallet, montant, actor=admin)`. C'est toujours une écriture `FUNDING` tracée dans le grand livre du wallet.
