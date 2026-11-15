"""#22: better sign reading. Matching rules run in CI; model tests run where
the OCR models are downloaded (python launcher/download_models.py)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

import numpy as np

from launcher import download_models
from tests.face_helpers import no_network
from tests.helpers import snapshot
from travelphotos.itinerary import Stop, parse_itinerary, split_aliases
from travelphotos.places import benchmark, matching
from travelphotos.places import models as place_models

SIGNS = os.path.join(os.path.dirname(__file__), "data", "signs")


def stop(name, *aliases, index=1):
    return Stop(index=index, day=1, name=name, aliases=list(aliases))


def score(name, line, *aliases):
    return matching.stop_score(stop(name, *aliases), line)


class JapaneseAndChineseFormsTests(unittest.TestCase):
    def test_japanese_kanji_compare_with_chinese(self):
        self.assertEqual(matching.normalize("伏見稲荷"), matching.normalize("伏見稻荷"))
        self.assertEqual(matching.normalize("京都駅"), matching.normalize("京都驛"))
        self.assertEqual(score("京都車站", "京都駅"), matching.CORE_SCORE)

    def test_simplified_and_traditional_both_ways(self):
        self.assertEqual(score("嵐山", "岚山"), 1.0)  # simplified sign, traditional itinerary
        self.assertEqual(score("岚山", "嵐山"), 1.0)  # and the reverse
        self.assertEqual(score("伏見稻荷大社", "伏见稻荷大社"), 1.0)

    def test_basic_rules_are_the_old_behaviour(self):
        self.assertEqual(matching.stop_score(stop("京都車站"), "京都", rules="basic"), 0.0)
        self.assertEqual(matching.stop_score(stop("嵐山", "Arashiyama"), "Arashiyama", rules="basic"), 0.0)


class CoreNameTests(unittest.TestCase):
    def test_a_sign_with_only_the_core_name_matches(self):
        self.assertEqual(score("京都車站", "京都"), matching.CORE_SCORE)
        self.assertEqual(score("伏見稻荷大社", "伏見稲荷"), matching.CORE_SCORE)
        self.assertLess(matching.CORE_SCORE, matching.HIGH_SCORE, "core names are medium confidence")

    def test_other_stations_and_places_do_not_match(self):
        for name, line in [
            ("京都車站", "京都市役所前"),
            ("京都車站", "京都河原町"),
            ("京都車站", "東京"),
            ("奈良公園", "奈良"),
            ("奈良公園", "奈良駅"),
            ("奈良公園", "近鉄奈良"),
            ("明治神宮", "明治"),
            ("嵐山", "富士山"),
        ]:
            with self.subTest(name=name, line=line):
                self.assertEqual(score(name, line), 0.0)

    def test_latin_names_still_match_whole_words_only(self):
        self.assertEqual(score("Nara", "Narita Airport"), 0.0)
        self.assertEqual(score("嵐山", "Narita", "Nara"), 0.0)


class AliasTests(unittest.TestCase):
    def test_marked_brackets_are_aliases(self):
        self.assertEqual(split_aliases("嵐山（別名 Arashiyama）"), ("嵐山", ["Arashiyama"]))
        self.assertEqual(split_aliases("嵐山（別名：Arashiyama）"), ("嵐山", ["Arashiyama"]))
        self.assertEqual(split_aliases("雷門 (aka Kaminarimon; Kaminari-mon)"), ("雷門", ["Kaminarimon", "Kaminari-mon"]))
        self.assertEqual(split_aliases("雷門 (AKA: Kaminarimon)"), ("雷門", ["Kaminarimon"]))
        stops = parse_itinerary("第1天：嵐山（別名 Arashiyama） → 清水寺\n")
        self.assertEqual([(s.name, s.aliases) for s in stops], [("嵐山", ["Arashiyama"]), ("清水寺", [])])

    def test_other_brackets_stay_part_of_the_name(self):
        for text in (
            "京都飯店（午餐）",
            "清水寺 (早上)",
            "金閣寺（鹿苑寺）",
            "Day trip (2)",
            "嵐山（Arashiyama）",
            "清水寺 (morning)",
            "京都飯店 (check-in)",
            "Hotel Granvia (Kyoto)",
        ):
            with self.subTest(text=text):
                self.assertEqual(split_aliases(text), (text, []))
        stops = parse_itinerary("京都飯店（午餐）\n清水寺 (早上)\n")
        self.assertEqual([s.name for s in stops], ["京都飯店（午餐）", "清水寺 (早上)"])
        self.assertEqual([s.aliases for s in stops], [[], []])

    def test_alias_matches_a_slightly_misread_latin_line(self):
        self.assertGreaterEqual(score("嵐山", "Hankyu Arashlyama Station", "Arashiyama"), matching.MIN_SCORE)
        self.assertEqual(score("嵐山", "Hankyu Arashlyama Station"), 0.0, "no alias, no match")

    def test_alias_matches_inside_run_together_latin(self):
        self.assertGreaterEqual(score("嵐山", "HankyuArashlyama Statlon", "Arashiyama"), matching.MIN_SCORE)
        self.assertEqual(score("嵐山", "HankyuArashlyama Statlon"), 0.0, "only aliases, not stop names")
        self.assertEqual(score("奈良公園", "NaritaExpress", "Nara"), 0.0, "short aliases stay whole-word")
        self.assertEqual(score("嵐山", "HankyuArastaStation", "Arashiyama"), 0.0, "two letters off is not a match")

    def test_english_notes_do_not_match_signs(self):
        """Review finding: plain English notes must not become aliases."""
        stops = parse_itinerary("清水寺 (morning)\n京都飯店 (check-in)\nHotel Granvia (Kyoto)\n")
        for line in ("Good Morning", "Check-in", "Welcome to Kyoto", "Kyoto Tower"):
            with self.subTest(line=line):
                self.assertEqual(matching.best_matches([("a.jpg", line)], stops), [])

    def test_alias_is_used_in_best_matches_but_name_is_reported(self):
        stops = parse_itinerary("嵐山（別名 Arashiyama）\n富士山\n")
        found = matching.best_matches([("a.jpg", "Arashiyama")], stops)
        self.assertEqual([m.stop.name for m in found], ["嵐山"])


class FakeEngine:
    def __init__(self, texts):
        self.texts = texts

    def read_text(self, rgb):
        return self.texts[int(rgb[0, 0, 0])]


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        for i in range(5):
            Image.new("RGB", (32, 32), (i * 40, 0, 0)).save(os.path.join(self.dir, f"p{i}.png"))
        self.engine = FakeEngine({0: ["伏見稲荷"], 40: ["京都市役所前"], 80: ["Arashlyama"], 120: ["清水寺"], 160: []})

    def test_counts_hits_misses_and_false_positives(self):
        labels = [
            {"file": "p0.png", "expected": "伏見稻荷大社"},
            {"file": "p1.png", "expected": None},
            {"file": "p2.png", "expected": "嵐山"},
            {"file": "p3.png", "expected": "伏見稻荷大社"},
            {"file": "p4.png", "expected": None},
        ]
        result = benchmark.run(self.dir, labels, benchmark.ITINERARY, self.engine)
        self.assertEqual([r["outcome"] for r in result["rows"]], ["hit", "ok", "miss", "wrong", "ok"])
        self.assertEqual((result["hits"], result["positives"], result["wrong"], result["false_positives"]), (1, 3, 1, 0))
        out = io.StringIO()
        benchmark.report(result, out)
        self.assertIn("命中 1/3", out.getvalue())

    def test_labels_from_csv_and_own_itinerary(self):
        csv_path = os.path.join(self.dir, "labels.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write("p2.png,嵐山\np4.png,\n")
        labels = benchmark.load_labels(csv_path)
        self.assertEqual(labels, [{"file": "p2.png", "expected": "嵐山"}, {"file": "p4.png", "expected": None}])
        result = benchmark.run(self.dir, labels, "嵐山（別名 Arashiyama）\n", self.engine)
        self.assertEqual(result["hits"], 1)

    def test_basic_rules_reproduce_the_old_numbers(self):
        labels = [{"file": "p0.png", "expected": "伏見稻荷大社"}]
        self.assertEqual(benchmark.run(self.dir, labels, benchmark.ITINERARY, self.engine, rules="basic")["hits"], 0)


class TestSetTests(unittest.TestCase):
    """The repo's real sign photos: licensed for reuse, recorded, small."""

    def test_every_photo_has_source_author_and_license(self):
        with open(os.path.join(SIGNS, "labels.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        files = sorted(n for n in os.listdir(SIGNS) if n.lower().endswith(".jpg"))
        self.assertEqual(sorted(r["file"] for r in rows), files)
        self.assertGreaterEqual(len(rows), 20)
        self.assertGreaterEqual(sum(1 for r in rows if r["expected"]), 12)
        for r in rows:
            with self.subTest(file=r["file"]):
                self.assertRegex(r["source"], r"^https://commons\.wikimedia\.org/wiki/File:")
                self.assertTrue(r["author"].strip())
                self.assertRegex(r["license"], r"^(CC0|CC BY(-SA)? [0-9.]+|Public domain)$")
                self.assertTrue(r["modifications"])
                self.assertIn(r["set"], ("tuning", "held-out"))

    def test_photos_are_small(self):
        from PIL import Image

        total = 0
        for name in os.listdir(SIGNS):
            if name.lower().endswith(".jpg"):
                path = os.path.join(SIGNS, name)
                total += os.path.getsize(path)
                with Image.open(path) as im:
                    self.assertLessEqual(max(im.size), 800, name)
        self.assertLess(total, 3_000_000)


def _wheel(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class WheelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.payload = {"pkg/models/a.onnx": b"model a", "pkg/models/b.onnx": b"model b", "../evil.onnx": b"x", "pkg/other.py": b"x"}
        self.models = tuple(
            place_models.WheelModel(os.path.basename(m), m, hashlib.sha256(d).hexdigest(), len(d))
            for m, d in self.payload.items()
            if m.startswith("pkg/models/")
        )

    def patched(self, wheel_bytes, sha=None):
        wheel = place_models.WheelFile("https://example.invalid/p.whl", sha or hashlib.sha256(wheel_bytes).hexdigest(), len(wheel_bytes))
        return mock.patch.multiple(place_models, WHEEL=wheel, MODELS=self.models)

    def test_extracts_only_the_named_models_and_checks_them(self):
        data = _wheel(self.payload)
        calls = []

        def opener(url, timeout):
            calls.append(url)
            return FakeResponse(data)

        with self.patched(data):
            self.assertTrue(download_models.ensure_ocr_models(self.tmp.name, log=lambda *_: None, opener=opener))
            self.assertTrue(download_models.ensure_ocr_models(self.tmp.name, log=lambda *_: None, opener=opener))
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["a.onnx", "b.onnx"])
        self.assertEqual(len(calls), 1, "second run uses the local files")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp.name), "evil.onnx")))

    def test_wrong_wheel_checksum_leaves_nothing(self):
        data = _wheel(self.payload)
        with self.patched(data, sha="0" * 64):
            ok = download_models.ensure_ocr_models(self.tmp.name, log=lambda *_: None, opener=lambda u, timeout: FakeResponse(data))
        self.assertFalse(ok)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_wrong_model_checksum_leaves_no_partial_file(self):
        bad = dict(self.payload)
        bad["pkg/models/b.onnx"] = b"MODEL B"  # same size, other content
        data = _wheel(bad)
        with self.patched(data):
            ok = download_models.ensure_ocr_models(self.tmp.name, log=lambda *_: None, opener=lambda u, timeout: FakeResponse(data))
        self.assertFalse(ok)
        self.assertEqual(os.listdir(self.tmp.name), ["a.onnx"])


def _models_ready():
    return not place_models.missing_models(place_models.model_dir())


@unittest.skipUnless(_models_ready(), "OCR models not downloaded (python launcher/download_models.py)")
class RealSignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from travelphotos.places.ocr import load_engine

        cls.engine = load_engine()
        with open(os.path.join(SIGNS, "labels.json"), encoding="utf-8") as fh:
            cls.labels = json.load(fh)

    def test_real_sign_photos_hit_rate_without_false_matches(self):
        before = snapshot(SIGNS)
        tuning = [r for r in self.labels if r["set"] == "tuning"]
        with no_network():
            result = benchmark.run(SIGNS, tuning, benchmark.ITINERARY, self.engine)
        self.assertGreaterEqual(result["hits"], 8, [(r["file"], r["got"], r["lines"][:4]) for r in result["rows"]])
        self.assertEqual(result["wrong"], 0)
        self.assertEqual(result["false_positives"], 0)
        self.assertEqual(snapshot(SIGNS), before, "photos are only read")

    def test_held_out_photos_have_no_false_matches(self):
        held = [r for r in self.labels if r["set"] == "held-out"]
        if not held:
            self.skipTest("no held-out photos")
        result = benchmark.run(SIGNS, held, benchmark.ITINERARY, self.engine)
        self.assertEqual(result["wrong"], 0)
        self.assertEqual(result["false_positives"], 0)

    def test_turned_photos_are_still_read(self):
        from travelphotos.faces import media

        stops = parse_itinerary(benchmark.ITINERARY)
        for name, expected in (("sign02.jpg", "伏見稻荷大社"), ("sign16.jpg", "清水寺"), ("sign25.jpg", "京都車站")):
            rgb = media.load_photo(os.path.join(SIGNS, name), 1600)
            for turns in (1, 2, 3):  # 90° counter-clockwise, 180°, 90° clockwise
                with self.subTest(photo=name, turns=turns):
                    lines = self.engine.read_text(np.ascontiguousarray(np.rot90(rgb, turns)))
                    self.assertEqual(benchmark.decide(lines, stops), expected, lines[:6])

    def test_vertical_writing_is_read(self):
        from travelphotos.faces import media

        rgb = media.load_photo(os.path.join(SIGNS, "sign07.jpg"), 1600)  # stone pillar, written top to bottom
        stops = parse_itinerary(benchmark.ITINERARY)
        self.assertEqual(benchmark.decide(self.engine.read_text(rgb), stops), "伏見稻荷大社")


if __name__ == "__main__":
    unittest.main()
