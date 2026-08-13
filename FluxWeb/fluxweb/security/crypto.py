"""Symmetric encryption for stored panel credentials.

Differences from the previous implementation (audit C-1, H-15):

* The key comes from a dedicated ``ENCRYPTION_KEY``, not from ``SECRET_KEY``.
  Rotating the session key no longer makes stored credentials unreadable, and
  a leaked session key no longer decrypts them.
* No PBKDF2-over-a-static-salt step. ``ENCRYPTION_KEY`` is a real Fernet key.
* Decryption failure raises instead of returning the ciphertext as if it were
  the plaintext, which previously showed users a base64 blob labelled as their
  password.
"""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

log = logging.getLogger(__name__)


def _fernet() -> Fernet:
    key = current_app.extensions["flux_config"].encryption_key
    # Cache per app instance; building a Fernet parses and validates the key.
    cache = current_app.extensions.setdefault("flux_fernet_cache", {})
    if key not in cache:
        cache[key] = Fernet(key.encode() if isinstance(key, str) else key)
    return cache[key]


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a value for storage. ``None``/empty passes through unchanged."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a stored value.

    Returns ``None`` when the value cannot be decrypted (wrong key, or a value
    written before encryption existed). Callers must treat ``None`` as "no
    credential available" and offer a regeneration path.
    """
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        log.warning("Could not decrypt a stored credential; ENCRYPTION_KEY may have changed.")
        return None
