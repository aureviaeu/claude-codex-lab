"""Read photos and sampled video frames as RGB arrays. Read-only."""

from __future__ import annotations

from collections.abc import Iterator

from PIL import Image, ImageOps

try:  # Optional: lets Pillow open HEIC files.
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:  # pragma: no cover - optional dependency
    pass

# Images are scaled down to this longest side before detection: faster, and
# faces in travel photos stay large enough.
MAX_SIDE = 1600
# Never sample more frames than this from one video.
MAX_SAMPLES = 600


def _shrink(img: Image.Image, max_side: int) -> Image.Image:
    if max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side))
    return img


def load_photo(path: str, max_side: int = MAX_SIDE):
    """RGB array of a photo, upright, or None when it cannot be read."""
    import numpy as np

    try:
        with Image.open(path) as img:
            img.draft("RGB", (max_side, max_side))
            img = ImageOps.exif_transpose(img)
            img = _shrink(img.convert("RGB"), max_side)
            return np.asarray(img, dtype="uint8")
    except Exception:
        return None


def video_frames(path: str, interval: float, max_side: int = MAX_SIDE, max_samples: int = MAX_SAMPLES) -> Iterator[tuple[float, object]]:
    """Yield (seconds, RGB array) every `interval` seconds of a video.

    Raises OSError when the video cannot be opened.
    """
    import cv2
    import numpy as np

    if interval <= 0:
        raise ValueError("interval must be positive")
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise OSError(f"cannot open video: {path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        def convert(frame):
            img = Image.fromarray(np.ascontiguousarray(frame[:, :, ::-1]))
            return np.asarray(_shrink(img, max_side), dtype="uint8")

        if fps > 0 and count > 0:
            step = max(1, int(round(interval * fps)))
            for n, index in enumerate(range(0, count, step)):
                if n >= max_samples:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = cap.read()
                if not ok:
                    break
                yield index / fps, convert(frame)
        else:  # unknown frame rate: read everything, keep one frame per interval by timestamp
            next_t, n = 0.0, 0
            while n < max_samples:
                ok, frame = cap.read()
                if not ok:
                    break
                t = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
                if t + 1e-6 >= next_t:
                    yield t, convert(frame)
                    next_t = t + interval
                    n += 1
    finally:
        cap.release()


def video_frame_at(path: str, seconds: float, max_side: int = MAX_SIDE):
    """One RGB frame near `seconds`, or None."""
    import cv2

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if fps > 0:  # same frame index as video_frames picked
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(max(0.0, seconds) * fps)))
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        return None
    import numpy as np

    img = Image.fromarray(np.ascontiguousarray(frame[:, :, ::-1]))
    return np.asarray(_shrink(img, max_side), dtype="uint8")
