import http.client
import json
import os
import re
import tempfile
import threading
import unittest
from datetime import datetime

from travelphotos import server as srv
from tests.helpers import save_jpeg, scene, snapshot

PKG_DIR = os.path.dirname(srv.__file__)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.inp = os.path.join(cls.tmp.name, "trip")
        save_jpeg(scene(1), os.path.join(cls.inp, "late.jpg"), datetime(2024, 5, 1, 18, 0))
        save_jpeg(scene(2), os.path.join(cls.inp, "early.jpg"), datetime(2024, 5, 1, 8, 0))
        save_jpeg(scene(3), os.path.join(cls.inp, "nodate.jpg"))
        cls.before = snapshot(cls.inp)
        cls.server, cls.url, cls.state = srv.create_server(0, cls.inp)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        page = cls.request("GET", "/")[2].decode("utf-8")
        cls.token = re.search(r'name="token" content="([^"]+)"', page).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, method, path, body=None, token=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{cls.port}"}
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

    def api(self, method, path, body=None):
        status, _h, data = self.request(method, path, body, token=self.token)
        return status, json.loads(data)

    def test_binds_to_localhost_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))

    def test_api_requires_token(self):
        status, _h, _d = self.request("GET", "/api/state")
        self.assertEqual(status, 403)
        status, _h, _d = self.request("GET", "/api/state", token="wrong")
        self.assertEqual(status, 403)

    def test_rejects_foreign_host_header(self):
        status, _h, _d = self.request("GET", "/", host=f"evil.example:{self.port}")
        self.assertEqual(status, 403)
        status, _h, _d = self.request("GET", "/api/state", token=self.token, host="evil.example")
        self.assertEqual(status, 403)

    def test_static_assets(self):
        for path in ("/app.js", "/style.css"):
            status, _h, _d = self.request("GET", path)
            self.assertEqual(status, 200)

    def test_full_flow(self):
        status, data = self.api("POST", "/api/scan", {"input_dir": self.inp, "itinerary": "A → B", "line_chat": ""})
        self.assertEqual(status, 200, data)
        self.assertEqual([f["id"] for f in data["files"]], ["early.jpg", "late.jpg", "nodate.jpg"])
        self.assertEqual(len(data["stops"]), 2)

        status, thumb_h, thumb = self.request("GET", "/api/thumb?id=early.jpg&token=" + self.token)
        self.assertEqual(status, 200)
        self.assertEqual(thumb_h["Content-Type"], "image/jpeg")
        self.assertTrue(thumb.startswith(b"\xff\xd8"))
        status, _h, _d = self.request("GET", "/api/thumb?id=../../etc/passwd&token=" + self.token)
        self.assertEqual(status, 404)

        status, data = self.api("POST", "/api/arrange", {"assignments": {"late.jpg": 1}, "manual_order": None})
        self.assertEqual([f["id"] for f in data["files"]][0], "late.jpg")

        status, data = self.api(
            "POST", "/api/arrange", {"assignments": {"late.jpg": 1}, "manual_order": ["nodate.jpg"]}
        )
        self.assertEqual([f["id"] for f in data["files"]], ["nodate.jpg", "late.jpg", "early.jpg"])
        self.assertTrue(data["files"][0]["manual"])

        out = os.path.join(self.tmp.name, "out")
        status, data = self.api("POST", "/api/apply", {"output_dir": out})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["applied"]["written"], 3)
        self.assertTrue(os.path.isfile(os.path.join(out, "0001_nodate.jpg")))
        self.assertEqual(snapshot(self.inp), self.before)

        status, data = self.api("POST", "/api/apply", {"output_dir": self.inp})
        self.assertEqual(status, 400)
        self.assertIn("輸出資料夾", data["error"])

    def test_bad_input_dir(self):
        status, data = self.api("POST", "/api/scan", {"input_dir": os.path.join(self.tmp.name, "missing")})
        self.assertEqual(status, 400)
        self.assertIn("找不到", data["error"])


class NoNetworkCodeTests(unittest.TestCase):
    """The app must never call out to the network."""

    FORBIDDEN = re.compile(
        r"^\s*(?:import|from)\s+(?:urllib\.request|http\.client|requests|httpx|aiohttp|ftplib|smtplib)\b"
        r"|create_connection|urlopen",
        re.MULTILINE,
    )

    def test_no_network_clients(self):
        for name in os.listdir(PKG_DIR):
            if name.endswith(".py"):
                with open(os.path.join(PKG_DIR, name), encoding="utf-8") as fh:
                    self.assertIsNone(self.FORBIDDEN.search(fh.read()), name)

    def test_frontend_loads_nothing_remote(self):
        static = os.path.join(PKG_DIR, "static")
        for name in os.listdir(static):
            with open(os.path.join(static, name), encoding="utf-8") as fh:
                self.assertNotRegex(fh.read(), r"https?://", name)


if __name__ == "__main__":
    unittest.main()
