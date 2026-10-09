/// Business rules and error codes of the API, in plain French for the user.
/// The server decides; these sentences only explain its answer.
library;

import 'api/api_error.dart';

const ruleMessages = <String, String>{
  // sessions / attendance (ADR 0012, 0014)
  'session_not_started': 'La séance n\'a pas encore commencé : déclarez votre présence après le début.',
  'session_cancelled': 'Cette séance est annulée.',
  'checkin_already_verified': 'Cette séance a déjà été vérifiée par l\'administration.',
  'invalid_status': 'Choix invalide.',
  // communication (ADR 0015)
  'conversation_closed': 'Cette conversation est fermée.',
  'message_empty': 'Le message est vide.',
  'attachment_type_not_allowed': 'Type de fichier refusé : PDF, PNG ou JPEG uniquement.',
  'complaint_final': 'Cette réclamation est close ou annulée.',
  'invalid_transition': 'Ce changement de statut n\'est pas permis.',
  'reason_required': 'Indiquez le motif.',
  // parent registration and linking (ADR 0026)
  'student_not_found':
      'Aucun élève ne correspond à ce matricule et à cette date de naissance. Vérifiez-les sur un document scolaire.',
  'already_linked': 'Vous êtes déjà rattaché(e) à cet élève.',
  'link_request_pending': 'Une demande est déjà en cours pour cet élève.',
  'request_not_pending': 'Cette demande n\'est plus en cours.',
  'document_number_invalid': 'Numéro de pièce d\'identité invalide.',
  'sponsor_code_invalid': 'Code de parrainage invalide ou expiré. Demandez un nouveau code au parent vérifié.',
  'already_sponsored': 'Cette demande est déjà parrainée.',
  // forum (ADR 0015)
  'thread_locked': 'Cette discussion est verrouillée : on ne peut plus y répondre.',
  'title_required': 'Indiquez un titre.',
  'body_required': 'Le message est vide.',
  'post_already_deleted': 'Ce message a déjà été retiré.',
  // finance (ADR 0013): the server decides, the app only explains
  'idempotency_conflict':
      'Cette demande de paiement a déjà servi pour un autre paiement : recommencez depuis la facture.',
  'invoice_not_payable': 'Cette facture n\'est plus à payer (déjà réglée ou annulée).',
  'amount_exceeds_balance': 'Le montant dû a changé entre-temps : rechargez la facture.',
  'invoice_other_student': 'Cette facture ne concerne pas cet enfant.',
  'wallet_required': 'Choisissez un portefeuille mobile.',
  'payment_reason_required': 'Choisissez la facture à régler.',
  'document_source_not_final': 'Ce document n\'est pas encore disponible (bulletin non validé, paiement non abouti).',
};

const codeMessages = <String, String>{
  'INVALID_CREDENTIALS': 'Identifiant ou mot de passe incorrect (ou compte suspendu).',
  'INVALID_REFRESH_TOKEN': 'Votre session a expiré : reconnectez-vous.',
  'INVALID_ACCESS_TOKEN': 'Votre session a expiré : reconnectez-vous.',
  'NOT_AUTHENTICATED': 'Votre session a expiré : reconnectez-vous.',
  'INVALID_ACTIVATION_CODE':
      'Ce code d\'activation est invalide, expiré ou déjà utilisé. Demandez un nouveau code à l\'administration.',
  'NO_ACTIVE_MEMBERSHIP':
      'Votre compte n\'est pas actif dans cet établissement (suspendu ?). Contactez l\'administration.',
  'PERMISSION_DENIED': 'Vous n\'avez pas accès à cette information.',
  'NOT_FOUND': 'Élément introuvable (ou non visible avec vos droits).',
  'RATE_LIMITED': 'Trop de tentatives : patientez une minute puis réessayez.',
  'NETWORK': 'Connexion au serveur impossible. Vérifiez votre réseau.',
  'TIMEOUT': 'Le serveur ne répond pas. Réessayez dans un instant.',
};

String explain(ApiException error) {
  final rule = error.rule;
  if (rule != null && ruleMessages.containsKey(rule)) return ruleMessages[rule]!;
  if (codeMessages.containsKey(error.code)) return codeMessages[error.code]!;
  if (error.status >= 500) return 'Le serveur a rencontré une erreur. Réessayez plus tard.';
  return error.message;
}
