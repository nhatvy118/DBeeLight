"""Symmetric encryption for OAuth tokens stored at rest in Postgres.

Tokens (Google ``access_token`` / ``refresh_token``) are user credentials —
storing them plaintext in the DB risks broad exposure if the DB is ever
dumped, backed up to insecure storage, or accessed by other workloads.

Usage:
    set ``TOKEN_ENCRYPTION_KEY`` env var to a base64-encoded 32-byte key
    (generate with ``Fernet.generate_key().decode()``).

In dev, if the key is missing, we fall back to *plaintext* with a loud
warning logged once. Production deploys MUST set the key.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_warned_no_key = False
_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    """Return a Fernet instance lazily; ``None`` when no key is configured."""
    global _fernet, _warned_no_key
    if _fernet is not None:
        return _fernet

    raw = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    if not raw:
        if not _warned_no_key:
            logger.warning(
                "TOKEN_ENCRYPTION_KEY not set — Google tokens will be stored "
                "in plaintext. Set this env var in production. Generate a key "
                "with: python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )
            _warned_no_key = True
        return None

    try:
        _fernet = Fernet(raw.encode("utf-8"))
        return _fernet
    except Exception as e:
        logger.error(
            "TOKEN_ENCRYPTION_KEY is invalid (%s). Generate a valid one with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())' — falling back to plaintext "
            "for now; tokens will NOT be encrypted at rest.", e,
        )
        return None


def encrypt_token(value: Optional[str]) -> Optional[str]:
    """Encrypt a token for storage. Returns ``None`` if input is None/empty."""
    if not value:
        return None
    f = _get_fernet()
    if f is None:
        # plaintext fallback (dev only — already warned)
        return value
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_token(value: Optional[str]) -> Optional[str]:
    """Decrypt a stored token. Returns ``None`` if input is None/empty.

    If the value isn't a valid Fernet ciphertext, treat it as plaintext
    (covers the dev-no-key case + any tokens stored before encryption was
    enabled).
    """
    if not value:
        return None
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Pre-encryption value or wrong key — fall back to raw and let the
        # caller deal with API errors if it's truly garbage.
        logger.warning("decrypt_token: value is not a valid Fernet ciphertext, using raw")
        return value
