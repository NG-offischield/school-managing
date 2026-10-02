"""Token primitives (see ADR 0002 for the full design).

- Access token: short-lived (15 min), signed with SECRET_KEY by Django's
  `signing` module. It only carries the session id; on every request the
  session is re-checked in the database, so a revoked session stops working
  immediately (no "valid JWT until expiry" problem after logout).
- Refresh token: long random secret given to the client once. The server
  keeps only its SHA-256 hash. It is rotated on every refresh.
"""

import hashlib
import secrets

from django.conf import settings
from django.core import signing
from django.utils.crypto import salted_hmac

# A namespace, not a secret: the secret is SECRET_KEY. The salt only ensures a
# value signed for another purpose can never be accepted as an access token.
ACCESS_TOKEN_SALT = "accounts.access-token"  # noqa: S105


def new_refresh_token() -> str:
    # 48 random bytes ≈ 384 bits of entropy: not guessable, so a fast hash
    # (SHA-256) is enough to protect it at rest (unlike human passwords).
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_device_identifier(identifier: str) -> str:
    """Keyed hash: the raw identifier cannot be recovered or brute-forced
    without the server's SECRET_KEY."""
    return salted_hmac("accounts.device-identifier", identifier, algorithm="sha256").hexdigest()


def make_access_token(session) -> str:
    return signing.dumps({"sid": str(session.id)}, salt=ACCESS_TOKEN_SALT)


def read_access_token(token: str) -> str | None:
    """Return the session id if the token is authentic and not expired."""
    try:
        payload = signing.loads(
            token,
            salt=ACCESS_TOKEN_SALT,
            max_age=settings.ACCESS_TOKEN_LIFETIME.total_seconds(),
        )
    except signing.BadSignature:  # also covers SignatureExpired
        return None
    return payload.get("sid") if isinstance(payload, dict) else None
