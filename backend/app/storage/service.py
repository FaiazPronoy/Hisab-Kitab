import shutil
import uuid
from pathlib import Path

from app.core.config import get_settings


class StorageService:
    """Files live under UUID keys, never the uploaded name. A local volume
    here; an S3 version only needs the same four methods."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or get_settings().storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def new_key(self, suffix: str = "") -> str:
        return f"{uuid.uuid4().hex}{suffix}"

    def path(self, key: str) -> Path:
        if "/" in key or "\\" in key or ".." in key:
            raise ValueError("bad storage key")
        return self.root / key

    def save_stream(self, key: str, src) -> Path:
        p = self.path(key)
        with open(p, "wb") as f:
            shutil.copyfileobj(src, f, length=1024 * 1024)
        return p

    def save_bytes(self, key: str, data: bytes) -> Path:
        p = self.path(key)
        p.write_bytes(data)
        return p

    def delete(self, key: str):
        self.path(key).unlink(missing_ok=True)


def storage() -> StorageService:
    return StorageService()
