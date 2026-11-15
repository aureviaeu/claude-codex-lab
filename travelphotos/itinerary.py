"""Parse a tour itinerary and a LINE chat export (reference only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Stop:
    index: int  # 1-based order in the whole trip
    day: int  # 1-based day number
    name: str
    # Extra spellings used only for matching sign text (#22), written after
    # the name in brackets: 嵐山（Arashiyama）. Never shown as the name.
    aliases: list[str] = field(default_factory=list)


# Only a bracketed part made of Latin letters, digits, spaces and a few
# separators is an alias; anything else (清水寺 (早上)) stays part of the name.
_ALIAS = re.compile(r"^(?P<name>.+?)\s*[（(](?P<alias>[A-Za-z][A-Za-z0-9 .'\-;；,，]*)[）)]\s*$")


def split_aliases(text: str) -> tuple[str, list[str]]:
    """'嵐山（Arashiyama）' -> ('嵐山', ['Arashiyama']); other text unchanged."""
    match = _ALIAS.match(text)
    if not match:
        return text, []
    aliases = [a.strip() for a in re.split(r"[;；,，]", match.group("alias")) if a.strip()]
    return match.group("name").strip(), aliases


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_DAY_HEADER = re.compile(
    r"^\s*(?:"
    r"(?:day|d)\s*(?P<n1>\d+)"
    r"|第\s*(?P<n2>[\d一二三四五六七八九十]+)\s*[天日]"
    r"|(?P<md>\d{1,2}\s*[/月]\s*\d{1,2}\s*日?(?:\s*[\(（][^\)）]*[\)）])?)"
    r")\s*[:：.、\-–]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s*(?:→|->|⇒|➔|＞|>|、|/|／)\s*")
_BULLET = re.compile(r"^\s*(?:[-*•・]|\d+[.)、]|[（(]\d+[)）])\s*")


def _cn_to_int(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if len(text) == 2 and text[0] == "十":
        return 10 + _CN_NUM.get(text[1], 0)
    if len(text) == 2 and text[1] == "十":
        return _CN_NUM.get(text[0], 0) * 10
    if len(text) == 3 and text[1] == "十":
        return _CN_NUM.get(text[0], 0) * 10 + _CN_NUM.get(text[2], 0)
    return _CN_NUM.get(text)


def parse_itinerary(text: str) -> list[Stop]:
    """Turn itinerary text into an ordered list of stops.

    Lines like "第1天", "Day 2" or "10/15" start a new day; the rest of such a
    line, and every other non-empty line, lists stops in visiting order.
    Several stops on one line can be separated by →, ->, >, 、 or /.
    """
    stops: list[Stop] = []
    day = 1
    seen_header = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _DAY_HEADER.match(line)
        if match:
            number = match.group("n1") or match.group("n2")
            parsed = _cn_to_int(number) if number else None
            if parsed:
                day = parsed
            elif seen_header:
                day += 1
            seen_header = True
            line = match.group("rest").strip()
            if not line:
                continue
        line = _BULLET.sub("", line)
        for part in _SPLIT.split(line):
            name = part.strip(" \t:：,，。")
            if name:
                name, aliases = split_aliases(name)
                stops.append(Stop(index=len(stops) + 1, day=day, name=name, aliases=aliases))
    return stops


@dataclass
class ChatMediaMessage:
    time: datetime
    sender: str
    kind: str  # "photo", "video" or "album"


_CHAT_DATE = re.compile(r"^\s*(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})")
_CHAT_MSG = re.compile(
    r"^\s*(?P<ampm1>上午|下午|午前|午後|AM|PM)?\s*(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ampm2>AM|PM)?\t(?P<rest>.*)$",
    re.IGNORECASE,
)
_PHOTO_MARKERS = ("[照片]", "[相片]", "[圖片]", "[Photo]", "[写真]", "[사진]")
_VIDEO_MARKERS = ("[影片]", "[視訊]", "[Video]", "[動画]", "[동영상]")
_ALBUM_MARKERS = ("[相簿]", "[Album]", "[アルバム]")


def parse_line_chat(text: str) -> list[ChatMediaMessage]:
    """Return the send times of photo and video messages in a LINE export."""
    current: date | None = None
    out: list[ChatMediaMessage] = []
    for raw in text.splitlines():
        match = _CHAT_DATE.match(raw)
        if match and "\t" not in raw:
            try:
                current = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
            continue
        match = _CHAT_MSG.match(raw)
        if not match or current is None:
            continue
        rest = match.group("rest")
        kind = None
        if any(m in rest for m in _PHOTO_MARKERS):
            kind = "photo"
        elif any(m in rest for m in _VIDEO_MARKERS):
            kind = "video"
        elif any(m in rest for m in _ALBUM_MARKERS):
            kind = "album"
        if kind is None:
            continue
        hour = int(match.group("h"))
        minute = int(match.group("m"))
        ampm = (match.group("ampm1") or match.group("ampm2") or "").upper()
        if ampm in ("下午", "午後", "PM") and hour < 12:
            hour += 12
        elif ampm in ("上午", "午前", "AM") and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            continue
        sender = rest.split("\t", 1)[0] if "\t" in rest else ""
        out.append(ChatMediaMessage(time=datetime.combine(current, datetime.min.time()).replace(hour=hour, minute=minute), sender=sender, kind=kind))
    return out


def summarize_chat(messages: list[ChatMediaMessage]) -> list[dict]:
    """Group media messages by day: count and first/last send time."""
    days: dict[date, list[ChatMediaMessage]] = {}
    for msg in messages:
        days.setdefault(msg.time.date(), []).append(msg)
    summary = []
    for day in sorted(days):
        items = sorted(days[day], key=lambda m: m.time)
        summary.append(
            {
                "date": day.isoformat(),
                "count": len(items),
                "photos": sum(1 for m in items if m.kind == "photo"),
                "videos": sum(1 for m in items if m.kind == "video"),
                "albums": sum(1 for m in items if m.kind == "album"),
                "first": items[0].time.strftime("%H:%M"),
                "last": items[-1].time.strftime("%H:%M"),
            }
        )
    return summary
