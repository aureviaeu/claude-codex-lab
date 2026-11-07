"""Local web interface. Listens on 127.0.0.1 only; nothing is uploaded anywhere."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import folders, itinerary, ordering, output, similarity
from .face_state import FaceState
from .faces import pipeline as face_pipeline
from .faces.engine import FaceUnavailable
from .faces.store import StoreError
from .scan import ScanResult, scan

HOST = "127.0.0.1"
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MAX_BODY = 32 * 1024 * 1024
_STATIC = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class AppState:
    def __init__(self, default_input: str = "", data_dir: str | None = None, face_engine_factory=None):
        self.lock = threading.Lock()
        self.faces = FaceState(data_dir, face_engine_factory)
        self.default_input = default_input
        self.scan: ScanResult | None = None
        self.stops: list[itinerary.Stop] = []
        self.chat_summary: list[dict] = []
        self.assignments: dict[str, int] = {}
        self.manual_order: list[str] | None = None
        self.result: ordering.OrderResult | None = None

    # The methods below are called with self.lock held.
    def do_scan(self, input_dir: str, itinerary_text: str, chat_text: str) -> None:
        if not input_dir or not input_dir.strip():
            raise ValueError("請輸入要整理的資料夾。")
        self.scan = scan(os.path.expanduser(input_dir.strip()))
        self.stops = itinerary.parse_itinerary(itinerary_text or "")
        self.chat_summary = itinerary.summarize_chat(itinerary.parse_line_chat(chat_text or ""))
        self.assignments = {}
        self.manual_order = None
        self.faces.reset_analysis()
        self._recompute()

    def arrange(self, assignments: dict, manual_order: list | None) -> None:
        if self.scan is None:
            raise ValueError("請先掃描資料夾。")
        ids = {f.id for f in self.scan.files}
        clean: dict[str, int] = {}
        for fid, stop in (assignments or {}).items():
            if fid in ids and isinstance(stop, int) and not isinstance(stop, bool):
                clean[fid] = stop
        self.assignments = clean
        if manual_order is None:
            self.manual_order = None
        else:
            if not isinstance(manual_order, list) or not all(isinstance(x, str) for x in manual_order):
                raise ValueError("順序格式不正確。")
            self.manual_order = [x for x in manual_order if x in ids]
        self._recompute()

    def face_action(self, action: str, body: dict) -> dict:
        """POST /api/faces/<action>. Returns extra fields for the response."""
        faces = self.faces
        if action == "analyze":
            if self.scan is None:
                raise ValueError("請先掃描資料夾。")
            faces.analyze(self.scan.files, body.get("interval", face_pipeline.DEFAULT_INTERVAL))
            return {}
        if action == "reference":
            info = faces.add_reference(str(body.get("name") or ""), str(body.get("folder") or ""), str(body.get("person_id") or ""))
            return {"reference": info}
        if action == "save-cluster":
            cid = body.get("cluster_id")
            if not isinstance(cid, int) or isinstance(cid, bool):
                raise ValueError("人臉分組格式不正確。")
            return {"saved": faces.save_cluster(cid, str(body.get("name") or ""), str(body.get("person_id") or ""))}
        if action == "select":
            faces.select(body.get("person_ids", []), body.get("enabled", False))
            return {}
        if action == "rename":
            faces.rename(str(body.get("person_id") or ""), str(body.get("name") or ""))
            return {}
        if action == "remove":
            faces.remove_person(str(body.get("person_id") or ""))
            return {}
        if action == "delete-all":
            return {"deleted": faces.delete_all()}
        raise ValueError("找不到這個動作。")

    def _recompute(self) -> None:
        assert self.scan is not None
        self.result = ordering.order(self.scan.files, self.stops, self.assignments, self.manual_order)

    def to_json(self) -> dict:
        if self.scan is None or self.result is None:
            return {"scanned": False, "default_input": self.default_input, "similarity": similarity.available(), "faces": self.faces.to_json()}
        faces = self.faces.to_json()
        face_decisions = faces["decisions"]
        groups = []
        for g in self.result.groups:
            groups.append({"id": g.id, "size": len(g.members), "first": g.members[0].id, "stop": g.stop.index if g.stop else None})
        files = []
        for p in self.result.placements:
            files.append(
                {
                    "id": p.file.id,
                    "name": p.file.name,
                    "kind": p.file.kind,
                    "position": p.position,
                    "group": p.group,
                    "confidence": p.confidence,
                    "confidence_label": ordering.CONFIDENCE_LABEL[p.confidence],
                    "basis": p.basis,
                    "estimated_time": p.estimated_time.strftime("%Y-%m-%d %H:%M") if p.estimated_time else None,
                    "stop": p.stop.index if p.stop else None,
                    "unmatched": p.unmatched,
                    "manual": p.manual,
                    "face": face_decisions.get(p.file.id),
                }
            )
        return {
            "scanned": True,
            "similarity": similarity.available(),
            "input_dir": self.scan.input_dir,
            "input_media": self.scan.total_media,
            "files": files,
            "groups": groups,
            "duplicates": [{"id": d.file.id, "duplicate_of": d.duplicate_of} for d in self.scan.duplicates],
            "skipped": self.scan.skipped,
            "stops": [{"index": s.index, "day": s.day, "name": s.name} for s in self.stops],
            "assignments": self.assignments,
            "manual": self.manual_order is not None,
            "chat": self.chat_summary,
            "faces": faces,
        }


def make_handler(state: AppState, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "travelphotos"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        # --- helpers -------------------------------------------------
        def _host_ok(self) -> bool:
            port = self.server.server_address[1]
            host = (self.headers.get("Host") or "").strip().lower()
            return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _token_ok(self, query: dict) -> bool:
            given = self.headers.get("X-Token") or (query.get("token") or [""])[0]
            return hmac.compare_digest(given.encode(), token.encode())

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _guard(self) -> dict | None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if not self._host_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "只接受本機連線（localhost）。"})
                return None
            if parsed.path.startswith("/api/") and not self._token_ok(query):
                self._json(HTTPStatus.FORBIDDEN, {"error": "連線憑證不正確，請重新整理頁面。"})
                return None
            return {"path": parsed.path, "query": query}

        # --- routes --------------------------------------------------
        def do_GET(self):
            req = self._guard()
            if req is None:
                return
            path = req["path"]
            if path == "/":
                with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
                    html = fh.read().replace("__TOKEN__", token)
                self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")
            elif path in _STATIC:
                name, ctype = _STATIC[path]
                with open(os.path.join(STATIC_DIR, name), "rb") as fh:
                    self._send(HTTPStatus.OK, fh.read(), ctype)
            elif path == "/api/state":
                with state.lock:
                    self._json(HTTPStatus.OK, state.to_json())
            elif path == "/api/folders":
                try:
                    self._json(HTTPStatus.OK, folders.list_folders((req["query"].get("path") or [""])[0]))
                except folders.FolderError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            elif path == "/api/faces/crop":
                try:
                    index = int((req["query"].get("face") or [""])[0])
                except ValueError:
                    index = -1
                with state.lock:
                    hit = state.faces.hit(index)
                    files = {f.id: f for f in state.scan.files} if state.scan else {}
                item = files.get(hit.file_id) if hit else None
                data = face_pipeline.crop_jpeg(item.path, item.kind, hit.frame, hit.face.box) if item else None
                if data is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "沒有人臉圖"})
                else:
                    self._send(HTTPStatus.OK, data, "image/jpeg")
            elif path == "/api/thumb":
                fid = (req["query"].get("id") or [""])[0]
                with state.lock:
                    files = {f.id: f for f in state.scan.files} if state.scan else {}
                item = files.get(fid)
                data = similarity.thumbnail_jpeg(item.path) if item and item.kind == "photo" else None
                if data is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "沒有縮圖"})
                else:
                    self._send(HTTPStatus.OK, data, "image/jpeg")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "找不到"})

        def do_POST(self):
            req = self._guard()
            if req is None:
                return
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "需要 JSON。"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "資料太大。"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "JSON 格式不正確。"})
                return
            path = req["path"]
            try:
                with state.lock:
                    if path == "/api/scan":
                        state.do_scan(str(body.get("input_dir") or ""), str(body.get("itinerary") or ""), str(body.get("line_chat") or ""))
                        self._json(HTTPStatus.OK, state.to_json())
                    elif path == "/api/arrange":
                        assignments = body.get("assignments") or {}
                        if not isinstance(assignments, dict):
                            raise ValueError("站點對應格式不正確。")
                        state.arrange(assignments, body.get("manual_order"))
                        self._json(HTTPStatus.OK, state.to_json())
                    elif path == "/api/mkdir":
                        self._json(HTTPStatus.OK, folders.make_folder(str(body.get("parent") or ""), str(body.get("name") or "")))
                    elif path == "/api/apply":
                        if state.scan is None or state.result is None:
                            raise ValueError("請先掃描資料夾。")
                        summary = output.apply(
                            state.scan,
                            state.result,
                            str(body.get("output_dir") or ""),
                            state.chat_summary,
                            face_filter=state.faces.output_filter(),
                        )
                        self._json(HTTPStatus.OK, {"applied": summary, **state.to_json()})
                    elif path.startswith("/api/faces/"):
                        extra = state.face_action(path[len("/api/faces/") :], body)
                        self._json(HTTPStatus.OK, {**extra, **state.to_json()})
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "找不到"})
            except (ValueError, FileNotFoundError, output.OutputError, FaceUnavailable, StoreError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except OSError as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"檔案操作失敗：{exc}"})

    return Handler


def create_server(
    port: int = 8765, default_input: str = "", data_dir: str | None = None, face_engine_factory=None
) -> tuple[ThreadingHTTPServer, str, AppState]:
    """Create the server bound to 127.0.0.1. Returns (server, url, state)."""
    state = AppState(default_input, data_dir, face_engine_factory)
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((HOST, port), make_handler(state, token))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    return server, url, state
