"""Raw snapshot storage abstraction."""
import hashlib
import os
import uuid
from pathlib import Path

from app.config import settings
from app.logging import get_logger

logger = get_logger(__name__)


class SnapshotStorage:
    """Storage for raw snapshot content.

    Uses safe generated filenames (UUID-based) organized in date-prefixed
    subdirectories. Never derives paths directly from URLs.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.snapshot_storage_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def store(self, content: bytes, content_hash: str | None = None) -> str:
        """Store raw content and return the storage location path.

        Args:
            content: Raw bytes to store.
            content_hash: Optional pre-computed SHA-256 hash.

        Returns:
            Relative path to the stored file.
        """
        if content_hash is None:
            content_hash = hashlib.sha256(content).hexdigest()

        # Use first 4 chars of hash for directory sharding
        shard = content_hash[:4]
        filename = f"{uuid.uuid4().hex}.bin"
        rel_path = f"{shard}/{filename}"
        full_path = self.base_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "wb") as f:
            f.write(content)

        logger.debug("snapshot_stored", path=str(rel_path), size=len(content), hash=content_hash)
        return str(rel_path)

    def retrieve(self, location: str) -> bytes:
        """Retrieve raw content by location path."""
        full_path = self.base_dir / location
        # Prevent directory traversal
        resolved = full_path.resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError("Invalid snapshot location: directory traversal detected")

        with open(resolved, "rb") as f:
            return f.read()

    def compute_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()

    def delete(self, location: str) -> None:
        """Delete a stored snapshot by location path (best-effort, no error if missing)."""
        full_path = self.base_dir / location
        resolved = full_path.resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError("Invalid snapshot location: directory traversal detected")
        try:
            resolved.unlink(missing_ok=True)
        except Exception as e:
            logger.debug("snapshot_delete_failed", path=str(location), error=str(e))

    def exists(self, location: str) -> bool:
        """Check if a snapshot exists."""
        full_path = self.base_dir / location
        resolved = full_path.resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            return False
        return resolved.exists()
