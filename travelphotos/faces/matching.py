"""Decide whether a file shows one of the selected people.

Owner's answers on #6:
- unsure (side face, blur, unclear face) -> keep and mark "uncertain";
- group photos with strangers are kept when a selected person is in them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .store import Person

# SFace cosine similarity. 0.363 is OpenCV's recommended same-person threshold.
MATCH = 0.363
# Between UNCERTAIN and MATCH the face may be the person: keep, but say so.
UNCERTAIN = 0.28

MATCH_KEEP, UNCERTAIN_KEEP, UNREADABLE_KEEP = "match", "uncertain", "unreadable"
NO_FACES, OTHERS = "no_faces", "others"
STATUS_LABEL = {
    MATCH_KEEP: "保留",
    UNCERTAIN_KEEP: "保留（不確定）",
    UNREADABLE_KEEP: "保留（不確定）",
    NO_FACES: "排除",
    OTHERS: "排除",
}


@dataclass
class Decision:
    keep: bool
    status: str
    reason: str
    people: list[str] = field(default_factory=list)
    uncertain_people: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return STATUS_LABEL[self.status]


class Matcher:
    """Nearest known person for a face vector."""

    def __init__(self, people: list[Person]):
        self.people = [p for p in people if p.embeddings]
        rows, owners = [], []
        for i, p in enumerate(self.people):
            for e in p.embeddings:
                rows.append(e)
                owners.append(i)
        self._matrix = np.asarray(rows, dtype="float64").reshape(len(rows), -1) if rows else None
        self._owners = np.asarray(owners, dtype="int64")

    def similarities(self, embedding: list[float]) -> dict[str, float]:
        """Best cosine similarity per person id."""
        if self._matrix is None:
            return {}
        sims = self._matrix @ np.asarray(embedding, dtype="float64")
        best: dict[str, float] = {}
        for owner, s in zip(self._owners.tolist(), sims.tolist()):
            pid = self.people[owner].id
            if s > best.get(pid, -2.0):
                best[pid] = s
        return best

    def name(self, person_id: str) -> str:
        return next(p.name for p in self.people if p.id == person_id)

    def identify(self, embedding: list[float]) -> tuple[str | None, float]:
        """(person id, similarity) of the closest known person at or above MATCH."""
        sims = self.similarities(embedding)
        if not sims:
            return None, 0.0
        pid, s = max(sims.items(), key=lambda kv: kv[1])
        return (pid, s) if s >= MATCH else (None, s)


def decide(embeddings: list[list[float]], readable: bool, matcher: Matcher, selected: set[str]) -> Decision:
    """Decision for one file from all face vectors found in it."""
    matched: list[str] = []
    maybe: list[str] = []
    for emb in embeddings:
        sims = matcher.similarities(emb)
        if not sims:
            continue
        top, top_s = max(sims.items(), key=lambda kv: kv[1])
        if top_s >= MATCH and top in selected:
            if top not in matched:
                matched.append(top)
            continue
        if top_s >= MATCH:
            continue  # clearly someone else the owner saved, but did not select
        for pid in selected:
            if sims.get(pid, -1.0) >= UNCERTAIN and pid not in maybe:
                maybe.append(pid)
    names = [matcher.name(p) for p in matched]
    maybe_names = [matcher.name(p) for p in maybe if p not in matched]
    if names:
        reason = "偵測到：" + "、".join(names)
        if maybe_names:
            reason += "（可能還有：" + "、".join(maybe_names) + "）"
        return Decision(True, MATCH_KEEP, reason, names, maybe_names)
    if maybe_names:
        return Decision(
            True,
            UNCERTAIN_KEEP,
            "可能是 " + "、".join(maybe_names) + "（人臉不清楚或相似度不足），先保留",
            [],
            maybe_names,
        )
    if not readable:
        return Decision(True, UNREADABLE_KEEP, "無法讀取這個檔案做人臉辨識，先保留")
    if not embeddings:
        return Decision(False, NO_FACES, "未偵測到指定人物（沒有偵測到人臉）")
    return Decision(False, OTHERS, f"未偵測到指定人物（偵測到 {len(embeddings)} 張其他人臉）")
