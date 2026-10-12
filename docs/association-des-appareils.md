# Association des appareils — note technique (phase K, non implémentée)

Statut : **proposition pour une phase future**. Rien de ce document n'est
implémenté ; aucune clé, aucun secret ni aucun identifiant n'est ajouté au code.

## Ce qui existe aujourd'hui

- Chaque client (poste d'administration Windows, applications Parent,
  Enseignant, Personnel, Gardien) se connecte avec **le compte d'une personne**
  (identifiant + mot de passe, ou code d'activation à usage unique).
- Le serveur délivre des jetons de session liés à un appareil déclaré
  (`identifier`, nom, plateforme) ; « Mon compte » liste ces sessions et permet
  de les fermer (session courante comprise).
- Le poste d'administration ne garde que le jeton de rafraîchissement, dans le
  coffre sécurisé du système (jamais le mot de passe).

## Ce qui est écarté

**Aucune clé globale partagée** (« clé d'administration » commune à tous les
postes, mot de passe d'installation, secret compilé dans une application) :
une fuite unique compromettrait toutes les écoles et ne pourrait pas être
révoquée poste par poste.

## Principe proposé : un justificatif par installation

1. **Enrôlement** : l'administrateur, connecté avec son propre compte, génère un
   code d'association court, à usage unique et de courte durée (ex. 10 minutes)
   pour UN appareil ; le code est saisi sur l'appareil.
2. **Justificatif propre à l'installation** : l'appareil crée lui-même une paire
   de clés (Keystore Android / coffre Windows) ; le serveur n'enregistre que la
   clé publique, l'école, le rôle autorisé (ex. « borne gardien ») et l'auteur de
   l'association. La clé privée ne quitte jamais l'appareil.
3. **Révocation** : chaque appareil associé est listé côté administration ;
   révoquer l'un ferme ses sessions sans toucher aux autres.
4. **Rotation** : le justificatif est renouvelé périodiquement (et à chaque mise
   à jour majeure) ; l'ancien reste valable un court délai de recouvrement.
5. **Expiration** : une association non utilisée pendant N jours expire et doit
   être refaite ; un code d'association non utilisé expire de lui-même.
6. **Transport** : HTTPS obligatoire hors réseau de développement (le poste
   d'administration avertit déjà d'une connexion non chiffrée vers un autre
   poste) ; pas d'adresse IP figée dans le code.
7. **Traçabilité** : association, rotation, révocation et refus sont journalisés
   (qui, quand, quel appareil), comme les autres opérations d'administration.

## Points à trancher avant implémentation

- Rôles concernés (bornes gardien partagées ? postes de secrétariat ?).
- Durées : validité du code d'association, période de rotation, délai d'expiration.
- Combinaison avec le compte personnel : l'association autorise l'appareil, la
  personne s'authentifie toujours elle-même.
- Procédure en cas de perte ou de vol (révocation à distance, alerte).
