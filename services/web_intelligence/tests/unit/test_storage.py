"""Tests for snapshot storage."""
import hashlib

import pytest

from app.storage.snapshot_storage import SnapshotStorage


def test_store_and_retrieve(tmp_path):
    storage = SnapshotStorage(base_dir=tmp_path)
    content = b"test snapshot content"
    path = storage.store(content)
    assert storage.exists(path)
    retrieved = storage.retrieve(path)
    assert retrieved == content


def test_compute_hash():
    storage = SnapshotStorage(base_dir=__import__("pathlib").Path("/tmp"))
    content = b"hello world"
    h = storage.compute_hash(content)
    expected = hashlib.sha256(content).hexdigest()
    assert h == expected


def test_directory_traversal_prevention(tmp_path):
    storage = SnapshotStorage(base_dir=tmp_path)
    with pytest.raises(ValueError):
        storage.retrieve("../../../etc/passwd")


def test_safe_filename_not_derived_from_url(tmp_path):
    storage = SnapshotStorage(base_dir=tmp_path)
    content = b"content"
    path = storage.store(content)
    assert "http" not in path
    assert "://" not in path
    assert len(path.split("/")[-1].replace(".bin", "")) == 32
