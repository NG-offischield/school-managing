# ADR 0010 — Administration du catalogue pédagogique et journal d'audit

- **Statut :** accepté — 2026-10-03

## Constat de départ

- `PedagogicalCategory` et `Subject` n'étaient exposés qu'en lecture.
- `create_subject` ne vérifiait ni l'acteur, ni que la catégorie était active, ni qu'elle appartenait à la même école. Seule la clé composite PostgreSQL bloquait ce dernier cas.

Le futur client PySide6 n'avait donc aucun moyen d'administrer le catalogue.

## Décisions

1. **Services d'administration** (`apps/academics/services.py`) : `create_category`, `update_category`, `set_category_active`, `create_subject`, `update_subject`, `set_subject_active`. Chacun :
   - exige ADMIN ou SUPER_ADMIN **dans l'école de la donnée** ;
   - vérifie que les références (catégorie, échelle) sont de la même école et actives ;
   - écrit un `AuditLog` (couche ADMINISTRATIVE) dans la même transaction.
2. **`code` immuable.** Il est normalisé en majuscules et unique par école ; c'est l'identifiant stable des clients, des règles de compatibilité et des imports. Le nom, la description, la catégorie d'une matière, son type, son échelle par défaut et sa visibilité restent modifiables.
3. **Jamais de suppression.**
   - Les FK sont en `PROTECT` en base, et il n'existe aucun endpoint DELETE : on désactive, puis on peut réactiver.
   - Une catégorie utilisée par une matière **active** ne peut pas être désactivée (409 `category_in_use`).
   - Une matière enseignée dans un cours actif d'une année PLANNED ou ACTIVE ne peut pas être désactivée (409 `subject_in_use`).
   - Réactiver une matière exige que sa catégorie soit active.
   - `create_course` refuse une matière ou une catégorie inactive, en relisant leur état en base plutôt qu'en faisant confiance à l'objet transmis.
4. **Une seule catégorie par matière** : pas de relation ManyToMany. L'enseignement transversal reste géré par `SubjectCompatibilityRule` et les dérogations.
5. **API pour le client PySide6** (`apps/academics/catalog_api.py`) :
   - lecture pour tous les membres, avec `?search=`, `?active=`, `?category=`, `?subject_type=` et la pagination (`page_size` jusqu'à 100) ;
   - écriture par `POST`, `PATCH`, `.../deactivate/` et `.../reactivate/` ;
   - la catégorie est toujours transmise **par son id**, résolu dans l'école courante (404 sinon) ; un libellé libre est refusé (400).
6. **Codes de conflit.** `duplicate_code`, `category_in_use` et `subject_in_use` renvoient 409 `CONFLICT` ; les autres règles métier renvoient 400 `BUSINESS_RULE_VIOLATION`.

## `AuditLog` (spec §4.10)

- Nouvelle app `audit`. Les champs sont ceux de la spec, et l'audit est écrit **dans** la transaction métier : il est annulé avec elle.
- Couches utilisées : BUSINESS et ADMINISTRATIVE. La couche SECURITY de la spec est assurée par `SecurityEvent`, qui doit survivre aux rollbacks (ADR 0005). C'est un **écart assumé** par rapport à la spec, qui place les trois couches dans `AuditLog`.
- **Ajout seul** : un trigger PostgreSQL refuse DELETE et UPDATE. Seule exception : la mise à NULL de `school` ou `actor` (`SET_NULL`), pour que l'historique survive à la suppression d'une référence.
