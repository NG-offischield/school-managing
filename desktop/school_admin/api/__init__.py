"""API client: the only way the desktop reaches data."""

from .client import ApiClient
from .errors import ApiError

__all__ = ["ApiClient", "ApiError"]
