"""Password storage."""

import hashlib


def hash_password(password: str) -> str:
    """Return the value stored in the database for this password."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()
