"""Measure sign reading on a folder of labelled photos (#22).

    python -m travelphotos.places.benchmark                 # the repo's test set
    python -m travelphotos.places.benchmark --photos DIR --labels labels.csv --itinerary trip.txt

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
from .pipeline import AMBIGUOUS_MARGIN, OCR_MAX_SIDE

DEFAULT_SET = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tests", "data", "signs")
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
    rows, started = [], time.time()
    for item in labels:
        rgb = media.load_photo(os.path.join(photos, item["file"]), OCR_MAX_SIDE)
        lines = engine.read_text(rgb) if rgb is not None else []
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


_LABEL = {"hit": "命中", "ok": "正確（沒有對到）", "miss": "未讀出", "wrong": "錯站", "false_positive": "誤判"}


def report(result: dict, out=sys.stdout) -> None:
    for r in result["rows"]:
        exp = r["expected"] or "（不應對到）"
        lines = "、".join(r["lines"][:8])
        print(f"{r['file']}\t預期 {exp}\t結果 {r['got'] or '未知'}\t{_LABEL[r['outcome']]}\t讀到：{lines}", file=out)
    print(
        f"命中 {result['hits']}/{result['positives']}，錯站 {result['wrong']}，"
        f"誤判 {result['false_positives']}/{result['negatives']}，每張 {result['seconds_per_photo']} 秒",
        file=out,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="招牌辨識命中率（只在本機執行）")
    ap.add_argument("--photos", default=DEFAULT_SET, help="照片資料夾")
    ap.add_argument("--labels", help="labels.json 或 CSV（檔案, 預期站名）；預設為照片資料夾裡的 labels.json")
    ap.add_argument("--itinerary", help="行程表文字檔；預設為測試集用的行程表")
    ap.add_argument("--engine", choices=["new", "legacy"], default="new", help="legacy = #22 之前的辨識模型")
    ap.add_argument("--rules", choices=["full", "basic"], default="full", help="basic = #22 之前的比對規則")
    ap.add_argument("--json", help="另存完整結果為 JSON")
    args = ap.parse_args(argv)
    labels = load_labels(args.labels or os.path.join(args.photos, "labels.json"))
    itinerary = ITINERARY
    if args.itinerary:
        with open(args.itinerary, encoding="utf-8") as fh:
            itinerary = fh.read()
    result = run(args.photos, labels, itinerary, make_engine(args.engine), args.rules)
    report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
