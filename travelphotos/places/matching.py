"""Compare text read from photos with the itinerary's place names."""

from __future__ import annotations

import re
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
# Below this a stop is not considered a match.
MIN_SCORE = 0.6
# Names this short (after normalising) only match when found exactly:
# one shared character between two-character names is not evidence.
MIN_FUZZY_LEN = 3

_LATIN_WORD = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Width, case, traditional/simplified and punctuation insensitive form."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    if _T2S is not None:
        text = _T2S.convert(text)
    return "".join(ch for ch in text if ch.isalnum())


def _words(text: str) -> list[str]:
    return _LATIN_WORD.findall(unicodedata.normalize("NFKC", text or "").lower())


def name_score(name: str, text: str) -> float:
    """How well the raw `text` contains the place `name` (0..1).

    1.0 when the name appears exactly (ignoring width, case, punctuation and
    traditional/simplified). Otherwise, for names of at least MIN_FUZZY_LEN
    characters, a window of the name's own length must share all but one
    character in order (one misread character): the score is the shared
    fraction. Latin names are compared word by word, so "Nara" never
    matches inside "Narita".
    """
    n = normalize(name)
    t = normalize(text)
    if not n or not t:
        return 0.0
    if n.isascii():
        name_words = _words(name)
        text_words = _words(text)
        k = len(name_words)
        if k == 0:
            return 0.0
        for i in range(len(text_words) - k + 1):
            if text_words[i : i + k] == name_words:
                return 1.0
        if len(n) < MIN_FUZZY_LEN + 2:
            return 0.0
        best = 0.0
        for i in range(len(text_words) - k + 1):
            cand = "".join(text_words[i : i + k])
            if abs(len(cand) - len(n)) <= 1:
                shared = sum(b.size for b in SequenceMatcher(None, n, cand).get_matching_blocks())
                if shared >= len(n) - 1:
                    best = max(best, shared / max(len(n), len(cand)))
        return best
    if n in t:
        return 1.0
    if len(n) < MIN_FUZZY_LEN or len(t) < len(n):
        return 0.0
    best = 0.0
    for start in range(len(t) - len(n) + 1):
        shared = sum(b.size for b in SequenceMatcher(None, n, t[start : start + len(n)]).get_matching_blocks())
        if shared >= len(n) - 1:
            best = max(best, shared / len(n))
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
    out: list[TextMatch] = []
    for stop in stops:
        best: TextMatch | None = None
        for fid, line in lines:
            score = name_score(stop.name, line)
            if score >= MIN_SCORE and (best is None or score > best.score):
                best = TextMatch(stop, score, line, fid)
        if best is not None:
            out.append(best)
    out.sort(key=lambda m: (-m.score, m.stop.index))
    return out
