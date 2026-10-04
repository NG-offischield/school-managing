"""Turn an exception into what the user sees (one place for every screen).

A message always has a short title (what failed, e.g. "Impossible de créer
la matière") and an understandable explanation; the technical detail (error
code, HTTP status) is secondary and never shown alone. No raw Python
exception reaches the user.
"""

from dataclasses import dataclass

from ..api.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NetworkError,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)
from ..messages import RULE_MESSAGES, explain


@dataclass(frozen=True)
class Feedback:
    kind: str  # "error" | "warning" | "info" | "success"
    title: str
    text: str
    detail: str = ""  # secondary, technical
    session_expired: bool = False
    reload: bool = False  # the list should be refreshed (stale data)


FIELD_LABELS = {"code": "Code", "name": "Nom", "category": "Catégorie", "description": "Description"}


def _detail(exc):
    parts = [p for p in (getattr(exc, "code", None), getattr(exc, "rule", None)) if p]
    status = getattr(exc, "status", None)
    if status:
        parts.append(f"HTTP {status}")
    return " · ".join(parts)


def describe(exc, action=None):
    """`action`: what the user was doing, e.g. "Impossible de créer la matière"."""
    if isinstance(exc, Unauthorized):
        return Feedback("warning", "Session expirée", exc.message, session_expired=True)
    if isinstance(exc, NetworkError):
        return Feedback("error", action or "Serveur injoignable", exc.message, _detail(exc))
    if isinstance(exc, Forbidden):
        return Feedback("error", action or "Permission refusée", f"Permission refusée : {exc.message}", _detail(exc))
    if isinstance(exc, NotFound):
        return Feedback(
            "warning",
            action or "Ressource indisponible",
            f"{exc.message} La liste va être actualisée.",
            _detail(exc),
            reload=True,
        )
    if isinstance(exc, Conflict):
        return Feedback(
            "warning", action or "Conflit", explain(exc), _detail(exc), reload=exc.rule != "planning_conflict"
        )
    if isinstance(exc, ValidationFailed):
        if exc.rule in RULE_MESSAGES:
            return Feedback("warning", action or "Données invalides", explain(exc), _detail(exc))
        lines = [f"{FIELD_LABELS.get(k, k)} : {' '.join(v)}" for k, v in exc.field_errors().items()]
        text = exc.message if not lines else f"{exc.message} " + " · ".join(lines)
        return Feedback("warning", action or "Données invalides", text, _detail(exc))
    if isinstance(exc, RateLimited):
        return Feedback("warning", action or "Patientez", exc.message, _detail(exc))
    if isinstance(exc, ApiError):
        return Feedback("error", action or "Erreur du serveur", exc.message, _detail(exc))
    return Feedback(
        "error",
        action or "Erreur inattendue",
        "Une erreur imprévue est survenue. Réessayez ; si elle persiste, contactez le support.",
        type(exc).__name__,
    )
