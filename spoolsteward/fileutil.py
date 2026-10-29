"""File helpers shared by more than one part of the application."""

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, read in 1 MiB blocks so a big archive never sits in memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
