"""Copy files into a new output folder in the estimated order and write a report.

The input folder is only read. Files are copied, never moved, and the output
folder must be outside the input folder.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime

from .ordering import CONFIDENCE_LABEL, OrderResult
from .scan import ScanResult

MANIFEST = ".travelphotos-manifest.json"
REPORT_CSV = "report.csv"
REPORT_JSON = "report.json"
_TMP_PREFIX = ".travelphotos-tmp-"
_KIND_LABEL = {"photo": "照片", "video": "影片"}


class OutputError(Exception):
    """The output folder cannot be used. The message is shown to the owner."""


def _inside(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives on Windows
        return False


def _load_manifest(out: str) -> dict | None:
    path = os.path.join(out, MANIFEST)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        raise OutputError(f"無法讀取輸出資料夾中的 {MANIFEST}，請改用新的輸出資料夾。")
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise OutputError(f"{MANIFEST} 格式不正確，請改用新的輸出資料夾。")
    return data


def check_output_dir(input_dir: str, output_dir: str) -> dict | None:
    """Validate output_dir and return its manifest when it is ours already."""
    if not output_dir or not output_dir.strip():
        raise OutputError("請輸入輸出資料夾。")
    inp = os.path.realpath(input_dir)
    out = os.path.realpath(os.path.expanduser(output_dir.strip()))
    if _inside(out, inp):
        raise OutputError("輸出資料夾不能是輸入資料夾，也不能放在輸入資料夾裡面。")
    if _inside(inp, out):
        raise OutputError("輸入資料夾不能放在輸出資料夾裡面。")
    if not os.path.exists(out):
        return None
    if not os.path.isdir(out):
        raise OutputError("輸出路徑已存在，但不是資料夾。")
    manifest = _load_manifest(out)
    if manifest is None:
        if os.listdir(out):
            raise OutputError("輸出資料夾不是空的。請選一個新的或空的資料夾。")
        return None
    if os.path.realpath(manifest.get("input_dir", "")) != inp:
        raise OutputError("這個輸出資料夾是另一個輸入資料夾的結果。請選一個新的或空的資料夾。")
    return manifest


def output_name(position: int, total: int, original: str) -> str:
    width = max(4, len(str(total)))
    return f"{position:0{width}d}_{original}"


def apply(scan: ScanResult, result: OrderResult, output_dir: str, chat_summary: list | None = None) -> dict:
    """Write (or re-order) the output folder. Returns a short summary."""
    manifest = check_output_dir(scan.input_dir, output_dir)
    out = os.path.realpath(os.path.expanduser(output_dir.strip()))
    managed: dict[str, str] = dict(manifest["files"]) if manifest else {}
    managed = {sha: name for sha, name in managed.items() if os.path.isfile(os.path.join(out, name))}

    total = len(result.placements)
    targets = {p.file.sha256: output_name(p.position, total, p.file.name) for p in result.placements}
    owned_names = set(managed.values())
    for name in targets.values():
        if os.path.exists(os.path.join(out, name)) and name not in owned_names:
            raise OutputError(f"輸出資料夾中已有不是本工具產生的檔案：{name}")

    os.makedirs(out, exist_ok=True)

    # Every change to the output folder is logged so a failure part-way can be
    # undone; the folder then matches its manifest again, as before the run.
    undo: list[tuple[str, str, str | None]] = []

    def move(src: str, dst: str) -> None:
        os.replace(os.path.join(out, src), os.path.join(out, dst))
        undo.append(("move", src, dst))

    def create(name: str) -> str:
        undo.append(("create", name, None))
        return os.path.join(out, name)

    leftovers: list[str] = []
    copied = renamed = 0
    try:
        # Phase 1: move files we wrote before out of the way, so new names cannot clash.
        staged: dict[str, str] = {}
        for i, (sha, name) in enumerate(sorted(managed.items())):
            tmp = f"{_TMP_PREFIX}{i}"
            move(name, tmp)
            staged[sha] = tmp

        # Phase 2: put every file at its new name.
        new_manifest: dict[str, str] = {}
        for p in result.placements:
            sha = p.file.sha256
            if sha in staged:
                move(staged.pop(sha), targets[sha])
                renamed += 1
            else:
                shutil.copy2(p.file.path, create(targets[sha]))
                copied += 1
            new_manifest[sha] = targets[sha]

        # Files from an earlier run that are no longer part of the order stay, renamed.
        for sha, tmp in staged.items():
            base = "未使用_" + managed[sha]
            name, n = base, 1
            while os.path.exists(os.path.join(out, name)):
                n += 1
                name = f"未使用{n}_{managed[sha]}"
            move(tmp, name)
            leftovers.append(name)

        # Reports and manifest: write new copies first, then swap them in,
        # keeping the old ones until the very end. The manifest goes last.
        _write_reports(out, scan, result, chat_summary or [], targets, prefix=_TMP_PREFIX, create=create)
        with open(create(_TMP_PREFIX + MANIFEST), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "version": 1,
                    "input_dir": scan.input_dir,
                    "updated": datetime.now().isoformat(timespec="seconds"),
                    "files": new_manifest,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        backups: list[str] = []
        for final in (REPORT_CSV, REPORT_JSON, MANIFEST):
            if os.path.exists(os.path.join(out, final)):
                backup = f"{_TMP_PREFIX}old-{final}"
                move(final, backup)
                backups.append(backup)
            move(_TMP_PREFIX + final, final)
    except BaseException as exc:
        failed = _rollback(out, undo)
        if failed:
            raise OutputError(
                "輸出途中發生錯誤，且無法完全還原輸出資料夾（"
                + "、".join(failed)
                + "）。請改用新的輸出資料夾。"
            ) from exc
        if isinstance(exc, OSError):
            raise OutputError(f"輸出途中發生錯誤，已還原輸出資料夾，未做任何變更：{exc}") from exc
        raise

    for backup in backups:
        try:
            os.remove(os.path.join(out, backup))
        except OSError:
            pass
    return {
        "output_dir": out,
        "written": total,
        "copied": copied,
        "renamed": renamed,
        "duplicates_skipped": len(scan.duplicates),
        "leftovers": leftovers,
        "report": os.path.join(out, REPORT_CSV),
    }


def report_rows(scan: ScanResult, result: OrderResult, targets: dict[str, str] | None = None) -> list[dict]:
    total = len(result.placements)
    rows = []
    for p in result.placements:
        name = targets[p.file.sha256] if targets else output_name(p.position, total, p.file.name)
        rows.append(
            {
                "新順序": p.position,
                "新檔名": name,
                "原始檔案": p.file.id,
                "類型": _KIND_LABEL.get(p.file.kind, p.file.kind),
                "可信度": CONFIDENCE_LABEL[p.confidence],
                "排序依據": p.basis,
                "推定時間": p.estimated_time.strftime("%Y-%m-%d %H:%M:%S") if p.estimated_time else "",
                "分組": p.group,
                "行程站點": f"{p.stop.index}. {p.stop.name}" if p.stop else ("未對應" if p.unmatched else ""),
                "手動調整": "是" if p.manual else "",
            }
        )
    for d in scan.duplicates:
        rows.append(
            {
                "新順序": "",
                "新檔名": "",
                "原始檔案": d.file.id,
                "類型": _KIND_LABEL.get(d.file.kind, d.file.kind),
                "可信度": "",
                "排序依據": f"重複檔：內容與 {d.duplicate_of} 完全相同，已略過，未輸出",
                "推定時間": "",
                "分組": "",
                "行程站點": "",
                "手動調整": "",
            }
        )
    return rows


REPORT_FIELDS = ["新順序", "新檔名", "原始檔案", "類型", "可信度", "排序依據", "推定時間", "分組", "行程站點", "手動調整"]


def _rollback(out: str, undo: list[tuple[str, str, str | None]]) -> list[str]:
    """Undo logged changes, newest first. Returns names that could not be restored."""
    failed: list[str] = []
    for op, a, b in reversed(undo):
        try:
            if op == "move":
                os.replace(os.path.join(out, b), os.path.join(out, a))
            elif os.path.exists(os.path.join(out, a)):
                os.remove(os.path.join(out, a))
        except OSError:
            failed.append(a)
    return failed


def _write_reports(
    out: str,
    scan: ScanResult,
    result: OrderResult,
    chat_summary: list,
    targets: dict[str, str],
    prefix: str = "",
    create=None,
) -> None:
    def path(name: str) -> str:
        return create(prefix + name) if create else os.path.join(out, prefix + name)

    rows = report_rows(scan, result, targets)
    # utf-8-sig so Excel shows the Chinese headers correctly.
    with open(path(REPORT_CSV), "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with open(path(REPORT_JSON), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "input_dir": scan.input_dir,
                "input_media": scan.total_media,
                "output_files": len(result.placements),
                "duplicates": [{"file": d.file.id, "duplicate_of": d.duplicate_of} for d in scan.duplicates],
                "unsupported_files": scan.skipped,
                "line_chat_reference": chat_summary,
                "files": rows[: len(result.placements)],
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
