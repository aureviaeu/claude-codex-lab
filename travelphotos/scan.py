"""Find media files, read their clues, and detect exact duplicates."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime

from . import metadata, similarity


@dataclass
class MediaFile:
    id: str  # path relative to the input folder, with forward slashes
    path: str  # absolute path
    kind: str  # "photo" or "video"
    size: int
    sha256: str
    time: datetime | None = None
    time_source: str | None = None
    dhash: int | None = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


@dataclass
class Duplicate:
    file: MediaFile
    duplicate_of: str  # id of the kept file


@dataclass
class ScanResult:
    input_dir: str
    files: list[MediaFile] = field(default_factory=list)  # unique files
    duplicates: list[Duplicate] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # ids of unsupported files

    @property
    def total_media(self) -> int:
        return len(self.files) + len(self.duplicates)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_media(input_dir: str):
    """Yield (id, absolute path) for every file under input_dir, sorted."""
    for root, dirs, files in os.walk(input_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, input_dir).replace(os.sep, "/")
            yield rel, path


def scan(input_dir: str, compute_hash: bool = True) -> ScanResult:
    """Scan input_dir. Files are only read, never written."""
    input_dir = os.path.abspath(input_dir)
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"找不到資料夾：{input_dir}")
    result = ScanResult(input_dir=input_dir)
    by_hash: dict[str, MediaFile] = {}
    for rel, path in iter_media(input_dir):
        kind = metadata.media_kind(path)
        if kind is None:
            result.skipped.append(rel)
            continue
        digest = _sha256(path)
        item = MediaFile(id=rel, path=path, kind=kind, size=os.path.getsize(path), sha256=digest)
        kept = by_hash.get(digest)
        if kept is not None:
            result.duplicates.append(Duplicate(file=item, duplicate_of=kept.id))
            continue
        by_hash[digest] = item
        item.time, item.time_source = metadata.embedded_datetime(path)
        if item.time is None:
            name_time = metadata.filename_datetime(os.path.basename(path))
            if name_time is not None:
                item.time, item.time_source = name_time, metadata.SOURCE_FILENAME
        if kind == "photo" and compute_hash:
            item.dhash = similarity.dhash(path)
        result.files.append(item)
    return result
