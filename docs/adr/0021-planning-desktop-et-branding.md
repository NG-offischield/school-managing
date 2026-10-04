# ADR 0021 — Planning sur le poste d'administration et identité du logiciel

- **Statut :** accepté — 2026-10-04
- **Périmètre :**
  - page PySide6 « Vie scolaire → Planning » : semaine, créneaux, salles, disponibilités, vacances ;
  - identité visuelle du logiciel School Managing sur le poste ;
  - backend : modification d'une interruption (`PATCH /admin/school-breaks/{id}/`), seul manque constaté.
- **Hors périmètre :** finance, paie, communication, Flutter, activation des comptes, packaging Windows.
- **Migrations :** aucune.

## 1. Aucun nouveau moteur

Le poste est un client du moteur existant (ADR 0012) : `Course`, `ScheduleSlot`, `TeachingSession`,
`Room`, `TeacherUnavailabilityRequest`, `SchoolBreak`. `services/planning.py` envoie les requêtes et
relaie les réponses ; il ne recalcule **aucun** conflit, aucune compatibilité, aucune disponibilité.

| Écran | API utilisées |
|---|---|
| Semaine | `GET sessions/?date_from&date_to&school_class&teacher&room&subject`, `POST admin/sessions/generate/`, `POST admin/sessions/{id}/cancel|move|room|substitute|restore-teacher/` |
| Créneaux | `GET schedules/`, `POST admin/schedules/check/` (vérification à blanc), `POST admin/schedules/`, `…/{id}/end/`, `…/{id}/reschedule/` |
| Salles | `GET rooms/`, `POST|PATCH admin/rooms/`, `…/deactivate|reactivate/`, `POST admin/classes/{id}/main-room/` |
| Disponibilités | `GET admin/unavailability/`, `…/{id}/impacted-sessions/`, `…/{id}/decide/` |
| Vacances | `GET school-breaks/`, `POST admin/school-breaks/`, `PATCH admin/school-breaks/{id}/` (nouveau) |

Toute action sur une séance exige un motif (journal des changements du planning).

## 2. Conflits expliqués, jamais masqués

Un 409 `planning_conflict` porte `details.context.conflicts` (types CLASS / TEACHER / ROOM, jour et
heures ou date de la séance). `messages.explain_conflicts` les traduit : « Classe déjà occupée — lundi
08:00–10:00 », « Salle déjà occupée — le 02/03 08:00–10:00 ». Le bandeau affiche ce texte et ne recharge
pas la page (l'utilisateur garde son contexte). Les autres refus ont un message par règle :
`teacher_incompatible`, `teacher_unavailable`, `course_inactive`, `outside_year`, `room_in_use`,
`session_not_scheduled`, `already_decided`…

## 3. Modification d'une interruption

`update_school_break` (ADMIN) applique les mêmes contrôles que la création (`invalid_dates`,
`break_type_invalid`, nom requis) et journalise `SCHOOL_BREAK_UPDATED`. Une autre école reçoit 404,
un enseignant 403.

## 4. Tableau de bord

Deux indicateurs réels : « Séances aujourd'hui » (hors annulées, avec en cours / annulées) et
« Changements de planning » (7 derniers jours, `planning/changes/`).

## 5. Identité : logiciel ≠ établissement

- Le logo School Managing est l'identité du **logiciel** : écran de connexion, barre latérale, titre
  et icône des fenêtres, « À propos », futur exécutable. Un seul chargeur : `ui/branding.py`, fichiers
  dans `ui/assets/brand/` (horizontal, compact, monochrome, icône). Aucun logo n'a été fabriqué :
  sans fichier officiel, le nom s'affiche en texte.
- Les **documents officiels** de l'école utilisent exclusivement `SchoolBranding` (nom, logo, couleurs
  de l'établissement). Le registre Documents/PDF n'est pas modifié. Un test backend vérifie qu'un
  bulletin porte le nom et le logo de l'école et qu'aucune source `apps/documents` ne mentionne
  School Managing ; l'E2E vérifie un emploi du temps PDF réel.

## 6. Interface

Semaine dessinée en QPainter (`ui/week_view.py`) : une colonne par jour, séances côte à côte en cas de
chevauchement, couleur par statut (planifiée, remplacée, déplacée, réalisée, annulée) avec légende,
info-bulle, clavier (flèches, Entrée). Vue liste en alternative. Dialogues `FormDialog` couverts par
`tests/test_responsive.py` (1366×768, 1280×720, 1024×768, 800×480).
