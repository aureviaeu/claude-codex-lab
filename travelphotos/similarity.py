"""Perceptual difference hash (dHash) for grouping similar photos."""

from __future__ import annotations

try:  # Pillow is required for content similarity; everything else works without it.
    from PIL import Image
except ImportError:  # pragma: no cover - exercised only when Pillow is missing
    Image = None

try:  # Optional: lets Pillow open HEIC files.
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:  # pragma: no cover - optional dependency
    pass

HASH_W = 9
HASH_H = 8


def available() -> bool:
    return Image is not None


def dhash(path: str) -> int | None:
    """Return a 64-bit difference hash, or None when the image cannot be read."""
    if Image is None:
        return None
    try:
        with Image.open(path) as img:
            img.draft("L", (HASH_W * 8, HASH_H * 8))
            small = img.convert("L").resize((HASH_W, HASH_H), Image.BILINEAR)
            px = small.tobytes()  # one byte per pixel in mode "L"
    except Exception:
        return None
    value = 0
    for row in range(HASH_H):
        for col in range(HASH_W - 1):
            left = px[row * HASH_W + col]
            right = px[row * HASH_W + col + 1]
            value = (value << 1) | (1 if left > right else 0)
    return value


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def thumbnail_jpeg(path: str, size: int = 240) -> bytes | None:
    """Return a small JPEG preview, or None when the image cannot be read."""
    if Image is None:
        return None
    import io

    try:
        with Image.open(path) as img:
            img.draft("RGB", (size * 2, size * 2))
            try:
                from PIL import ImageOps

                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img = img.convert("RGB")
            img.thumbnail((size, size))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
            return buf.getvalue()
    except Exception:
        return None
