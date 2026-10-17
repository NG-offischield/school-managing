# Vidéo de démonstration (3 à 5 minutes)

La vidéo garde une trace durable du projet, même si l'hébergement gratuit s'arrête. **Aucune vidéo n'a encore été enregistrée.** Ce document prépare l'enregistrement manuel.

- **Fichier vidéo :** il reste **hors du dépôt Git**, par exemple dans `C:\Users\<vous>\Videos\School Managing\isbree-demo-AAAAMMJJ.mp4`, avec une copie sur un disque externe ou un cloud personnel.
- **Publication :** sur YouTube, en public ou non répertorié. Ajoutez ensuite l'URL réelle au README.

## Avant d'enregistrer

- Utilisez la **démo en ligne**, ou `localhost` avec la base de démonstration. Ne montrez jamais la base `school` de développement.
- Fermez les onglets personnels, l'e-mail et les notifications Windows (assistant de concentration activé).
- Ne filmez **jamais** :
  - un fichier `.env`, un jeton, ou le mot de passe administrateur ;
  - les variables des tableaux de bord Render ou Neon ;
  - une adresse IP locale ;
  - une donnée personnelle réelle.

  Le mot de passe **commun des comptes de démonstration**, publié volontairement, peut apparaître.
- Dans le formulaire de préinscription, saisissez des données **manifestement fictives**, par exemple « Parent Exemple », `parent@exemple.test`, `+237 600 00 00 00`.
- Réveillez les services une minute avant l'enregistrement en ouvrant le site, le portail et `/api/v1/health/` : les services gratuits sont en veille.

## Script (≈ 4 min)

| Temps | Écran | À dire (idée, pas à lire mot à mot) |
|---|---|---|
| 0:00–0:20 | Accueil du site public | « School Managing est une plateforme de gestion scolaire. Voici sa démonstration pour un établissement fictif, ISBREE. Les contenus marqués *Démonstration* sont fictifs. » |
| 0:20–0:50 | À propos, Formations, Vie scolaire | Présentation de l'école ; les niveaux affichés viennent de la base (seuls ceux ouverts à la préinscription) ; tout est administrable. |
| 0:50–1:10 | Actualités, FAQ, Contact (lien téléphone), menu sur mobile (fenêtre étroite) | Navigation, accessibilité (tests axe automatisés), version mobile. |
| 1:10–1:50 | Admissions → Préinscription | Montrer l'encadré « Démonstration », une erreur de saisie corrigée, puis l'envoi : la référence `PRE-…` vient du serveur. « Une demande acceptée n'inscrit pas l'élève : l'établissement invite la famille dans son Espace ISBREE. » |
| 1:50–2:10 | Lien « Espace ISBREE » → page de connexion | Comptes de démonstration en lecture seule ; les pages privées ne sont jamais indexées ni mises en cache. |
| 2:10–2:50 | Connexion Parent | Enfant à lien **vérifié** uniquement, ressources de sa classe, actualités, FAQ ; applications « pas encore disponibles » (aucun faux lien). Puis tenter `/espace/enseignant` : « Espace non accessible ». Déconnexion. |
| 2:50–3:20 | Connexion Enseignant, puis Gardien | Les contenus changent selon le rôle, choisi parmi les rôles détenus et revérifié par le serveur. |
| 3:20–3:40 | Section « Applications mobiles » de l'espace connecté | Chaque rôle voit seulement son application : version, taille, empreinte SHA-256, étapes d'installation. Le build est un build de débogage pour la démonstration, hébergé sur GitHub Releases (fichier public). Si l'application est déjà installée sur un téléphone, montrer son écran de connexion. |
| 3:20–4:20 | Schéma ou README sur GitHub | Architecture : Django/DRF + PostgreSQL + Redis (API seule autorité), deux applications Next.js en BFF (jetons dans un cookie chiffré HttpOnly), poste d'administration PySide6, quatre applications Flutter, tests (backend, desktop, Vitest, Playwright + axe). Mentionner les limites : démo, hébergement gratuit. |
| 4:20–4:40 | Page GitHub du dépôt | « Le code et tout son historique sont publics à cette adresse. » |

## Checklist OBS Studio (Windows)

1. **Paramètres → Sortie :**
   - mode simple ;
   - format **MP4** (ou MKV puis *Fichier → Convertir en MP4*) ;
   - qualité « Haute » ;
   - encodeur matériel s'il est proposé.
2. **Paramètres → Vidéo :** résolution de base et de sortie **1920×1080**, 30 i/s.
3. **Audio :** micro réglé pour que la voix atteigne environ −12 dB. Désactivez l'audio du bureau s'il n'est pas utile, et faites un essai de 10 secondes.
4. **Sources :**
   - **Capture de fenêtre** du navigateur, de préférence à la capture d'écran entière (moins de risque de montrer autre chose) ;
   - zoom du navigateur à 110–125 % pour la lisibilité.
5. **Vérifications :**
   - profil de navigateur dédié, sans favoris personnels ni extensions visibles ;
   - barre d'adresse vérifiée : pas d'URL `localhost` avec des paramètres sensibles.
6. **Démarrer l'enregistrement**, suivre le script, puis **Arrêter**.
7. Relisez la vidéo **en entier** pour repérer un secret, une IP ou une donnée personnelle. S'il y en a un, recoupez ou réenregistrez.
8. Rangez le fichier hors du dépôt, faites une copie de sauvegarde, puis publiez sur YouTube (titre, description avec le lien du dépôt).
9. Ajoutez l'URL YouTube réelle dans la section « Démonstration » du README, puis commitez.
