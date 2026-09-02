"""File storage behind a small interface.

Uploaded statements are written under a key the application generates, never
under a name the browser supplied, and are read back only through this module.
That keeps a crafted filename from escaping the storage directory, and leaves
one place to swap in S3 later."""
from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from app.core.config import settings

SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    cleaned = SAFE.sub("_", Path(name).name).strip("._") or "upload.pdf"
    return cleaned[:120]


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def load(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalStorage(StorageBackend):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError("Refusing to touch a path outside the storage directory.")
        return target

    def save(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        # Only the local backend ships today; the interface is what makes an
        # S3 implementation a drop-in rather than a rewrite.
        _backend = LocalStorage(settings.storage_path)
    return _backend


def statement_key(bank_code: str, when: date | None, original_name: str) -> str:
    stamp = (when or date.today()).strftime("%Y/%m")
    return f"statements/{safe_filename(bank_code)}/{stamp}/{uuid.uuid4().hex}_{safe_filename(original_name)}"
