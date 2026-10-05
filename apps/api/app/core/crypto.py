"""Encryption of what students say and what MAYA notes about them (spec §28, §30; docs/design/
03-memory-schema.md): messages, memories, constraints, summaries, emotion readings, guardians' contacts.

Fernet (AES-128-CBC with an HMAC) with a key the database never sees: MEMORY_ENCRYPTION_KEY, or, if
that isn't set, a key file made on first use (MEMORY_KEY_PATH, readable by this user only). A dump of
the database, or a backup of it, then reads as ciphertext. Losing the key loses the data: back the key
up separately from the database.

What stays readable: embeddings (they have to be searched), and labels such as interests and goal
titles, which the student sees on screen and MAYA matches by name.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

PREFIX = "enc1:"
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.memory_encryption_key:
        return Fernet(settings.memory_encryption_key.encode())
    path = Path(settings.memory_key_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
        logger.warning("made a new encryption key at %s — back it up: without it, students' data can't be read", path)
    return Fernet(path.read_bytes().strip())


def encrypt(text: str) -> str:
    if text.startswith(PREFIX):
        return text  # already encrypted (re-saving a row that was read raw)
    return PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(text: str) -> str:
    if not text.startswith(PREFIX):
        return text  # written before encryption
    try:
        return _fernet().decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("a value couldn't be decrypted: wrong MEMORY_ENCRYPTION_KEY?")
        return ""
