from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from weld_data_workbench.errors import UnsafeArchiveError
from weld_data_workbench.io.archive import extract_tar_safely, inspect_tar


def test_safe_archive_extract(tmp_path: Path) -> None:
    archive = tmp_path / "safe.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        payload = b"hello"
        info = tarfile.TarInfo("root/file.txt")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))

    members = list(inspect_tar(archive))
    assert members[0].name == "root/file.txt"
    destination = tmp_path / "out"
    assert extract_tar_safely(archive, destination) == 1
    assert (destination / "root/file.txt").read_text() == "hello"


def test_archive_traversal_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as handle:
        payload = b"bad"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))

    with pytest.raises(UnsafeArchiveError):
        extract_tar_safely(archive, tmp_path / "out")
