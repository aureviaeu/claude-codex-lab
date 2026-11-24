"""The place summary: stops visited, in order, with counts and a sample photo."""

from __future__ import annotations

from ..itinerary import Stop
from ..ordering import CONFIDENCE_LABEL, Placement
from .pipeline import PlaceResult

# No stop: no readable place name, or text that fits no single stop and no
# guess from neighbouring photos (#32).
UNKNOWN = "不確定"
INFERRED = "推測"  # a stop guessed from the photos before and after (#32)
MANUAL = "手動指定"


def group_label(stop: Stop | None, places: PlaceResult | None, file_id: str) -> tuple[str, str]:
    """(confidence label, evidence) for the stop a file ended up at."""
    gp = places.by_file().get(file_id) if places else None
    if stop is None:
        if gp is not None and gp.stop is not None:
            return MANUAL, "在頁面上手動設為未對應"
        return UNKNOWN, (gp.evidence if gp else "")
    if gp is not None and gp.stop is not None and gp.stop.index == stop.index:
        if gp.method == "inferred":
            return INFERRED, gp.evidence
        return CONFIDENCE_LABEL[gp.confidence], gp.evidence
    return MANUAL, "在頁面上手動選擇站點"


def headline(stop: Stop | None, label: str) -> str:
    """不確定, 推測：<stop>, or <stop>（可信度：<label>）."""
    if stop is None:
        return MANUAL + "：未對應" if label == MANUAL else UNKNOWN
    if label == INFERRED:
        return f"{INFERRED}：{stop.name}"
    return f"{stop.name}（可信度：{label}）"


def place_note(stop: Stop | None, places: PlaceResult | None, file_id: str) -> str:
    """One line for the report's 景點判斷 column ("" before any analysis)."""
    if places is None and stop is None:
        return ""
    label, evidence = group_label(stop, places, file_id)
    head = headline(stop, label)
    return f"{head}：{evidence}" if evidence else head


def build(placements: list[Placement], stops: list[Stop], places: PlaceResult | None) -> dict:
    """Visits in output order. Consecutive files at the same stop form one
    visit; a stop listed twice in the itinerary is listed twice here."""
    by_file = places.by_file() if places else {}
    visits: list[dict] = []
    unknown: list[Placement] = []
    current: list[Placement] = []

    def close() -> None:
        if not current:
            return
        stop = current[0].stop
        labels, evidence = [], []
        for p in current:
            label, ev = group_label(stop, places, p.file.id)
            if label not in labels:
                labels.append(label)
            if ev and ev not in evidence:
                evidence.append(ev)
        visits.append(
            {
                "order": len(visits) + 1,
                "stop": stop.index,
                "day": stop.day,
                "name": stop.name,
                "photos": sum(1 for p in current if p.file.kind == "photo"),
                "videos": sum(1 for p in current if p.file.kind == "video"),
                "files": [p.file.id for p in current],
                "representative": _representative(current, by_file),
                "confidence": "、".join(labels),
                "evidence": evidence,
            }
        )
        current.clear()

    for p in placements:
        if p.stop is None:
            close()
            unknown.append(p)
        elif current and current[0].stop.index != p.stop.index:
            close()
            current.append(p)
        else:
            current.append(p)
    close()
    visited = {v["stop"] for v in visits}
    texts = []
    for gp in places.groups if places else []:
        if gp.texts:
            stop = gp.stop.name if gp.stop else UNKNOWN
            if gp.stop is not None and gp.method == "inferred":
                stop = f"{INFERRED}：{gp.stop.name}"
            texts.append({"group": gp.key, "stop": stop, "lines": [t for _f, t in gp.texts]})
    return {
        "analyzed": places is not None,
        "has_itinerary": bool(stops),
        "warnings": list(places.warnings) if places else [],
        "visits": visits,
        "unknown": {
            "photos": sum(1 for p in unknown if p.file.kind == "photo"),
            "videos": sum(1 for p in unknown if p.file.kind == "video"),
            "files": [p.file.id for p in unknown],
        },
        "missed_stops": [{"index": s.index, "day": s.day, "name": s.name} for s in stops if s.index not in visited],
        "texts": texts,
    }


def _representative(run: list[Placement], by_file: dict) -> str:
    ids = {p.file.id for p in run}
    for p in run:
        gp = by_file.get(p.file.id)
        if gp is not None and gp.best_file in ids and gp.stop is not None and gp.stop.index == p.stop.index:
            return gp.best_file
    photos = [p for p in run if p.file.kind == "photo"]
    pick = photos[len(photos) // 2] if photos else run[0]
    return pick.file.id


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _link(name: str) -> str:
    return "<" + name.replace("<", "%3C").replace(">", "%3E") + ">"


def markdown(summary: dict, names: dict[str, str] | None = None) -> str:
    """The summary as Markdown. `names` maps file id -> output file name."""
    names = names or {}
    out = ["# 景點總結", ""]
    for w in summary["warnings"]:
        out += [f"> {w}", ""]
    if not summary["has_itinerary"]:
        out += ["沒有提供行程表，所以無法判斷景點，所有照片都列為「不確定」；下方列出讀到的文字。", ""]
    if summary["visits"]:
        out += ["| 順序 | 景點 | 行程 | 照片 | 影片 | 可信度 | 代表照片 |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for v in summary["visits"]:
            rep = names.get(v["representative"], v["representative"])
            out.append(
                f"| {v['order']} | {_md(v['name'])} | 第 {v['day']} 天第 {v['stop']} 站 | {v['photos']} | {v['videos']} | {_md(v['confidence'])} | {_md(rep)} |"
            )
        out.append("")
        for v in summary["visits"]:
            rep = names.get(v["representative"], v["representative"])
            out += [f"## {v['order']}. {v['name']}", ""]
            out.append(f"第 {v['day']} 天，行程第 {v['stop']} 站。照片 {v['photos']} 張，影片 {v['videos']} 段。可信度：{v['confidence']}。")
            out.append("")
            for ev in v["evidence"]:
                out.append(f"- {ev}")
            if v["evidence"]:
                out.append("")
            out += [f"![{v['name']} 代表照片]({_link(rep)})", ""]
    unk = summary["unknown"]
    if unk["files"]:
        why = "沒有可讀的地名，前後照片也無法推測" if summary["has_itinerary"] else "沒有行程表，無法判斷景點"
        out += [f"## {UNKNOWN}", "", f"{why}：照片 {unk['photos']} 張，影片 {unk['videos']} 段。", ""]
        out += [f"- {_md(names.get(fid, fid))}" for fid in unk["files"]]
        out.append("")
    if summary["missed_stops"]:
        out += ["## 行程中沒有照片的站點", ""]
        out += [f"- 第 {s['day']} 天第 {s['index']} 站：{_md(s['name'])}" for s in summary["missed_stops"]]
        out.append("")
    if summary["texts"]:
        out += ["## 讀到的文字", ""]
        for t in summary["texts"]:
            lines = "、".join(f"「{_md(x)}」" for x in t["lines"][:20])
            out.append(f"- {_md(t['group'])} 那組（{_md(t['stop'])}）：{lines}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
