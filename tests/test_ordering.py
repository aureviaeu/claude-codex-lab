import os
import shutil
import tempfile
import unittest
from datetime import datetime

from travelphotos import ordering
from travelphotos.itinerary import parse_itinerary
from travelphotos.scan import scan
from tests.helpers import save_jpeg, save_mp4, scene, variant


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inp = os.path.join(self.tmp.name, "in")

    def tearDown(self):
        self.tmp.cleanup()

    def ids(self, result):
        return [p.file.id for p in result.placements]

    def test_exif_order(self):
        # Names are deliberately in the wrong order; EXIF must win.
        save_jpeg(scene(1), os.path.join(self.inp, "c.jpg"), datetime(2024, 5, 1, 9, 0))
        save_jpeg(scene(2), os.path.join(self.inp, "a.jpg"), datetime(2024, 5, 1, 15, 0))
        save_jpeg(scene(3), os.path.join(self.inp, "sub", "b.jpg"), datetime(2024, 5, 2, 8, 0))
        save_jpeg(scene(4), os.path.join(self.inp, "d.jpg"), datetime(2024, 4, 30, 20, 0))
        result = ordering.order(scan(self.inp).files)
        self.assertEqual(self.ids(result), ["d.jpg", "c.jpg", "a.jpg", "sub/b.jpg"])
        for p in result.placements:
            self.assertEqual(p.confidence, ordering.HIGH)
            self.assertIn("EXIF", p.basis)

    def test_filename_time_is_medium(self):
        save_jpeg(scene(1), os.path.join(self.inp, "IMG_20240501_100000.jpg"))
        save_jpeg(scene(2), os.path.join(self.inp, "x.jpg"), datetime(2024, 5, 1, 9, 0))
        result = ordering.order(scan(self.inp).files)
        self.assertEqual(self.ids(result), ["x.jpg", "IMG_20240501_100000.jpg"])
        self.assertEqual(result.placements[1].confidence, ordering.MEDIUM)
        self.assertIn("檔名", result.placements[1].basis)

    def test_untimed_photo_joins_similar_group(self):
        base = scene(10)
        save_jpeg(base, os.path.join(self.inp, "t1.jpg"), datetime(2024, 5, 1, 9, 0))
        save_jpeg(scene(11), os.path.join(self.inp, "t2.jpg"), datetime(2024, 5, 1, 13, 0))
        save_jpeg(variant(base, 1), os.path.join(self.inp, "zz_untimed.jpg"))
        save_jpeg(scene(12), os.path.join(self.inp, "lonely.jpg"))
        result = ordering.order(scan(self.inp).files)
        self.assertEqual(self.ids(result), ["t1.jpg", "zz_untimed.jpg", "t2.jpg", "lonely.jpg"])
        similar = result.placements[1]
        self.assertEqual(similar.confidence, ordering.MEDIUM)
        self.assertIn("t1.jpg", similar.basis)
        self.assertEqual(similar.group, result.placements[0].group)
        self.assertEqual(result.placements[3].confidence, ordering.LOW)

    def test_similar_group_keeps_capture_order_with_photo_between(self):
        # a and c look alike; b was taken between them. Capture times must win.
        base = scene(20)
        save_jpeg(base, os.path.join(self.inp, "a.jpg"), datetime(2024, 5, 1, 10, 0))
        save_jpeg(scene(21), os.path.join(self.inp, "b.jpg"), datetime(2024, 5, 1, 10, 15))
        save_jpeg(variant(base, 1), os.path.join(self.inp, "c.jpg"), datetime(2024, 5, 1, 10, 30))
        save_jpeg(scene(22), os.path.join(self.inp, "d.jpg"), datetime(2024, 5, 1, 15, 0))
        result = ordering.order(scan(self.inp).files)
        self.assertEqual(self.ids(result), ["a.jpg", "b.jpg", "c.jpg", "d.jpg"])
        for p in result.placements:
            self.assertEqual(p.confidence, ordering.HIGH)

    def test_videos_included(self):
        save_jpeg(scene(1), os.path.join(self.inp, "p.jpg"), datetime(2024, 5, 1, 12, 0))
        save_mp4(os.path.join(self.inp, "nodate.mp4"), None)
        result = ordering.order(scan(self.inp).files)
        self.assertEqual(sorted(self.ids(result)), ["nodate.mp4", "p.jpg"])

    def test_itinerary_order_wins_and_unmatched_last(self):
        stops = parse_itinerary("第1天：小樽運河 → 天狗山\n第2天：富良野")
        # Times say temple < garden < night, but the itinerary says otherwise.
        save_jpeg(scene(1), os.path.join(self.inp, "temple.jpg"), datetime(2024, 5, 1, 8, 0))
        save_jpeg(scene(2), os.path.join(self.inp, "garden.jpg"), datetime(2024, 5, 1, 11, 0))
        save_jpeg(scene(3), os.path.join(self.inp, "night.jpg"), datetime(2024, 5, 1, 20, 0))
        save_jpeg(scene(4), os.path.join(self.inp, "unknown.jpg"), datetime(2024, 4, 1, 7, 0))
        files = scan(self.inp).files
        assignments = {"temple.jpg": 3, "garden.jpg": 1, "night.jpg": 2}
        result = ordering.order(files, stops, assignments)
        self.assertEqual(self.ids(result), ["garden.jpg", "night.jpg", "temple.jpg", "unknown.jpg"])
        self.assertEqual(result.placements[0].stop.name, "小樽運河")
        self.assertIn("行程第 1 站", result.placements[0].basis)
        self.assertTrue(result.placements[3].unmatched)
        self.assertIn("未對應", result.placements[3].basis)

    def test_manual_order(self):
        for i in range(4):
            save_jpeg(scene(i), os.path.join(self.inp, f"{i}.jpg"), datetime(2024, 5, 1, 8 + i, 0))
        files = scan(self.inp).files
        result = ordering.order(files, manual_order=["3.jpg", "0.jpg", "1.jpg"])
        self.assertEqual(self.ids(result), ["3.jpg", "0.jpg", "1.jpg", "2.jpg"])
        self.assertEqual([p.manual for p in result.placements], [True, False, False, False])
        self.assertIn("手動調整", result.placements[0].basis)
        self.assertEqual([p.position for p in result.placements], [1, 2, 3, 4])

    def test_mtime_is_not_used(self):
        a = save_jpeg(scene(1), os.path.join(self.inp, "a.jpg"))
        b = save_jpeg(scene(2), os.path.join(self.inp, "b.jpg"))
        os.utime(a, (2_000_000_000, 2_000_000_000))
        os.utime(b, (1_000_000_000, 1_000_000_000))
        for p in ordering.order(scan(self.inp).files).placements:
            self.assertIsNone(p.estimated_time)
            self.assertEqual(p.confidence, ordering.LOW)


class DuplicateTests(unittest.TestCase):
    def test_exact_duplicates_detected(self):
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in")
            first = save_jpeg(scene(1), os.path.join(inp, "a.jpg"))
            os.makedirs(os.path.join(inp, "again"))
            shutil.copyfile(first, os.path.join(inp, "again", "a copy.jpg"))
            save_jpeg(scene(2), os.path.join(inp, "b.jpg"))
            with open(os.path.join(inp, "notes.txt"), "w") as fh:
                fh.write("not media")
            result = scan(inp)
            self.assertEqual([f.id for f in result.files], ["a.jpg", "b.jpg"])
            self.assertEqual(len(result.duplicates), 1)
            self.assertEqual(result.duplicates[0].file.id, "again/a copy.jpg")
            self.assertEqual(result.duplicates[0].duplicate_of, "a.jpg")
            self.assertEqual(result.skipped, ["notes.txt"])
            self.assertEqual(result.total_media, 3)


if __name__ == "__main__":
    unittest.main()
