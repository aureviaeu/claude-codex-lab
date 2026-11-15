"""#26: damaged model files and unexpected errors give a readable message."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import re
import subprocess
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

from launcher import download_models
from tests.face_helpers import ME, FakeEngine, save_photo
from tests.test_full_flow import _REPO, _browser_available, _playwright_entry
from tests.test_places import FakeOcr
from travelphotos import server as srv
from travelphotos.faces import paths as face_paths
from travelphotos.places import models as place_models
from travelphotos.places.ocr import OcrUnavailable


def _damage(directory: str, models) -> None:
    """Right size, unreadable content: what an interrupted copy leaves."""
    os.makedirs(directory, exist_ok=True)
    for m in models:
        with open(os.path.join(directory, m.name), "wb") as fh:
            fh.write(b"\0" * m.size)


class ServerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trip = os.path.join(self.tmp.name, "trip")
        self.data = os.path.join(self.tmp.name, "data")
        save_photo(os.path.join(self.trip, "a.jpg"), ME)

    def start(self, **kw):
        server, _url, state = srv.create_server(0, self.trip, data_dir=self.data, **kw)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.port = server.server_address[1]
        page = self.call("GET", "/")[1].decode()
        self.token = re.search(r'name="token" content="([^"]+)"', page).group(1)
        return state

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {"Host": f"127.0.0.1:{self.port}", "X-Token": getattr(self, "token", "")}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        out = (res.status, res.read())
        conn.close()
        return out

    def api(self, path, body=None):
        status, data = self.call("POST" if body is not None else "GET", path, body)
        return status, json.loads(data)


class ServerErrorTests(ServerBase):
    def test_damaged_text_model_gives_a_clear_message(self):
        _damage(place_models.model_dir(self.data), place_models.MODELS)
        self.start()
        self.api("/api/scan", {"input_dir": self.trip, "itinerary": "清水寺"})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 400)
        for word in ("文字辨識模型", "損壞", "啟動檔"):
            self.assertIn(word, data["error"])

    def test_each_damaged_onnxruntime_model_gives_the_same_message(self):
        """Review finding: the recognizer and direction models load with
        onnxruntime, whose errors are not RuntimeError."""
        from travelphotos.places import ocr

        for broken in (place_models.TEXT_RECOGNIZER, place_models.TEXT_DIRECTION):
            with self.subTest(model=broken.name), tempfile.TemporaryDirectory() as d:
                _damage(d, place_models.MODELS)
                with mock.patch("cv2.dnn.readNet", return_value=object()):  # the detector loads fine
                    with self.assertRaises(OcrUnavailable) as cm:
                        ocr.OnnxOcr(d)
                self.assertIn("損壞", str(cm.exception))

    def test_damaged_face_model_gives_a_clear_message(self):
        _damage(face_paths.model_dir(self.data), face_paths.MODELS)
        self.start()
        self.api("/api/scan", {"input_dir": self.trip})
        status, data = self.api("/api/faces/analyze", {"interval": 2})
        self.assertEqual(status, 400)
        for word in ("人臉模型", "損壞", "啟動檔"):
            self.assertIn(word, data["error"])

    def test_a_failed_load_is_not_remembered(self):
        calls = []

        def factory():
            calls.append(1)
            if len(calls) == 1:
                raise OcrUnavailable("文字辨識模型檔無法載入，可能已損壞")
            return FakeOcr({})

        self.start(place_engine_factory=factory, face_engine_factory=FakeEngine)
        self.api("/api/scan", {"input_dir": self.trip, "itinerary": "清水寺"})
        self.assertEqual(self.api("/api/places/analyze", {})[0], 400)
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["places"]["analyzed"])

    def test_unexpected_error_gives_500_and_the_server_keeps_working(self):
        state = self.start()
        with mock.patch.object(state, "do_scan", side_effect=RuntimeError("boom")), mock.patch("sys.stderr", io.StringIO()) as err:
            status, data = self.api("/api/scan", {"input_dir": self.trip})
        self.assertEqual(status, 500)
        self.assertIn("未預期的錯誤", data["error"])
        self.assertIn("RuntimeError", data["error"])
        self.assertNotIn("boom", data["error"], "no program details on the page")
        self.assertIn("boom", err.getvalue(), "details go to the terminal")
        self.assertEqual(self.api("/api/state")[0], 200)
        with mock.patch.object(type(state), "to_json", side_effect=KeyError("x")), mock.patch("sys.stderr", io.StringIO()):
            status, data = self.api("/api/state")
        self.assertEqual(status, 500)
        self.assertIn("KeyError", data["error"])

    def test_missing_models_message_is_unchanged(self):
        self.start()
        self.api("/api/scan", {"input_dir": self.trip, "itinerary": "清水寺"})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 400)
        self.assertIn("還沒有下載文字辨識模型", data["error"])


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LauncherRepairTests(unittest.TestCase):
    """Restarting with the launcher replaces a damaged model of the same size."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_damaged_face_model_is_downloaded_again(self):
        payload = b"good face model"
        model = face_paths.ModelFile("f.onnx", hashlib.sha256(payload).hexdigest(), "https://example.invalid/f.onnx", len(payload))
        with open(os.path.join(self.tmp.name, "f.onnx"), "wb") as fh:
            fh.write(b"\0" * len(payload))
        with mock.patch.object(face_paths, "MODELS", (model,)), mock.patch.object(place_models, "MODELS", ()):
            ok = download_models.ensure_models(self.tmp.name, log=lambda *_: None, opener=lambda u, timeout: FakeResponse(payload))
        self.assertTrue(ok)
        with open(os.path.join(self.tmp.name, "f.onnx"), "rb") as fh:
            self.assertEqual(fh.read(), payload)

    def test_damaged_text_model_is_taken_from_the_wheel_again(self):
        import zipfile

        good = b"good text model"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("pkg/t.onnx", good)
        wheel_bytes = buf.getvalue()
        model = place_models.WheelModel("t.onnx", "pkg/t.onnx", hashlib.sha256(good).hexdigest(), len(good))
        wheel = place_models.WheelFile("https://example.invalid/p.whl", hashlib.sha256(wheel_bytes).hexdigest(), len(wheel_bytes))
        with open(os.path.join(self.tmp.name, "t.onnx"), "wb") as fh:
            fh.write(b"\0" * len(good))
        with mock.patch.multiple(place_models, WHEEL=wheel, MODELS=(model,)):
            ok = download_models.ensure_ocr_models(self.tmp.name, log=lambda *_: None, opener=lambda u, timeout: FakeResponse(wheel_bytes))
        self.assertTrue(ok)
        with open(os.path.join(self.tmp.name, "t.onnx"), "rb") as fh:
            self.assertEqual(fh.read(), good)


class PageMessageCodeTests(unittest.TestCase):
    def test_page_catches_a_failed_request(self):
        with open(os.path.join(_REPO, "travelphotos", "static", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertRegex(js, r"try\s*\{\s*res = await fetch\(path, opts\);\s*\}\s*catch")
        self.assertIn("工具沒有回應，請確認啟動檔的視窗還開著", js)
        self.assertIn("工具回應無法讀取", js)


_PAGE_SCRIPT = textwrap.dedent(
    r"""
    const { chromium } = require(process.env.TRAVELPHOTOS_PLAYWRIGHT);
    const [url, trip] = process.argv.slice(2);
    (async () => {
      const browser = await chromium.launch();
      const page = await browser.newPage();
      const results = {};
      for (const mode of ["500", "400", "notjson", "abort"]) {
        await page.unroute("**/api/scan");
        await page.route("**/api/scan", (route) => {
          if (mode === "500") return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "伺服器說 500" }) });
          if (mode === "400") return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "伺服器說 400" }) });
          if (mode === "notjson") return route.fulfill({ status: 502, contentType: "text/html", body: "<h1>Bad Gateway</h1>" });
          return route.abort("connectionrefused");
        });
        await page.goto(url);
        await page.fill("#input-dir", trip);
        await page.click("#scan");
        await page.waitForFunction(() => document.querySelector("#scan-status").classList.contains("error"));
        results[mode] = await page.textContent("#scan-status");
      }
      console.log(JSON.stringify(results));
      await browser.close();
    })().catch((e) => { console.error(e); process.exit(1); });
    """
)


@unittest.skipUnless(_browser_available(), "no browser automation (node + playwright) on this computer")
class PageMessageBrowserTests(ServerBase):
    def test_page_shows_server_and_connection_errors_in_chinese(self):
        self.start(face_engine_factory=FakeEngine, place_engine_factory=lambda: FakeOcr({}))
        script = os.path.join(self.tmp.name, "errors.js")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_PAGE_SCRIPT)
        done = subprocess.run(
            ["node", script, f"http://127.0.0.1:{self.port}/", self.trip],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=_REPO,
            env={**os.environ, "TRAVELPHOTOS_PLAYWRIGHT": _playwright_entry()},
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        shown = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(shown["500"], "伺服器說 500")
        self.assertEqual(shown["400"], "伺服器說 400")
        self.assertIn("工具回應無法讀取（502）", shown["notjson"])
        self.assertIn("工具沒有回應", shown["abort"])


if __name__ == "__main__":
    unittest.main()
