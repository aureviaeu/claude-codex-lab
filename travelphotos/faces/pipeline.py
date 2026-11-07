"""Run face detection over the scanned files and reference photos."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import media
from .engine import Face

DEFAULT_INTERVAL = 2.0  # seconds between sampled video frames
MIN_INTERVAL, MAX_INTERVAL = 0.2, 600.0


@dataclass
class FaceHit:
    file_id: str
    frame: float | None  # seconds into a video, None for photos
    face: Face


@dataclass
class FileFaces:
    file_id: str
    kind: str
    readable: bool
    samples: int  # images analysed (1 for a photo, frames for a video)
    hits: list[FaceHit] = field(default_factory=list)


def check_interval(value) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError):
        raise ValueError("影片抽樣間隔要是數字（秒）。") from None
    if not (MIN_INTERVAL <= interval <= MAX_INTERVAL):
        raise ValueError(f"影片抽樣間隔要在 {MIN_INTERVAL:g} 到 {MAX_INTERVAL:g} 秒之間。")
    return interval


def analyze_file(engine, file_id: str, path: str, kind: str, interval: float) -> FileFaces:
    result = FileFaces(file_id=file_id, kind=kind, readable=False, samples=0)
    if kind == "photo":
        rgb = media.load_photo(path)
        if rgb is None:
            return result
        result.readable, result.samples = True, 1
        result.hits = [FaceHit(file_id, None, f) for f in engine.detect(rgb)]
        return result
    try:
        for seconds, rgb in media.video_frames(path, interval):
            result.samples += 1
            result.hits.extend(FaceHit(file_id, round(seconds, 3), f) for f in engine.detect(rgb))
    except OSError:
        pass
    result.readable = result.samples > 0
    return result


def analyze(engine, files, interval: float) -> dict[str, FileFaces]:
    """files: objects with .id, .path and .kind (scan.MediaFile)."""
    return {f.id: analyze_file(engine, f.id, f.path, f.kind, interval) for f in files}


def reference_faces(engine, folder: str) -> tuple[list[list[float]], list[str], list[str]]:
    """Largest face of each photo in `folder` (not recursive).

    Returns (embeddings, used file names, skipped file names).
    """
    from ..metadata import media_kind

    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"找不到資料夾：{folder}")
    embeddings, used, skipped = [], [], []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if name.startswith(".") or not os.path.isfile(path) or media_kind(path) != "photo":
            continue
        rgb = media.load_photo(path)
        faces = engine.detect(rgb) if rgb is not None else []
        if not faces:
            skipped.append(name)
            continue
        biggest = max(faces, key=lambda f: f.box[2] * f.box[3])
        embeddings.append(biggest.embedding)
        used.append(name)
    return embeddings, used, skipped


def crop_jpeg(path: str, kind: str, frame: float | None, box: tuple[int, int, int, int], size: int = 112) -> bytes | None:
    """A small JPEG of one face, for the page. None when it cannot be read."""
    import io

    from PIL import Image

    rgb = media.load_photo(path) if kind == "photo" else media.video_frame_at(path, frame or 0.0)
    if rgb is None:
        return None
    img = Image.fromarray(rgb)
    x, y, w, h = box
    pad = int(max(w, h) * 0.25)
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(img.width, x + w + pad), min(img.height, y + h + pad)
    if right <= left or bottom <= top:
        return None
    face = img.crop((left, top, right, bottom))
    face.thumbnail((size, size))
    buf = io.BytesIO()
    face.save(buf, "JPEG", quality=85)
    return buf.getvalue()
