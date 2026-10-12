"""Errors of the API client, mapped from the backend's error body (ADR 0007):

    {"success": false, "error": {"code": "...", "message": "...", "details": {...}}}

The backend message is already translated (Accept-Language: fr); the UI
shows it as is and adds the action that matters for each class:

    NetworkError      offline / server unreachable / timeout   -> retry later
    Unauthorized 401  session missing, expired or revoked      -> back to login
    Forbidden 403     role not allowed                        -> permission message
    NotFound 404      resource unavailable (or another school's) -> refresh the list
    Conflict 409      business conflict (duplicate code, in use...) -> explicit message
    ValidationFailed 400 invalid data / business rule          -> field messages
"""

from ..i18n import Tr


class ApiError(Exception):
    status = None
    default_message = Tr("Erreur inattendue du serveur.")

    def __init__(self, message=None, *, code=None, status=None, details=None):
        self.message = message or self.default_message
        self.code = code
        if status is not None:
            self.status = status
        self.details = details or {}
        super().__init__(self.message)

    @property
    def rule(self):
        """Business rule of a 400/409 (e.g. "duplicate_code"), if any."""
        return self.details.get("rule") if isinstance(self.details, dict) else None

    def field_errors(self):
        """{field: [messages]} of a validation error (400)."""
        if not isinstance(self.details, dict):
            return {}
        return {k: v for k, v in self.details.items() if isinstance(v, list)}


class NetworkError(ApiError):
    default_message = Tr("Serveur injoignable. Vérifiez la connexion réseau puis réessayez.")


class RequestTimeout(NetworkError):
    default_message = Tr("Le serveur ne répond pas (délai dépassé). Réessayez dans un instant.")


class ValidationFailed(ApiError):
    status = 400
    default_message = Tr("Données invalides.")


class Unauthorized(ApiError):
    status = 401
    default_message = Tr("Session expirée : veuillez vous reconnecter.")


class Forbidden(ApiError):
    status = 403
    default_message = Tr("Vous n'avez pas la permission d'effectuer cette action.")


class NotFound(ApiError):
    status = 404
    default_message = Tr("Ressource introuvable ou indisponible.")


class Conflict(ApiError):
    status = 409
    default_message = Tr("Conflit avec l'état actuel des données.")


class RateLimited(ApiError):
    status = 429
    default_message = Tr("Trop de tentatives. Patientez avant de réessayer.")


class ServerError(ApiError):
    status = 500
    default_message = Tr("Erreur interne du serveur.")


_BY_STATUS = {400: ValidationFailed, 401: Unauthorized, 403: Forbidden, 404: NotFound, 409: Conflict, 429: RateLimited}


def error_for(status, body):
    """Build the right ApiError from an HTTP status and the decoded body."""
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    cls = _BY_STATUS.get(status, ServerError if status >= 500 else ApiError)
    return cls(error.get("message"), code=error.get("code"), status=status, details=error.get("details"))
