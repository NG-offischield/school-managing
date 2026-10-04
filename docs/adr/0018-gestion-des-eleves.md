# ADR 0018 — Gestion des élèves (fiche, inscription, photo)

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - administration des élèves (`people.services`, `people/student_api.py`, `people/photos.py`) ;
  - page PySide6 « Gestion académique → Élèves ».
- **Hors périmètre :** workflow de vérification des parents (CNI, double authentification, parrainage du second parent) ; les liens Parent/Élève existants ne changent pas.
- **Migrations :** aucune. `Student` et `StudentEnrollment` portaient déjà tous les champs, les contraintes PostgreSQL et l'interdiction de suppression.

## 1. Audit de l'existant

| Élément | Constat | Décision |
|---|---|---|
| `Student` | Identité, `photo` (ImageField), lieu de naissance, adresse, taille, statut, `archived_at` ; `delete()` interdit ; clés étrangères PROTECT | réutilisé tel quel |
| Matricule | `student_number` et `registration_number`, UNIQUE par école ; aucun générateur dans la spec ni dans le code | saisis par l'école, unicité vérifiée par le serveur (409), garantie par PostgreSQL ; jamais fabriqués par le poste |
| `StudentEnrollment` | une inscription par élève et par année ; classe de la même année et de la même école (clés composites) ; statuts ACTIVE / COMPLETED / WITHDRAWN | réutilisé ; aucun second modèle |
| Services | `create_student`, `enroll_student`, `archive_student` sans audit ni contrôle de rôle complet | enveloppés par des services `admin_*` |
| API | lecture seule (`/students/`, `/students/{id}/`, `/students/{id}/enrollments/`) | conservée avec la même visibilité par rôle, complétée des écritures |
| Données d'urgence | aucune dans `Student` ; la carte élève reprend les parents vérifiés | rien d'inventé |

## 2. Règles

- **Création :** champs obligatoires, date de naissance passée et plausible, taille de 30 à 250 cm.
  - Doublon de matricule ou de numéro d'inscription (insensible à la casse) : 409.
  - L'inscription peut être faite dans la même requête : élève et inscription sont créés dans **une seule transaction**.
- **Modification :** identité et champs administratifs. Le statut ne change pas par PATCH. Un élève archivé ne se modifie pas (400 `student_archived`).
- **Inscription :**
  - élève actif seulement ;
  - classe active de l'école, dans une année ouverte ;
  - une seule inscription par année (409 `already_enrolled`) ;
  - date comprise dans l'année ;
  - capacité de la classe respectée (409 `class_full`, même comptage que le planning).
- **Changement de classe :**
  - la même inscription passe dans une autre classe de **la même année** (400 `class_other_year`, refusé aussi par PostgreSQL) ;
  - jamais la même classe (409) ni une inscription close (409) ;
  - notes, présences et documents déjà saisis restent attachés là où ils ont été faits.
- **Retrait :** l'inscription passe WITHDRAWN avec une date de fin.
  - Par défaut, cette date est aujourd'hui, mais jamais avant la date d'inscription (une inscription préparée pour une année future se retire le jour où elle commence).
  - Une date explicite antérieure à l'inscription est refusée (400 `withdraw_before_enrollment`).
- **Archivage :** refusé tant qu'une inscription est active (409 `active_enrollment`). Réactivation possible.
  - Rien n'est supprimé : notes, bulletins, présences, QR, factures et documents restent (PROTECT, `HardDeleteForbidden`).

Toutes ces écritures :

- exigent le rôle ADMIN ou SUPER_ADMIN de l'école de l'élève ;
- sont journalisées dans l'AuditLog, couche BUSINESS ;
- renvoient 404 pour un élève, une inscription ou une classe d'une autre école.

## 3. API

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/students/?search=&status=&academic_year=&level=&school_class=&enrollment_status=` | visibilité existante (admin, parent vérifié, enseignant de la classe), paginé |
| POST | `/students/` (`enrollment` facultatif) | admin |
| GET / PATCH | `/students/{id}/` | visible / admin |
| POST | `/students/{id}/archive/`, `/students/{id}/reactivate/` | admin |
| GET / POST | `/students/{id}/enrollments/` | visible / admin |
| POST | `/enrollments/{id}/change-class/`, `/enrollments/{id}/withdraw/` | admin |
| GET / POST / DELETE | `/students/{id}/photo/` | visible / admin |
| GET | `/students/{id}/history/` | admin |

**Liste :**

- chaque ligne porte l'inscription de l'année choisie (l'année courante par défaut) grâce à des sous-requêtes : aucune requête par élève ;
- `enrollment_status=NONE` donne les élèves non inscrits ;
- les administrateurs reçoivent les champs administratifs (adresse, taille) ; les autres rôles gardent la sérialisation existante.

## 4. Photo

- **Vérification :** le type est établi par décodage avec Pillow (JPEG, PNG ou WebP), jamais d'après le nom ou l'en-tête du client. Taille maximale 3 Mo ; côtés entre 120 et 6 000 px.
- **Réencodage :** JPEG de 800 px au plus. Les **métadonnées EXIF (GPS, appareil) sont supprimées**.
- **Stockage :** sous un nom aléatoire (`students/photos/<uuid>.jpg`), dans le stockage par défaut, qui n'a aucune route publique.
- **Lecture :** le fichier n'est servi que par `GET /students/{id}/photo/`, qui vérifie la visibilité, avec `Cache-Control: private, no-store`.
- **Ce qui quitte le poste :** uniquement les octets et un nom neutre (`photo.png`), jamais le chemin local.
- **Carte élève :** elle utilise cette photo sans changement.

## 5. Tests de mutation

`backend/tools/mutation_students.py` retire tour à tour une protection, puis vérifie que les tests échouent :

- filtrage école (classe, élève, service) ;
- contrôles année/classe (autre année, deuxième inscription, date hors de l'année) ;
- contrôles de permission (création, changement de classe, historique).

Résultat : 9 mutations sur 9 tuées.

## 6. Poste PySide6

- **Page Élèves :**
  - liste paginée par l'API (50 lignes par page), sans tri local d'une page partielle ;
  - filtres année, niveau, classe (qui suit l'année et le niveau), situation d'inscription et statut ;
  - recherche sur nom, prénom et matricule.
- **Actions :** Fiche, Modifier, Archiver/Réactiver, Ajouter. Depuis la fiche : Inscrire, Changer de classe, Retirer de la classe.
- **Dialogues :** tous passent par `FormDialog` (ADR 0017 §5). Le formulaire élève est découpé en sections (Identité, Photo, Informations complémentaires, Inscription), défile, et garde ses boutons visibles en 1366×768 et 1280×720. Le choix suit Année → Niveau → Classe, avec des listes venant de l'API.
- **Champs date :** Tab passe au champ suivant ; à l'intérieur du champ, on utilise les flèches, la saisie ou le calendrier.
- **Tableau de bord :** l'indicateur « Élèves » compte les élèves **actifs**. Les graphiques d'effectifs déjà alimentés par les inscriptions réelles (ADR 0017) reflètent les nouvelles inscriptions.
