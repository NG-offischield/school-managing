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
    "level_in_use": "Des classes actives d'une année ouverte utilisent ce niveau : il ne peut pas être désactivé.",
}


def explain(error):
    """Plain message of an ApiError: the rule's explanation if known, else the server message."""
    return RULE_MESSAGES.get(getattr(error, "rule", None), error.message)
