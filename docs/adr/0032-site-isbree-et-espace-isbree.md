# ADR 0032 — Site public ISBREE et Espace ISBREE (portail web)

- **Statut :** accepté — 2026-10-14
- **Périmètre :**
  - deux applications web Next.js indépendantes sur le backend School Managing :
    - `web/isbree-public` : site institutionnel, admissions, préinscription ;
    - `web/isbree-portal` : « Espace ISBREE », portail authentifié par rôle ;
  - leur API Django (`apps.website`, `apps.admissions`) ;
  - leur administration dans le desktop PySide6 (module « Site ISBREE »).
- **Hors périmètre :**
  - mise en production, domaines, publication sur les stores ;
  - builds Release signés, notifications push, paiement en ligne ;
  - conversion automatique d'une préinscription en inscription.

## 1. Décisions

### 1.1 Deux applications, un seul backend

Le site public et le portail sont deux serveurs Next.js 16 distincts : ports 3000 et 3001, déploiements et en-têtes séparés.

- **Navigateurs :** ils n'appellent **jamais** Django. Chaque serveur Next appelle l'API *server-to-server* (`DJANGO_INTERNAL_API_URL`).
- **Base de données :** aucun client ne s'y connecte.
- **Secrets :** aucune clé n'est exposée au navigateur (aucune variable `NEXT_PUBLIC_`).

### 1.2 Adresse du visiteur derrière le serveur web

Les limites de débit de Django comptent par adresse : connexion, activation, préinscription 5/heure. Derrière Next, tous les visiteurs auraient la même adresse.

- `X-Forwarded-For` n'est **pas** cru : les applications mobiles appellent Django directement et pourraient le forger.
- Un serveur web se prouve avec un jeton partagé `WEB_BFF_TOKEN`, comparé en temps constant. Il transmet alors l'adresse du visiteur dans `X-ISBREE-Client-IP` (`common/bff.py`).
- Sans jeton valide, ces en-têtes sont ignorés et supprimés.
- Côté Next, l'adresse vient des entrées **de droite** de `X-Forwarded-For` (`ISBREE_TRUSTED_PROXY_HOPS`). En production, Next doit donc être derrière un reverse proxy qui ajoute l'adresse réelle.

### 1.3 Contenus administrables

- **Ce qu'on administre :**
  - les pages : présentation, admissions, mentions légales, confidentialité, conditions, règlement… ;
  - la FAQ par catégorie, les actualités, les images, les lieux ;
  - les ressources par rôle, avec un PDF facultatif ;
  - le profil de l'établissement et les versions d'applications Android.
- **Statut et publics :**
  - chaque contenu a un statut `DRAFT` / `PUBLISHED` / `ARCHIVED` ;
  - il a aussi un ou plusieurs publics : `PUBLIC`, `PARENT`, `TEACHER`, `STAFF`, `GUARDIAN`. Une ressource de rôle n'est jamais publique.
- **Rien n'est supprimé** : on archive.
- **Format du texte :** du texte brut, sans HTML (`##` intertitre, `-` liste). React échappe tout.
- **Marquage honnête :**
  - `to_validate` signale un texte **provisoire**, affiché comme tel au lecteur ;
  - `is_demo` signale une donnée **fictive** (bandeau `ISBREE_DEMO_MODE`) ;
  - `is_illustration` signale une image qui ne représente pas l'établissement. La légende le dit toujours.
- **Adresse :** l'adresse exacte n'est publiée qu'une fois `address_confirmed` coché.
- **Formations :** n'affichent **que** les niveaux `public_visible` réellement ouverts.
- **Fichiers :**
  - les images sont réencodées (JPEG/PNG), sans EXIF, avec un côté de 2400 px au plus ;
  - les PDF sont vérifiés : pas de contenu actif, pas chiffrés, 200 pages au plus ;
  - le stockage est privé et la lecture passe par des vues vérifiées.

### 1.4 Préinscription → invitation, jamais inscription

1. **Envoi :** la famille envoie la demande depuis le site. La validation est faite côté navigateur, puis dans une *server action* Next, puis par Django. Le formulaire a un champ piège (honeypot) et une limite de 5 demandes par heure.
2. **Initialisation :** seul le serveur fixe le statut `RECEIVED`, la date et la version du consentement, et la référence `PRE-AAAA-NNNN`.
3. **Examen :** il suit les transitions contrôlées : reçue → en examen → infos demandées → acceptée / refusée. Un motif est obligatoire pour refuser ou demander des informations, et une décision est définitive. Chaque étape est tracée (`PreEnrollmentEvent` et audit).
4. **Invitation :** elle n'est possible que pour une demande **acceptée**. Elle crée un compte Parent **sans enfant rattaché**, et un code d'activation (ADR 0024) qui a ces propriétés :
   - il est stocké sous forme de hash SHA-256 ;
   - il est valable 48 h et à usage unique ;
   - il est révoqué par une nouvelle invitation ;
   - il est limité à 1 invitation toutes les 5 minutes, et à 10 au total.
5. **Remise du lien :** le lien `{ISBREE_PORTAL_URL}/activation#code=…` porte le code dans le **fragment**, que le navigateur n'envoie jamais à un serveur. Il est affiché **une seule fois** à l'administrateur. **Aucun e-mail n'est envoyé :** l'établissement remet le lien lui-même.
6. **Après acceptation :** l'inscription de l'élève et le rattachement vérifié de l'enfant restent des actes manuels distincts (ADR 0026).
7. **E-mail déjà utilisé :** une adresse e-mail existante n'est jamais rattachée automatiquement (`account_exists`).

### 1.5 Portail : BFF à cookie chiffré

- **Session :**
  - les jetons Django (accès 15 min, rafraîchissement 30 j) sont dans **un** cookie chiffré A256GCM (`jose`, clé `PORTAL_SESSION_SECRET`) ;
  - ce cookie est `HttpOnly`, `SameSite=Lax` et `Secure` en HTTPS ;
  - rien n'est écrit dans `localStorage`.
- **Rafraîchissement :**
  - il a lieu dans `proxy.ts`, **une seule fois par session** même si plusieurs requêtes arrivent en parallèle (mémoire du processus, 30 s) ;
  - c'est nécessaire car Django traite la réutilisation d'un jeton de rafraîchissement comme un vol et révoque la session ;
  - limite : cette mémoire est propre au processus. **Un processus Next par portail** tant qu'un cache partagé n'est pas ajouté.
- **CSRF :** les formulaires sont des *server actions*, dont Next refuse les POST d'une autre origine. Le cookie est `SameSite=Lax`.
- **Déconnexion :** elle révoque la session dans Django.
- **Rôle :**
  - le contexte de rôle est choisi par l'URL (`/espace/parent`…) **parmi les rôles détenus**, lus dans `/auth/me/` ;
  - Django revérifie à chaque appel (`portal/context/?role=`), et un rôle non détenu donne 403 ;
  - un compte multi-rôle choisit son espace, et les données ne sont jamais mélangées.
- **Parent :** il ne voit que les enfants à lien **vérifié** et actif. Les ressources de classe exigent cet enfant ; un autre identifiant donne 404.
- **Cache :** le portail n'utilise pas Cache Components. Toutes les réponses sont `private, no-store`, avec `noindex` (méta et `X-Robots-Tag`) et `robots.txt` en `Disallow: /`. Le portail n'a pas de sitemap.

### 1.6 Applications mobiles

- **Publication :** seules les versions **publiées** d'un APK Release **signé** sont proposées, pour les rôles détenus. Le serveur refuse :
  - un APK non signé (ni v1 ni v2) ;
  - un APK signé avec un certificat « Android Debug » (vérifié sur l'APK debug réel de 197 Mo) ;
  - un `versionCode` déjà utilisé.
- **Sans version publiée :** l'application est annoncée « pas encore disponible ». Aucun faux lien n'est affiché, et il n'y a pas d'iOS.
- **Téléchargement :** il passe par le portail, qui relaie, et Django contrôle rôle, statut et débit (20/heure). Le SHA-256 est affiché pour vérification.
- **Keystore :** aucun keystore n'a été inventé. Une version Release signée suppose le keystore de l'établissement (voir `docs/isbree-web.md`).

### 1.7 Sécurité HTTP

- **CSP sans nonce** sur les deux sites : `default-src 'self'`, aucune origine externe, `frame-ancestors 'none'`, `object-src 'none'`, `form-action 'self'`. Les scripts *inline* de Next sont autorisés :
  - le site public est pré-rendu, donc un nonce par requête est impossible ;
  - le portail applique la même politique, par cohérence.
- **Autres en-têtes :** `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`. HSTS et `upgrade-insecure-requests` ne sont ajoutés qu'avec une URL `https://`.
- **Site public :**
  - contenu partagé mis en cache 1 min (`"use cache"`, `cacheLife("minutes")`) ;
  - un échec de l'API est mis en cache quelques secondes seulement, et affiché honnêtement (« momentanément indisponible ») ;
  - le sitemap ne liste que les pages publiques.

### 1.8 Identité visuelle

- **Couleurs :** bleu profond, vert naturel, ivoire, accents terracotta et ocre. Les jetons sont centralisés (`globals.css`, `@theme`) et le contraste est AA.
- **Typographies :** Fraunces (titres) et Source Sans 3 (texte), auto-hébergées par `next/font`.
- **Logo :** monogramme **provisoire** inventé (arche, soleil, pousse en forme de « I », livre ouvert). Il est présenté comme tel dans le pied de page, en attendant le logo officiel.

## 2. Conséquences

- **Administration :** le desktop PySide6 administre préinscriptions, contenus, images, ressources (PDF), lieux, applications, profil et état de publication. L'admin Django reste un outil de développement.
- **Fonctions de personnel :** l'API n'expose pas encore la liste des fonctions du personnel. Limiter une ressource à une fonction n'est donc possible que côté backend (`staff_function`).
- **Commande `isbree_readiness` :** elle liste ce qui empêche une ouverture officielle :
  - textes provisoires ou démonstration publiés ;
  - adresse non confirmée ;
  - pages légales absentes ;
  - versions Release absentes.

  Elle n'empêche jamais le travail local.
