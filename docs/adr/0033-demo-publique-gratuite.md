# ADR 0033 — Démo publique gratuite et publication du dépôt

- **Statut :** accepté — 2026-10-15
- **Périmètre :**
  - publication du dépôt sur GitHub (portfolio) ;
  - préproduction de **démonstration** du site ISBREE, de l'Espace ISBREE et de l'API, à **0 FCFA**.
- **Hors périmètre :**
  - ouverture officielle aux familles et données réelles ;
  - builds Release signés et stores ;
  - domaine personnalisé et services payants.

## 1. Hébergement : fournisseurs et raisons

Conditions vérifiées le 15/10/2026 sur les pages officielles. Elles sont à revérifier au moment de créer les comptes.

| Besoin | Choix | Raison | Limites acceptées pour une démo |
|---|---|---|---|
| PostgreSQL | **Neon Free** | 0 $, sans carte, permanent | 1 Go, 100 h de calcul par mois, veille après 5 min, 6 h d'historique de restauration |
| API Django, portail, site | **Render Free** (`render.yaml`) | services web gratuits, image Docker possible | veille après 15 min (environ 1 min au réveil), 750 h par mois partagées, pas de disque persistant, instances « pas pour la production » |
| Redis | **Render Key Value Free** | même réseau interne que l'API | en mémoire seulement : compteurs et cache perdus au redémarrage |

Rejeté : **Render Postgres Free**. La base expire 30 jours après sa création, ce qui ne convient pas à une démo de portfolio durable.

**Risque connu :** Render peut demander une carte comme « vérification anti-fraude ». La règle du projet est alors d'**arrêter** : `docs/deploiement-demo.md` décrit un plan B.

## 2. Audit avant publication du dépôt (15/10/2026)

Les 864 chemins de l'historique ont été inspectés, ainsi que le contenu de **tous** les commits (`git log -p --all`, 70 commits, 1 tag).

- **Fichiers sensibles :** aucun `.env` réel, dump, sauvegarde SQL, APK, AAB, keystore, certificat, journal, dossier de build ou upload privé, sur aucun commit.
- **Secrets locaux :** les valeurs réelles des fichiers ignorés (`.env`, `.env.isbree.local`, `.env.local` des deux applications) ont été recherchées dans tout l'historique. Les seules présentes sont des valeurs non secrètes (URL locales, nom du module de réglages, URL Redis locale). Aucune clé, aucun jeton, aucun mot de passe.
- **Formes connues de clés :** aucune clé privée, clé AWS ou Google, ni jeton GitHub ou Slack.
- **Mots de passe en dur :** seulement des valeurs de tests (fixtures).
- **Données personnelles :** les seules adresses réelles sont celle de l'auteur (commits) et le contact public accepté pour ISBREE. Les autres domaines (`ecole.test`, `example.cm`…) sont des données de test. La spécification `.docx` ne contient ni e-mail, ni téléphone, ni auteur dans ses métadonnées.
- **Adresses IP privées :** il y en a dans les comptes rendus de tests réseau local (`docs/`) et dans les tests unitaires. Elles sont privées (RFC 1918), injoignables depuis Internet, et ne sont pas codées en dur dans les applications. Risque jugé faible : conservées.

**Conclusion :** l'historique peut être publié tel quel. Aucune réécriture et aucun secret à révoquer.

## 3. Garde-fous de la démo

- **Réglages `config.settings.demo` :**
  - ils reprennent tout `production.py` : DEBUG désactivé, HTTPS, cookies `Secure`, HSTS ;
  - `ISBREE_PUBLIC_DEMO = True` ;
  - base distante en TLS (`POSTGRES_SSLMODE=require`) ;
  - hôte Render ajouté à `ALLOWED_HOSTS` ;
  - contrôle de santé exempté de la redirection HTTPS.
- **Comptes de démonstration en lecture seule** (`common/demo.py`) :
  - le mot de passe partagé des comptes Parent, Enseignant, Personnel et Gardien est publié ;
  - toute requête qui modifie quelque chose (POST, PUT, PATCH, DELETE) est refusée (403 `DEMO_READ_ONLY`), sauf la connexion, le rafraîchissement de session et la déconnexion. Un visiteur ne peut donc ni changer le mot de passe commun, ni déconnecter les autres, ni écrire des messages ;
  - les lectures restent soumises aux permissions habituelles : le garde-fou ne fait que **retirer** des droits.
- **Administrateur jamais partagé :** avec les réglages de démo, `seed_isbree` refuse de s'exécuter si `ISBREE_ADMIN_PASSWORD` est absent ou égal au mot de passe partagé. Avant ce garde-fou, l'administrateur recevait le même mot de passe que les comptes de démonstration.
- **Données :**
  - une base **neuve** est créée par `seed_isbree --demo`, avec uniquement des données fictives, marquées « Démonstration » ;
  - ni import, ni copie de la base de développement, ni identifiant existant.
- **Préinscription :** le formulaire affiche, en mode démo, qu'il n'est **pas** le système d'admission et qu'il ne faut saisir que des données fictives. Les demandes restent dans la base de démo et ne sont jamais transmises à l'établissement.
- **Portail :**
  - les identifiants des comptes de démonstration et le mot de passe commun sont affichés sur la page de connexion, uniquement si `ISBREE_DEMO_MODE=true` **et** `ISBREE_DEMO_SHARED_PASSWORD` sont définis ;
  - la valeur vient de l'environnement de l'hébergeur et ne figure jamais dans Git.
- **Secrets :** ils sont générés par l'hébergeur (`generateValue`) ou saisis dans son tableau de bord. Ils sont distincts de ceux du développement et n'apparaissent dans aucun fichier.

## 4. Conséquences

- La démo n'est **pas** la production : contenus provisoires, données fictives, aucune garantie de disponibilité, aucune sauvegarde automatique durable.
- Le premier accès après une période d'inactivité est lent (veille), ce que le README doit annoncer.
- Restent à confirmer **sur la démo en ligne**, après déploiement :
  - l'adresse visiteur transmise derrière le proxy de Render (`ISBREE_TRUSTED_PROXY_HOPS`) ;
  - l'hôte utilisé par le contrôle de santé.
