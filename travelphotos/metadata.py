"""Read capture times from file contents and file names.

Only the file contents and the file name are used. The file system
modification time is never used, because saving from LINE rewrites it.
"""

from __future__ import annotations

import re
import struct
from datetime import datetime, timedelta, timezone

# Confidence levels and basis keys used across the package.
SOURCE_EXIF = "exif"
SOURCE_CONTAINER = "container"
SOURCE_FILENAME = "filename"

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}

_TIFF_ASCII = 2
_TAG_DATETIME = 0x0132
_TAG_EXIF_IFD = 0x8769
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME_DIGITIZED = 0x9004
_TAG_SUBSEC_ORIGINAL = 0x9291

_MP4_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
_MIN_YEAR = 2000
_MAX_YEAR = 2100
# Cap how much of a HEIC file is searched for an Exif block.
_HEIC_SCAN_LIMIT = 64 * 1024 * 1024


def _plausible(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if not (_MIN_YEAR <= dt.year < _MAX_YEAR):
        return None
    return dt


def _parse_exif_datetime(raw: str, subsec: str | None = None) -> datetime | None:
    raw = raw.strip().rstrip("\x00").strip()
    try:
        dt = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if subsec:
        digits = "".join(ch for ch in subsec if ch.isdigit())[:6]
        if digits:
            dt = dt.replace(microsecond=int(digits.ljust(6, "0")))
    return _plausible(dt)


def parse_tiff_datetime(tiff: bytes) -> datetime | None:
    """Return the capture time stored in a TIFF/Exif block, or None."""
    if len(tiff) < 8:
        return None
    order = tiff[:2]
    if order == b"II":
        end = "<"
    elif order == b"MM":
        end = ">"
    else:
        return None
    try:
        if struct.unpack(end + "H", tiff[2:4])[0] != 42:
            return None
        ifd0 = struct.unpack(end + "I", tiff[4:8])[0]
        main = _read_ifd(tiff, ifd0, end)
        exif_ifd = {}
        pointer = main.get(_TAG_EXIF_IFD)
        if isinstance(pointer, int):
            exif_ifd = _read_ifd(tiff, pointer, end)
    except (struct.error, IndexError):
        return None

    def text(ifd: dict, tag: int) -> str | None:
        value = ifd.get(tag)
        return value if isinstance(value, str) else None

    subsec = text(exif_ifd, _TAG_SUBSEC_ORIGINAL)
    for ifd, tag in (
        (exif_ifd, _TAG_DATETIME_ORIGINAL),
        (exif_ifd, _TAG_DATETIME_DIGITIZED),
        (main, _TAG_DATETIME),
    ):
        raw = text(ifd, tag)
        if raw:
            dt = _parse_exif_datetime(raw, subsec if tag == _TAG_DATETIME_ORIGINAL else None)
            if dt:
                return dt
    return None


def _read_ifd(tiff: bytes, offset: int, end: str) -> dict:
    """Read the ASCII and LONG entries of one IFD."""
    values: dict = {}
    if offset <= 0 or offset + 2 > len(tiff):
        return values
    count = struct.unpack(end + "H", tiff[offset:offset + 2])[0]
    for i in range(min(count, 512)):
        entry = offset + 2 + i * 12
        if entry + 12 > len(tiff):
            break
        tag, typ, n = struct.unpack(end + "HHI", tiff[entry:entry + 8])
        payload = tiff[entry + 8:entry + 12]
        if typ == _TIFF_ASCII:
            if n <= 4:
                data = payload[:n]
            else:
                start = struct.unpack(end + "I", payload)[0]
                data = tiff[start:start + n]
            values[tag] = data.split(b"\x00", 1)[0].decode("ascii", "replace")
        elif typ == 4 and n == 1:  # LONG
            values[tag] = struct.unpack(end + "I", payload)[0]
    return values


def _exif_from_jpeg(path: str) -> bytes | None:
    with open(path, "rb") as fh:
        if fh.read(2) != b"\xff\xd8":
            return None
        while True:
            marker = fh.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                return None
            kind = marker[1]
            if kind in (0xD9, 0xDA):  # end of image / start of scan
                return None
            if kind == 0x01 or 0xD0 <= kind <= 0xD7:
                continue
            length_raw = fh.read(2)
            if len(length_raw) < 2:
                return None
            length = struct.unpack(">H", length_raw)[0]
            if length < 2:
                return None
            data = fh.read(length - 2)
            if kind == 0xE1 and data.startswith(b"Exif\x00\x00"):
                return data[6:]


def _exif_from_png(path: str) -> bytes | None:
    with open(path, "rb") as fh:
        if fh.read(8) != b"\x89PNG\r\n\x1a\n":
            return None
        while True:
            head = fh.read(8)
            if len(head) < 8:
                return None
            length, kind = struct.unpack(">I4s", head)
            if kind == b"eXIf":
                data = fh.read(length)
                if data.startswith(b"Exif\x00\x00"):
                    data = data[6:]
                return data
            if kind == b"IEND":
                return None
            fh.seek(length + 4, 1)  # data + CRC


def _exif_from_heic(path: str) -> bytes | None:
    with open(path, "rb") as fh:
        data = fh.read(_HEIC_SCAN_LIMIT)
    start = 0
    while True:
        idx = data.find(b"Exif\x00\x00", start)
        if idx < 0:
            return None
        tiff = data[idx + 6:]
        if tiff[:4] in (b"II*\x00", b"MM\x00*"):
            return tiff
        start = idx + 1


def _iter_boxes(fh, start: int, stop: int):
    pos = start
    while pos + 8 <= stop:
        fh.seek(pos)
        head = fh.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head)
        header = 8
        if size == 1:
            big = fh.read(8)
            if len(big) < 8:
                return
            size = struct.unpack(">Q", big)[0]
            header = 16
        elif size == 0:
            size = stop - pos
        if size < header:
            return
        yield kind, pos + header, pos + size
        pos += size


def container_datetime(path: str) -> datetime | None:
    """Return the MP4/MOV `mvhd` creation time as local time, or None."""
    import os

    stop = os.path.getsize(path)
    try:
        with open(path, "rb") as fh:
            for kind, body, end in _iter_boxes(fh, 0, stop):
                if kind != b"moov":
                    continue
                for sub, sbody, _send in _iter_boxes(fh, body, end):
                    if sub != b"mvhd":
                        continue
                    fh.seek(sbody)
                    version = fh.read(4)[:1]
                    if version == b"\x01":
                        raw = fh.read(8)
                        seconds = struct.unpack(">Q", raw)[0] if len(raw) == 8 else 0
                    else:
                        raw = fh.read(4)
                        seconds = struct.unpack(">I", raw)[0] if len(raw) == 4 else 0
                    if not seconds:
                        return None
                    try:
                        utc = _MP4_EPOCH + timedelta(seconds=seconds)
                    except OverflowError:
                        return None
                    return _plausible(utc.astimezone().replace(tzinfo=None))
    except (OSError, struct.error):
        return None
    return None


def embedded_datetime(path: str) -> tuple[datetime | None, str | None]:
    """Return (capture time, source) read from the file contents."""
    ext = _ext(path)
    try:
        if ext in (".jpg", ".jpeg"):
            tiff = _exif_from_jpeg(path)
        elif ext == ".png":
            tiff = _exif_from_png(path)
        elif ext in (".heic", ".heif"):
            tiff = _exif_from_heic(path)
        elif ext in VIDEO_EXTS:
            dt = container_datetime(path)
            return (dt, SOURCE_CONTAINER) if dt else (None, None)
        else:
            tiff = None
    except OSError:
        return None, None
    if tiff:
        dt = parse_tiff_datetime(tiff)
        if dt:
            return dt, SOURCE_EXIF
    return None, None


# 20231015_123456, 2023-10-15 12.34.56, IMG_20231015_123456789, PXL_20231015_123456
_FILENAME_DT = re.compile(
    r"(?<!\d)(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
    r"[ _T-]?([01]\d|2[0-3])[-_.:]?([0-5]\d)[-_.:]?([0-5]\d)(\d{1,3})?(?!\d)"
)
# Unix time in milliseconds, for example line_1697350000000.jpg
_FILENAME_EPOCH_MS = re.compile(r"(?<!\d)(1\d{12})(?!\d)")


def filename_datetime(name: str) -> datetime | None:
    """Return a date and time written in the file name, or None."""
    match = _FILENAME_DT.search(name)
    if match:
        y, mo, d, h, mi, s, frac = match.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
        except ValueError:
            dt = None
        if dt:
            if frac:
                dt = dt.replace(microsecond=int(frac.ljust(3, "0")) * 1000)
            return _plausible(dt)
    match = _FILENAME_EPOCH_MS.search(name)
    if match:
        try:
            dt = datetime.fromtimestamp(int(match.group(1)) / 1000)
        except (OverflowError, OSError, ValueError):
            return None
        if 2005 <= dt.year < 2040:
            return dt
    return None


def media_kind(path: str) -> str | None:
    ext = _ext(path)
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def _ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""
