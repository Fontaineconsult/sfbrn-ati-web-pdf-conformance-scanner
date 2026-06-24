"""SHA-256 hashing helpers for PDF files and raw bytes."""

from __future__ import annotations

import hashlib
import os

# Read files in 1 MiB chunks so large PDFs do not have to be loaded entirely
# into memory just to be hashed.
_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | os.PathLike) -> str:
    """Return the hex SHA-256 digest of the file at ``path``.

    The file is streamed in fixed-size chunks to keep memory usage bounded
    regardless of file size.
    """
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()
