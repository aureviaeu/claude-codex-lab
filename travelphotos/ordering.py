"""Estimate the shooting order without relying on file system times.

Clues, from most to least trustworthy:
1. capture time stored in the file (EXIF or video container),
2. a date and time written in the file name,
3. content similarity: similar photos taken around the same time form a group,
4. an itinerary: groups matched to a stop are ordered by the itinerary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import metadata, similarity
from .itinerary import Stop
from .scan import MediaFile

HIGH, MEDIUM, LOW = "high", "medium", "low"
CONFIDENCE_LABEL = {HIGH: "高", MEDIUM: "中", LOW: "低"}

# Photos within this many dHash bits are treated as the same scene.
SIMILARITY_THRESHOLD = 10
# Timed files closer than this belong to the same time slot.
TIME_GAP = timedelta(minutes=10)
# Similar-looking photos further apart than this are not grouped.
SIMILAR_MAX_SPAN = timedelta(hours=1)

_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Group:
    id: int
    members: list[MediaFile]
    anchor: datetime | None = None
    stop: Stop | None = None


@dataclass
class Placement:
    file: MediaFile
    position: int
    group: int
    confidence: str
    basis: str
    estimated_time: datetime | None = None
    stop: Stop | None = None
    unmatched: bool = False
    manual: bool = False


@dataclass
class OrderResult:
    placements: list[Placement]
    groups: list[Group] = field(default_factory=list)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _similar(a: MediaFile, b: MediaFile, threshold: int) -> bool:
    if a.dhash is None or b.dhash is None:
        return False
    if a.time and b.time and abs(a.time - b.time) > SIMILAR_MAX_SPAN:
        return False
    return similarity.distance(a.dhash, b.dhash) <= threshold


def build_groups(files: list[MediaFile], threshold: int = SIMILARITY_THRESHOLD) -> list[list[MediaFile]]:
    """Group files by time slot and by content similarity."""
    uf = _UnionFind(len(files))
    timed = sorted((i for i, f in enumerate(files) if f.time), key=lambda i: files[i].time)
    for prev, cur in zip(timed, timed[1:]):
        if files[cur].time - files[prev].time <= TIME_GAP:
            uf.union(prev, cur)
    hashed = [i for i, f in enumerate(files) if f.dhash is not None]
    for x, i in enumerate(hashed):
        for j in hashed[x + 1:]:
            if _similar(files[i], files[j], threshold):
                uf.union(i, j)
    # Groups are emitted contiguously, so two groups whose capture-time spans
    # overlap would break chronological order between their timed members.
    # Merge them; inside one group timed members are sorted by time.
    spans: dict[int, list[datetime]] = {}
    for i in timed:
        root = uf.find(i)
        t = files[i].time
        if root not in spans:
            spans[root] = [t, t]
        else:
            spans[root][1] = max(spans[root][1], t)
    current, current_end = None, None
    for root, (start, end) in sorted(spans.items(), key=lambda kv: (kv[1][0], kv[0])):
        if current is not None and start <= current_end:
            uf.union(current, root)
            current_end = max(current_end, end)
        else:
            current, current_end = root, end
    buckets: dict[int, list[MediaFile]] = {}
    for i, f in enumerate(files):
        buckets.setdefault(uf.find(i), []).append(f)
    return [buckets[k] for k in sorted(buckets)]


def _order_within(members: list[MediaFile]) -> list[MediaFile]:
    timed = sorted((f for f in members if f.time), key=lambda f: (f.time, f.id))
    untimed = sorted((f for f in members if not f.time), key=lambda f: f.id)
    if not timed:
        return untimed
    result = list(timed)
    for f in untimed:
        best = _nearest(f, timed)
        if best is None:
            result.append(f)
        else:
            at = result.index(best) + 1
            while at < len(result) and result[at].time is None:
                at += 1
            result.insert(at, f)
    return result


def _nearest(f: MediaFile, candidates: list[MediaFile]) -> MediaFile | None:
    if f.dhash is None:
        return None
    best, best_d = None, None
    for c in candidates:
        if c.dhash is None:
            continue
        d = similarity.distance(f.dhash, c.dhash)
        if best_d is None or d < best_d:
            best, best_d = c, d
    return best


def _own_basis(f: MediaFile) -> tuple[str, str] | None:
    if f.time is None:
        return None
    stamp = f.time.strftime(_FMT)
    if f.time_source == metadata.SOURCE_EXIF:
        return HIGH, f"照片內的 EXIF 拍攝時間 {stamp}"
    if f.time_source == metadata.SOURCE_CONTAINER:
        return HIGH, f"影片檔內的建立時間 {stamp}"
    return MEDIUM, f"檔名中的時間 {stamp}"


def order(
    files: list[MediaFile],
    stops: list[Stop] | None = None,
    assignments: dict[str, int] | None = None,
    manual_order: list[str] | None = None,
    threshold: int = SIMILARITY_THRESHOLD,
) -> OrderResult:
    """Return files in their estimated shooting order.

    assignments maps a file id to a 1-based stop index. A group takes the
    earliest stop assigned to any of its members. When stops are given,
    groups without a stop go last and are flagged as unmatched.
    manual_order is a list of file ids chosen by the owner; it wins over
    the estimate.
    """
    stops = stops or []
    by_index = {s.index: s for s in stops}
    assignments = {k: v for k, v in (assignments or {}).items() if v in by_index}

    groups: list[Group] = []
    for gid, members in enumerate(build_groups(files, threshold), start=1):
        group = Group(id=gid, members=_order_within(members))
        times = [f.time for f in members if f.time]
        group.anchor = min(times) if times else None
        assigned = [assignments[f.id] for f in members if f.id in assignments]
        if assigned:
            group.stop = by_index[min(assigned)]
        groups.append(group)

    far = datetime.max

    def key(g: Group):
        first = g.members[0].id
        if g.stop is not None:
            return (0, g.stop.index, g.anchor or far, first)
        return (1, 0 if g.anchor else 1, g.anchor or far, first)

    groups.sort(key=key)

    placements: list[Placement] = []
    for g in groups:
        for f in g.members:
            own = _own_basis(f)
            parts: list[str] = []
            estimated = f.time
            if g.stop is not None:
                parts.append(f"行程第 {g.stop.index} 站（第 {g.stop.day} 天）：{g.stop.name}")
            if own:
                confidence, text = own
                parts.append(text)
            elif g.anchor is not None:
                confidence = MEDIUM
                estimated = g.anchor
                peer = _nearest(f, [m for m in g.members if m.time])
                peer_name = peer.name if peer else "同組照片"
                parts.append(f"沒有時間資料；內容與 {peer_name} 相似，排在同一組（約 {g.anchor.strftime(_FMT)}）")
            elif g.stop is not None:
                confidence = MEDIUM
            elif len(g.members) > 1:
                confidence = LOW
                parts.append("沒有時間資料；與其他照片內容相似分成一組，整組排在有時間的照片之後")
            else:
                confidence = LOW
                parts.append("沒有時間或相似線索，排在最後")
            unmatched = bool(stops) and g.stop is None
            if unmatched:
                parts.append("未對應到行程站點，整組排在已對應的站點之後")
            placements.append(
                Placement(
                    file=f,
                    position=0,
                    group=g.id,
                    confidence=confidence,
                    basis="；".join(parts),
                    estimated_time=estimated,
                    stop=g.stop,
                    unmatched=unmatched,
                )
            )

    if manual_order:
        auto_pos = {p.file.id: i for i, p in enumerate(placements)}
        by_id = {p.file.id: p for p in placements}
        chosen: list[Placement] = []
        seen: set[str] = set()
        for fid in manual_order:
            if fid in by_id and fid not in seen:
                chosen.append(by_id[fid])
                seen.add(fid)
        chosen.extend(p for p in placements if p.file.id not in seen)
        kept = _longest_increasing([auto_pos[p.file.id] for p in chosen])
        for i, p in enumerate(chosen):
            if i not in kept:
                p.manual = True
                p.confidence = HIGH
                p.basis = "手動調整位置；原本依據：" + p.basis
        placements = chosen

    for i, p in enumerate(placements, start=1):
        p.position = i
    return OrderResult(placements=placements, groups=groups)


def _longest_increasing(values: list[int]) -> set[int]:
    """Return the indexes of one longest increasing subsequence.

    Files on it kept their relative order; every other file was moved by hand.
    """
    import bisect

    tails: list[int] = []  # values
    tail_idx: list[int] = []  # index in `values` of each tail
    prev = [-1] * len(values)
    for i, v in enumerate(values):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[k] = v
            tail_idx[k] = i
        prev[i] = tail_idx[k - 1] if k else -1
    out: set[int] = set()
    i = tail_idx[-1] if tail_idx else -1
    while i >= 0:
        out.add(i)
        i = prev[i]
    return out
