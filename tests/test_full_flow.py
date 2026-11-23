"""#3: the three parts (#5 order, #6 people, #7 places) work together and alone.

The trip folder looks like files saved from LINE: no EXIF time, no GPS,
modification times in the wrong order; the order comes from the file names.
Faces and sign text are read by the fake engines from the #6 and #7 tests, so
the expected results do not depend on model accuracy; RealModelsOfflineTests
loads the real models. Everything goes through the same HTTP API the page uses.
"""

from __future__ import annotations

import contextlib
import csv
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

from tests.face_helpers import ME, MOM, STRANGER, FakeEngine, picture, save_photo, save_video
from tests.helpers import snapshot
from tests.optional import needs
from tests.test_places import MARKERS, FakeOcr
from travelphotos import server as srv
from travelphotos.places import cloud

ITINERARY = "清水寺\n伏見稻荷大社\n金閣寺\n"
TEXTS = {0: ["清水寺"], 1: ["伏见稻荷大社 入口"], 2: ["金阁寺"]}

# (file name, people, sign marker) in the real shooting order.
PHOTOS = [
    ("IMG_20240401_090000.jpg", (ME,), 0),  # Kiyomizu, me, sign
    ("IMG_20240401_090500.jpg", (STRANGER,), None),  # Kiyomizu, a stranger
    ("IMG_20240401_130000.jpg", (), 1),  # Fushimi Inari, sign, nobody
    ("IMG_20240401_130200.jpg", (MOM,), None),  # Fushimi Inari, mom
    ("IMG_20240402_100000.jpg", (ME, MOM), 2),  # Kinkaku-ji, both, sign
]
VIDEOS = [
    ("VID_20240401_130400.mp4", {MOM: (0, 6)}),  # Fushimi Inari, mom
    ("VID_20240402_100300.mp4", {STRANGER: (0, 6)}),  # Kinkaku-ji, a stranger
]
ALL_IN_ORDER = [
    "IMG_20240401_090000.jpg",
    "IMG_20240401_090500.jpg",
    "IMG_20240401_130000.jpg",
    "IMG_20240401_130200.jpg",
    "VID_20240401_130400.mp4",
    "IMG_20240402_100000.jpg",
    "VID_20240402_100300.mp4",
]
FAMILY_IN_ORDER = [
    "IMG_20240401_090000.jpg",
    "IMG_20240401_130200.jpg",
    "VID_20240401_130400.mp4",
    "IMG_20240402_100000.jpg",
]

# places.md rows for the full flow: (place, photos, videos, representative).
FAMILY_PLACES = [
    ("清水寺", 1, 0, "0001_IMG_20240401_090000.jpg"),
    ("伏見稻荷大社", 1, 1, "0002_IMG_20240401_130200.jpg"),
    ("金閣寺", 1, 0, "0004_IMG_20240402_100000.jpg"),
]


def build_trip(folder: str) -> None:
    for name, people, marker in PHOTOS:
        img = picture(*people)
        if marker is not None:
            img.paste(MARKERS[marker], (0, 0, 16, 16))
        os.makedirs(folder, exist_ok=True)
        img.save(os.path.join(folder, name), "JPEG", quality=95)  # no EXIF, no GPS
    for name, appearances in VIDEOS:
        save_video(os.path.join(folder, name), appearances)
    # Saving from LINE rewrites modification times: make them run backwards.
    for i, name in enumerate(ALL_IN_ORDER):
        stamp = 1_800_000_000 - i * 3600
        os.utime(os.path.join(folder, name), (stamp, stamp))


class ExternalNetworkUsed(AssertionError):
    pass


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@contextlib.contextmanager
def no_external_network():
    """Fail any connection or name lookup that is not to this computer."""
    attempts: list = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def host_of(address):
        return address[0] if isinstance(address, tuple) else str(address)

    def check(host):
        if str(host) not in _LOOPBACK:
            attempts.append(host)
            raise ExternalNetworkUsed(f"network access to {host}")

    def connect(self, address):
        check(host_of(address))
        return real_connect(self, address)

    def connect_ex(self, address):
        check(host_of(address))
        return real_connect_ex(self, address)

    def create_connection(address, *a, **k):
        check(host_of(address))
        return real_create(address, *a, **k)

    def getaddrinfo(host, *a, **k):
        check(host)
        return real_getaddrinfo(host, *a, **k)

    with mock.patch.object(socket.socket, "connect", connect), mock.patch.object(
        socket.socket, "connect_ex", connect_ex
    ), mock.patch.object(socket, "create_connection", create_connection), mock.patch.object(socket, "getaddrinfo", getaddrinfo):
        yield attempts


class FlowBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trip = os.path.join(self.tmp.name, "trip")
        build_trip(self.trip)
        self.refs_me = os.path.join(self.tmp.name, "refs-me")
        self.refs_mom = os.path.join(self.tmp.name, "refs-mom")
        save_photo(os.path.join(self.refs_me, "me.jpg"), ME)
        save_photo(os.path.join(self.refs_mom, "mom.jpg"), MOM)
        self.before = snapshot(self.trip)

    def start(self):
        server, _url, _state = srv.create_server(
            0,
            self.trip,
            data_dir=os.path.join(self.tmp.name, "data"),
            face_engine_factory=FakeEngine,
            place_engine_factory=lambda: FakeOcr(TEXTS),
        )
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.port = server.server_address[1]
        self.server = server
        status, body = self.raw("GET", "/")
        self.token = re.search(r'name="token" content="([^"]+)"', body.decode()).group(1)

    def raw(self, method, path, body=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "X-Token": getattr(self, "token", "")}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        out = (res.status, res.read())
        conn.close()
        return out

    def api(self, path, body):
        status, data = self.raw("POST", path, body)
        data = json.loads(data)
        self.assertEqual(status, 200, data)
        return data

    # --- steps, in the order of the page ------------------------------
    def scan(self, itinerary=""):
        return self.api("/api/scan", {"input_dir": self.trip, "itinerary": itinerary})

    def places(self):
        return self.api("/api/places/analyze", {})

    def keep_me_and_mom(self):
        self.api("/api/faces/analyze", {"interval": 2})
        me = self.api("/api/faces/reference", {"name": "本人", "folder": self.refs_me})
        mom = self.api("/api/faces/reference", {"name": "媽媽", "folder": self.refs_mom})
        ids = [p["id"] for p in mom["faces"]["people"]]
        self.assertEqual(len(ids), 2, me["faces"]["people"])
        return self.api("/api/faces/select", {"person_ids": ids, "enabled": True})

    def output(self, name):
        out = os.path.join(self.tmp.name, name)
        data = self.api("/api/apply", {"output_dir": out})
        return out, data

    # --- checks --------------------------------------------------------
    def media_in(self, out):
        return sorted(n for n in os.listdir(out) if n[:4].isdigit())

    def expect_files(self, out, names):
        width = 4
        expected = [f"{i:0{width}d}_{n}" for i, n in enumerate(names, start=1)]
        self.assertEqual(self.media_in(out), expected)

    def expect_originals_untouched(self):
        self.assertEqual(snapshot(self.trip), self.before)

    def report_rows(self, out):
        with open(os.path.join(out, "report.csv"), encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    def places_md(self, out):
        with open(os.path.join(out, "places.md"), encoding="utf-8") as fh:
            return fh.read()

    def expect_places(self, md, rows):
        """rows: (name, photos, videos, representative output name) in trip order."""
        table = [line for line in md.splitlines() if line.startswith("| ") and not line.startswith("| 順序") and "---" not in line]
        got = [(c[2], c[4], c[5], c[7]) for c in (re.split(r"\s*\|\s*", line) for line in table)]
        self.assertEqual(got, [(n, str(p), str(v), rep) for n, p, v, rep in rows])


class FullFlowTests(FlowBase):
    def run_full_flow(self):
        self.start()
        data = self.scan(ITINERARY)
        self.assertEqual([f["id"] for f in data["files"]], ALL_IN_ORDER, "order from file names, not modification times")
        self.places()
        self.keep_me_and_mom()
        out, data = self.output("out")
        self.assertEqual(data["applied"]["face_excluded"], 3)
        self.expect_files(out, FAMILY_IN_ORDER)
        self.expect_places(self.places_md(out), FAMILY_PLACES)
        self.expect_originals_untouched()

    def test_full_flow_keeps_family_in_order_with_a_place_summary(self):
        self.run_full_flow()

    def test_full_flow_offline(self):
        with no_external_network() as attempts:
            self.run_full_flow()
        self.assertEqual(attempts, [])

    def test_full_flow_offline_with_cloud_setting_on(self):
        with mock.patch.dict(os.environ, {cloud.ENV_FLAG: "1"}), no_external_network() as attempts:
            self.run_full_flow()
            data = json.loads(self.raw("GET", "/api/state")[1])
        self.assertEqual(attempts, [])
        self.assertEqual(data["places"]["summary"]["warnings"], [cloud.NOT_IMPLEMENTED])


class StandaloneTests(FlowBase):
    def only_order(self):
        self.start()
        self.scan()
        out, _ = self.output("only-order")
        self.expect_files(out, ALL_IN_ORDER)
        self.assertFalse(os.path.exists(os.path.join(out, "places.md")))
        self.assertTrue(all(r["人物篩選"] == "" for r in self.report_rows(out)))
        self.expect_originals_untouched()

    def only_people(self):
        self.start()
        self.scan()
        self.keep_me_and_mom()
        out, _ = self.output("only-people")
        self.expect_files(out, FAMILY_IN_ORDER)
        self.assertFalse(os.path.exists(os.path.join(out, "places.md")))
        self.expect_originals_untouched()

    def only_places(self):
        self.start()
        self.scan(ITINERARY)
        self.places()
        out, _ = self.output("only-places")
        self.expect_files(out, ALL_IN_ORDER)
        self.expect_places(
            self.places_md(out),
            [
                ("清水寺", 2, 0, "0001_IMG_20240401_090000.jpg"),
                ("伏見稻荷大社", 2, 1, "0003_IMG_20240401_130000.jpg"),
                ("金閣寺", 1, 1, "0006_IMG_20240402_100000.jpg"),
            ],
        )
        self.expect_originals_untouched()

    def test_only_order(self):
        self.only_order()

    def test_only_people(self):
        self.only_people()

    def test_only_places(self):
        self.only_places()

    def test_each_alone_offline_with_and_without_cloud_setting(self):
        for setting in ({}, {cloud.ENV_FLAG: "1"}):
            for flow in (self.only_order, self.only_people, self.only_places):
                with self.subTest(flow=flow.__name__, setting=setting):
                    self.tearDown_server()
                    with mock.patch.dict(os.environ, setting), no_external_network() as attempts:
                        flow()
                    self.assertEqual(attempts, [])

    def tearDown_server(self):
        if getattr(self, "server", None) is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        for name in ("only-order", "only-people", "only-places", "data"):
            shutil.rmtree(os.path.join(self.tmp.name, name), ignore_errors=True)


class LocalOnlyTests(FlowBase):
    def test_server_is_local_only(self):
        self.start()
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, _ = self.raw("GET", "/api/state", host="photos.example.com")
        self.assertEqual(status, 403)
        status, _ = self.raw("GET", "/api/state", host=f"192.168.1.20:{self.port}")
        self.assertEqual(status, 403)
        status, _ = self.raw("GET", "/api/state")
        self.assertEqual(status, 200)

    def test_offline_helper_blocks_outside_but_allows_this_computer(self):
        with no_external_network() as attempts, self.assertRaises(ExternalNetworkUsed):
            socket.create_connection(("example.com", 80), timeout=1)
        self.assertEqual(attempts, ["example.com"])


def _models_ready():
    from travelphotos.faces import paths as face_paths
    from travelphotos.places import models as place_models

    d = face_paths.model_dir()
    return not face_paths.missing_models(d) and not place_models.missing_models(d)


@needs(_models_ready(), "models not downloaded (python launcher/download_models.py)")
class RealModelsOfflineTests(unittest.TestCase):
    def test_real_models_load_and_run_without_network(self):
        import numpy as np

        from travelphotos.faces.engine import load_engine as load_faces
        from travelphotos.places.ocr import load_engine as load_ocr

        blank = np.full((120, 160, 3), 200, np.uint8)
        with no_external_network() as attempts:
            load_faces().detect(blank)
            load_ocr().read_text(blank)
        self.assertEqual(attempts, [])


_BROWSER_SCRIPT = textwrap.dedent(
    r"""
    const { chromium } = require(process.env.TRAVELPHOTOS_PLAYWRIGHT);
    const [url, trip, itinerary, refMe, refMom, out, mode] = process.argv.slice(2);
    (async () => {
      const browser = await chromium.launch();
      const page = await browser.newPage();
      page.on("dialog", (d) => d.accept());
      await page.goto(url);
      await page.fill("#input-dir", trip);
      if (mode === "full") await page.fill("#itinerary", itinerary);
      await page.click("#scan");
      await page.waitForSelector("#step-review:not([hidden])");
      if (mode === "full") {
        await page.click("#places-analyze");
        await page.waitForFunction(() => document.querySelector("#places-status").textContent.startsWith("完成"));
      }
      if (mode === "full" || mode === "people") {
        await page.click("#face-analyze");
        await page.waitForFunction(() => document.querySelector("#faces-status").textContent.startsWith("完成"));
        for (const [name, dir] of [["本人", refMe], ["媽媽", refMom]]) {
          await page.evaluate(() => (document.querySelector("#ref-box").open = true));
          await page.fill("#ref-name", name);
          await page.fill("#ref-dir", dir);
          const before = await page.locator("#people input[type=checkbox]").count();
          await page.click("#ref-add");
          await page.waitForFunction((n) => document.querySelectorAll("#people input[type=checkbox]").length > n, before);
        }
        const boxes = page.locator("#people input[type=checkbox]");
        for (let i = 0; i < (await boxes.count()); i++) {
          if (!(await boxes.nth(i).isChecked())) {
            await boxes.nth(i).check();
            await page.waitForFunction((k) => document.querySelectorAll("#people input[type=checkbox]")[k].checked, i);
          }
        }
        await page.check("#face-enabled");
        await page.waitForFunction(() => document.querySelector("#face-enabled").checked && !document.querySelector("#face-enabled").disabled);
      }
      await page.fill("#output-dir", out);
      await page.click("#apply");
      await page.waitForFunction(() => /完成|已/.test(document.querySelector("#apply-status").textContent) || document.querySelector("#apply-status").classList.contains("error"));
      const status = await page.textContent("#apply-status");
      const isError = await page.evaluate(() => document.querySelector("#apply-status").classList.contains("error"));
      console.log(JSON.stringify({ status, isError }));
      await browser.close();
    })().catch((e) => { console.error(e); process.exit(1); });
    """
)


_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _playwright_entry() -> str | None:
    """Absolute path of Playwright's entry point as node resolves it from the
    repository, so the generated script (in a temp folder) loads the same one."""
    if shutil.which("node") is None:
        return None
    try:
        done = subprocess.run(
            ["node", "-e", "process.stdout.write(require.resolve('playwright'))"], capture_output=True, text=True, timeout=30, cwd=_REPO
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = done.stdout.strip()
    return path if done.returncode == 0 and os.path.isabs(path) and os.path.exists(path) else None


def _browser_available() -> bool:
    return _playwright_entry() is not None


@needs(_browser_available(), "no browser automation (node + playwright) on this computer; check by hand")
class BrowserFlowTests(FlowBase):
    """Clicks through the real page in a headless browser."""

    def click_through(self, mode, out_name):
        self.start()
        script = os.path.join(self.tmp.name, "flow.js")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_BROWSER_SCRIPT)
        out = os.path.join(self.tmp.name, out_name)
        url = f"http://127.0.0.1:{self.port}/"
        done = subprocess.run(
            ["node", script, url, self.trip, ITINERARY, self.refs_me, self.refs_mom, out, mode],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=_REPO,
            env={**os.environ, "TRAVELPHOTOS_PLAYWRIGHT": _playwright_entry()},
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        result = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertFalse(result["isError"], result["status"])
        return out

    def test_full_flow_in_the_page(self):
        out = self.click_through("full", "browser-full")
        self.expect_files(out, FAMILY_IN_ORDER)
        self.expect_places(self.places_md(out), FAMILY_PLACES)
        rows = {r["原始檔案"]: r for r in self.report_rows(out)}
        self.assertTrue(rows["IMG_20240402_100000.jpg"]["景點判斷"].startswith("金閣寺"))
        self.expect_originals_untouched()

    def test_only_people_in_the_page(self):
        out = self.click_through("people", "browser-people")
        self.expect_files(out, FAMILY_IN_ORDER)
        self.assertFalse(os.path.exists(os.path.join(out, "places.md")))
        self.expect_originals_untouched()


if __name__ == "__main__":
    unittest.main()
