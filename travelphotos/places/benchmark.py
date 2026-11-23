"""Measure sign reading on a folder of labelled photos (#22), and the guess
from neighbouring photos on ordered sequences (#32).

    python -m travelphotos.places.benchmark                 # the repo's test set (+ benchmark-local/ if present)
    python -m travelphotos.places.benchmark --photos DIR --labels labels.csv --itinerary trip.txt
    python -m travelphotos.places.benchmark --local DIR     # your own photos, kept out of git

labels: labels.json ([{"file": ..., "expected": stop name or null}, ...]) or a
CSV with two columns: file, expected stop name (empty = should match nothing).
Runs entirely on this computer; the photos are only read.

A photo counts as
- 命中 (hit): its best stop is the expected one (medium or high confidence),
- 錯站 (wrong): a photo with a place name got another stop,
- 誤判 (false positive): a photo that should match nothing got any stop,
- 未讀出 (miss): a photo with a place name got no stop.
The decision is the app's own: two different places scoring within
AMBIGUOUS_MARGIN of each other give no stop.

Sequences (#32): sequences.json ([{"name": ..., "photos": [{"file": ...,
"expected": stop or null}, ...]}, ...]) or sequence.csv (file, expected
stop; one trip). Photos are listed in shooting order, and file paths are
relative to that file. Here `expected` is what the app should end up
showing: the stop the photo was taken at, read from text or guessed
(推測) from the photos before and after; null = it must stay 不確定. Each
photo is its own group, so the app's text decision and its neighbour guess
(pipeline.infer_in_order) are measured; look-alike matching is not.

Local photos: the folder benchmark-local/ at the top of the repository is
git-ignored. Put your own photos there with labels.json / labels.csv,
sequences.json / sequence.csv and, optionally, itinerary.txt; it is read
whenever it exists. Never commit your own photos.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

from ..faces import media
from ..itinerary import parse_itinerary
from .matching import best_matches, normalize
from .pipeline import AMBIGUOUS_MARGIN, OCR_MAX_SIDE, GroupPlace, _decide_by_text, infer_in_order

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SET = os.path.join(REPO, "tests", "data", "signs")
DEFAULT_SEQUENCES = os.path.join(REPO, "tests", "data", "sequences", "sequences.json")
# The owner's own photos and labels; listed in .gitignore, never committed.
LOCAL_DIR = os.path.join(REPO, "benchmark-local")
# The itinerary the test set is labelled against: a Japan tour, with
# look-alike names (嵐山 / 富士山) and stations next to places of the same name.
ITINERARY = """第1天：伏見稻荷大社 → 清水寺 → 京都車站 → 京都飯店
第2天：嵐山 → 金閣寺 → 奈良公園
第3天：淺草寺 → 雷門 → 東京鐵塔 → 富士山
"""


def load_labels(path: str) -> list[dict]:
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        return [{"file": r["file"], "expected": r.get("expected") or None} for r in rows]
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [{"file": r[0].strip(), "expected": (r[1].strip() if len(r) > 1 else "") or None} for r in csv.reader(fh) if r and r[0].strip()]


def load_sequences(path: str) -> list[dict]:
    """[{"name", "photos": [{"file", "expected"}]}] with files made absolute."""
    base = os.path.dirname(os.path.abspath(path))
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data and isinstance(data[0], dict) and "photos" not in data[0]:
            data = [{"name": os.path.basename(path), "photos": data}]
    else:
        data = [{"name": os.path.basename(path), "photos": load_labels(path)}]
    out = []
    for i, seq in enumerate(data, start=1):
        photos = [{"file": os.path.join(base, p["file"]), "expected": p.get("expected") or None} for p in seq["photos"]]
        out.append({"name": seq.get("name") or f"sequence {i}", "photos": photos})
    return out


def _find(folder: str, *names: str) -> str | None:
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


class _Reader:
    """Reads each photo once, even when a sequence uses it again."""

    def __init__(self, engine):
        self.engine = engine
        self.cache: dict[str, list[str]] = {}

    def read_text(self, path: str) -> list[str]:
        key = os.path.abspath(path)
        if key not in self.cache:
            rgb = media.load_photo(key, OCR_MAX_SIDE)
            self.cache[key] = list(self.engine.read_text(rgb)) if rgb is not None else []
        return self.cache[key]


def decide(lines: list[str], stops, rules: str = "full") -> str | None:
    matches = best_matches([("", line) for line in lines], stops, rules)
    if not matches:
        return None
    top = matches[0]
    rival = next((m for m in matches[1:] if normalize(m.stop.name) != normalize(top.stop.name)), None)
    if rival is not None and top.score - rival.score < AMBIGUOUS_MARGIN:
        return None
    return top.stop.name


def make_engine(kind: str):
    from .models import model_dir
    from .ocr import LegacyZooOcr, load_engine

    return LegacyZooOcr(model_dir()) if kind == "legacy" else load_engine()


def run(photos: str, labels: list[dict], itinerary: str, engine, rules: str = "full") -> dict:
    stops = parse_itinerary(itinerary)
    reader = engine if isinstance(engine, _Reader) else _Reader(engine)
    rows, started = [], time.time()
    for item in labels:
        lines = reader.read_text(os.path.join(photos, item["file"]))
        got = decide(lines, stops, rules)
        exp = item["expected"]
        if exp is None:
            outcome = "ok" if got is None else "false_positive"
        elif got is None:
            outcome = "miss"
        else:
            outcome = "hit" if normalize(got) == normalize(exp) else "wrong"
        rows.append({"file": item["file"], "expected": exp, "got": got, "outcome": outcome, "lines": lines})
    positives = [r for r in rows if r["expected"] is not None]
    negatives = [r for r in rows if r["expected"] is None]
    return {
        "photos": len(rows),
        "hits": sum(r["outcome"] == "hit" for r in rows),
        "positives": len(positives),
        "wrong": sum(r["outcome"] == "wrong" for r in rows),
        "false_positives": sum(r["outcome"] == "false_positive" for r in rows),
        "negatives": len(negatives),
        "seconds_per_photo": round((time.time() - started) / max(1, len(rows)), 2),
        "rows": rows,
    }


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and normalize(a) == normalize(b)


def _outcome(expected: str | None, got: str | None, how: str) -> str:
    if expected is None:
        return "ok" if got is None else "wrong"
    if got is None:
        return "uncertain"
    if not _same(got, expected):
        return "wrong"
    return "inferred_hit" if how == "inferred" else "hit"


def run_sequences(sequences: list[dict], itinerary: str, engine) -> dict:
    """The app's text decision, then its guess from neighbouring photos (#32).

    Each photo is one group, in the listed order. Returns rows and counts
    both before the guess (text only) and after it.
    """
    stops = parse_itinerary(itinerary)
    reader = engine if isinstance(engine, _Reader) else _Reader(engine)
    rows = []
    for seq in sequences:
        order, seen = [], set()
        for item in seq["photos"]:
            key = os.path.basename(item["file"])
            while key in seen:
                key += "'"
            seen.add(key)
            gp = GroupPlace(key=key, member_ids=[key])
            gp.texts = [(key, line) for line in reader.read_text(item["file"]) if line.strip()]
            if stops:
                _decide_by_text(gp, stops)
            order.append(gp)
        text_only = [gp.stop.name if gp.stop else None for gp in order]
        if stops:
            infer_in_order(order)
        for item, gp, before in zip(seq["photos"], order, text_only):
            got = gp.stop.name if gp.stop else None
            rows.append(
                {
                    "sequence": seq["name"],
                    "file": gp.key,
                    "expected": item["expected"],
                    "text_got": before,
                    "text_outcome": _outcome(item["expected"], before, "text"),
                    "got": got,
                    "how": gp.method if gp.stop else "",
                    "outcome": _outcome(item["expected"], got, gp.method),
                    "evidence": gp.evidence,
                    "lines": [t for _f, t in gp.texts],
                }
            )

    def count(field: str, *values: str) -> int:
        return sum(r[field] in values for r in rows)

    return {
        "photos": len(rows),
        "positives": sum(r["expected"] is not None for r in rows),
        "negatives": sum(r["expected"] is None for r in rows),
        "before": {
            "hits": count("text_outcome", "hit"),
            "uncertain": count("text_outcome", "uncertain"),
            "kept_uncertain": count("text_outcome", "ok"),
            "wrong": count("text_outcome", "wrong"),
        },
        "text_hits": count("outcome", "hit"),
        "inferred_hits": count("outcome", "inferred_hit"),
        "uncertain": count("outcome", "uncertain"),
        "kept_uncertain": count("outcome", "ok"),
        "wrong": count("outcome", "wrong"),
        "rows": rows,
    }


_SEQ_LABEL = {"hit": "命中（文字）", "inferred_hit": "命中（推測）", "uncertain": "不確定（應有站）", "ok": "正確（保持不確定）", "wrong": "錯站"}


def report_sequences(result: dict, out=None) -> None:
    out = out or sys.stdout
    current = None
    for r in result["rows"]:
        if r["sequence"] != current:
            current = r["sequence"]
            print(f"[{current}]", file=out)
        exp = r["expected"] or "（應保持不確定）"
        got = "不確定" if r["got"] is None else (f"推測：{r['got']}" if r["how"] == "inferred" else r["got"])
        print(f"  {r['file']}\t預期 {exp}\t結果 {got}\t{_SEQ_LABEL[r['outcome']]}\t{r['evidence']}", file=out)
    b = result["before"]
    print(
        f"推測前：命中 {b['hits']}/{result['positives']}，錯站 {b['wrong']}；"
        f"推測後：命中 {result['text_hits'] + result['inferred_hits']}/{result['positives']}"
        f"（文字 {result['text_hits']}、推測 {result['inferred_hits']}），"
        f"不確定 {result['uncertain']}，保持不確定 {result['kept_uncertain']}/{result['negatives']}，錯站 {result['wrong']}",
        file=out,
    )


_LABEL = {"hit": "命中", "ok": "正確（沒有對到）", "miss": "未讀出", "wrong": "錯站", "false_positive": "誤判"}


def report(result: dict, out=None) -> None:
    out = out or sys.stdout
    for r in result["rows"]:
        exp = r["expected"] or "（不應對到）"
        lines = "、".join(r["lines"][:8])
        print(f"{r['file']}\t預期 {exp}\t結果 {r['got'] or '不確定'}\t{_LABEL[r['outcome']]}\t讀到：{lines}", file=out)
    print(
        f"命中 {result['hits']}/{result['positives']}，錯站 {result['wrong']}，"
        f"誤判 {result['false_positives']}/{result['negatives']}，每張 {result['seconds_per_photo']} 秒",
        file=out,
    )


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="招牌辨識命中率與前後照片推測（只在本機執行）")
    ap.add_argument("--photos", help="照片資料夾；預設為 repo 的測試集")
    ap.add_argument("--labels", help="labels.json 或 CSV（檔案, 預期站名）；預設為照片資料夾裡的 labels.json")
    ap.add_argument("--sequences", help="照片順序檔 sequences.json 或 sequence.csv（依拍攝順序列出，預期站名）")
    ap.add_argument("--itinerary", help="行程表文字檔；預設為測試集用的行程表")
    ap.add_argument("--local", help=f"本機額外照片資料夾（預設 {LOCAL_DIR}，已列在 .gitignore）")
    ap.add_argument("--no-local", action="store_true", help="不讀本機額外照片")
    ap.add_argument("--engine", choices=["new", "legacy"], default="new", help="legacy = #22 之前的辨識模型")
    ap.add_argument("--rules", choices=["full", "basic"], default="full", help="basic = #22 之前的比對規則（只用於單張）")
    ap.add_argument("--json", help="另存完整結果為 JSON")
    args = ap.parse_args(argv)
    itinerary = _read(args.itinerary) if args.itinerary else ITINERARY

    sets = []  # (title, photos dir, labels path or None, sequences path or None, itinerary)
    if args.photos:
        sets.append(("照片", args.photos, args.labels or _find(args.photos, "labels.json"), args.sequences or _find(args.photos, "sequences.json", "sequence.csv"), itinerary))
    else:
        sets.append(("公開測試集", DEFAULT_SET, args.labels or os.path.join(DEFAULT_SET, "labels.json"), args.sequences or DEFAULT_SEQUENCES, itinerary))
    local = args.local or (None if args.photos else LOCAL_DIR)
    if local and not args.no_local:
        if os.path.isdir(local):
            own = _find(local, "itinerary.txt")
            sets.append(
                (
                    f"本機額外照片（{local}）",
                    local,
                    _find(local, "labels.json", "labels.csv"),
                    _find(local, "sequences.json", "sequence.csv"),
                    _read(own) if own else itinerary,
                )
            )
        elif args.local:
            ap.error(f"找不到資料夾：{args.local}")

    reader = _Reader(make_engine(args.engine))
    results = []
    for title, photos, labels, sequences, trip in sets:
        entry: dict = {"title": title}
        print(f"== {title} ==")
        if labels:
            entry["photos"] = run(photos, load_labels(labels), trip, reader, args.rules)
            report(entry["photos"])
        if sequences:
            print("-- 前後照片推測 --")
            entry["sequences"] = run_sequences(load_sequences(sequences), trip, reader)
            report_sequences(entry["sequences"])
        if not labels and not sequences:
            print("沒有 labels.json／labels.csv 或 sequences.json／sequence.csv，略過。")
        results.append(entry)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
