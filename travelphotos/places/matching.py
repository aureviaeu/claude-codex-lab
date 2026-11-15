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

# Japanese simplified kanji (shinjitai) -> the traditional form, so that
# 伏見稲荷 / 京都駅 on a sign compare equal to 伏見稻荷 / 京都驛 (#22). OpenCC's
# t2s then maps both to the same simplified characters.
_JP_TO_TRAD = str.maketrans(
    "稲駅広桜浅沢竜宝関鉄楽円塩黒県区栄恵歩渓滝湾斎条寿来帰総発辺剣険単営覚観権当灯隠蔵姫舗仏仮伝価倹児労勲巌峡徳戦拝挙撃数断昼暁様横毎気温満焼犠猟獣砕礼祷禅穂粋経絵継続緑縄聴芸茎薬虫蛍装読譲豊賛転軽鉱銭閲陥隣雑霊頼顔駆験髄鶏麦黙齢郷",
    "稻驛廣櫻淺澤龍寶關鐵樂圓鹽黑縣區榮惠步溪瀧灣齋條壽來歸總發邊劍險單營覺觀權當燈隱藏姬鋪佛假傳價儉兒勞勳巖峽德戰拜舉擊數斷晝曉樣橫每氣溫滿燒犧獵獸碎禮禱禪穗粹經繪繼續綠繩聽藝莖藥蟲螢裝讀讓豐贊轉輕礦錢閱陷鄰雜靈賴顏驅驗髓雞麥默齡鄉",
)

# Endings dropped to get a stop's core name: a sign often shows only 京都 for
# 京都車站 or 伏見稲荷 for 伏見稻荷大社. Normalized (simplified) forms.
STATION_SUFFIXES = ("火车站", "车站", "站", "驿")
OTHER_SUFFIXES = ("大社", "神社", "神宫", "公园")
CORE_SCORE = 0.8  # medium confidence


def normalize(text: str, variants: bool = True) -> str:
    """Width, case, Japanese/traditional/simplified and punctuation insensitive form.

    variants=False skips the Japanese kanji table (the rules before #22).
    """
    text = unicodedata.normalize("NFKC", text or "").lower()
    if variants:
        text = text.translate(_JP_TO_TRAD)
    if _T2S is not None:
        text = _T2S.convert(text)
    return "".join(ch for ch in text if ch.isalnum())


def _words(text: str) -> list[str]:
    return _LATIN_WORD.findall(unicodedata.normalize("NFKC", text or "").lower())


def _core(n: str) -> tuple[str, bool] | None:
    """(core, is_station) of a normalized stop name, or None."""
    for suffix in sorted(STATION_SUFFIXES + OTHER_SUFFIXES, key=len, reverse=True):
        if n.endswith(suffix) and len(n) - len(suffix) >= 2:
            return n[: -len(suffix)], suffix in STATION_SUFFIXES
    return None


def core_score(name: str, text: str) -> float:
    """CORE_SCORE when a sign line shows the stop's core name, else 0.

    A station stop (京都車站) matches a line that is exactly its core (京都) or
    the core plus a station ending (京都駅); a line that only starts with it
    (京都市役所前, 京都河原町) does not. Any other stop needs a core of at
    least three characters (伏見稲荷 for 伏見稻荷大社), so 奈良 on a station
    sign never matches 奈良公園.
    """
    n, t = normalize(name), normalize(text)
    found = _core(n) if n and not n.isascii() else None
    if not found or not t:
        return 0.0
    core, station = found
    if station:
        return CORE_SCORE if t == core or any(t == core + s for s in STATION_SUFFIXES) else 0.0
    if len(core) >= 3 and t.startswith(core):
        return CORE_SCORE
    return 0.0


def stop_score(stop: Stop, text: str, rules: str = "full") -> float:
    """Best score of a stop's name and aliases against one line of text.

    rules="basic" is the matching before #22 (no Japanese kanji table, no
    core names, no aliases); the benchmark uses it for the before numbers.
    """
    if rules == "basic":
        return name_score(stop.name, text, variants=False)
    best = max(name_score(stop.name, text), core_score(stop.name, text))
    for alias in getattr(stop, "aliases", None) or []:
        best = max(best, name_score(alias, text))
    return best


def name_score(name: str, text: str, variants: bool = True) -> float:
    """How well the raw `text` contains the place `name` (0..1).

    1.0 when the name appears exactly (ignoring width, case, punctuation and
    traditional/simplified). Otherwise, for names of at least MIN_FUZZY_LEN
    characters, a window of the name's own length must share all but one
    character in order (one misread character): the score is the shared
    fraction. Latin names are compared word by word, so "Nara" never
    matches inside "Narita".
    """
    n = normalize(name, variants)
    t = normalize(text, variants)
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


def best_matches(lines: list[tuple[str, str]], stops: list[Stop], rules: str = "full") -> list[TextMatch]:
    """Best match per stop over (file_id, text line) pairs, highest first.

    Stops below MIN_SCORE are left out.
    """
    out: list[TextMatch] = []
    for stop in stops:
        best: TextMatch | None = None
        for fid, line in lines:
            score = stop_score(stop, line, rules)
            if score >= MIN_SCORE and (best is None or score > best.score):
                best = TextMatch(stop, score, line, fid)
        if best is not None:
            out.append(best)
    out.sort(key=lambda m: (-m.score, m.stop.index))
    return out
