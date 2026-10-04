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
    "level_in_use": "Des classes actives d'une année ouverte utilisent ce niveau : il ne peut pas être désactivé.",
}


def explain(error):
    """Plain message of an ApiError: the rule's explanation if known, else the server message."""
    return RULE_MESSAGES.get(getattr(error, "rule", None), error.message)
