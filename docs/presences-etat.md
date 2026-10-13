# Présences : état des workflows (13 octobre 2026)

Audit des fonctionnalités de présence. Chaque ligne indique ce qui existe réellement et ce qui manque.

| Fonctionnalité | Modèle | API | Service | Interface | Tests | État |
|---|---|---|---|---|---|---|
| Correction d'une présence | `StudentDailyAttendance` (+ audit `ATTENDANCE_CORRECTED`) | `POST /admin/attendance/{id}/correct/` | `correct_attendance` : motif obligatoire, admin, même école, heure d'arrivée → présent ou en retard | **Desktop** : onglet « Présences du jour », bouton « Corriger… » / double-clic | backend existants ; desktop `test_attendance_page.py` | **Terminé** (desktop) |
| Codes QR annuels | `StudentQRCode` (version, révocation, audit) | `GET /admin/qr-codes/`, `issue/`, `issue-class/`, `reissue/`, `{id}/revoke/` | émission idempotente, élève inscrit, année ouverte, motif pour révoquer | **Desktop** : onglet « Codes QR » (par classe) ; la carte d'élève (Documents) imprime le code actif | backend existants ; desktop `test_attendance_page.py` | **Terminé** (desktop) |
| Présence des enseignants | `TeacherSessionCheckIn` | `POST /teacher/sessions/{id}/check-in/` (mobile) ; `POST /admin/sessions/{id}/validate/` et `reject/` | `validate_session` / `reject_session` : séance terminée, non payée, corrections tracées | Mobile enseignant : auto-déclaration (existant). **Desktop** : Planning → « Séance ▾ » → valider / séance non assurée | backend existants ; desktop `test_planning.py` | **Terminé** (desktop) |
| Convocations | `Convocation` (+ notification `CONVOCATION`) | `GET/POST /admin/convocations/`, `POST …/{id}/status/` ; `GET /parents/convocations/` | parent au lien vérifié, motif, fin après début | Parent mobile : consultation (existant). Desktop : **aucune** | backend existants | **Bloqué** (voir ci-dessous) |
| Présence du personnel non enseignant | — | — | — | Personnel mobile : indique l'absence de la fonction (ADR 0027) | — | **Non défini** |

## Convocations : ce qui manque avant une interface d'administration

1. **Choisir le parent convoqué.** `POST /admin/convocations/` exige l'identifiant d'un `ParentProfile`. Or aucune route d'administration ne liste les parents vérifiés d'un élève. Les demandes de rattachement ne couvrent pas les liens déjà établis.
2. **Afficher la liste.** `ConvocationSerializer` ne renvoie que des identifiants (`student`, `parent`), sans noms. Il faudrait des champs en lecture seule (nom de l'élève, nom du parent), ajoutés au contrat.
3. **Déclenchement automatique.** La spécification indique que « les alertes rouges peuvent créer des convocations programmées ». Le seuil, l'auteur et le créneau d'une convocation automatique ne sont pas définis.

Ces points demandent une décision de contrat d'API : ils n'ont pas été inventés.

## Personnel non enseignant

La spécification ne définit que la présence des enseignants (auto-déclaration puis vérification, qui rend la séance payable). Pour le personnel non enseignant, il n'y a ni règle, ni modèle, ni endpoint. Avant tout développement, il faut définir :
- le mode de pointage (QR, déclaration, saisie administrative) ;
- l'effet sur la paie (salaire fixe) ;
- les horaires de référence ;
- les droits de correction.
