"""Turn an exception into what the user sees (one place for every screen)."""

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


@dataclass(frozen=True)
class Feedback:
    kind: str  # "error" | "warning" | "info" | "success"
    title: str
    text: str
    session_expired: bool = False
    reload: bool = False  # the list should be refreshed (stale data)


FIELD_LABELS = {"code": "Code", "name": "Nom", "category": "Catégorie", "description": "Description"}


def describe(exc):
    if isinstance(exc, Unauthorized):
        return Feedback("warning", "Session expirée", exc.message, session_expired=True)
    if isinstance(exc, NetworkError):
        return Feedback("error", "Hors ligne", exc.message)
    if isinstance(exc, Forbidden):
        return Feedback("error", "Permission refusée", exc.message)
    if isinstance(exc, NotFound):
        return Feedback("warning", "Ressource indisponible", f"{exc.message} La liste va être actualisée.", reload=True)
    if isinstance(exc, Conflict):
        return Feedback("warning", "Conflit", exc.message, reload=True)
    if isinstance(exc, ValidationFailed):
        fields = exc.field_errors()
        lines = [f"• {FIELD_LABELS.get(k, k)} : {' '.join(v)}" for k, v in fields.items()]
        return Feedback("warning", "Données invalides", "\n".join([exc.message, *lines]) if lines else exc.message)
    if isinstance(exc, RateLimited):
        return Feedback("warning", "Patientez", exc.message)
    if isinstance(exc, ApiError):
        return Feedback("error", "Erreur", exc.message)
    return Feedback("error", "Erreur inattendue", f"{type(exc).__name__}: {exc}")
