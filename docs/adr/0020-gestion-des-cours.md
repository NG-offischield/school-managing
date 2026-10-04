# ADR 0020 — Gestion des cours

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - administration des cours (`gradebook.services`, `gradebook/course_api.py`) ;
  - page PySide6 « Gestion académique → Cours ».
- **Hors périmètre :**
  - le planning, qui n'est pas refait : il utilise les cours tels quels ;
  - finance, paie, activation du compte enseignant.
- **Migrations :** aucune.

## 1. Modèle

`Course` reste **l'unique** relation pédagogique : matière + enseignant + classe + année, avec coefficient, heures hebdomadaires et barème facultatif. Il n'existe aucun `TeacherClassAssignment`.

- L'année d'un cours est celle de sa classe, et les clés composites l'imposent.
- Plusieurs enseignants peuvent partager une matière dans une classe (co-enseignement). C'était déjà permis et attendu par le calcul des bulletins.

## 2. Qui peut enseigner : décidé par le serveur

`gradebook.services.teacher_refusal(enseignant, matière, classe)` renvoie `None` si l'enseignant peut enseigner, sinon une règle :

| Règle | Signification |
|---|---|
| `teacher_other_school` | enseignant d'une autre école |
| `teacher_inactive` | statut professionnel ou statut d'emploi non actif (même définition que le planning) |
| `teacher_not_qualified` | aucune qualification acceptée (aucune, en attente, retirée), ou revue exigée par le moteur mais qualification non vérifiée |
| `incompatible_subject` | le moteur de compatibilité (ADR 0019), évalué **au niveau de la classe** et **aujourd'hui**, répond « incompatible » |

`GET /courses/eligible-teachers/?school_class=&subject=` renvoie `eligible`, les enseignants autorisés, et `excluded`, ceux qui ont une qualification pour la matière mais sont refusés, avec la règle. Le poste ne fait qu'afficher ces listes.

## 3. Règles de création, modification et activation

- **Création :** refusée pour :
  - une classe, une matière, un enseignant ou un barème d'une autre école (404, et contrôle dans le service) ;
  - une matière inactive, une catégorie inactive, une classe inactive ou une année clôturée (400) ;
  - un enseignant refusé selon le §2 (400) ;
  - un doublon : même enseignant, matière, classe et année (409 `duplicate_course`) ;
  - un coefficient différent de celui des autres cours actifs de la matière dans la classe (409 `course_coefficient_conflict`, car le bulletin exige un coefficient par matière).

  Ces contrôles sont dans `create_course` : ils protègent tous les appelants, y compris l'API historique `admin/courses/` du planning.
- **Modification :**
  - champs modifiables : enseignant, coefficient, heures, barème ;
  - classe, matière et année immuables (409 `course_identity_immutable`) ;
  - année clôturée refusée (400) ;
  - changement d'enseignant refusé tant que le cours est planifié (409 `course_scheduled`), car créneaux et séances portent l'enseignant prévu.
- **Désactivation :** refusée (409 `course_scheduled`, avec le nombre de créneaux et de séances) tant que le planning utilise encore le cours : créneaux publiés d'une année ouverte **non terminés**, ou séances à venir. Un créneau terminé (`effective_to` passé) ne bloque plus. Notes, séances et bulletins restent.
- **Réactivation :** les mêmes contrôles qu'une création (classe, matière, année, enseignant, coefficient).
- **Audit :** COURSE_CREATED, COURSE_UPDATED, COURSE_ACTIVATED et COURSE_DEACTIVATED, avec les états avant et après.

## 4. API

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/courses/?search=&status=&academic_year=&school_class=&level=&subject=&teacher=` | admin : tous ; enseignant : ses cours (inchangé) ; paginé |
| POST | `/courses/` | admin |
| GET / PATCH | `/courses/{id}/` | admin ou son enseignant / admin (le détail admin ajoute les créneaux en cours et les séances à venir) |
| POST | `/courses/{id}/deactivate/`, `/courses/{id}/reactivate/` | admin |
| GET | `/courses/eligible-teachers/?school_class=&subject=` | admin |

Les champs historiques de la liste (`class_name`, `subject_code`, `teacher_name`…) sont conservés.

## 5. Tests de mutation

`backend/tools/mutation_check.py courses` retire tour à tour une protection, puis vérifie que les tests échouent :

- filtrage école : recherche de la classe, de la matière, de l'enseignant ou du barème ; recherche du cours ; contrôle dans le service ;
- compatibilité : verdict « incompatible » ignoré ; enseignant non vérifié du tout ;
- année : création dans une année clôturée ; modification d'un cours d'une année clôturée.

Résultat : 7 mutations sur 7 tuées.

## 6. Poste PySide6

- **Page Cours :**
  - liste paginée par l'API ;
  - recherche sur matière, classe et enseignant ;
  - filtres année (courante par défaut), classe (qui suit l'année) et matière ;
  - actions Fiche, Modifier, Désactiver/Réactiver, Ajouter.
- **Formulaire :** Année → Classe → Matière → Enseignant.
  - La liste des enseignants est demandée au serveur pour la classe et la matière choisies, et les exclus sont affichés avec leur raison.
  - En modification, classe, matière et année sont figées.
  - Le formulaire passe par `FormDialog` (ADR 0017 §5), avec contenu défilant et boutons fixes.
- **Fiche :** cours, enseignant, évaluation, planning (créneaux en cours, séances à venir).
- **Bout en bout :** le test réel crée la matière, l'enseignant, la classe et l'année, puis le cours. Il le planifie ensuite par l'API existante du planning et vérifie qu'il apparaît dans les créneaux de la classe.
