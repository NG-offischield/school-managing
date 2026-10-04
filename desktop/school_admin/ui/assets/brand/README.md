# Logo School Managing (identité du logiciel)

Déposer ici, **une seule fois**, les fichiers officiels du logo choisi (concept 5) :

| Fichier | Usage |
|---|---|
| `logo-horizontal.svg` (ou `.png`) | écran de connexion, « À propos » |
| `logo-compact.svg` (ou `.png`) | barre latérale |
| `logo-monochrome.svg` (ou `.png`) | fonds sombres / impressions internes du logiciel |
| `app-icon.ico` (ou `.png`) | icône de fenêtre, futur exécutable et installateur Windows |

Le chargement est centralisé dans `school_admin/ui/branding.py` : aucun écran ne
lit ces fichiers directement. Tant qu'ils sont absents, le poste affiche le texte
neutre « School Managing » (aucun logo n'est inventé).

Ce logo représente **le logiciel**. Il n'apparaît jamais sur les documents
officiels d'une école (bulletins, cartes, reçus, fiches de paie, relevés,
emplois du temps PDF, convocations) : ceux-ci utilisent exclusivement le
branding de l'établissement (`SchoolBranding` côté serveur).
