"""Business rules returned by the backend (`error.details.rule`), in plain
French for the administrator. One table, used by the screens (ui/feedback.py)
and by client services (dashboard indicators)."""

RULE_MESSAGES = {
    "duplicate_code": "Ce code est déjà utilisé : choisissez-en un autre.",
    "category_in_use": "Cette catégorie est encore utilisée par des matières actives : désactivez-les d'abord.",
    "category_inactive": "Cette catégorie est inactive : choisissez une catégorie active.",
    "category_required": "Choisissez une catégorie existante.",
    "subject_in_use": "Cette matière est encore utilisée (cours en cours) : elle ne peut pas être désactivée.",
    "code_immutable": "Le code ne peut pas être modifié après la création.",
    "code_required": "Le code est obligatoire.",
    "no_current_year": "Aucune année scolaire courante n'est définie.",
    "duplicate_class_name": "Une classe porte déjà ce nom pour cette année scolaire : choisissez-en un autre.",
    "class_in_use": "Cette classe a encore des élèves inscrits ou des cours actifs : elle ne peut pas être désactivée.",
    "class_year_immutable": "L'année scolaire d'une classe ne peut pas être modifiée après sa création.",
    "year_closed": "Cette année scolaire est clôturée : ses classes ne peuvent plus être modifiées.",
    "level_inactive": "Ce niveau est inactif : choisissez un niveau actif.",
    "level_required": "Choisissez un niveau.",
    "room_inactive": "Cette salle est inactive : choisissez une salle active.",
    "room_capacity_exceeded": "La salle est trop petite pour les élèves inscrits dans la classe.",
    "name_required": "Le nom est obligatoire.",
    "academic_year_required": "Choisissez une année scolaire.",
    "duplicate_year_name": "Une année scolaire porte déjà ce nom : choisissez-en un autre.",
    "year_overlap": "Ces dates chevauchent une autre année scolaire de l'école : ajustez le début ou la fin.",
    "invalid_dates": "La date de fin doit être postérieure à la date de début.",
    "year_is_current": (
        "L'année courante ne peut pas être clôturée : définissez d'abord une autre année comme courante."
    ),
    "year_has_active_enrollments": (
        "Des élèves sont encore inscrits dans cette année : enregistrez d'abord les décisions de fin d'année."
    ),
    "year_content_outside_dates": (
        "Des périodes, présences ou séances de cette année tomberaient hors des nouvelles dates."
    ),
    "duplicate_student_number": "Ce matricule est déjà attribué à un autre élève de l'école.",
    "duplicate_registration_number": "Ce numéro d'inscription est déjà attribué à un autre élève de l'école.",
    "already_enrolled": "L'élève est déjà inscrit pour cette année scolaire : changez plutôt sa classe.",
    "class_full": "Cette classe est complète : choisissez une autre classe ou augmentez sa capacité.",
    "active_enrollment": "L'élève est encore inscrit dans une classe : retirez-le d'abord de sa classe.",
    "enrollment_closed": "Cette inscription est terminée ou retirée : elle ne peut plus être modifiée.",
    "same_class": "L'élève est déjà dans cette classe.",
    "class_other_year": "La nouvelle classe doit appartenir à la même année scolaire.",
    "withdraw_before_enrollment": "La date de retrait ne peut pas précéder la date d'inscription.",
    "class_inactive": "Cette classe est inactive : choisissez une classe active.",
    "class_required": "Choisissez une classe.",
    "student_archived": "Cet élève est archivé : réactivez-le avant de modifier sa fiche.",
    "student_not_active": "Seul un élève actif peut être inscrit.",
    "date_outside_year": "La date d'inscription doit être comprise dans l'année scolaire.",
    "birth_date_future": "La date de naissance doit être dans le passé.",
    "birth_date_invalid": "Cette date de naissance n'est pas plausible.",
    "height_invalid": "La taille doit être comprise entre 30 et 250 cm.",
    "photo_invalid": "Ce fichier n'est pas une image lisible.",
    "photo_format": "Utilisez une photo JPEG, PNG ou WebP.",
    "photo_too_large": "La photo est trop lourde (3 Mo au plus) ou trop grande.",
    "photo_too_small": "La photo est trop petite : au moins 120 pixels de côté.",
    "duplicate_employee_number": "Ce matricule est déjà attribué à un autre employé de l'école.",
    "email_in_use": "Cette adresse e-mail est déjà utilisée par un autre compte.",
    "email_required": "Indiquez une adresse e-mail valide.",
    "already_employee": "Cette personne est déjà employée par l'école.",
    "already_qualified": "L'enseignant a déjà cette matière.",
    "teacher_in_use": "L'enseignant a encore des cours actifs ou des séances à venir : réaffectez-les d'abord.",
    "qualification_in_use": "Un cours actif utilise cette matière : elle ne peut pas être retirée.",
    "primary_subject_qualification": (
        "La matière principale ne peut pas être retirée : changez d'abord de matière principale."
    ),
    "incompatible_subject": (
        "Matière incompatible avec la catégorie pédagogique de l'enseignant : une dérogation motivée est nécessaire."
    ),
    "qualification_rejected": "Cette matière a été retirée : ajoutez-la de nouveau pour qu'elle soit réévaluée.",
    "employment_not_active": "L'emploi de cette personne n'est pas actif : modifiez d'abord son statut d'emploi.",
    "subject_inactive": "Cette matière est inactive.",
    "expiry_past": "La date de fin de la dérogation doit être dans le futur.",
    "reason_required": "Indiquez le motif.",
    "duplicate_course": "Cet enseignant a déjà cette matière dans cette classe.",
    "course_coefficient_conflict": (
        "Cette matière a déjà un autre coefficient dans cette classe : utilisez le même coefficient."
    ),
    "course_identity_immutable": "La classe, la matière et l'année d'un cours ne changent pas : créez un autre cours.",
    "course_scheduled": "Ce cours est encore utilisé par le planning (créneaux en cours ou séances à venir).",
    "teacher_inactive": "Cet enseignant n'est pas actif.",
    "teacher_not_qualified": "Cet enseignant n'a pas de qualification validée pour cette matière.",
    "teacher_other_school": "Cet enseignant appartient à une autre école.",
    "subject_other_school": "Cette matière appartient à une autre école.",
    "scale_unavailable": "Ce barème ne peut pas être utilisé.",
    "planning_conflict": "Ce créneau entre en conflit avec le planning existant.",
    "already_decided": "Cette demande a déjà été traitée.",
    "break_type_invalid": "Type d'interruption inconnu.",
    "course_inactive": "Ce cours est inactif : réactivez-le dans « Cours ».",
    "invalid_decision": "Décision non valide.",
    "invalid_range": "Période trop longue : générez au plus 120 jours à la fois.",
    "invalid_times": "L'heure de fin doit être après l'heure de début.",
    "invalid_weekday": "Jour de la semaine non valide.",
    "not_substituted": "Cette séance n'a pas de remplaçant : l'enseignant prévu assure déjà la séance.",
    "outside_year": "La date est hors de l'année scolaire du cours.",
    "room_in_use": "Cette salle est encore utilisée par des créneaux ou des séances à venir.",
    "same_session": "Choisissez deux séances différentes.",
    "same_teacher": "Ce remplaçant est déjà l'enseignant de la séance.",
    "session_not_scheduled": "Cette séance n'est plus planifiée (annulée ou réalisée).",
    "slot_not_published": "Ce créneau n'est plus publié.",
    "teacher_incompatible": "Cet enseignant n'est pas autorisé pour cette matière (compatibilité).",
    "teacher_unavailable": "L'enseignant est indisponible sur ce créneau (absence validée).",
    "level_in_use": "Des classes actives d'une année ouverte utilisent ce niveau : il ne peut pas être désactivé.",
    # finance and payroll (ADR 0022)
    "idempotency_conflict": (
        "Cette demande de paiement a déjà servi pour un autre paiement : relancez une nouvelle saisie."
    ),
    "idempotency_key_required": "Identifiant de paiement manquant : relancez la saisie.",
    "invoice_has_payments": "Cette facture a déjà reçu des paiements : remboursez-les avant de l'annuler.",
    "invoice_cancelled": "Cette facture est annulée.",
    "invoice_not_payable": "Une des factures choisies n'est plus payable (payée ou annulée).",
    "invoice_other_student": "Une des factures choisies n'appartient pas à cet élève.",
    "invoice_empty": "Une facture doit avoir au moins une ligne.",
    "payment_not_refundable": "Ce paiement ne peut pas être remboursé (échoué ou déjà entièrement remboursé).",
    "refund_exceeds_payment": "Le montant dépasse ce qui reste remboursable sur ce paiement.",
    "amount_exceeds_balance": "Le montant dépasse le reste à payer des factures choisies.",
    "insufficient_balance": "Solde insuffisant pour cette opération.",
    "wallet_blocked": "Ce portefeuille est bloqué.",
    "wallet_required": "Choisissez un portefeuille.",
    "payment_reason_required": "Choisissez au moins une facture ou un motif de paiement actif.",
    "fee_type_invalid": "Ce motif de frais est invalide ou inactif.",
    "invalid_amount": "Montant invalide : un nombre positif avec au plus deux décimales.",
    "invalid_method": "Mode de paiement inconnu.",
    "period_overlap": "Cette période chevauche une autre période de paie ou reprend son nom.",
    "period_closed": "Cette période de paie est clôturée : elle ne peut plus être modifiée.",
    "period_not_settled": "Toutes les paies de la période doivent être payées ou annulées avant la clôture.",
    "payroll_already_paid": "Cette paie est déjà payée : aucun second paiement n'est possible.",
    "payroll_already_approved": "Cette paie est déjà approuvée.",
    "payroll_cancelled": "Cette paie est annulée.",
    "payroll_not_approved": "Cette paie doit d'abord être approuvée.",
    "payroll_stale": (
        "Les données ont changé depuis le calcul (séances, validations, taux ou corrections) : "
        "recalculez la période avant d'approuver."
    ),
    "session_already_paid": "Une séance de cette paie a déjà été payée.",
    "session_in_approved_payroll": "Cette séance figure dans une paie approuvée : annulez d'abord cette paie.",
    "rate_overlap": "Un taux plus récent existe déjà.",
    "rate_locked_by_payroll": "Une paie approuvée ou payée utilise déjà ce taux après cette date.",
    # communication and documents (ADR 0023)
    "attachment_corrupted": "Ce fichier est illisible ou endommagé.",
    "attachment_empty": "Ce fichier est vide.",
    "attachment_too_large": "Ce fichier dépasse la taille autorisée.",
    "attachment_type_not_allowed": "Type de fichier refusé : PDF, PNG ou JPEG uniquement (contenu vérifié).",
    "too_many_attachments": "Trop de pièces jointes (5 au maximum).",
    "client_id_conflict": "Ce message a déjà été envoyé avec un autre contenu : relancez la saisie.",
    "complaint_final": "Cette réclamation est close ou annulée : elle ne peut plus changer.",
    "complaint_not_draft": "Seul un brouillon peut être modifié.",
    "complaint_not_open": "Cette réclamation n'est plus ouverte.",
    "complaint_without_recipient": "La réclamation doit avoir un destinataire.",
    "conversation_closed": "Cette conversation est fermée.",
    "conversation_type_reserved": "Ce type de conversation est réservé.",
    "document_official": "Un document officiel est figé : il ne se regénère pas.",
    "document_source_not_final": (
        "La source n'est pas encore définitive (bulletin non validé, paiement non abouti, QR absent…)."
    ),
    "document_superseded": "Ce document a été remplacé par une version plus récente.",
    "invalid_transition": "Ce changement de statut n'est pas permis depuis l'état actuel.",
    "message_already_deleted": "Ce message est déjà masqué.",
    "message_empty": "Le message est vide.",
    "message_too_long": "Le message est trop long.",
    "no_administrator": "Aucun administrateur à qui écrire.",
    "participant_inactive": "Ce participant n'est plus actif.",
    "participants_required": "Choisissez au moins un participant.",
    "post_already_deleted": "Ce message est déjà masqué.",
    "roles_required": "Choisissez au moins un rôle.",
    "invalid_roles": "Rôle non autorisé pour le forum.",
    "student_required": "Un élève est requis pour ce type de conversation.",
    "thread_locked": "Ce sujet est verrouillé ou archivé : il n'accepte plus de réponse.",
    # account lifecycle (ADR 0024)
    "account_already_active": "Ce compte est déjà activé : l'enseignant se connecte avec son mot de passe.",
    "account_disabled": "Ce compte est suspendu : réactivez-le d'abord.",
    "account_not_disabled": "Ce compte n'est pas suspendu.",
    "no_pending_activation": "Aucun code d'activation en attente pour ce compte.",
    "cannot_disable_self": "Vous ne pouvez pas suspendre votre propre compte.",
    # parent registrations and links (ADR 0026)
    "registration_not_pending": "Cette inscription a déjà été traitée.",
    "request_not_pending": "Cette demande de rattachement n'est plus en cours.",
    "identity_mismatch": "Le numéro saisi ne correspond pas à la pièce déclarée par le parent.",
    "identity_rejected": "Vérification d'identité refusée (trop d'écarts) : refusez la demande.",
    "identity_not_verified": "Vérifiez d'abord l'identité du parent (pièce présentée à l'école).",
    "student_approval_required": "La désignation par l'élève manque (ou l'élève a refusé).",
    "rights_exceed_sponsor": "Un parent parrainé ne peut pas avoir plus de droits financiers que son parrain.",
    "sponsor_not_verified": "Le parrain n'est plus un parent vérifié de l'élève.",
    "already_linked": "Ce parent est déjà rattaché à cet élève.",
    "link_request_pending": "Une demande est déjà en cours pour cet élève.",
}


WEEKDAYS = ["", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
CONFLICT_KINDS = {"CLASS": "classe déjà occupée", "TEACHER": "enseignant déjà occupé", "ROOM": "salle déjà occupée"}


def explain_conflicts(conflicts):
    """The server's conflict list (409 planning_conflict / slot check) in plain
    French: « classe déjà occupée, salle déjà occupée — lundi 08:00–10:00 »."""
    lines = []
    for conflict in conflicts or []:
        what = ", ".join(CONFLICT_KINDS.get(k, k) for k in conflict.get("kinds", [])) or "conflit"
        if "weekday" in conflict:
            when = f"{WEEKDAYS[conflict['weekday']]} {conflict['start_time'][:5]}–{conflict['end_time'][:5]}"
        elif "scheduled_start" in conflict:
            start, end = conflict["scheduled_start"], conflict["scheduled_end"]
            when = f"le {start[8:10]}/{start[5:7]} {start[11:16]}–{end[11:16]}"
        elif "date" in conflict:
            when = f"le {conflict['date'][8:10]}/{conflict['date'][5:7]}"
        else:
            when = ""
        lines.append(f"{what} — {when}".strip(" —"))
    return " ; ".join(lines)


def explain(error):
    """Plain message of an ApiError: the rule's explanation if known, else the server message."""
    rule = getattr(error, "rule", None)
    if rule == "planning_conflict":
        context = (error.details or {}).get("context") or {}
        details = explain_conflicts(context.get("conflicts"))
        if details:
            return f"{RULE_MESSAGES[rule]} {details[0].upper()}{details[1:]}."
    return RULE_MESSAGES.get(rule, error.message)
