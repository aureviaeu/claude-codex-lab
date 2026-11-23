"""Decide one itinerary stop (or unknown) per group of similar photos.

1. Groups come from travelphotos.ordering.build_groups, the same groups the
   ordering uses, so each group is judged once.
2. Text is read from up to MAX_FILES_PER_GROUP files of the group (a few
   frames per video) and compared with the stop names. An exact name is
   high confidence, a near match medium.
3. A group with no readable sign takes the place of the identified group it
   looks most like (colour layout), with low confidence, only when the
   likeness is strong and clearly better than any other place.
4. Groups are walked in time order; when a name appears more than once in
   the itinerary (a hotel), the next visit in itinerary order is chosen.
5. A group still without a stop is "不確定". When the nearest identified
   groups before and after it (by capture time, or by file name when it has
   no time) are at the same itinerary stop, it is guessed to be there too
   and labelled "推測" (#32). Neighbours at different stops, or a missing
   neighbour, leave it uncertain.
No network is used anywhere here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..faces import media
from ..itinerary import Stop
from ..ordering import HIGH, LOW, MEDIUM, SIMILARITY_THRESHOLD, build_groups
from ..scan import MediaFile
from . import cloud
from .matching import HIGH_SCORE, best_matches, normalize

MAX_FILES_PER_GROUP = 8
VIDEO_FRAMES = 3
VIDEO_INTERVAL = 3.0
OCR_MAX_SIDE = 1600
# Two different places scoring within this of each other: too close to call.
AMBIGUOUS_MARGIN = 0.05
# Colour-layout likeness needed to borrow a place (0..1), and the lead it
# needs over the next different place.
VISUAL_MIN = 0.8
VISUAL_MARGIN = 0.05
_BINS = 4  # per channel; 64-bin colour histogram on a 4x4 grid


@dataclass
class GroupPlace:
    key: str  # smallest file id in the group
    member_ids: list[str]
    stop: Stop | None = None
    confidence: str | None = None  # HIGH / MEDIUM / LOW, None when unknown
    method: str = ""  # "text", "visual", "inferred" (推測 from neighbours) or ""
    evidence: str = ""
    score: float = 0.0
    texts: list[tuple[str, str]] = field(default_factory=list)  # (file id, line)
    best_file: str | None = None


@dataclass
class PlaceResult:
    groups: list[GroupPlace]
    has_itinerary: bool
    warnings: list[str] = field(default_factory=list)

    def by_file(self) -> dict[str, GroupPlace]:
        return {fid: g for g in self.groups for fid in g.member_ids}

    def assignments(self) -> dict[str, int]:
        """file id -> stop index, one entry per identified group."""
        return {g.key: g.stop.index for g in self.groups if g.stop is not None}


def _pick(items: list, limit: int) -> list:
    """Up to `limit` items spread evenly; none when there is no room."""
    if limit <= 0:
        return []
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def _images(f: MediaFile):
    if f.kind == "photo":
        img = media.load_photo(f.path, OCR_MAX_SIDE)
        return [img] if img is not None else []
    try:
        return [frame for _t, frame in media.video_frames(f.path, VIDEO_INTERVAL, OCR_MAX_SIDE, VIDEO_FRAMES)]
    except Exception:
        return []


def _read_group(members: list[MediaFile], engine) -> list[tuple[str, str]]:
    photos = [f for f in members if f.kind == "photo"]
    videos = [f for f in members if f.kind == "video"]
    chosen = _pick(photos, MAX_FILES_PER_GROUP) + _pick(videos, max(0, MAX_FILES_PER_GROUP - min(len(photos), MAX_FILES_PER_GROUP)))
    lines: list[tuple[str, str]] = []
    for f in chosen:
        for img in _images(f):
            for line in engine.read_text(img):
                if line.strip() and (f.id, line) not in lines:
                    lines.append((f.id, line))
    return lines


def colour_layout(path: str) -> list[float] | None:
    """A small colour histogram per region of a 4x4 grid, summing to 1."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.draft("RGB", (128, 128))
            small = im.convert("RGB").resize((32, 32))
            px = small.tobytes()
    except Exception:
        return None
    cells = 16
    hist = [0.0] * (cells * _BINS**3)
    for y in range(32):
        for x in range(32):
            i = (y * 32 + x) * 3
            r, g, b = px[i] * _BINS // 256, px[i + 1] * _BINS // 256, px[i + 2] * _BINS // 256
            cell = (y // 8) * 4 + x // 8
            hist[cell * _BINS**3 + (r * _BINS + g) * _BINS + b] += 1
    total = float(32 * 32)
    return [v / total for v in hist]


def _group_layout(members: list[MediaFile]) -> list[float] | None:
    feats = [colour_layout(f.path) for f in _pick([m for m in members if m.kind == "photo"], 4)]
    feats = [x for x in feats if x is not None]
    if not feats:
        return None
    return [sum(col) / len(feats) for col in zip(*feats)]


def likeness(a: list[float], b: list[float]) -> float:
    return sum(min(x, y) for x, y in zip(a, b))


def _decide_by_text(gp: GroupPlace, stops: list[Stop]) -> None:
    matches = best_matches(gp.texts, stops)
    if not matches:
        if gp.texts:
            gp.evidence = "讀到的文字沒有對應到行程地點" if stops else "沒有行程表，只列出讀到的文字"
        return
    top = matches[0]
    rival = next((m for m in matches[1:] if normalize(m.stop.name) != normalize(top.stop.name)), None)
    if rival is not None and top.score - rival.score < AMBIGUOUS_MARGIN:
        gp.evidence = f"招牌文字同時像「{top.stop.name}」和「{rival.stop.name}」，無法判斷"
        return
    gp.stop = top.stop
    gp.score = top.score
    gp.confidence = HIGH if top.score >= HIGH_SCORE else MEDIUM
    gp.method = "text"
    gp.best_file = top.file_id
    how = "完全符合" if top.score >= 1.0 else f"相似度 {top.score:.2f}"
    gp.evidence = f"招牌文字「{top.text}」（{top.file_id}）與「{top.stop.name}」{how}"


def _decide_by_look(unknown: list[tuple[GroupPlace, list[float] | None]], known: list[tuple[GroupPlace, list[float] | None]]) -> None:
    refs = [(g, f) for g, f in known if f is not None]
    for gp, feat in unknown:
        if feat is None or not refs:
            continue
        scored = sorted(((likeness(feat, f), g) for g, f in refs), key=lambda x: -x[0])
        best, ref = scored[0]
        other = next((s for s, g in scored[1:] if normalize(g.stop.name) != normalize(ref.stop.name)), 0.0)
        if best >= VISUAL_MIN and best - other >= VISUAL_MARGIN:
            gp.stop = ref.stop
            gp.score = best
            gp.confidence = LOW
            gp.method = "visual"
            gp.evidence = f"沒有可用的招牌文字；畫面與 {ref.key} 那組（{ref.stop.name}）相似 {best:.2f}"


def _resolve_repeats(ordered: list[tuple[GroupPlace, datetime | None]], stops: list[Stop]) -> None:
    """Same name more than once in the itinerary (a hotel): pick the visit.

    Groups are walked in time order. When the group has a time, the
    occurrence on the same trip day (days counted from the earliest group
    time) wins. Otherwise the next occurrence at or after the last chosen
    stop is used, and a group on a later date than the previous group at
    that same stop moves on to a later occurrence, so two visits on
    different days are never merged even when nothing between them was
    recognised.

    A group with no time at all cannot be placed on a day, so when the
    occurrence it would take is already used by another group, it takes the
    next unused one, or else the earliest unused one (dated groups come
    first and may already hold the later visit), so a hotel on two nights
    becomes two visits; once every occurrence is used, it stays on the
    last one.
    """
    dates = [t.date() for _gp, t in ordered if t is not None]
    first_day = min(dates) if dates else None
    last = 0
    seen: dict[int, object] = {}  # stop index -> date of the last group placed there
    used: set[int] = set()  # stop indexes already given to a group
    for gp, t in ordered:
        if gp.stop is None:
            continue
        name = normalize(gp.stop.name)
        same = sorted((s for s in stops if normalize(s.name) == name), key=lambda s: s.index)
        chosen = None
        if t is not None and first_day is not None and len(same) > 1:
            trip_day = (t.date() - first_day).days + 1
            on_day = [s for s in same if s.day == trip_day]
            if on_day:
                chosen = min(on_day, key=lambda s: (s.index < last, s.index))
        if chosen is None:
            later = [s for s in same if s.index >= last]
            chosen = later[0] if later else same[0]
            prev = seen.get(chosen.index)
            if t is not None and prev is not None and t.date() > prev:
                after = [s for s in same if s.index > chosen.index]
                if after:
                    chosen = after[0]
            if t is None and chosen.index in used:
                unused = [s for s in same if s.index > chosen.index and s.index not in used] or [
                    s for s in same if s.index not in used
                ]
                if unused:
                    chosen = unused[0]
                else:
                    chosen = [s for s in same if s.index >= chosen.index][-1]
        gp.stop = chosen
        used.add(chosen.index)
        last = chosen.index
        if t is not None:
            seen[chosen.index] = t.date()


def neighbours(order: list[GroupPlace], anchors: dict[str, Stop]) -> dict[str, tuple[GroupPlace | None, GroupPlace | None]]:
    """(nearest anchor before, nearest anchor after) for each group in `order`
    that is not an anchor. `anchors` maps a group key to its stop."""
    before: list[GroupPlace | None] = []
    last = None
    for gp in order:
        before.append(last)
        if gp.key in anchors:
            last = gp
    out: dict[str, tuple[GroupPlace | None, GroupPlace | None]] = {}
    nxt = None
    for i in range(len(order) - 1, -1, -1):
        gp = order[i]
        if gp.key in anchors:
            nxt = gp
        else:
            out[gp.key] = (before[i], nxt)
    return out


def _stop_label(stop: Stop) -> str:
    return f"第 {stop.index} 站「{stop.name}」"


def guess_from_neighbours(gp: GroupPlace, before: GroupPlace | None, after: GroupPlace | None, anchors: dict[str, Stop]) -> None:
    """Give an uncertain group its neighbours' stop when both agree (#32).

    Only the exact same itinerary stop counts: two visits to one hotel are
    different stops, so a group between them stays uncertain.
    """
    reason = gp.evidence or "沒有讀到文字"
    if before is None or after is None:
        side = "前後" if before is None and after is None else ("前面" if before is None else "後面")
        gp.evidence = f"{reason}；{side}沒有已判斷景點的照片，無法推測"
        return
    b, a = anchors[before.key], anchors[after.key]
    if b.index != a.index:
        gp.evidence = f"{reason}；前一組（{before.key}）在{_stop_label(b)}、後一組（{after.key}）在{_stop_label(a)}，分屬不同行程站，無法推測"
        return
    gp.stop = b
    gp.score = 0.0
    gp.confidence = LOW
    gp.method = "inferred"
    gp.evidence = f"{reason}；前一組（{before.key}）與後一組（{after.key}）都在{_stop_label(b)}，推測為同一站"


def infer_in_order(order: list[GroupPlace]) -> None:
    """Step 5 on one sequence of groups already in shooting order (benchmark)."""
    anchors = {gp.key: gp.stop for gp in order if gp.stop is not None}
    found = neighbours(order, anchors)
    for gp in order:
        if gp.key in found:
            guess_from_neighbours(gp, *found[gp.key], anchors)


def _infer_from_neighbours(entries: list[tuple[GroupPlace, list[MediaFile], datetime | None]]) -> None:
    """Step 5: uncertain groups between two groups at the same stop.

    A group with a capture time is compared with the timed groups around it
    in time order; a group without one with the groups around it in file
    name order (camera counters), since it has no time to compare. Only
    stops found before this step (text, look-alike, repeats) are used as
    neighbours, so a guess never feeds another guess.
    """
    anchors = {gp.key: gp.stop for gp, _m, _t in entries if gp.stop is not None}
    timed = [gp for gp, _m, t in sorted((e for e in entries if e[2] is not None), key=lambda e: (e[2], e[0].key))]
    by_name = sorted((gp for gp, _m, _t in entries), key=lambda gp: gp.key)
    found = neighbours(by_name, anchors)
    found.update(neighbours(timed, anchors))
    for gp, _m, _t in entries:
        if gp.key in found:
            guess_from_neighbours(gp, *found[gp.key], anchors)


def analyze(files: list[MediaFile], stops: list[Stop] | None, engine, threshold: int = SIMILARITY_THRESHOLD, environ=None) -> PlaceResult:
    """Judge every group once. `engine.read_text(rgb)` returns text lines."""
    stops = stops or []
    result = PlaceResult(groups=[], has_itinerary=bool(stops))
    warning = cloud.cloud_warning(environ)
    if warning:
        result.warnings.append(warning)
    entries = []
    for members in build_groups(files, threshold):
        ids = sorted(f.id for f in members)
        gp = GroupPlace(key=ids[0], member_ids=ids)
        gp.texts = _read_group(sorted(members, key=lambda f: f.id), engine)
        _decide_by_text(gp, stops)
        times = [f.time for f in members if f.time]
        entries.append((gp, members, min(times) if times else None))
        result.groups.append(gp)
    if stops:
        known = [(gp, _group_layout(m)) for gp, m, _t in entries if gp.stop is not None]
        unknown = [(gp, _group_layout(m)) for gp, m, _t in entries if gp.stop is None and not gp.evidence.startswith("招牌文字同時像")]
        _decide_by_look(unknown, known)
        far = datetime.max
        _resolve_repeats([(gp, t) for gp, _m, t in sorted(entries, key=lambda e: (e[2] or far, e[0].key))], stops)
        _infer_from_neighbours(entries)
    for gp in result.groups:
        if gp.stop is None and not gp.evidence:
            gp.evidence = "沒有讀到文字" if stops else "沒有行程表"
    return result
