"""Build small test photos and videos."""

from __future__ import annotations

import os
import random
import struct
from datetime import datetime, timezone

from PIL import Image


def scene(seed: int, size=(96, 72)) -> Image.Image:
    """A distinct picture per seed: random blocks, so dHash differs a lot."""
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    bw, bh = size[0] // 8, size[1] // 6
    for bx in range(8):
        for by in range(6):
            color = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
            img.paste(color, (bx * bw, by * bh, (bx + 1) * bw, (by + 1) * bh))
    return img


def variant(img: Image.Image, seed: int) -> Image.Image:
    """Nearly the same picture (same scene, a few pixels changed)."""
    rnd = random.Random(seed)
    out = img.copy()
    for _ in range(3):
        x, y = rnd.randrange(out.width), rnd.randrange(out.height)
        out.putpixel((x, y), (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    return out


def save_jpeg(img: Image.Image, path: str, taken: datetime | None = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kwargs = {}
    if taken is not None:
        exif = Image.Exif()
        exif[0x0132] = taken.strftime("%Y:%m:%d %H:%M:%S")
        exif.get_ifd(0x8769)[0x9003] = taken.strftime("%Y:%m:%d %H:%M:%S")
        kwargs["exif"] = exif
    img.save(path, "JPEG", quality=95, **kwargs)
    return path


def save_png(img: Image.Image, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")
    return path


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def save_mp4(path: str, created: datetime | None) -> str:
    """A tiny MP4-shaped file with an mvhd creation time (UTC)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seconds = 0
    if created is not None:
        epoch = datetime(1904, 1, 1, tzinfo=timezone.utc)
        seconds = int((created - epoch).total_seconds())
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", seconds, seconds) + b"\x00" * 88)
    data = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41") + _box(b"mdat", os.urandom(64)) + _box(b"moov", mvhd)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def snapshot(folder: str) -> dict:
    """Content bytes and mtime of every file under folder."""
    out = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, folder)] = (fh.read(), os.stat(path).st_mtime_ns)
    return out
