"""Measure accuracy on a labelled set of photos:

    python -m travelphotos.faces.evaluate --photos DIR --labels labels.csv --people 本人,媽媽

labels.csv has two columns, file and people (names separated by ; or 、;
empty when none of the saved people appear). People must already be saved
in the tool. Prints a per-file table and the accuracy, and can write a CSV.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass

from . import matching, paths, pipeline
from .store import FaceStore


@dataclass
class Evaluation:
    rows: list[dict]
    total: int
    correct: int
    true_keep: int
    false_keep: int
    missed: int
    true_exclude: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        kept = self.true_keep + self.false_keep
        return self.true_keep / kept if kept else 0.0

    @property
    def recall(self) -> float:
        wanted = self.true_keep + self.missed
        return self.true_keep / wanted if wanted else 0.0


def read_labels(path: str) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip() or row[0].strip().lower() in {"file", "檔案"}:
                continue
            names = row[1] if len(row) > 1 else ""
            labels[row[0].strip()] = {n.strip() for n in re.split(r"[;；、,]", names) if n.strip()}
    return labels


def evaluate(decisions: dict[str, matching.Decision], labels: dict[str, set[str]], selected_names: set[str]) -> Evaluation:
    rows = []
    tk = fk = miss = te = 0
    for fid in sorted(labels):
        d = decisions.get(fid)
        if d is None:
            continue
        expected = bool(labels[fid] & selected_names)
        ok = expected == d.keep
        if expected and d.keep:
            tk += 1
        elif d.keep:
            fk += 1
        elif expected:
            miss += 1
        else:
            te += 1
        rows.append(
            {
                "檔案": fid,
                "標記人物": "、".join(sorted(labels[fid])),
                "應保留": "是" if expected else "否",
                "結果": d.label,
                "原因": d.reason,
                "正確": "是" if ok else "否",
            }
        )
    return Evaluation(rows, len(rows), tk + te, tk, fk, miss, te)


def summary_lines(ev: Evaluation) -> list[str]:
    return [
        f"檔案數：{ev.total}",
        f"準確率：{ev.accuracy:.1%}（{ev.correct}/{ev.total}）",
        f"保留的檔案中確實有指定人物（精確率）：{ev.precision:.1%}",
        f"有指定人物的檔案被保留（召回率）：{ev.recall:.1%}",
        f"誤留 {ev.false_keep} 個，漏掉 {ev.missed} 個",
    ]


def main(argv: list[str] | None = None, engine=None, store: FaceStore | None = None, out=sys.stdout) -> int:
    from ..scan import scan

    parser = argparse.ArgumentParser(prog="python -m travelphotos.faces.evaluate", description="用已標記的照片計算人物篩選的準確率")
    parser.add_argument("--photos", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--people", required=True, help="要保留的人名，用逗號分隔")
    parser.add_argument("--interval", default=pipeline.DEFAULT_INTERVAL)
    parser.add_argument("--report", help="另存結果 CSV")
    args = parser.parse_args(argv)

    if store is None:
        store = FaceStore(paths.store_path())
    if engine is None:
        from .engine import FaceUnavailable, load_engine

        try:
            engine = load_engine()
        except FaceUnavailable as exc:
            print(exc, file=sys.stderr)
            return 1
    wanted = {n.strip() for n in args.people.split(",") if n.strip()}
    selected = {p.id for p in store.people if p.name in wanted}
    unknown = wanted - {p.name for p in store.people}
    if unknown:
        print("工具裡沒有這些人：" + "、".join(sorted(unknown)), file=sys.stderr)
        return 2
    labels = read_labels(args.labels)
    files = scan(args.photos, compute_hash=False).files
    analysis = pipeline.analyze(engine, [f for f in files if f.id in labels], pipeline.check_interval(args.interval))
    matcher = matching.Matcher(store.people)
    decisions = {
        fid: matching.decide([h.face.embedding for h in ff.hits], ff.readable, matcher, selected) for fid, ff in analysis.items()
    }
    ev = evaluate(decisions, labels, wanted)
    for row in ev.rows:
        print(f"{row['正確']}\t{row['檔案']}\t應保留:{row['應保留']}\t{row['結果']}\t{row['原因']}", file=out)
    for line in summary_lines(ev):
        print(line, file=out)
    if args.report:
        with open(args.report, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["檔案", "標記人物", "應保留", "結果", "原因", "正確"])
            writer.writeheader()
            writer.writerows(ev.rows)
            fh.write("\n" + "\n".join(summary_lines(ev)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
