# ADR 0019 — Gestion des enseignants (fiche, compte, qualifications, compatibilité)

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - administration des enseignants (`people.services`, `people/teacher_api.py`) ;
  - agrégat de tableau de bord `admin/dashboard/teachers/` ;
  - page PySide6 « Gestion académique → Enseignants ».
- **Hors périmètre :**
  - les cours (`Course` = matière + enseignant + classe + année ; aucun `TeacherClassAssignment`) ;
  - le planning, qui n'est pas refait ;
  - la paie (affichée en lecture seule) ;
  - l'activation du compte (premier mot de passe).
- **Migrations :** aucune.

## 1. Audit — chaîne réutilisée

```
User (personne, globale) → SchoolMembership (école, rôle TEACHER via MembershipRole)
  → EmployeeProfile (matricule = « numéro d'enseignant », statut d'emploi, embauche, adresse)
    → TeacherProfile (catégorie pédagogique, matière principale, statut professionnel)
      → TeacherSubjectQualification (matières) / CompatibilityOverride (dérogations)
```

| Élément | Constat | Décision |
|---|---|---|
| Moteur de compatibilité | `people/compatibility.py` : dérogation, puis règle la plus spécifique, puis matière principale ou même catégorie, sinon validation | seule autorité ; le poste n'affiche que son verdict |
| Services | `create_employee`, `create_teacher` (déclare la matière principale), `declare/verify/reject_qualification`, `grant_compatibility_override` | réutilisés, enveloppés par des services `admin_*` avec contrôles et audit |
| Comptes | `User.objects.create_user(password=None)` donne un mot de passe inutilisable ; aucun mécanisme d'invitation | le compte enseignant est créé **sans mot de passe** ; son activation est une procédure séparée, à venir |
| Rôles | catalogue `Role` (rôles système), `MembershipRole` | le rôle TEACHER vient du catalogue ; aucun rôle libre |
| Planning | un enseignant planifiable a un statut professionnel ET un statut d'emploi ACTIVE | même définition de « actif » partout |
| Photo | `User.profile_photo` existe, mais aucune API ne la gère | non exposée dans cette phase |
| Fonction | `StaffFunctionAssignment` concerne le personnel (StaffProfile), pas les enseignants | la fonction affichée est « Enseignant » |

## 2. Règles

- **Création :** une seule transaction pour User, membership ACTIVE avec le rôle TEACHER, EmployeeProfile de type TEACHER, TeacherProfile et la qualification de la matière principale, jugée par le moteur. Tout refus défait tout :
  - matricule pris (409 `duplicate_employee_number`) ;
  - e-mail utilisé par un compte d'une autre école (409 `email_in_use` : un compte d'une autre école n'est **jamais** rattaché en silence) ;
  - personne déjà employée ici (409 `already_employee`) ;
  - matière principale incompatible (400 `incompatible_subject`) ;
  - catégorie ou matière inactive (400).
  - Seule exception : un membre de **cette** école sans profil d'employé (un parent, par exemple) devient enseignant sur son compte existant.
- **Modification :**
  - identité (sur le User) ;
  - données RH : matricule, embauche, adresse, statut d'emploi ;
  - profil : catégorie, matière principale (jugée par le moteur), statut professionnel, résumé, présentation.
- **Désactivation :** statut professionnel INACTIVE. Elle est refusée (409 `teacher_in_use`, avec le nombre de cours et de séances) tant qu'il reste des cours actifs d'une année ouverte ou des séances planifiées à venir. Passer à un statut d'emploi non actif suit la même règle. Rien n'est supprimé (PROTECT) : cours, séances, notes, paie et compte restent. La réactivation exige un emploi actif.
- **Qualifications :**
  - ajout administratif jugé par le moteur : compatible ou dérogation donne DECLARED ; à valider donne PENDING ; incompatible est refusé et rien n'est stocké ;
  - validation par l'administration ;
  - retrait (motif obligatoire) refusé pour la matière principale (409) et tant qu'un cours actif l'utilise (409 `qualification_in_use`) ;
  - une matière retirée puis ajoutée de nouveau est **réévaluée**, sur la même ligne.
- **Dérogations :** administrateurs seulement. Elles enregistrent motif, auteur, date, portée (matière, niveau facultatif) et une expiration future facultative, et sont tracées.

Toutes ces écritures :

- exigent le rôle ADMIN ou SUPER_ADMIN de l'école ;
- sont journalisées dans l'AuditLog, couche ADMINISTRATIVE ;
- renvoient 404 pour un enseignant, une matière, une catégorie ou un niveau d'une autre école.

## 3. API

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/teachers/?search=&status=active\|inactive&category=&subject=` | admin : tous ; enseignant : lui-même (inchangé) ; paginé |
| POST | `/teachers/` | admin |
| GET / PATCH | `/teachers/{id}/` | visible / admin (le détail admin ajoute le nombre de cours actifs et de séances à venir) |
| POST | `/teachers/{id}/deactivate/`, `/teachers/{id}/reactivate/` | admin |
| GET / POST | `/teachers/{id}/qualifications/` | visible (liste vide hors périmètre, comme avant) / admin |
| POST | `/teacher-qualifications/{id}/verify/`, `/teacher-qualifications/{id}/reject/` | admin |
| GET | `/teachers/{id}/compatibility/?subject=&level=` | admin : verdict, code de raison (`override`, `rule_*`, `primary_subject`, `same_category`, `no_rule`), règle ou dérogation appliquée |
| GET | `/teachers/{id}/compatibility-rules/` | admin : règles de la catégorie de l'enseignant (lecture seule) |
| GET / POST | `/teachers/{id}/overrides/` | admin |
| GET | `/admin/dashboard/teachers/` | admin : enseignants actifs et répartition par catégorie |

## 4. Tests de mutation

`backend/tools/mutation_check.py teachers` retire tour à tour une protection, puis vérifie que les tests échouent :

- filtrage école : recherche de la matière, de la catégorie ou du niveau ; recherche de l'enseignant ; contrôle dans le service ;
- permissions : ajout de qualification ; modification par l'administrateur d'une autre école ; lecture du verdict ;
- compatibilité : déclaration incompatible acceptée ; règle « incompatible » lue comme compatible ; matière principale non jugée à la création.

Résultat : 9 mutations sur 9 tuées. La suite `students` est inchangée (9 sur 9).

## 5. Poste PySide6

- **Page Enseignants :**
  - liste paginée par l'API ;
  - recherche sur nom, prénom, e-mail et matricule ;
  - filtres statut, catégorie et matière qualifiée, sur une seconde ligne pour rester lisibles en 1024 px.
- **Actions :** Fiche, Modifier, Désactiver/Réactiver, Qualifications, Ajouter.
- **Fiche :** identité, profil professionnel, qualifications, planning (nombre de cours et de séances, emploi du temps PDF dans Documents), rémunération (taux de vacation déjà exposés par la paie, en lecture seule), état du compte.
- **Dialogue Qualifications :** « Vérifier la compatibilité » interroge le serveur et affiche le verdict et sa raison. Il permet d'ajouter, valider, retirer (avec motif) ou accorder une dérogation motivée (avec expiration facultative). Les règles et les dérogations de l'enseignant y sont listées.
- **Formulaires :** tous passent par `FormDialog` (ADR 0017 §5), avec en-tête fixe, contenu défilant et boutons fixes. Ils sont testés en 1366×768, 1280×720, 1024×768 et 800×480.
- **Tableau de bord :** l'indicateur « Enseignants » compte les enseignants actifs, avec leur répartition par catégorie.
