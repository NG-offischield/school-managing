# Plans de l'établissement (plans 2D)

L'administration **importe** les plans de ses locaux, les **publie** et choisit **qui peut les voir**. Les parents et les enseignants autorisés les consultent ensuite dans leur application.

Ces plans sont dessinés **ailleurs**, par un dessinateur ou un architecte, dans un logiciel spécialisé (AutoCAD, Revit, ArchiCAD, LibreCAD, Inkscape…). School Managing **n'est pas un logiciel de dessin** : il ne modifie jamais un plan.

| Où | Ce qu'on y fait |
|---|---|
| Poste d'administration | Documents → onglet **Plans** : création, import, aperçu, versions, publication, retrait, destinataires, liste des accès |
| Applications Parent et Enseignant | **« Plan de l'établissement »** (Parent : raccourci de l'accueil et profil ; Enseignant : onglet Profil) : liste, ouverture, zoom et déplacement (images), ouverture du PDF dans le lecteur du téléphone ; bouton « Ouvrir le plan » sur la notification |
| API | `admin/plans/…` (administration) et `plans/…` (lecteurs) : voir `backend/apps/documents/plans_api.py` |

## Formats acceptés

| Format | Accepté | Contrôle réel effectué |
|---|---|---|
| **PDF** | oui | Signature `%PDF-`, puis ouverture avec `pypdf`. Le fichier doit être lisible, non chiffré et compter de 1 à 50 pages. **Refusé** s'il contient du contenu actif : JavaScript, lancement d'application, fichiers joints, média intégré. |
| **PNG** | oui | L'image est réellement décodée par Pillow, dimensions vérifiées avant le décodage des pixels. Elle est **réencodée** : les métadonnées (auteur, logiciel…) disparaissent, la résolution complète est conservée. |
| **JPEG** | oui | Même traitement que le PNG : l'EXIF disparaît (position GPS, appareil…) et l'orientation est appliquée. |
| SVG | **non** | Un SVG peut contenir du script. Exportez-le en PDF ou en PNG. |
| DWG / DXF | **non** | Aucun moteur de CAO ici. Voir la section suivante. |

C'est le **contenu** du fichier qui décide de son type, jamais son nom. Un exécutable renommé `plan.pdf` est refusé, tout comme un PNG nommé `.pdf` (extension trompeuse).

**Limites**, réglées en un seul endroit, `config/settings/base.py` :

| Réglage | Valeur |
|---|---|
| `SCHOOL_PLAN_MAX_BYTES` | 20 Mo (modifiable par variable d'environnement) |
| `SCHOOL_PLAN_MAX_IMAGE_SIDE` | 8 000 px par côté |
| `SCHOOL_PLAN_MAX_PDF_PAGES` | 50 pages |

Ce sont des plafonds pour un plan de site complet, pas les 800 px des photos d'élèves.

### Depuis un fichier DWG / DXF

Dans le logiciel d'architecture :

1. ouvrir la présentation (layout) du plan à diffuser ;
2. **Imprimer / Tracer** vers **PDF**, par exemple « DWG To PDF » dans AutoCAD, en vectoriel et à l'échelle de la feuille. On peut aussi **exporter** en PNG, à au moins 150 dpi ;
3. utiliser des noms de salles et de bâtiments **identiques à ceux de School Managing** (« R12 », « Laboratoire », « Bâtiment A ») : c'est ce qui permet de s'y retrouver ;
4. importer ce PDF ou ce PNG dans le poste d'administration.

Le PDF vectoriel reste net quand on zoome. Le PNG s'affiche directement dans les applications.

## Cycle de vie

```
brouillon ──importer──▶ version 1 (brouillon) ──publier──▶ plan PUBLIÉ (v1 courante)
           ──importer──▶ version 2 (brouillon)   — les lecteurs voient toujours la v1
           ──publier v2─▶ v1 « remplacée » (conservée), v2 courante
           ──retirer───▶ plan RETIRÉ : absent des listes, téléchargements refusés
```

- **Importer n'est pas publier.** Une nouvelle version ne remplace jamais silencieusement celle que voient les lecteurs : la publication est une action distincte.
- **Rien n'est supprimé.** Toutes les versions et l'historique sont conservés : statut, auteur, date, empreinte SHA-256. Seule l'administration peut ouvrir une ancienne version (aperçu, historique).
- Un plan retiré peut être republié.
- Modifier le titre, la description, le bâtiment ou l'étage **ne notifie personne**.

## Qui voit un plan publié

Le serveur décide **à chaque lecture et à chaque téléchargement**. Rien n'est accordé une fois pour toutes : un plan retiré, ou un droit perdu (lien parent désactivé, enseignant suspendu, audience modifiée), ferme l'accès dès la requête suivante.

| Diffusion | Lecteurs |
|---|---|
| **AUTO** | Les parents **vérifiés** de l'école (au moins un lien actif et vérifié) et les enseignants **en activité** de l'école |
| **MANUELLE** | Les publics choisis parmi : tous les parents vérifiés, tous les enseignants en activité, les parents vérifiés des élèves d'une **classe**, les enseignants ayant un cours actif dans une **classe** |

- L'administration de l'école voit toujours ses plans.
- **Jamais** : gardiens, personnel, parents non vérifiés, autre école.
- Un plan en diffusion manuelle ne peut pas être publié sans au moins un public. On ne peut pas non plus vider le public d'un plan déjà publié : il faut alors retirer le plan.
- « **Qui a accès ?** » dans le poste d'administration liste les personnes résolues au moment de la demande.

## Notifications

À la **publication d'une version**, que ce soit la première ou une nouvelle, chaque lecteur reçoit une notification « Plan publié » ou « Plan mis à jour ». Elle passe par le service de notifications existant, de type `PLAN` :
- elle est enregistrée ;
- elle est poussée en direct par WebSocket ;
- elle se relit plus tard ;
- elle se désactive dans les préférences.

Les lecteurs sont notifiés **une seule fois par version**. Republier la même version, retirer le plan, modifier ses informations ou importer un brouillon ne notifie personne. Aucune notification ne part vers une autre école.

## Sécurité du fichier

- **Stockage :** dans le stockage **privé** (`PRIVATE_MEDIA_ROOT/plans/<école>/<nom aléatoire>`), sans aucune route publique. Le nom d'origine n'est conservé que comme information.
- **Téléchargement :** uniquement par `GET /plans/{id}/file/`, pour les lecteurs et la version courante seulement, ou par `GET /admin/plans/{id}/versions/{v}/file/`, pour l'administration. Le serveur revérifie l'identité, l'école, le rôle, le statut et le public à chaque appel.
- **En-têtes de réponse :** `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox`. Ce qui n'est pas autorisé répond 404, comme ce qui n'existe pas.
- **Garanties PostgreSQL :**
  - toutes les références restent dans l'école du plan ;
  - la version courante d'un plan est **l'une de ses propres versions** ;
  - au plus une version publiée par plan ;
  - un plan publié a toujours une version ;
  - type MIME limité à PDF, PNG et JPEG.
- **Applications mobiles :** le fichier est retéléchargé à chaque ouverture (droit revérifié). Une image reste **en mémoire** et n'est jamais écrite. Un PDF est écrit dans le cache privé de l'application, confié au lecteur PDF du téléphone par le FileProvider de school_core (seul le dossier `cache/shared/` est partagé, avec un droit de lecture temporaire), puis la copie de l'application est aussitôt supprimée. Au changement de serveur ou en quittant la session, `cache/shared/` est vidé : rien de l'ancienne école ne reste.

## Vérifications

| Niveau | Où |
|---|---|
| Backend | `backend/tests/test_school_plans.py` : fichiers réels et piégés, cycle de vie, diffusion AUTO / MANUELLE, notifications, isolation, intégrité PostgreSQL, WebSocket |
| Poste d'administration | `desktop/tests/test_plans.py` (tests de widgets, contre un faux backend) |
| Mobile | `school_core/test/plans_test.dart`, `parent/test/plans_test.dart`, `teacher/test/plans_test.dart` (tests de widgets, contre un faux serveur HTTP) |
| Réseau réel | `e2e/school_plans.mjs` : import, publication, diffusion, téléchargement, notifications en direct, isolation DEMO ↔ TEST01, contre un backend de TEST (voir `e2e/README.md`) |

Les tests de widgets ne sont pas des tests E2E : seul `e2e/school_plans.mjs` passe par le vrai réseau.
