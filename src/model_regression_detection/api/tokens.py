"""Bearer token generation and verification using PBKDF2-SHA256.

Token format: ``mrds_<token_id>_<secret_hex>`` where ``token_id`` is the
primary key of the ``ProjectTokenRow``, enabling O(1) lookup during auth.
"""

import hashlib
import os
import secrets

_TOKEN_PREFIX = "mrds_"  # noqa: S105
_HASH_ITERATIONS = 600_000
_SALT_LENGTH = 32
_DK_LENGTH = 32


def generate_token(token_id: str) -> tuple[str, str]:
    """Return ``(plaintext_token, pbkdf2_hash)``.

    The plaintext is returned exactly once and must be communicated to the
    caller. Only the hash is stored.
    """
    raw = secrets.token_hex(32)
    secret = f"{_TOKEN_PREFIX}{token_id}_{raw}"
    salt = os.urandom(_SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, _HASH_ITERATIONS, dklen=_DK_LENGTH)
    token_hash = salt.hex() + ":" + dk.hex()
    return secret, token_hash


def verify_token(secret: str, token_hash: str) -> bool:
    """Return True when *secret* matches the stored *token_hash*."""
    try:
        salt_hex, dk_hex = token_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except (ValueError, KeyError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), salt, _HASH_ITERATIONS, dklen=_DK_LENGTH
    )
    return actual == expected


def parse_token_id(secret: str) -> str | None:
    """Extract the token ID from a ``mrds_<id>_<secret>`` token, or None."""
    if not secret.startswith(_TOKEN_PREFIX):
        return None
    parts = secret.split("_", 2)
    if len(parts) < 3:
        return None
    return parts[1]
