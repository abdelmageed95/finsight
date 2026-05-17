"""Shared content-hashing helper for filing text."""

import hashlib


def content_hash(text: str) -> str:
    """Return the SHA-256 hex digest of a text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
