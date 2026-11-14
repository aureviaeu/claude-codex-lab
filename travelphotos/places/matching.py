"""Compare text read from photos with the itinerary's place names."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..itinerary import Stop

try:  # Pure-Python OpenCC: the OCR model writes simplified characters.
    from opencc import OpenCC

    _T2S = OpenCC("t2s")
except Exception:  # pragma: no cover - requirements include it
    _T2S = None

# A stop name found exactly in the text scores 1.0.
HIGH_SCORE = 0.85
# Below this a stop is not considered a match (one wrong character in a
# three-character name scores 0.67, in a two-character name 0.5).
MIN_SCORE = 0.6


def normalize(text: str) -> str:
    """Width, case, traditional/simplified and punctuation insensitive form."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    if _T2S is not None:
        text = _T2S.convert(text)
    return "".join(ch for ch in text if ch.isalnum())


def name_score(name: str, text: str) -> float:
    """How well `text` (already normalized) contains the place `name` (0..1)."""
    n = normalize(name)
    if not n or not text:
        return 0.0
    if n in text:
        return 1.0
    if len(n) < 2:
        return 0.0
    best = 0.0
    for size in (len(n) - 1, len(n), len(n) + 1):
        if size < 1 or size > len(text):
            continue
        for start in range(len(text) - size + 1):
            best = max(best, SequenceMatcher(None, n, text[start : start + size]).ratio())
    return best


@dataclass
class TextMatch:
    stop: Stop
    score: float
    text: str  # the line that matched, as read
    file_id: str


def best_matches(lines: list[tuple[str, str]], stops: list[Stop]) -> list[TextMatch]:
    """Best match per stop over (file_id, text line) pairs, highest first.

    Stops below MIN_SCORE are left out.
    """
    norm = [(fid, line, normalize(line)) for fid, line in lines]
    out: list[TextMatch] = []
    for stop in stops:
        best: TextMatch | None = None
        for fid, line, text in norm:
            score = name_score(stop.name, text)
            if score >= MIN_SCORE and (best is None or score > best.score):
                best = TextMatch(stop, score, line, fid)
        if best is not None:
            out.append(best)
    out.sort(key=lambda m: (-m.score, m.stop.index))
    return out
