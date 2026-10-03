# ADR 0016 — Documents officiels et PDF

- **Statut :** accepté — 2026-10-04
- **Périmètre :** nouvelle app `documents` (`Document`, `DocumentDownload`). Elle couvre :
  - le rendu PDF ReportLab ;
  - les bulletins scolaires, reçus de paiement, bulletins de paie, relevés de présence d'un élève et registres de classe ;
  - les endpoints de la spec §6.12 (`/reports/...pdf/`, `/report-cards/{id}/pdf/`, `/payroll/{id}/payslip.pdf/`).
- **Hors périmètre :** carte élève (avec QR), PDF de l'emploi du temps, PySide6, Flutter, FCM, déploiement.

## 1. Bibliothèque : ReportLab

- Python pur, distribué en wheels, sans dépendance système. WeasyPrint aurait exigé Pango et cairo dans l'image.
- Fonctionne hors ligne sur le LAN de l'école, licence BSD.
- Ajouté à `requirements/base.txt` ; l'image Docker est reconstruite.

## 2. Un document = le rendu d'une source, jamais une donnée métier

Chaque constructeur (`builders.py`) **lit** son domaine source et produit `content`, l'instantané JSON exact de ce qui est imprimé. Rien n'est écrit dans les domaines sources (un test vérifie que le paiement est identique avant et après la génération du reçu).

| Document | Source | OFFICIEL quand | Sinon |
|---|---|---|---|
| bulletin | `ReportCard` et ses lignes (matières, moyennes, coefficients, appréciations, rang, effectif, validation) | bulletin VALIDATED | PROVISOIRE, administration seule |
| reçu | `Payment` et ses allocations positives | paiement reçu (SUCCEEDED, PARTIALLY_REFUNDED, REFUNDED) | refusé (409) |
| bulletin de paie | `TeacherPayroll` / `StaffPayroll` et les lignes de la version courante | paie PAID | APPROVED → PROVISOIRE ; préparée ou annulée → 409 |
| relevé de présence | `StudentDailyAttendance` sur une période | période passée et toutes les journées clôturées | PROVISOIRE |
| registre de classe | `StudentDailyAttendance` du jour et `TeachingSession` du jour | jour passé et journée clôturée | PROVISOIRE |

Le reçu ne montre que les faits **immuables** de la transaction : un remboursement ultérieur ne le modifie pas, il a sa propre trace financière.

Aucun nouveau système de présence n'est créé.

## 3. Officiel, provisoire, versions, idempotence

- **Empreinte :** `fingerprint` = sha256 de `content`.
- **Même empreinte que le document courant :** le même document est renvoyé (idempotent).
- **Document courant OFFICIEL :** il est renvoyé tel quel et n'est **jamais** régénéré (409 `document_official` sur `/regenerate/`).
- **Document courant PROVISOIRE et source modifiée :** une nouvelle version est créée, la précédente passe SUPERSEDED.
- **Contraintes PostgreSQL :**
  - un seul document courant par (type, source, paramètres) ;
  - versions uniques ;
  - exactement la bonne colonne source par type (CHECK) ;
  - documents jamais supprimés ni réécrits : seule la transition PROVISIONAL → SUPERSEDED est permise (trigger) ;
  - traces de téléchargement en ajout seul.

## 4. Branding

- **Source :** `School` (nom, raison sociale, adresse, contacts, logo) et `SchoolBranding` (couleurs primaire et secondaire). Rien n'est codé en dur.
- **Mise en page :**
  - bandeau d'en-tête à la couleur primaire, avec le logo s'il existe ;
  - pied de page avec le nom de l'école, la mention officielle ou provisoire, le code de vérification et la page ;
  - filigrane « PROVISOIRE » ou tampon « OFFICIEL ».
- **Instantané :** le branding fait partie du `content`. Un document officiel garde le branding de sa date de génération.

## 5. Stockage et accès

| Point | Règle |
|---|---|
| Stockage | stockage `private` (ADR 0015), nom aléatoire, sans route publique |
| Téléchargement | `/documents/{id}/download/` uniquement après contrôle des droits, en-têtes `private, no-store` et `nosniff`, tracé dans `DocumentDownload` |
| Génération | auditée dans `AuditLog` (`DOCUMENT_GENERATED`) |
| Vérification | `/documents/verify/?code=` : authenticité d'un document imprimé, même école seulement, sans contenu pour qui n'a pas le droit de le lire |

Droits, construits sur les relations existantes (rien n'est copié) :

| Rôle | Documents accessibles |
|---|---|
| ADMIN / SUPER_ADMIN | tous les documents de son école |
| parent | bulletins **officiels** et relevés de présence de ses enfants (lien actif et vérifié) ; reçus seulement avec `can_view_financial_data` |
| payeur | ses propres reçus |
| employé | ses propres bulletins de paie |
| enseignant | le registre des classes où il a un cours actif |
| autres | rien |

Codes de retour :
- non autorisé ou autre école → 404 ;
- source pas encore documentable → 409 `document_source_not_final` ;
- régénération par un non-administrateur → 403.

## 6. Écarts par rapport à la spec — à valider

1. Il n'y a pas de table `Payslip` dédiée ni de colonnes `pdf_path` : le registre central `Document` couvre tous les types, avec versions et instantané. `ReportCard.pdf_path`, sur le stockage public par défaut, n'est **pas** utilisé.
2. Un endpoint de reçu est ajouté (`/payments/{id}/receipt.pdf/`), ainsi que l'endpoint de vérification d'authenticité.
3. La carte élève et le PDF de l'emploi du temps (§6.12) ne sont pas encore produits.
