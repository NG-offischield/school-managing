# ADR 0017 — Années scolaires, niveaux et tableau de bord

- **Statut :** accepté — 2026-10-04
- **Périmètre :** administration des années scolaires et des niveaux (services `academics`, API `structure_api.py`), agrégats en lecture seule du tableau de bord (`core/dashboard_api.py`), écrans PySide6 correspondants.
- **Hors périmètre :** élèves, enseignants, planning, présences, finance, paie, communication, documents (aucun écran nouveau pour ces domaines).
- **Migrations :** aucune. Les modèles `AcademicYear` et `Level` et leurs contraintes PostgreSQL existants suffisent.

## 1. Années scolaires

Cycle de vie : **planifiée** (création) → **en cours** (dès qu'elle devient courante) → **clôturée**. Une année n'est jamais supprimée.

| Action | Règle | Code |
|---|---|---|
| créer | nom obligatoire, unique dans l'école (insensible à la casse) | 409 `duplicate_year_name` |
| créer / modifier | fin > début | 400 `invalid_dates` |
| créer / modifier | pas de chevauchement avec une autre année de l'école | 409 `year_overlap` |
| modifier | seulement si l'année est ouverte (planifiée ou en cours) | 400 `year_closed` |
| modifier les dates | les périodes, présences journalières et séances déjà datées doivent rester dans l'intervalle | 409 `year_content_outside_dates` |
| définir comme courante | refusé si clôturée ; l'ancienne courante reste « en cours » mais n'est plus proposée par défaut | 400 `year_closed` |
| clôturer | refusé pour l'année courante (en désigner une autre d'abord) | 409 `year_is_current` |
| clôturer | refusé tant que des élèves y sont inscrits (inscriptions ACTIVE) | 409 `year_has_active_enrollments` |

PostgreSQL reste le dernier rempart : nom unique, contrainte d'exclusion sur les dates, une seule année courante, année courante = ACTIVE. Les services vérifient ces règles avant l'écriture pour renvoyer un message clair.

Une année clôturée est figée par les services existants : classes, inscriptions, cours et présences y sont refusés.

Endpoints :

- `GET/POST /academic-years/` ;
- `GET/PATCH /academic-years/{id}/` ;
- `POST /academic-years/{id}/set-current/` et `POST /academic-years/{id}/close/`.

Les listes ajoutent `class_count` (classes actives de l'année).

## 2. Niveaux

- **Code :** obligatoire, en majuscules, unique dans l'école (409 `duplicate_code`), non modifiable après création (400 `code_immutable`).
- **Champs modifiables :** nom, cycle (texte libre, ADR 0008), ordre, préfixe des classes, visibilité publique.
- **Désactivation :** refusée tant qu'une classe active d'une année ouverte utilise le niveau (409 `level_in_use`). La réactivation n'a pas de condition. Une classe ne peut pas être créée sur un niveau inactif (règle existante `level_inactive`).

Endpoints :

- `GET/POST /levels/` ;
- `GET/PATCH /levels/{id}/` ;
- `POST /levels/{id}/deactivate/` et `POST /levels/{id}/reactivate/`.

La liste ajoute `class_count`, le nombre de classes qui bloquent la désactivation.

Pour toutes ces écritures :

- rôle ADMIN ou SUPER_ADMIN de l'école courante, sinon 403 ;
- un identifiant d'une autre école donne 404 ;
- chaque écriture est journalisée dans l'AuditLog, couche ADMINISTRATIVE.

## 3. Agrégats du tableau de bord

Aucune API n'exposait ces séries. Les calculer dans le client aurait obligé à télécharger toutes les présences et toutes les inscriptions. Trois endpoints en lecture seule (ADMIN/SUPER_ADMIN), séparés pour que chaque graphique puisse échouer ou être vide sans bloquer les autres :

| Endpoint | Contenu |
|---|---|
| `GET /admin/dashboard/attendance-trend/?days=14` | comptes par statut pour chaque jour ayant des présences journalières |
| `GET /admin/dashboard/enrollments/?academic_year=` | élèves inscrits (ACTIVE) par niveau et par classe active, effectif inscrit à la fin de chaque mois ; année courante par défaut |
| `GET /admin/dashboard/activity/?limit=10` | dernières actions de la couche ADMINISTRATIVE : action, type, libellé, auteur, date |

Seuls des comptes et des libellés de lignes de configuration (nom ou code) sortent du serveur : aucun nom d'élève, aucun contenu d'audit.

## 4. Client PySide6

- **Navigation :** Gestion académique contient, dans l'ordre, Années scolaires, Niveaux, Catégories pédagogiques, Matières, Classes (Ctrl+1 … Ctrl+6).
- **Pas de règle métier dans le poste :** il vérifie seulement que les champs obligatoires sont remplis. Il désactive une action impossible et en donne la raison (année clôturée, année déjà courante). Le serveur décide ; ses refus sont traduits par `messages.RULE_MESSAGES`.
- **Tableau de bord :** indicateurs existants, plus l'indicateur « Encaissements » (`/admin/finance/dashboard/`). Les graphiques sont dessinés avec QPainter :
  - courbe des présences ;
  - barres des élèves par niveau ou par classe ;
  - courbe de l'évolution des effectifs ;
  - liste de l'activité récente.

  Chaque graphique gère quatre états : chargement, données, aucune donnée, erreur. Il se redessine à sa taille et affiche une info-bulle par point. Aucune valeur n'est inventée ni interpolée.

## 5. Règle UI globale : dialogues et petits écrans

Tout dialogue doit rester entièrement utilisable sur 1280×720 (et 1366×768, 1024×768). `FormDialog` impose :

- **Structure :** en-tête fixe, formulaire dans une `QScrollArea`, pied fixe avec la note « champ obligatoire », la raison d'un bouton désactivé et les boutons. La barre de défilement appartient au formulaire.
- **Taille :** largeur raisonnable (environ 520 à 560 px). La hauteur est celle du formulaire, bornée par l'écran moins une marge ; au-delà, le formulaire défile.
- **Largeur des champs selon la donnée :** `short` (codes, nombres, dates), `medium` (noms), `long` (texte libre).
- **Colonnes :** des champs peuvent être côte à côte (`beside=True`) ; ils repassent sur une colonne quand le dialogue est étroit. Une longue entrée de liste n'élargit pas le formulaire : la liste ouverte l'affiche en entier et l'info-bulle la répète.
- **Clavier :** Tab suit l'ordre des champs et fait défiler jusqu'au champ actif. Entrée enregistre, Échap ferme.

Des tests (`desktop/tests/test_responsive.py`) vérifient chaque dialogue aux tailles d'écran citées. Tout nouveau dialogue doit passer par `FormDialog`.
