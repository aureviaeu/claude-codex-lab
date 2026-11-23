"""Face step through the local web API, the model download, and the real engine."""

import hashlib
import http.client
import io
import json
import os
import re
import tempfile
import threading
import unittest
from unittest import mock

from PIL import Image

from launcher import bootstrap, download_models
from travelphotos.places import models as place_models
from tests.face_helpers import ME, MOM, STRANGER, FakeEngine, no_network, save_photo
from tests.optional import needs, skip_or_fail
from travelphotos import server as srv
from travelphotos.faces import engine as face_engine
from travelphotos.faces import paths


class FaceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.inp = os.path.join(cls.tmp.name, "trip")
        cls.data = os.path.join(cls.tmp.name, "data")
        save_photo(os.path.join(cls.inp, "me.jpg"), ME)
        save_photo(os.path.join(cls.inp, "mom.jpg"), MOM, STRANGER)
        cls.refs = os.path.join(cls.tmp.name, "refs")
        save_photo(os.path.join(cls.refs, "me.jpg"), ME)
        cls.server, cls.url, cls.state = srv.create_server(0, cls.inp, data_dir=cls.data, face_engine_factory=FakeEngine)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        page = cls.raw("GET", "/")[2].decode()
        cls.token = re.search(r'name="token" content="([^"]+)"', page).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    @classmethod
    def raw(cls, method, path, body=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{cls.port}"}
        if token:
            headers["X-Token"] = token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        out = (res.status, dict(res.getheaders()), res.read())
        conn.close()
        return out

    def api(self, path, body=None):
        status, _h, data = self.raw("POST" if body is not None else "GET", path, body, token=self.token)
        return status, json.loads(data)

    def test_face_flow_over_http(self):
        status, data = self.api("/api/scan", {"input_dir": self.inp})
        self.assertEqual(status, 200)
        self.assertTrue(data["faces"]["available"])
        status, data = self.api("/api/faces/reference", {"name": "本人", "folder": self.refs})
        self.assertEqual(status, 200, data)
        pid = data["faces"]["people"][0]["id"]
        status, data = self.api("/api/faces/analyze", {"interval": 2})
        self.assertEqual(status, 200, data)
        self.assertEqual(sum(c["faces"] for c in data["faces"]["clusters"]), 3)
        status, data = self.api("/api/faces/select", {"person_ids": [pid], "enabled": True})
        self.assertEqual(data["faces"]["counts"], {"kept": 1, "uncertain": 0, "excluded": 1})
        files = {f["id"]: f["face"] for f in data["files"]}
        self.assertEqual(files["me.jpg"]["label"], "保留")
        self.assertFalse(files["mom.jpg"]["keep"])

        sample = data["faces"]["clusters"][0]["samples"][0]
        status, headers, body = self.raw("GET", f"/api/faces/crop?face={sample}&token={self.token}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(Image.open(io.BytesIO(body)).format, "JPEG")
        self.assertEqual(self.raw("GET", f"/api/faces/crop?face=999&token={self.token}")[0], 404)
        self.assertEqual(self.raw("GET", f"/api/faces/crop?face={sample}")[0], 403, "token required")

        out = os.path.join(self.tmp.name, "out")
        status, data = self.api("/api/apply", {"output_dir": out})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["applied"]["written"], 1)
        self.assertEqual(data["applied"]["face_excluded"], 1)

        status, data = self.api("/api/faces/delete-all", {})
        self.assertTrue(data["deleted"])
        self.assertEqual(data["faces"]["people"], [])
        self.assertFalse(os.path.exists(os.path.join(self.data, "faces.json")))

    def test_errors_are_400_with_chinese_message(self):
        status, data = self.api("/api/faces/save-cluster", {"cluster_id": "x"})
        self.assertEqual(status, 400)
        status, data = self.api("/api/faces/nope", {})
        self.assertEqual(status, 400)
        status, data = self.api("/api/faces/reference", {"name": "x", "folder": os.path.join(self.tmp.name, "missing")})
        self.assertEqual(status, 400)
        self.assertIn("找不到", data["error"])


class AvailabilityTests(unittest.TestCase):
    def test_missing_models_explain_how_to_get_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = srv.AppState("", data_dir=tmp)
            data = state.faces.to_json()
            if data["message"] == face_engine.LIBS_MISSING:
                skip_or_fail(self, "opencv not installed")
            self.assertFalse(data["available"])
            self.assertIn("download_models.py", data["message"])
            with self.assertRaises(face_engine.FaceUnavailable):
                state.faces.engine()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.payload = b"model bytes"
        self.model = paths.ModelFile("m.onnx", hashlib.sha256(self.payload).hexdigest(), "https://example.invalid/m.onnx", len(self.payload))

    def test_downloads_and_verifies(self):
        urls = []

        def opener(url, timeout):
            urls.append(url)
            return FakeResponse(self.payload)

        with mock.patch.object(paths, "MODELS", (self.model,)), mock.patch.object(place_models, "MODELS", ()):
            self.assertTrue(download_models.ensure_models(self.tmp.name, log=lambda *_: None, opener=opener))
            self.assertTrue(download_models.ensure_models(self.tmp.name, log=lambda *_: None, opener=opener))
            self.assertEqual(paths.missing_models(self.tmp.name), [])
        self.assertEqual(urls, ["https://example.invalid/m.onnx"], "second run uses the local file")

    def test_wrong_checksum_is_discarded(self):
        with mock.patch.object(paths, "MODELS", (self.model,)), mock.patch.object(place_models, "MODELS", ()):
            ok = download_models.ensure_models(self.tmp.name, log=lambda *_: None, opener=lambda u, timeout: FakeResponse(b"evil"))
        self.assertFalse(ok)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_real_models_are_pinned(self):
        self.assertEqual(len(download_models.all_models()), 5)
        wheel = place_models.WHEEL
        self.assertRegex(wheel.url, r"^https://files\.pythonhosted\.org/packages/.+/rapidocr_onnxruntime-1\.2\.3-py3-none-any\.whl$")
        self.assertRegex(wheel.sha256, r"^[0-9a-f]{64}$")
        for m in place_models.MODELS:
            self.assertRegex(m.sha256, r"^[0-9a-f]{64}$")
            self.assertTrue(m.member.startswith("rapidocr_onnxruntime/models/") and m.member.endswith(m.name))
        for m in paths.MODELS:
            self.assertRegex(m.url, r"^https://media\.githubusercontent\.com/media/opencv/opencv_zoo/[0-9a-f]{40}/")
            self.assertRegex(m.sha256, r"^[0-9a-f]{64}$")

    def test_launcher_fetches_models_but_still_starts_when_that_fails(self):
        calls = []

        def call(cmd, cwd=None):
            calls.append(cmd)
            return 1 if "download_models.py" in cmd[-1] else 0

        with mock.patch.object(bootstrap, "ensure_env", return_value="py"), mock.patch.object(bootstrap.subprocess, "call", side_effect=call):
            self.assertEqual(bootstrap.main([]), 0)
        self.assertTrue(calls[0][-1].endswith(os.path.join("launcher", "download_models.py")))
        self.assertEqual(calls[1][:3], ["py", "-m", "travelphotos"])


def _real_model_dir():
    for d in (os.environ.get("TRAVELPHOTOS_TEST_MODELS"), paths.model_dir()):
        if d and not paths.missing_models(d):
            return d
    return None


@needs(_real_model_dir(), "face models not downloaded (python launcher/download_models.py)")
class RealEngineTests(unittest.TestCase):
    """Runs where the real models are present (CI downloads them first)."""

    def test_real_engine_runs_offline(self):
        with no_network():
            eng = face_engine.OpenCVEngine(_real_model_dir())
            import numpy as np

            self.assertEqual(eng.detect(np.full((240, 320, 3), 128, np.uint8)), [])


if __name__ == "__main__":
    unittest.main()
