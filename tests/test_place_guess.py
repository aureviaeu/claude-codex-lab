"""#32: a photo with no readable place name is 不確定, then guessed (推測)
from the photos before and after it when both are at the same stop."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock

from tests.helpers import save_jpeg, scene, snapshot
from tests.optional import needs
from tests.test_full_flow import _browser_available, _playwright_entry
from tests import test_places as tp
from tests.test_places import FakeOcr, marked
from travelphotos import ordering, output
from travelphotos.itinerary import parse_itinerary
from travelphotos.ordering import HIGH, LOW
from travelphotos.places import benchmark, pipeline, summary
from travelphotos.scan import scan

ITINERARY = """第1天：清水寺 → 伏見稻荷大社 → 京都飯店
第2天：金閣寺 → 嵐山 → 京都飯店
"""
# Marker -> lines the fake OCR reads.
TEXTS = {
    0: ["清水寺", "入口"],
    1: ["伏见稻荷大社"],
    2: ["京都饭店 KYOTO HOTEL"],
    3: ["金阁寺"],
    4: ["LAWSON", "便利商店"],  # text that is not a place name
    5: ["← 伏見稲荷大社", "清水寺 →"],  # several place names: no single stop
}
D1, D2 = datetime(2024, 4, 1), datetime(2024, 4, 2)


class TripFixture(unittest.TestCase):
    """Each photo is a different scene more than 10 minutes apart: one group each."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inp = os.path.join(self.tmp.name, "in")
        self.texts = dict(TEXTS)
        self.stops = parse_itinerary(ITINERARY)

    def trip(self, photos):
        """photos: (file name, time or None, marker or None)."""
        for seed, (name, taken, marker) in enumerate(photos, start=40):
            save_jpeg(marked(scene(seed), marker), os.path.join(self.inp, name), taken)
        self.scan = scan(self.inp)
        return pipeline.analyze(self.scan.files, self.stops, FakeOcr(self.texts), environ={})

    def at(self, r, fid):
        return r.by_file()[fid]


class GuessTests(TripFixture):
    def test_the_three_cases_between_photos_of_one_stop_are_guessed(self):
        r = self.trip(
            [
                ("a1.jpg", D1.replace(hour=9), 0),
                ("a2.jpg", D1.replace(hour=9, minute=20), None),  # building only, no text
                ("a3.jpg", D1.replace(hour=9, minute=40), 4),  # convenience store sign
                ("a4.jpg", D1.replace(hour=10), 5),  # sign with two place names
                ("a5.jpg", D1.replace(hour=10, minute=20), 0),
            ]
        )
        for fid in ("a2.jpg", "a3.jpg", "a4.jpg"):
            with self.subTest(fid=fid):
                g = self.at(r, fid)
                self.assertEqual((g.stop.name, g.method, g.confidence), ("清水寺", "inferred", LOW))
                self.assertIn("推測為同一站", g.evidence)
                self.assertIn("a1.jpg", g.evidence)
                self.assertIn("a5.jpg", g.evidence)
        self.assertIn("沒有讀到文字", self.at(r, "a2.jpg").evidence)
        self.assertIn("沒有對應", self.at(r, "a3.jpg").evidence)
        self.assertIn("同時像", self.at(r, "a4.jpg").evidence)
        # Photos read directly are unchanged.
        for fid in ("a1.jpg", "a5.jpg"):
            self.assertEqual((self.at(r, fid).method, self.at(r, fid).confidence), ("text", HIGH))
        self.assertEqual(r.assignments(), {"a1.jpg": 1, "a2.jpg": 1, "a3.jpg": 1, "a4.jpg": 1, "a5.jpg": 1})

    def test_between_two_different_stops_stays_uncertain(self):
        r = self.trip(
            [
                ("a1.jpg", D1.replace(hour=9), 0),
                ("x1.jpg", D1.replace(hour=11), None),
                ("x2.jpg", D1.replace(hour=12), 5),
                ("b1.jpg", D1.replace(hour=13), 1),
            ]
        )
        for fid in ("x1.jpg", "x2.jpg"):
            g = self.at(r, fid)
            self.assertIsNone(g.stop, fid)
            self.assertIsNone(g.confidence)
            self.assertIn("分屬不同行程站", g.evidence)
            self.assertIn("清水寺", g.evidence)
            self.assertIn("伏見稻荷大社", g.evidence)
        self.assertNotIn("x1.jpg", r.assignments())

    def test_hotel_on_two_nights_is_two_stops_so_nothing_between_is_guessed(self):
        r = self.trip(
            [
                ("h1.jpg", D1.replace(hour=21), 2),
                ("n1.jpg", D2.replace(hour=8), None),
                ("h2.jpg", D2.replace(hour=21), 2),
            ]
        )
        self.assertEqual((self.at(r, "h1.jpg").stop.index, self.at(r, "h2.jpg").stop.index), (3, 6))
        self.assertIsNone(self.at(r, "n1.jpg").stop)
        self.assertIn("第 3 站", self.at(r, "n1.jpg").evidence)
        self.assertIn("第 6 站", self.at(r, "n1.jpg").evidence)
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        s = summary.build(res.placements, self.stops, r)
        self.assertEqual([v["stop"] for v in s["visits"] if v["name"] == "京都飯店"], [3, 6], "still listed twice")

    def test_same_hotel_visit_on_one_night_is_guessed(self):
        r = self.trip(
            [
                ("h1.jpg", D1.replace(hour=20), 2),
                ("n1.jpg", D1.replace(hour=21), None),
                ("h2.jpg", D1.replace(hour=22), 2),
            ]
        )
        self.assertEqual(self.at(r, "n1.jpg").stop.index, 3)
        self.assertEqual(self.at(r, "n1.jpg").method, "inferred")

    def test_a_stop_seen_on_two_days_does_not_fill_the_days_between(self):
        """Review note: no guess across dates, even at the same stop."""
        r = self.trip(
            [
                ("a1.jpg", D1.replace(hour=17), 3),
                ("n1.jpg", D1.replace(hour=19), None),
                ("n2.jpg", D2.replace(hour=9), None),
                ("a2.jpg", D2.replace(hour=11), 3),
            ]
        )
        for fid in ("n1.jpg", "n2.jpg"):
            self.assertIsNone(self.at(r, fid).stop, fid)
            self.assertIn("拍攝日期不同", self.at(r, fid).evidence)

    def test_first_and_last_photo_have_only_one_neighbour(self):
        r = self.trip(
            [
                ("p0.jpg", D1.replace(hour=8), None),
                ("a1.jpg", D1.replace(hour=9), 0),
                ("a2.jpg", D1.replace(hour=10), 0),
                ("p9.jpg", D1.replace(hour=11), None),
            ]
        )
        self.assertIsNone(self.at(r, "p0.jpg").stop)
        self.assertIn("前面沒有已判斷景點的照片", self.at(r, "p0.jpg").evidence)
        self.assertIsNone(self.at(r, "p9.jpg").stop)
        self.assertIn("後面沒有已判斷景點的照片", self.at(r, "p9.jpg").evidence)

    def test_a_guess_never_feeds_another_guess(self):
        # Only one identified neighbour on each side of the run of uncertain photos.
        r = self.trip(
            [
                ("a1.jpg", D1.replace(hour=9), 0),
                ("u1.jpg", D1.replace(hour=10), None),
                ("u2.jpg", D1.replace(hour=11), None),
                ("u3.jpg", D1.replace(hour=12), None),
            ]
        )
        self.assertTrue(all(self.at(r, f).stop is None for f in ("u1.jpg", "u2.jpg", "u3.jpg")))

    def test_without_capture_time_the_file_name_order_is_used(self):
        r = self.trip(
            [
                ("IMG_0001.jpg", None, 3),
                ("IMG_0002.jpg", None, None),
                ("IMG_0003.jpg", None, 3),
                ("IMG_0004.jpg", None, None),
                ("IMG_0005.jpg", None, 1),
            ]
        )
        self.assertEqual(self.at(r, "IMG_0002.jpg").stop.name, "金閣寺")
        self.assertEqual(self.at(r, "IMG_0002.jpg").method, "inferred")
        self.assertIsNone(self.at(r, "IMG_0004.jpg").stop, "金閣寺 before, 伏見稻荷大社 after")

    def test_a_timed_group_uses_time_order_not_file_names(self):
        # File names disagree with capture times (the unknown photo sorts
        # first by name): time wins.
        r = self.trip(
            [
                ("b_kinkaku.jpg", D2.replace(hour=10), 3),
                ("a_unknown.jpg", D2.replace(hour=11), None),
                ("c_kinkaku.jpg", D2.replace(hour=12), 3),
            ]
        )
        self.assertEqual(self.at(r, "a_unknown.jpg").stop.name, "金閣寺")

    def test_no_itinerary_guesses_nothing(self):
        self.stops = []
        r = self.trip([("a1.jpg", D1.replace(hour=9), 0), ("a2.jpg", D1.replace(hour=10), None), ("a3.jpg", D1.replace(hour=11), 0)])
        self.assertTrue(all(g.stop is None for g in r.groups))


class LabelTests(TripFixture):
    def setUp(self):
        super().setUp()
        self.r = self.trip(
            [
                ("a1.jpg", D1.replace(hour=9), 0),
                ("a2.jpg", D1.replace(hour=10), None),
                ("a3.jpg", D1.replace(hour=11), 0),
                ("x1.jpg", D1.replace(hour=12), None),
                ("b1.jpg", D1.replace(hour=13), 1),
            ]
        )
        self.res = ordering.order(self.scan.files, self.stops, self.r.assignments())

    def test_labels_and_report_column(self):
        a2 = self.r.by_file()["a2.jpg"].stop
        self.assertEqual(summary.group_label(a2, self.r, "a2.jpg")[0], summary.INFERRED)
        self.assertEqual(summary.headline(a2, summary.INFERRED), "推測：清水寺")
        self.assertTrue(summary.place_note(a2, self.r, "a2.jpg").startswith("推測：清水寺："))
        self.assertTrue(summary.place_note(None, self.r, "x1.jpg").startswith("不確定："))
        self.assertTrue(summary.place_note(a2, self.r, "a1.jpg").startswith("清水寺（可信度：高）"), "read photos keep their label")

    def test_owner_clearing_a_guess_is_shown_as_manual(self):
        self.assertEqual(summary.group_label(None, self.r, "a2.jpg"), (summary.MANUAL, "在頁面上手動設為未對應"))
        self.assertEqual(summary.headline(None, summary.MANUAL), "手動指定：未對應")

    def test_summary_and_markdown(self):
        s = summary.build(self.res.placements, self.stops, self.r)
        kiyomizu = next(v for v in s["visits"] if v["name"] == "清水寺")
        self.assertEqual(kiyomizu["photos"], 3)
        self.assertEqual(kiyomizu["confidence"], "高、推測")
        self.assertEqual(s["unknown"]["files"], ["x1.jpg"])
        md = summary.markdown(s)
        self.assertIn("## 不確定", md)
        self.assertIn("前後照片也無法推測", md)
        self.assertNotIn("未知", md)
        self.assertIn("推測為同一站", md)

    def test_output_report_and_places_md(self):
        out = os.path.join(self.tmp.name, "out")
        before = snapshot(self.inp)
        output.apply(self.scan, self.res, out, places=output.PlaceContext(self.stops, self.r))
        with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
            rows = {r["原始檔案"]: r for r in json.load(fh)["files"]}
        self.assertTrue(rows["a2.jpg"]["景點判斷"].startswith("推測：清水寺"))
        self.assertTrue(rows["x1.jpg"]["景點判斷"].startswith("不確定"))
        self.assertTrue(rows["a1.jpg"]["景點判斷"].startswith("清水寺（可信度：高）"))
        self.assertEqual(snapshot(self.inp), before, "originals are never changed")


class GuessTrip(tp.PlaceFixture):
    """The #7 fixture plus a photo with no sign between two Kiyomizu photos."""

    start = tp.PlaceApiTests.start
    raw = tp.PlaceApiTests.raw
    api = tp.PlaceApiTests.api

    def setUp(self):
        super().setUp()
        # Between Kiyomizu (a1, a2) and Fushimi Inari (b1) in the base fixture,
        # add Kiyomizu photos on both sides of a photo with no sign.
        save_jpeg(marked(scene(60), 0), os.path.join(self.inp, "k1.jpg"), D1.replace(hour=10))
        save_jpeg(marked(scene(61), None), os.path.join(self.inp, "k2.jpg"), D1.replace(hour=10, minute=30))
        save_jpeg(marked(scene(62), 0), os.path.join(self.inp, "k3.jpg"), D1.replace(hour=11))

    def group(self, data, first):
        return next(g for g in data["groups"] if g["first"] == first)


class GuessApiTests(GuessTrip):
    """The page's API: 推測 is shown, and the owner can change it like any stop."""

    def test_guess_is_labelled_and_can_be_changed_by_hand(self):
        self.start(lambda: FakeOcr(self.texts))
        self.api("/api/scan", {"input_dir": self.inp, "itinerary": ITINERARY})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 200, data)
        g = self.group(data, "k2.jpg")
        self.assertEqual(g["stop"], 1)
        self.assertEqual((g["place"]["confidence"], g["place"]["headline"]), ("推測", "推測：清水寺"))
        self.assertIn("推測為同一站", g["place"]["evidence"])
        g1 = self.group(data, "g1.jpg")  # between Kinkaku-ji and the hotel
        self.assertIsNone(g1["stop"])
        self.assertEqual(g1["place"]["headline"], "不確定")
        # The owner moves the guessed group to Arashiyama: it wins, also on a re-run.
        status, data = self.api("/api/arrange", {"assignments": {**data["assignments"], "k2.jpg": 5}})
        status, data = self.api("/api/places/analyze", {})
        g = self.group(data, "k2.jpg")
        self.assertEqual(g["stop"], 5)
        self.assertEqual(g["place"]["confidence"], summary.MANUAL)
        # And can set it to 未對應, which a re-run keeps.
        cleared = {k: v for k, v in data["assignments"].items() if k != "k2.jpg"}
        self.api("/api/arrange", {"assignments": cleared})
        status, data = self.api("/api/places/analyze", {})
        self.assertNotIn("k2.jpg", data["assignments"])
        self.assertEqual(self.group(data, "k2.jpg")["place"]["headline"], "手動指定：未對應")


class FakeEngine:
    """Reads the red channel of the top-left pixel as a key."""

    def __init__(self, texts):
        self.texts = texts

    def read_text(self, rgb):
        return self.texts[int(rgb[0, 0, 0])]


class SequenceBenchmarkTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        for i in range(6):
            Image.new("RGB", (32, 32), (i * 40, 0, 0)).save(os.path.join(self.dir, f"p{i}.png"))
        # p0 Kiyomizu, p1 nothing, p2 Lawson, p3 two names, p4 Fushimi Inari, p5 Kyoto station
        self.engine = FakeEngine({0: ["清水寺"], 40: [], 80: ["LAWSON"], 120: ["伏見稲荷大社 清水寺"], 160: ["伏見稲荷"], 200: ["京都駅"]})

    def seq(self, *photos):
        return {"name": "t", "photos": [{"file": os.path.join(self.dir, f), "expected": e} for f, e in photos]}

    def test_counts_before_and_after_the_guess(self):
        seqs = [
            self.seq(("p0.png", "清水寺"), ("p1.png", "清水寺"), ("p2.png", "清水寺"), ("p0.png", "清水寺")),
            self.seq(("p4.png", "伏見稻荷大社"), ("p3.png", None), ("p5.png", "京都車站")),
            self.seq(("p4.png", "伏見稻荷大社"), ("p1.png", "京都車站"), ("p4.png", "伏見稻荷大社")),
        ]
        r = benchmark.run_sequences(seqs, benchmark.ITINERARY, self.engine)
        self.assertEqual([x["outcome"] for x in r["rows"]], ["hit", "inferred_hit", "inferred_hit", "hit", "hit", "ok", "hit", "hit", "wrong", "hit"])
        self.assertEqual(r["before"], {"hits": 6, "uncertain": 3, "kept_uncertain": 1, "wrong": 0})
        self.assertEqual((r["text_hits"], r["inferred_hits"], r["uncertain"], r["kept_uncertain"], r["wrong"]), (6, 2, 0, 1, 1))
        self.assertEqual(r["rows"][3]["file"], "p0.png'", "a photo used twice in one sequence is two entries")
        out = io.StringIO()
        benchmark.report_sequences(r, out)
        self.assertIn("推測：清水寺", out.getvalue())
        self.assertIn("錯站 1", out.getvalue())

    def test_sequence_files_json_and_csv(self):
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "sequence.csv"), "w", encoding="utf-8") as fh:
            fh.write("../p0.png,清水寺\n../p1.png,\n")
        seqs = benchmark.load_sequences(os.path.join(sub, "sequence.csv"))
        self.assertEqual(len(seqs), 1)
        self.assertEqual([p["expected"] for p in seqs[0]["photos"]], ["清水寺", None])
        self.assertTrue(os.path.isfile(seqs[0]["photos"][0]["file"]), "paths are relative to the file")
        with open(os.path.join(sub, "flat.json"), "w", encoding="utf-8") as fh:
            json.dump([{"file": "../p0.png", "expected": "清水寺"}], fh)
        self.assertEqual(benchmark.load_sequences(os.path.join(sub, "flat.json"))[0]["photos"][0]["expected"], "清水寺")

    def test_local_folder_is_read_after_the_public_set(self):
        local = os.path.join(self.dir, "local")
        os.makedirs(local)
        with open(os.path.join(local, "sequence.csv"), "w", encoding="utf-8") as fh:
            fh.write("../p4.png,伏見稻荷大社\n../p2.png,伏見稻荷大社\n../p4.png,伏見稻荷大社\n")
        with open(os.path.join(local, "labels.csv"), "w", encoding="utf-8") as fh:
            fh.write("../p5.png,京都車站\n")
        with open(os.path.join(local, "itinerary.txt"), "w", encoding="utf-8") as fh:
            fh.write("伏見稻荷大社\n京都車站\n")
        out = io.StringIO()
        json_path = os.path.join(self.dir, "r.json")
        with redirect_stdout(out), mock.patch.object(benchmark, "make_engine", lambda kind: self.engine):
            benchmark.main(["--photos", self.dir, "--local", local, "--json", json_path])
        with open(json_path, encoding="utf-8") as fh:
            sets = json.load(fh)
        self.assertEqual(len(sets), 2)
        own = sets[1]
        self.assertIn("本機額外照片", own["title"])
        self.assertEqual(own["photos"]["hits"], 1)
        self.assertEqual((own["sequences"]["inferred_hits"], own["sequences"]["wrong"]), (1, 0))
        self.assertIn("推測：伏見稻荷大社", out.getvalue())

    def test_missing_local_folder_is_an_error_only_when_named(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            benchmark.main(["--local", os.path.join(self.dir, "nope")])

    def test_local_folder_is_git_ignored(self):
        with open(os.path.join(benchmark.REPO, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn("/benchmark-local/", fh.read().splitlines())
        self.assertEqual(benchmark.LOCAL_DIR, os.path.join(benchmark.REPO, "benchmark-local"))
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", os.path.join("benchmark-local", "IMG_0001.jpg")], cwd=benchmark.REPO, capture_output=True
        )
        if ignored.returncode in (0, 1):  # 128: not a git checkout
            self.assertEqual(ignored.returncode, 0, "benchmark-local/ must be ignored by git")


class PublicSequenceTests(unittest.TestCase):
    def test_public_sequences_cover_the_three_cases(self):
        seqs = benchmark.load_sequences(benchmark.DEFAULT_SEQUENCES)
        files = {os.path.basename(p["file"]) for s in seqs for p in s["photos"]}
        for s in seqs:
            for p in s["photos"]:
                self.assertTrue(os.path.isfile(p["file"]), p["file"])
        # building only, a non-place sign, a sign with several place names
        self.assertTrue({"sign23.jpg", "held11.jpg", "store01.jpg", "sign13.jpg", "multi01.jpg"} <= files)
        sandwiched = [
            s for s in seqs if any(p["expected"] is None for p in s["photos"]) and len({p["expected"] for p in s["photos"] if p["expected"]}) > 1
        ]
        self.assertTrue(sandwiched, "a case between two different stops")
        here = os.path.dirname(benchmark.DEFAULT_SEQUENCES)
        with open(os.path.join(here, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        for name in os.listdir(here):
            if name.lower().endswith(".jpg"):
                self.assertIn(name, readme, "generated images are described in the README")


def _models_ready():
    from travelphotos.places import models as place_models

    return not place_models.missing_models(place_models.model_dir())


@needs(_models_ready(), "OCR models not downloaded (python launcher/download_models.py)")
class RealSequenceTests(unittest.TestCase):
    def test_public_sequences_with_the_real_models(self):
        from tests.face_helpers import no_network
        from travelphotos.places.ocr import load_engine

        seqs = benchmark.load_sequences(benchmark.DEFAULT_SEQUENCES)
        with no_network():
            r = benchmark.run_sequences(seqs, benchmark.ITINERARY, load_engine())
        detail = [(x["file"], x["expected"], x["got"], x["lines"][:4]) for x in r["rows"] if x["outcome"] not in ("hit", "inferred_hit", "ok")]
        self.assertEqual(r["wrong"], 0, detail)
        self.assertEqual(r["before"]["wrong"], 0)
        self.assertEqual(r["uncertain"], 0, detail)
        self.assertGreaterEqual(r["inferred_hits"], 5, detail)
        self.assertGreaterEqual(r["text_hits"], r["before"]["hits"], "photos read directly do not get worse")
        rows = {(x["sequence"], x["file"]): x for x in r["rows"]}
        for (seq, name), x in rows.items():
            if name in ("sign23.jpg", "store01.jpg", "multi01.jpg"):
                self.assertTrue(x["got"] is None or x["how"] == "inferred", (seq, name, x))


_GUESS_SCRIPT = textwrap.dedent(
    r"""
    const { chromium } = require(process.env.TRAVELPHOTOS_PLAYWRIGHT);
    const [url, trip, itinerary] = process.argv.slice(2);
    (async () => {
      const browser = await chromium.launch();
      const page = await browser.newPage();
      page.on("dialog", (d) => d.accept());
      await page.goto(url);
      await page.fill("#input-dir", trip);
      await page.fill("#itinerary", itinerary);
      await page.click("#scan");
      await page.waitForSelector("#step-review:not([hidden])");
      await page.click("#places-analyze");
      await page.waitForFunction(() => document.querySelector("#places-status").textContent.startsWith("完成"));
      const rows = async () => page.$$eval("#groups .group-row", (rs) => rs.map((r) => ({
        text: r.textContent, value: r.querySelector("select").value, guess: !!r.querySelector(".place-guess") })));
      const before = await rows();
      const status = await page.textContent("#places-status");
      // Groups are listed in itinerary order, so find the guessed one by its first file.
      const i = before.findIndex((r) => r.text.includes("推測："));
      const first = before[i].text.match(/從 (\S+) 開始/)[1];
      await page.locator("#groups select").nth(i).selectOption("5");
      await page.waitForFunction((f) => [...document.querySelectorAll("#groups .group-row")].some(
        (r) => r.textContent.includes(`從 ${f} 開始`) && r.textContent.includes("手動指定")), first);
      const after = await rows();
      const changed = after.find((r) => r.text.includes(`從 ${first} 開始`));
      console.log(JSON.stringify({ before, after, status, first, changed }));
      await browser.close();
    })().catch((e) => { console.error(e); process.exit(1); });
    """
)


@needs(_browser_available(), "no browser automation (node + playwright) on this computer; check by hand")
class GuessInThePageTests(GuessTrip):
    def test_page_shows_guess_and_uncertain_and_allows_a_change(self):
        self.start(lambda: FakeOcr(self.texts))
        script = os.path.join(self.tmp.name, "guess.js")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_GUESS_SCRIPT)
        done = subprocess.run(
            ["node", script, f"http://127.0.0.1:{self.port}/", self.inp, ITINERARY],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env={**os.environ, "TRAVELPHOTOS_PLAYWRIGHT": _playwright_entry()},
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        result = json.loads(done.stdout.strip().splitlines()[-1])
        guessed = [r for r in result["before"] if "推測：清水寺" in r["text"]]
        self.assertEqual(len(guessed), 1, result["before"])
        self.assertTrue(guessed[0]["guess"], "set apart with its own style")
        self.assertEqual(guessed[0]["value"], "1")
        self.assertTrue(any(r["text"].count("不確定") and r["value"] == "" for r in result["before"]), result["before"])
        self.assertIn("依前後照片推測", result["status"])
        self.assertEqual(result["first"], "k2.jpg")
        changed = result["changed"]
        self.assertEqual(changed["value"], "5")
        self.assertIn("可信度：手動指定", changed["text"])
        self.assertFalse(changed["guess"])


if __name__ == "__main__":
    unittest.main()
