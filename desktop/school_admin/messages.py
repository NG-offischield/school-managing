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
}


def explain(error):
    """Plain message of an ApiError: the rule's explanation if known, else the server message."""
    return RULE_MESSAGES.get(getattr(error, "rule", None), error.message)
