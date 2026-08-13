"""Single-use tokens for email verification and password reset.

Tokens are stored hashed. A database leak therefore does not let an attacker
verify addresses or reset passwords with the stolen values.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def generate_token() -> str:
    """Return a fresh URL-safe token to send to the user."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the value stored in the database for ``token``."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token against its stored hash."""
    return hmac.compare_digest(hash_token(token), stored_hash)
