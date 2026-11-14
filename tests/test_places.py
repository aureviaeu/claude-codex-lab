"""Places (#7): sign text vs. itinerary, look-alike groups, summary, output."""

from __future__ import annotations

import http.client
import json
import os
import re
import tempfile
import threading
import unittest
from datetime import datetime

import cv2
import numpy as np
from PIL import Image

from tests.face_helpers import no_network
from tests.helpers import save_jpeg, scene, variant
from travelphotos import ordering, output
from travelphotos import server as srv
from travelphotos.itinerary import parse_itinerary
from travelphotos.ordering import HIGH, LOW, MEDIUM
from travelphotos.places import cloud, matching, pipeline, summary
from travelphotos.places.ocr import OcrUnavailable, OpenCVOcr
from travelphotos.scan import scan

# The fake OCR engine reads a coloured marker in the top-left corner.
MARKERS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]


def marked(img: Image.Image, marker: int | None) -> Image.Image:
    out = img.copy()
    out.paste(MARKERS[marker] if marker is not None else (0, 0, 0), (0, 0, 16, 16))
    return out


class FakeOcr:
    """Returns the lines registered for the marker colour it sees."""

    def __init__(self, texts: dict[int, list[str]]):
        self.texts = texts
        self.calls = 0

    def read_text(self, rgb) -> list[str]:
        self.calls += 1
        r, g, b = (int(v) for v in np.asarray(rgb)[4:12, 4:12].reshape(-1, 3).mean(axis=0))
        for i, (mr, mg, mb) in enumerate(MARKERS):
            if abs(r - mr) + abs(g - mg) + abs(b - mb) < 90:
                return list(self.texts.get(i, []))
        return []


def save_video_with_marker(path: str, marker: int, seconds: int = 4, fps: int = 5) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (96, 72))
    frame = np.full((72, 96, 3), 90, dtype=np.uint8)
    b, g, r = MARKERS[marker][2], MARKERS[marker][1], MARKERS[marker][0]
    frame[0:16, 0:16] = (b, g, r)
    for _ in range(seconds * fps):
        writer.write(frame)
    writer.release()
    return path


ITINERARY = """第1天：清水寺 → 伏見稻荷大社 → 京都飯店
第2天：金閣寺 → 嵐山 → 京都飯店
"""


class MatchingTests(unittest.TestCase):
    def test_traditional_and_simplified_compare_equal(self):
        self.assertEqual(matching.normalize("淺草寺 東京鐵塔"), matching.normalize("浅草寺东京铁塔"))
        self.assertEqual(matching.name_score("伏見稻荷大社", "伏见稻荷大社 千本鸟居"), 1.0)

    def test_one_misread_character_is_a_medium_match(self):
        score = matching.name_score("清水寺", "清水芋入口")
        self.assertGreaterEqual(score, matching.MIN_SCORE)
        self.assertLess(score, matching.HIGH_SCORE)

    def test_unrelated_text_does_not_match(self):
        self.assertLess(matching.name_score("金閣寺", "出口 EXIT 7-11"), matching.MIN_SCORE)
        self.assertEqual(matching.best_matches([("a.jpg", "出口")], parse_itinerary(ITINERARY)), [])

    def test_latin_names_ignore_case_and_width(self):
        self.assertEqual(matching.name_score("Shibuya", "ＳＨＩＢＵＹＡ Station"), 1.0)
        self.assertEqual(matching.name_score("Kyoto Hotel", "KYOTO HOTEL 京都饭店"), 1.0)
        self.assertGreaterEqual(matching.name_score("Kinkakuji", "KINKAKUJl temple"), matching.MIN_SCORE)

    def test_short_names_need_an_exact_match(self):
        for name, text in [("嵐山", "富士山"), ("嵐山", "山"), ("奈良", "良品"), ("大阪", "大學"), ("京都", "東京"), ("台北", "北口")]:
            self.assertEqual(matching.name_score(name, text), 0.0, (name, text))
        self.assertEqual(matching.name_score("嵐山", "岚山 渡月桥"), 1.0)

    def test_latin_names_do_not_match_inside_other_words(self):
        self.assertEqual(matching.name_score("Nara", "Narita Airport"), 0.0)
        self.assertEqual(matching.name_score("Nara", "NARA PARK"), 1.0)

    def test_sharing_only_some_characters_is_not_a_match(self):
        stops = parse_itinerary("清水寺\n嵐山\n金閣寺\n伏見稻荷大社")
        self.assertEqual(matching.best_matches([("a.jpg", "高山 寺 入口")], stops), [])
        self.assertEqual(matching.best_matches([("a.jpg", "伏见神社")], stops), [])


class PlaceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inp = os.path.join(self.tmp.name, "in")
        d1, d2 = datetime(2024, 4, 1), datetime(2024, 4, 2)
        a = scene(1)
        # A: Kiyomizu, sign read exactly; two near-identical shots.
        save_jpeg(marked(a, 0), os.path.join(self.inp, "a1.jpg"), d1.replace(hour=9))
        save_jpeg(marked(variant(a, 2), None), os.path.join(self.inp, "a2.jpg"), d1.replace(hour=9, minute=1))
        # B: Fushimi Inari, sign in simplified characters; a video with a sign too.
        save_jpeg(marked(scene(3), 1), os.path.join(self.inp, "b1.jpg"), d1.replace(hour=13))
        save_video_with_marker(os.path.join(self.inp, "b2.mp4"), 1)
        # F: the same view as A three hours later, no sign: borrows A's place.
        save_jpeg(marked(variant(a, 4), None), os.path.join(self.inp, "f1.jpg"), d1.replace(hour=12))
        # C: the hotel on day 1.
        save_jpeg(marked(scene(5), 2), os.path.join(self.inp, "c1.jpg"), d1.replace(hour=20))
        # D: Kinkaku-ji, one character misread.
        save_jpeg(marked(scene(6), 3), os.path.join(self.inp, "d1.jpg"), d2.replace(hour=10))
        # E: the hotel again on day 2.
        save_jpeg(marked(scene(7), 2), os.path.join(self.inp, "e1.jpg"), d2.replace(hour=21))
        # G: no sign, looks like nothing else.
        save_jpeg(marked(scene(8), None), os.path.join(self.inp, "g1.jpg"), d2.replace(hour=15))
        # H: a sign that is not in the itinerary.
        save_jpeg(marked(scene(9), 4), os.path.join(self.inp, "h1.jpg"), d2.replace(hour=16))
        self.texts = {
            0: ["清水寺", "入口"],
            1: ["伏见稻荷大社"],
            2: ["京都饭店 KYOTO HOTEL"],
            3: ["金阁芋"],
            4: ["出口 EXIT"],
        }
        self.scan = scan(self.inp)
        self.stops = parse_itinerary(ITINERARY)

    def analyze(self, stops=None, environ=None):
        return pipeline.analyze(self.scan.files, self.stops if stops is None else stops, FakeOcr(self.texts), environ=environ or {})


class PipelineTests(PlaceFixture):
    def place_of(self, result, file_id):
        return result.by_file()[file_id]

    def test_each_group_gets_a_stop_or_unknown_with_confidence(self):
        r = self.analyze()
        a = self.place_of(r, "a1.jpg")
        self.assertEqual((a.stop.name, a.confidence, a.method), ("清水寺", HIGH, "text"))
        self.assertIs(self.place_of(r, "a2.jpg"), a, "similar photos are judged once, as one group")
        self.assertEqual(self.place_of(r, "b1.jpg").stop.index, 2)
        self.assertEqual(self.place_of(r, "b2.mp4").stop.index, 2, "video frames are read too")
        d = self.place_of(r, "d1.jpg")
        self.assertEqual((d.stop.name, d.confidence), ("金閣寺", MEDIUM))
        f = self.place_of(r, "f1.jpg")
        self.assertEqual((f.stop.name, f.confidence, f.method), ("清水寺", LOW, "visual"))
        for fid in ("g1.jpg", "h1.jpg"):
            self.assertIsNone(self.place_of(r, fid).stop)
            self.assertIsNone(self.place_of(r, fid).confidence)
        self.assertIn("沒有對應", self.place_of(r, "h1.jpg").evidence)

    def test_a_repeated_stop_takes_the_next_visit_in_order(self):
        r = self.analyze()
        self.assertEqual(self.place_of(r, "c1.jpg").stop.index, 3)
        self.assertEqual(self.place_of(r, "e1.jpg").stop.index, 6)

    def test_repeated_stop_on_another_day_without_a_stop_in_between(self):
        """Regression (Codex P1): the day-2 hotel must not merge into day 1's."""
        self.texts[3] = []  # D (day 2, Kinkaku-ji) is no longer recognised
        r = self.analyze()
        self.assertIsNone(self.place_of(r, "d1.jpg").stop)
        self.assertEqual(self.place_of(r, "c1.jpg").stop.index, 3)
        self.assertEqual(self.place_of(r, "e1.jpg").stop.index, 6)
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        s = summary.build(res.placements, self.stops, r)
        self.assertEqual([v["stop"] for v in s["visits"] if v["name"] == "京都飯店"], [3, 6])

    def test_repeated_stop_without_day_headings_uses_the_date(self):
        flat = parse_itinerary("清水寺\n伏見稻荷大社\n京都飯店\n金閣寺\n嵐山\n京都飯店")
        self.assertEqual({st.day for st in flat}, {1})
        self.texts[3] = []
        r = pipeline.analyze(self.scan.files, flat, FakeOcr(self.texts), environ={})
        self.assertEqual(r.by_file()["c1.jpg"].stop.index, 3)
        self.assertEqual(r.by_file()["e1.jpg"].stop.index, 6)

    def test_ambiguous_text_stays_unknown(self):
        self.texts[4] = ["金閣寺 嵐山"]
        r = self.analyze()
        self.assertIsNone(self.place_of(r, "h1.jpg").stop)
        self.assertIn("無法判斷", self.place_of(r, "h1.jpg").evidence)

    def test_without_itinerary_only_text_and_unknown(self):
        r = self.analyze(stops=[])
        self.assertFalse(r.has_itinerary)
        self.assertTrue(all(g.stop is None for g in r.groups))
        self.assertEqual(r.assignments(), {})
        lines = [t for g in r.groups for _f, t in g.texts]
        self.assertIn("清水寺", lines)
        res = ordering.order(self.scan.files, [])
        md = summary.markdown(summary.build(res.placements, [], r))
        self.assertIn("沒有提供行程表", md)
        self.assertIn("未知", md)
        self.assertIn("「清水寺」", md)

    def test_group_with_eight_photos_and_a_video(self):
        """Regression (Codex P1): no video slots left must not divide by zero."""
        trip = os.path.join(self.tmp.name, "big")
        base = scene(20)
        t = datetime(2024, 4, 1, 9)
        for i in range(8):
            save_jpeg(marked(variant(base, 100 + i), 0 if i == 0 else None), os.path.join(trip, f"p{i}.jpg"), t.replace(minute=i))
        save_video_with_marker(os.path.join(trip, "v.mp4"), 1)
        res = scan(trip)
        video = next(f for f in res.files if f.kind == "video")
        video.time = t.replace(minute=3)  # same time slot: one group of 9
        r = pipeline.analyze(res.files, self.stops, FakeOcr(self.texts), environ={})
        self.assertEqual(len(r.groups), 1)
        self.assertEqual(len(r.groups[0].member_ids), 9)
        self.assertEqual(r.groups[0].stop.name, "清水寺")

    def test_pick_with_no_room(self):
        self.assertEqual(pipeline._pick([1, 2, 3], 0), [])
        self.assertEqual(pipeline._pick([1, 2, 3, 4], 2), [1, 3])

    def test_works_with_network_blocked(self):
        with no_network():
            r = self.analyze()
        self.assertEqual(self.place_of(r, "a1.jpg").stop.index, 1)

    def test_groups_follow_itinerary_order(self):
        r = self.analyze()
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        order = [p.file.id for p in res.placements]
        stops = [p.stop.index if p.stop else None for p in res.placements]
        self.assertEqual(stops, sorted(stops, key=lambda s: (s is None, s or 0)))
        self.assertLess(order.index("f1.jpg"), order.index("b1.jpg"), "F joins Kiyomizu, before Fushimi Inari")
        self.assertEqual(set(order[-2:]), {"g1.jpg", "h1.jpg"}, "unknown groups go last")


class SummaryTests(PlaceFixture):
    def test_summary_lists_visits_in_order_with_counts_and_representative(self):
        r = self.analyze()
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        s = summary.build(res.placements, self.stops, r)
        got = [(v["stop"], v["name"], v["photos"], v["videos"]) for v in s["visits"]]
        self.assertEqual(
            got,
            [(1, "清水寺", 3, 0), (2, "伏見稻荷大社", 1, 1), (3, "京都飯店", 1, 0), (4, "金閣寺", 1, 0), (6, "京都飯店", 1, 0)],
        )
        self.assertEqual(s["visits"][0]["representative"], "a1.jpg", "the photo whose sign matched")
        self.assertEqual(s["visits"][0]["confidence"], "高、低")
        self.assertEqual(s["missed_stops"], [{"index": 5, "day": 2, "name": "嵐山"}])
        self.assertEqual(sorted(s["unknown"]["files"]), ["g1.jpg", "h1.jpg"])

    def test_markdown_links_output_names(self):
        r = self.analyze()
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        s = summary.build(res.placements, self.stops, r)
        md = summary.markdown(s, {"a1.jpg": "0001_a1.jpg"})
        self.assertIn("# 景點總結", md)
        self.assertIn("| 1 | 清水寺 | 第 1 天第 1 站 | 3 | 0 | 高、低 | 0001_a1.jpg |", md)
        self.assertIn("![清水寺 代表照片](<0001_a1.jpg>)", md)
        self.assertIn("## 行程中沒有照片的站點", md)
        self.assertEqual(md.count("## 3. 京都飯店") + md.count("## 5. 京都飯店"), 2, "a repeated stop is listed twice")

    def test_manual_stop_is_labelled(self):
        r = self.analyze()
        assignments = {**r.assignments(), "g1.jpg": 5}
        res = ordering.order(self.scan.files, self.stops, assignments)
        s = summary.build(res.placements, self.stops, r)
        arashiyama = [v for v in s["visits"] if v["stop"] == 5][0]
        self.assertEqual(arashiyama["confidence"], summary.MANUAL)


class OutputTests(PlaceFixture):
    def test_apply_writes_places_md_and_column(self):
        r = self.analyze()
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        out = os.path.join(self.tmp.name, "out")
        info = output.apply(self.scan, res, out, places=output.PlaceContext(self.stops, r))
        self.assertTrue(os.path.isfile(info["places_report"]))
        with open(os.path.join(out, output.PLACES_MD), encoding="utf-8") as fh:
            md = fh.read()
        first = sorted(n for n in os.listdir(out) if n.endswith("_a1.jpg"))[0]
        self.assertIn(f"![清水寺 代表照片](<{first}>)", md)
        with open(os.path.join(out, output.REPORT_JSON), encoding="utf-8") as fh:
            report = json.load(fh)
        rows = {row["原始檔案"]: row for row in report["files"]}
        self.assertTrue(rows["a1.jpg"]["景點判斷"].startswith("清水寺（可信度：高）"))
        self.assertTrue(rows["g1.jpg"]["景點判斷"].startswith("未知"))
        self.assertEqual(len(report["places"]["visits"]), 5)

    def test_apply_without_places_writes_no_places_md(self):
        res = ordering.order(self.scan.files)
        out = os.path.join(self.tmp.name, "out2")
        info = output.apply(self.scan, res, out)
        self.assertIsNone(info["places_report"])
        self.assertFalse(os.path.exists(os.path.join(out, output.PLACES_MD)))


    def test_old_places_md_is_removed_when_no_longer_written(self):
        r = self.analyze()
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        out = os.path.join(self.tmp.name, "out3")
        output.apply(self.scan, res, out, places=output.PlaceContext(self.stops, r))
        self.assertTrue(os.path.isfile(os.path.join(out, output.PLACES_MD)))
        output.apply(self.scan, ordering.order(self.scan.files), out)
        self.assertFalse(os.path.exists(os.path.join(out, output.PLACES_MD)))
        leftovers = [n for n in os.listdir(out) if n.startswith(".travelphotos-tmp")]
        self.assertEqual(leftovers, [])

    def test_failed_output_keeps_the_old_places_md(self):
        from unittest import mock

        r = self.analyze()
        res = ordering.order(self.scan.files, self.stops, r.assignments())
        out = os.path.join(self.tmp.name, "out4")
        output.apply(self.scan, res, out, places=output.PlaceContext(self.stops, r))
        with open(os.path.join(out, output.PLACES_MD), encoding="utf-8") as fh:
            before = fh.read()
        real_dump = json.dump

        def boom(obj, fh, **kw):
            if isinstance(obj, dict) and "files" in obj and "version" in obj:
                raise OSError("disk full")
            return real_dump(obj, fh, **kw)

        with mock.patch.object(output.json, "dump", boom), self.assertRaises(output.OutputError):
            output.apply(self.scan, ordering.order(self.scan.files), out)
        with open(os.path.join(out, output.PLACES_MD), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before, "rolled back")


class CloudTests(PlaceFixture):
    def test_cloud_is_off_by_default_and_never_implemented(self):
        self.assertFalse(cloud.cloud_requested({}))
        self.assertIsNone(cloud.cloud_recognizer({}))
        self.assertIsNone(cloud.cloud_recognizer({cloud.ENV_FLAG: "1"}))
        self.assertTrue(cloud.cloud_requested({cloud.ENV_FLAG: "yes"}))
        self.assertEqual(self.analyze().warnings, [])

    def test_turning_cloud_on_only_warns_and_stays_local(self):
        with no_network():
            r = self.analyze(environ={cloud.ENV_FLAG: "1"})
        self.assertEqual(r.warnings, [cloud.NOT_IMPLEMENTED])
        self.assertEqual(self.place_stop(r, "a1.jpg"), 1)

    def place_stop(self, r, fid):
        return r.by_file()[fid].stop.index


class PlaceApiTests(PlaceFixture):
    def start(self, factory):
        server, _url, state = srv.create_server(0, self.inp, data_dir=os.path.join(self.tmp.name, "data"), place_engine_factory=factory)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.port = server.server_address[1]
        page = self.raw("GET", "/")[1].decode()
        self.token = re.search(r'name="token" content="([^"]+)"', page).group(1)
        return state

    def raw(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
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

    def api(self, path, body):
        status, data = self.raw("POST", path, body)
        return status, json.loads(data)

    def test_analyze_fills_stops_and_keeps_manual_choices(self):
        self.start(lambda: FakeOcr(self.texts))
        status, data = self.api("/api/scan", {"input_dir": self.inp, "itinerary": ITINERARY})
        self.assertEqual(status, 200, data)
        self.assertFalse(data["places"]["analyzed"])
        # The owner puts G at Arashiyama before running the analysis.
        status, data = self.api("/api/arrange", {"assignments": {"g1.jpg": 5}})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["places"]["analyzed"])
        self.assertEqual(data["assignments"]["g1.jpg"], 5)
        self.assertEqual(data["assignments"]["a1.jpg"], 1)
        names = [v["name"] for v in data["places"]["summary"]["visits"]]
        self.assertEqual(names, ["清水寺", "伏見稻荷大社", "京都飯店", "金閣寺", "嵐山", "京都飯店"])
        group = next(g for g in data["groups"] if g["first"] == "d1.jpg")
        self.assertEqual(group["place"]["confidence"], "中")
        stops = [f["stop"] for f in data["files"]]
        self.assertEqual(stops[: len(stops) - 1], sorted(stops[: len(stops) - 1]))
        # Output writes places.md.
        out = os.path.join(self.tmp.name, "out")
        status, data = self.api("/api/apply", {"output_dir": out})
        self.assertEqual(status, 200, data)
        self.assertTrue(os.path.isfile(os.path.join(out, "places.md")))

    def test_rerun_replaces_automatic_stops_only(self):
        state = self.start(lambda: FakeOcr(self.texts))
        self.api("/api/scan", {"input_dir": self.inp, "itinerary": ITINERARY})
        self.api("/api/places/analyze", {})
        self.texts[3] = []  # D's sign no longer read
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 200, data)
        self.assertNotIn("d1.jpg", data["assignments"])
        self.assertEqual(state.auto_assignments.get("a1.jpg"), 1)

    def test_manual_unknown_survives_a_rerun(self):
        self.start(lambda: FakeOcr(self.texts))
        self.api("/api/scan", {"input_dir": self.inp, "itinerary": ITINERARY})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(data["assignments"]["d1.jpg"], 4)
        # The owner sets D's group to 未對應 (the page drops its assignment).
        cleared = {k: v for k, v in data["assignments"].items() if k != "d1.jpg"}
        status, data = self.api("/api/arrange", {"assignments": cleared})
        self.assertEqual(status, 200, data)
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 200, data)
        self.assertNotIn("d1.jpg", data["assignments"], "manual 未對應 is kept")
        group = next(g for g in data["groups"] if g["first"] == "d1.jpg")
        self.assertIsNone(group["stop"])
        self.assertEqual(data["assignments"]["a1.jpg"], 1, "other groups are still matched")
        # Choosing a stop again for that group lifts the manual 未對應.
        status, data = self.api("/api/arrange", {"assignments": {**data["assignments"], "d1.jpg": 5}})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(data["assignments"]["d1.jpg"], 5)

    def test_rescan_forgets_manual_unknown(self):
        state = self.start(lambda: FakeOcr(self.texts))
        self.api("/api/scan", {"input_dir": self.inp, "itinerary": ITINERARY})
        status, data = self.api("/api/places/analyze", {})
        self.api("/api/arrange", {"assignments": {k: v for k, v in data["assignments"].items() if k != "d1.jpg"}})
        self.assertEqual(state.cleared_groups, {"d1.jpg"})
        self.api("/api/scan", {"input_dir": self.inp, "itinerary": ITINERARY})
        self.assertEqual(state.cleared_groups, set())
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(data["assignments"]["d1.jpg"], 4)

    def test_missing_models_is_a_clear_error(self):
        def missing():
            raise OcrUnavailable("還沒有下載文字辨識模型")

        self.start(missing)
        self.api("/api/scan", {"input_dir": self.inp})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 400)
        self.assertIn("文字辨識模型", data["error"])

    def test_no_itinerary_runs_without_error(self):
        self.start(lambda: FakeOcr(self.texts))
        self.api("/api/scan", {"input_dir": self.inp})
        status, data = self.api("/api/places/analyze", {})
        self.assertEqual(status, 200, data)
        s = data["places"]["summary"]
        self.assertEqual(s["visits"], [])
        self.assertEqual(len(s["unknown"]["files"]), len(data["files"]))
        self.assertTrue(any("清水寺" in t["lines"] for t in s["texts"]))


class OcrEngineTests(unittest.TestCase):
    def test_missing_models_explain_how_to_download(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(OcrUnavailable) as cm:
            OpenCVOcr(d)
        self.assertIn("download_models.py", str(cm.exception))


def _real_model_dir():
    from travelphotos.places.models import missing_models, model_dir

    d = model_dir()
    return d if not missing_models(d) else None


def _cjk_font():
    for path in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/System/Library/Fonts/PingFang.ttc", "C:/Windows/Fonts/msjh.ttc"):
        if os.path.isfile(path):
            return path
    return None


@unittest.skipUnless(_real_model_dir() and _cjk_font(), "OCR models not downloaded (python launcher/download_models.py) or no CJK font")
class RealOcrTests(unittest.TestCase):
    """Reads a rendered sign with the real local models."""

    def test_reads_a_sign_and_matches_the_itinerary(self):
        from PIL import ImageDraw, ImageFont

        from travelphotos.places.ocr import load_engine

        with tempfile.TemporaryDirectory() as d:
            img = Image.new("RGB", (640, 480), (90, 140, 200))
            draw = ImageDraw.Draw(img)
            draw.rectangle((100, 180, 540, 290), fill=(250, 250, 240))
            draw.text((130, 200), "金閣寺 入口", font=ImageFont.truetype(_cjk_font(), 56), fill=(10, 10, 10))
            save_jpeg(img, os.path.join(d, "in", "sign.jpg"), datetime(2024, 4, 2, 10))
            res = scan(os.path.join(d, "in"))
            with no_network():
                r = pipeline.analyze(res.files, parse_itinerary(ITINERARY), load_engine(), environ={})
        g = r.by_file()["sign.jpg"]
        self.assertTrue(g.texts, "some text was read")
        self.assertEqual(g.stop.name, "金閣寺", g.texts)


if __name__ == "__main__":
    unittest.main()
