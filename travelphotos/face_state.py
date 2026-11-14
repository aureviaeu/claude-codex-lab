"""Server-side state for the "only me and family" step (#6).

Kept apart from server.py so the HTTP code stays small. Everything here runs
locally; see travelphotos/faces/__init__.py.
"""

from __future__ import annotations

import os

from . import output
from .faces import paths, pipeline
from .faces.engine import FaceUnavailable, LIBS_MISSING, MODELS_MISSING
from .faces.store import FaceStore, StoreError

# Face thumbnails shown per group on the page.
FACES_PER_CLUSTER = 6


def _libs_ok() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


class FaceState:
    """Called with AppState.lock held."""

    def __init__(self, data_dir: str | None = None, engine_factory=None):
        self.data_dir = data_dir or paths.data_dir()
        self._engine_factory = engine_factory
        self._engine = None
        self._store: FaceStore | None = None
        self.store_error = ""
        self._matcher = None
        self.reset_analysis()

    # --- lifecycle ----------------------------------------------------
    def reset_analysis(self) -> None:
        self.analysis: dict[str, pipeline.FileFaces] | None = None
        self.hits: list[pipeline.FaceHit] = []
        self.clusters = []
        self.interval = pipeline.DEFAULT_INTERVAL
        self.enabled = False
        self.selected: set[str] = set()
        self.decisions: dict | None = None

    @property
    def store(self) -> FaceStore:
        if self._store is None:
            try:
                self._store = FaceStore(paths.store_path(self.data_dir))
                self.store_error = ""
            except StoreError as exc:
                self.store_error = str(exc)
                raise
        return self._store

    def _people(self):
        try:
            return self.store.people
        except StoreError:
            return []

    def engine(self):
        if self._engine is None:
            if self._engine_factory is not None:
                self._engine = self._engine_factory()
            else:
                from .faces.engine import load_engine

                self._engine = load_engine(self.data_dir)
        return self._engine

    def availability(self) -> tuple[bool, str]:
        if self._engine is not None or self._engine_factory is not None:
            return True, ""
        if not _libs_ok():
            return False, LIBS_MISSING
        if paths.missing_models(paths.model_dir(self.data_dir)):
            return False, MODELS_MISSING
        return True, ""

    # --- actions ------------------------------------------------------
    def analyze(self, files, interval) -> None:
        interval = pipeline.check_interval(interval)
        engine = self.engine()
        self.analysis = pipeline.analyze(engine, files, interval)
        self.interval = interval
        self.hits = [h for ff in self.analysis.values() for h in ff.hits]
        from .faces.cluster import cluster_faces

        self.clusters = cluster_faces([h.face.embedding for h in self.hits])
        self._recompute()

    def add_reference(self, name: str, folder: str, person_id: str | None) -> dict:
        if not folder or not folder.strip():
            raise ValueError("請選擇放參考照片的資料夾。")
        embeddings, used, skipped = pipeline.reference_faces(self.engine(), folder.strip())
        if not embeddings:
            raise ValueError("這個資料夾裡的照片都沒有偵測到人臉。請放幾張這個人的清楚正面照。")
        person = self.store.add_embeddings(name, embeddings, person_id or None)
        self._recompute()
        return {"person": person.name, "used": used, "skipped": skipped}

    def save_cluster(self, cluster_id, name: str, person_id: str | None) -> str:
        cluster = next((c for c in self.clusters if c.id == cluster_id), None)
        if cluster is None:
            raise ValueError("找不到這一組人臉，請重新偵測。")
        person = self.store.add_embeddings(name, [self.hits[i].face.embedding for i in cluster.members], person_id or None)
        self._recompute()
        return person.name

    def select(self, person_ids, enabled) -> None:
        if not isinstance(person_ids, list) or not all(isinstance(x, str) for x in person_ids):
            raise ValueError("人物格式不正確。")
        known = {p.id for p in self._people()}
        self.selected = {x for x in person_ids if x in known}
        self.enabled = bool(enabled)
        self._recompute()

    def rename(self, person_id: str, name: str) -> None:
        self.store.rename(person_id, name)
        self._recompute()

    def remove_person(self, person_id: str) -> None:
        self.store.remove(person_id)
        self.selected.discard(person_id)
        self._recompute()

    def delete_all(self) -> bool:
        """Delete the saved face data file and every face vector in memory.

        Returns True when a saved file was removed. Works even when the file
        is damaged and cannot be loaded.
        """
        try:
            os.remove(paths.store_path(self.data_dir))
            removed = True
        except FileNotFoundError:
            removed = False
        self._store = None
        self.store_error = ""
        self._matcher = None
        self.reset_analysis()
        return removed

    def _recompute(self) -> None:
        from .faces import matching

        matcher = matching.Matcher(self._people())
        self.selected &= {p.id for p in matcher.people}
        if self.analysis is None or not self.selected:
            self.decisions = None
        else:
            self.decisions = {
                fid: matching.decide([h.face.embedding for h in ff.hits], ff.readable, matcher, self.selected)
                for fid, ff in self.analysis.items()
            }
        self._matcher = matcher

    # --- output -------------------------------------------------------
    def output_filter(self) -> output.FaceFilter | None:
        if not self.enabled:
            return None
        if self.analysis is None:
            raise ValueError("已勾選「只保留指定人物」，但還沒偵測人臉。請先按「偵測人臉」。")
        if not self.selected or self.decisions is None:
            raise ValueError("已勾選「只保留指定人物」，但還沒選要保留的人。")
        names = [p.name for p in self._people() if p.id in self.selected]
        return output.FaceFilter(people=names, decisions=dict(self.decisions))

    def hit(self, index: int):
        if 0 <= index < len(self.hits):
            return self.hits[index]
        return None

    def to_json(self) -> dict:
        ok, message = self.availability()
        people = []
        try:
            people = [{"id": p.id, "name": p.name, "count": len(p.embeddings)} for p in self.store.people]
        except StoreError as exc:
            message = str(exc)
        data = {
            "available": ok,
            "message": message,
            "store_error": self.store_error,
            "data_path": paths.store_path(self.data_dir),
            "people": people,
            "analyzed": self.analysis is not None,
            "interval": self.interval,
            "enabled": self.enabled,
            "selected": sorted(self.selected),
            "clusters": [],
            "decisions": {},
            "counts": None,
        }
        if self.analysis is not None:
            matcher = self._matcher
            for c in self.clusters:
                files = {self.hits[i].file_id for i in c.members}
                known = None
                if matcher is not None:
                    pid, _s = matcher.identify(c.centroid)
                    known = matcher.name(pid) if pid else None
                data["clusters"].append(
                    {"id": c.id, "faces": len(c.members), "files": len(files), "person": known, "samples": c.members[:FACES_PER_CLUSTER]}
                )
            data["unreadable"] = [fid for fid, ff in self.analysis.items() if not ff.readable]
        if self.decisions is not None:
            data["decisions"] = {
                fid: {"keep": d.keep, "status": d.status, "label": d.label, "reason": d.reason} for fid, d in self.decisions.items()
            }
            kept = [d for d in self.decisions.values() if d.keep]
            data["counts"] = {
                "kept": len(kept),
                "uncertain": sum(1 for d in kept if d.status != "match"),
                "excluded": len(self.decisions) - len(kept),
            }
        return data
