"""The owner's saved people ("me and family"), kept only on this computer.

One JSON file holds each person's name and face feature vectors, so the next
trip does not need setting up again (owner's answer on #6). `delete_all`
removes the file.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field

# Keep at most this many feature vectors per person; more adds little.
MAX_EMBEDDINGS = 60


class StoreError(Exception):
    """The face data file cannot be used. The message is shown to the owner."""


@dataclass
class Person:
    id: str
    name: str
    embeddings: list[list[float]] = field(default_factory=list)


def _clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise StoreError("請輸入名字。")
    if len(name) > 40:
        raise StoreError("名字太長（最多 40 個字）。")
    return name


class FaceStore:
    def __init__(self, path: str):
        self.path = path
        self.people: list[Person] = []
        self.load()

    def load(self) -> None:
        self.people = []
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            for item in data["people"]:
                embs = [[float(v) for v in e] for e in item["embeddings"]]
                self.people.append(Person(id=str(item["id"]), name=str(item["name"]), embeddings=embs))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.people = []
            raise StoreError(f"無法讀取人臉資料檔 {self.path}，可以按「刪除本機人臉資料」後重新設定。") from exc

    def save(self) -> None:
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        data = {
            "version": 1,
            "note": "Face features for travelphotos. Stored only on this computer.",
            "people": [
                {"id": p.id, "name": p.name, "embeddings": [[round(v, 6) for v in e] for e in p.embeddings]}
                for p in self.people
            ],
        }
        fd, tmp = tempfile.mkstemp(prefix=".faces-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def get(self, person_id: str) -> Person | None:
        return next((p for p in self.people if p.id == person_id), None)

    def add_embeddings(self, name: str, embeddings: list[list[float]], person_id: str | None = None) -> Person:
        """Add vectors to an existing person (by id) or to a new one (by name)."""
        if not embeddings:
            raise StoreError("沒有可用的人臉。")
        if person_id:
            person = self.get(person_id)
            if person is None:
                raise StoreError("找不到這個人，請重新整理頁面。")
        else:
            name = _clean_name(name)
            if any(p.name == name for p in self.people):
                raise StoreError(f"已經有叫「{name}」的人了。請選擇加到這個人，或換一個名字。")
            person = Person(id=secrets.token_hex(6), name=name)
            self.people.append(person)
        person.embeddings.extend([list(map(float, e)) for e in embeddings])
        if len(person.embeddings) > MAX_EMBEDDINGS:
            # Keep an even spread rather than only the newest.
            step = len(person.embeddings) / MAX_EMBEDDINGS
            person.embeddings = [person.embeddings[int(i * step)] for i in range(MAX_EMBEDDINGS)]
        self.save()
        return person

    def rename(self, person_id: str, name: str) -> None:
        person = self.get(person_id)
        if person is None:
            raise StoreError("找不到這個人，請重新整理頁面。")
        name = _clean_name(name)
        if any(p.name == name and p.id != person_id for p in self.people):
            raise StoreError(f"已經有叫「{name}」的人了。")
        person.name = name
        self.save()

    def remove(self, person_id: str) -> None:
        before = len(self.people)
        self.people = [p for p in self.people if p.id != person_id]
        if len(self.people) == before:
            raise StoreError("找不到這個人，請重新整理頁面。")
        self.save()

    def delete_all(self) -> bool:
        """Remove the face data file. Returns True when a file was removed."""
        self.people = []
        try:
            os.remove(self.path)
            return True
        except FileNotFoundError:
            return False
