from __future__ import annotations

import shutil
import tarfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..errors import UnsafeArchiveError
from .paths import is_relative_to


@dataclass(slots=True, frozen=True)
class ArchiveMemberInfo:
    name: str
    size_bytes: int
    member_type: str


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isdir():
        return "directory"
    if member.isfile():
        return "file"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    return "other"


def inspect_tar(path: Path) -> Iterator[ArchiveMemberInfo]:
    with tarfile.open(path, mode="r:*") as archive:
        for member in archive:
            yield ArchiveMemberInfo(
                name=member.name,
                size_bytes=int(member.size),
                member_type=_member_type(member),
            )


def _validated_destination(destination: Path, member: tarfile.TarInfo) -> Path:
    name_path = Path(member.name)
    if name_path.is_absolute() or ".." in name_path.parts:
        raise UnsafeArchiveError(f"Unsafe archive member path: {member.name}")
    output = (destination / name_path).resolve(strict=False)
    if not is_relative_to(output, destination):
        raise UnsafeArchiveError(f"Archive member escapes destination: {member.name}")
    if member.issym() or member.islnk():
        raise UnsafeArchiveError(f"Archive links are rejected by default: {member.name}")
    if not (member.isdir() or member.isfile()):
        raise UnsafeArchiveError(f"Unsupported archive member type: {member.name}")
    return output


def extract_tar_safely(
    archive_path: Path,
    destination: Path,
    *,
    overwrite: bool = False,
    progress: Callable[[int, ArchiveMemberInfo], None] | None = None,
) -> int:
    archive_path = archive_path.expanduser().resolve()
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    count = 0
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive:
            output = _validated_destination(destination, member)
            info = ArchiveMemberInfo(member.name, int(member.size), _member_type(member))

            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() and not overwrite:
                    count += 1
                    if progress:
                        progress(count, info)
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise UnsafeArchiveError(f"Unable to read archive member: {member.name}")
                temporary = output.with_name(output.name + ".partial")
                with source, temporary.open("wb") as target:
                    shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
                temporary.replace(output)

            count += 1
            if progress:
                progress(count, info)
    return count
