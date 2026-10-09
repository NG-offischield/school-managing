# Checklist : test Parent sur Pixel 7a par le réseau local

But : vérifier sur le **vrai téléphone** le parcours parent complet, avec un trafic qui passe par le Wi-Fi de la box et non par le câble USB. Les détails de configuration sont dans [mobile-lan-setup.md](mobile-lan-setup.md), les comptes et les montants dans [demo-data.md](demo-data.md).

Chaque case ne se coche qu'avec un résultat **réellement observé**.

## Constat préalable du 5 octobre 2026 (aucune modification faite)

| Point | Résultat observé |
|---|---|
| IPv4 du PC (Wi-Fi 3, passerelle 192.168.1.1) | `192.168.1.113` |
| Pixel 7a | branché, `adb devices` → `36231JEHN01676 device (Pixel_7a)` ; Android 17, API 37 |
| IP Wi-Fi du Pixel | `192.168.1.116/24` : même réseau que le PC |
| `adb reverse` | aucun (`adb reverse --list` vide) |
| Ping Pixel → PC | 2/2 réponses |
| Port 8000 depuis le Pixel | `GET http://192.168.1.113:8000/api/v1/health/` → **HTTP 200** `{"status":"ok"}` (test `nc` depuis le téléphone, par le Wi-Fi) |
| Backend | conteneurs `web`, `db`, `redis` démarrés ; `/health/` → 200 depuis le PC (127.0.0.1 et 192.168.1.113) |
| `.env` | `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.113` |
| `mobile/config/lan.json` | `API_URL=http://192.168.1.113:8000/api/v1/`, `WS_URL=ws://192.168.1.113:8000/ws/v1/realtime/` |
| APK Parent debug | construit le 05/10 à 21:41 avec `--dart-define-from-file=../../config/lan.json`, après le passage de `lan.json` à `.113` (21:33). Il vise donc `192.168.1.113:8000`. C'est une déduction à partir de l'ordre de construction : l'adresse n'est pas lisible dans l'APK. |
| Application installée sur le Pixel | **aucune** (pas de paquet `cm.schoolmanaging.*`) |
| Pare-feu Windows | Wi-Fi en profil **Public**, sans règle « School Managing API (LAN) ». Le port 8000 passe tout de même, grâce aux règles « Docker Desktop Backend » autorisées sur le profil Public. Voir mobile-lan-setup.md §6 pour restreindre cela au profil Privé. |
| Données | la base de **développement** ne contient pas encore le jeu `DEMO`. Le charger avant le test (étape 4). |

**Le test applicatif sur le Pixel n'a pas encore été réalisé.**

> **Mise à jour du 9 octobre 2026.** L'IPv4 du PC est passée à `192.168.1.102` (nouveau bail DHCP). `.env`, `lan.json` et l'APK du 05/10 visent encore `.113`. Il faut donc faire l'étape 2 (`configure_lan.ps1 -Restart`) avant le test. Le Wi-Fi est toujours en profil **Public** et la règle « School Managing API (LAN) » est toujours absente (constat en lecture seule, voir [integration-matrix.md](integration-matrix.md) § 8). Les étapes 14 bis à 14 quater ajoutent la communication et le forum.

> **Mise à jour : adresse réglable dans l'application.** Le test se fera plus tard, **sur un autre réseau local**. L'APK Parent debug est désormais construit **sans adresse compilée** : au premier lancement, il s'ouvre sur « Serveur de l'établissement ». On y saisit l'adresse affichée par `configure_lan.ps1` sur ce réseau-là, sans recompiler (étapes 6 bis et 6 ter). Les constats ci-dessus valaient pour l'ancien réseau.

## Déroulé

```
PC + téléphone même Wi-Fi
↓ IP PC
↓ backend Django
↓ port 8000 accessible
↓ APK Parent
↓ connexion → liste enfant → facture → wallet → paiement → reçu → historique
```

1. [ ] **Même Wi-Fi.** Le PC et le Pixel sont sur le Wi-Fi principal de la box (pas le réseau invité). Couper les données mobiles du Pixel.
2. [ ] **IP du PC.** Lancer `powershell -ExecutionPolicy Bypass -File mobile\tools\configure_lan.ps1 -Restart`. Noter l'interface choisie et la ligne « Adresse à saisir dans les applications ». Si le script signale plusieurs interfaces, relancer avec `-InterfaceAlias "<nom>"`.
3. [ ] **Backend.** `docker compose up -d` ; `curl http://<IPv4>:8000/api/v1/health/` → 200.
4. [ ] **Données de démonstration** dans la base utilisée par `web` (une seule fois) :
   ```powershell
   $env:DEMO_PASSWORD = Read-Host "Mot de passe des comptes de démonstration"
   docker compose exec -e DEMO_PASSWORD web python manage.py seed_demo
   Remove-Item Env:DEMO_PASSWORD
   ```
5. [ ] **Port 8000 depuis le téléphone.** Ouvrir `http://<IPv4>:8000/api/v1/health/` dans le navigateur du Pixel. Attendu : `{"success":true,"data":{"status":"ok"},…}`.
6. [ ] **APK Parent.** Installer l'APK construit **sans adresse compilée**. Il n'a pas à être reconstruit quand le réseau change :
   ```powershell
   cd mobile\apps\parent
   flutter build apk --debug          # seulement si l'APK n'existe pas encore
   adb install -r build\app\outputs\flutter-apk\app-debug.apk
   ```
   L'USB sert seulement à installer ; **pas d'`adb reverse`**.
6 bis. [ ] **Adresse du serveur dans l'application.** Au premier lancement, l'écran « Serveur de l'établissement » s'ouvre.
   1. Saisir l'adresse de l'étape 2.
   2. **« Tester la connexion ».** Sur Android 17, la fenêtre « Appareils à proximité » (réseau local) s'affiche à ce moment-là : **autoriser**.
   3. Attendu : « Serveur joignable ». Tout autre message se note tel quel : inaccessible, délai dépassé, HTTP 400, refus d'Android.
   4. « Enregistrer », puis confirmer.
6 ter. [ ] **Changement de serveur sans recompiler.**
   1. Profil → « Serveur ».
   2. Saisir une adresse fausse, par exemple un autre port, puis « Tester ». Attendu : un message d'erreur, et non un faux succès.
   3. Ressaisir la bonne adresse, « Enregistrer », puis confirmer.
   4. Attendu : l'application revient à la connexion et affiche le nouveau serveur.
7. [ ] **Lancement et réseau local.** Si Android 17 n'a pas encore demandé l'accès, il affiche « Accès au réseau local », puis la fenêtre « Appareils à proximité » : **autoriser**. L'écran de connexion affiche « Serveur : <IPv4>:8000 ».
8. [ ] **Connexion.** Compte `parent.a@demo-ecole.test` avec le mot de passe de démonstration. L'accueil s'affiche et l'icône « Connecté en direct » confirme le WebSocket.
9. [ ] **Liste enfant.** Léa Mbarga (6e A) apparaît, et elle seule.
10. [ ] **Facture.** Finance : la facture « Frais de scolarité » de Léa (numéro `F26-…` attribué par Finance), **75 000 XAF**, à payer, échéance visible.
11. [ ] **Wallet.** « Payer » → portefeuille `FAKE_ORANGE ••0101`, solde **100 000 XAF**.
12. [ ] **Paiement.** Confirmer → « Paiement réussi », référence `PAY-…`.
13. [ ] **Reçu.** « Télécharger le reçu » : le PDF s'ouvre avec le nom de l'établissement de démonstration et non le logo School Managing.
14. [ ] **Historique.** Retour à Finance : facture **Payée**, paiement dans l'historique, plus de bouton « Payer ». Solde du wallet : 25 000.
14 bis. [ ] **Notification en direct.** Le Pixel reste sur l'accueil (« Connecté en direct »). Sur le PC, le poste d'administration est connecté avec **`demo.admin`** (pas `admin`, qui est l'école `TEST01`). Dans Communication → Forum, il publie une **annonce** dans un espace école ouvert aux parents. Sur le Pixel, sans rafraîchir : le badge des notifications augmente et l'annonce apparaît dans les notifications.

14 ter. [ ] **Forum.** Sur le Pixel : Messages → onglet **Forum** → l'espace et l'annonce s'affichent. L'annonce est en lecture seule : pas de zone de réponse. Depuis le poste, publier une **discussion** ordinaire dans le même espace. Le Pixel est notifié (« Nouveau sujet : … ») et « Ouvrir la discussion » l'ouvre. Répondre depuis le Pixel : le poste reçoit la notification « Forum » en direct et voit la réponse dans la discussion.

14 quater. [ ] **Verrouillage et reconnexion.** Depuis le poste, verrouiller la discussion avec un motif. Sur le Pixel, une nouvelle réponse est refusée avec « Cette discussion est verrouillée », puis le bandeau « Verrouillé » et le motif s'affichent. Ensuite :
   1. couper le Wi-Fi du Pixel ;
   2. depuis le poste, envoyer un message au parent (Communication → Messagerie) ;
   3. rallumer le Wi-Fi.

   Attendu : le message et sa notification arrivent sans relancer l'application.

15. [ ] **Contre-épreuves, si le temps le permet :**
    - parent B (`parent.b@demo-ecole.test`) : « Solde du portefeuille insuffisant : aucun débit » ;
    - Wi-Fi coupé pendant un paiement : message, puis « Réessayer » sans second débit.
16. [ ] **Remise en état** : `docker compose exec web python manage.py seed_demo --refill-wallets`.

## Résultat

| Étape | OK / KO | Remarque |
|---|---|---|
| 1–5 réseau |  |  |
| 6–7 APK, adresse du serveur et permission |  |  |
| 8–9 connexion et enfant |  |  |
| 10–14 facture → historique |  |  |
| 14 bis–quater notifications, forum, reconnexion |  |  |
| 15 contre-épreuves |  |  |
