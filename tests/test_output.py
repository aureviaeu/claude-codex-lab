import csv
import json
import os
import shutil
import socket
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from travelphotos import ordering, output
from travelphotos.itinerary import parse_itinerary
from travelphotos.scan import scan
from tests.helpers import save_jpeg, save_mp4, save_png, scene, snapshot


def read_report(out):
    with open(os.path.join(out, output.REPORT_CSV), encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inp = os.path.join(self.tmp.name, "trip")
        self.out = os.path.join(self.tmp.name, "trip-sorted")
        save_jpeg(scene(1), os.path.join(self.inp, "b.jpg"), datetime(2024, 5, 1, 10, 0))
        save_jpeg(scene(2), os.path.join(self.inp, "a.jpg"), datetime(2024, 5, 1, 9, 0))
        dup = save_jpeg(scene(3), os.path.join(self.inp, "S__123.jpg"))
        os.makedirs(os.path.join(self.inp, "saved again"))
        shutil.copyfile(dup, os.path.join(self.inp, "saved again", "S__123.jpg"))
        save_png(scene(4), os.path.join(self.inp, "shot.png"))
        save_mp4(os.path.join(self.inp, "clip.mp4"), None)
        # Make the file system times misleading on purpose.
        for i, name in enumerate(sorted(os.listdir(self.inp))):
            path = os.path.join(self.inp, name)
            os.utime(path, (1_700_000_000 - i * 1000, 1_700_000_000 - i * 1000))
        self.before = snapshot(self.inp)

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self, **kwargs):
        result = scan(self.inp)
        return result, output.apply(result, ordering.order(result.files, **kwargs), self.out)

    def test_end_to_end(self):
        result, summary = self.run_pipeline()

        # Originals: content and mtime unchanged.
        self.assertEqual(snapshot(self.inp), self.before)

        # Output count = input count - duplicates.
        media = sorted(n for n in os.listdir(self.out) if not n.startswith(".") and not n.startswith("report"))
        self.assertEqual(result.total_media, 6)
        self.assertEqual(len(media), 6 - 1)
        self.assertEqual(summary["written"], 5)
        self.assertEqual(summary["duplicates_skipped"], 1)

        # EXIF order and the numbered prefix.
        self.assertEqual(media[0], "0001_a.jpg")
        self.assertEqual(media[1], "0002_b.jpg")
        with open(os.path.join(self.inp, "a.jpg"), "rb") as src, open(os.path.join(self.out, "0001_a.jpg"), "rb") as dst:
            self.assertEqual(src.read(), dst.read())

        rows = read_report(self.out)
        ordered = [r for r in rows if r["新順序"]]
        skipped = [r for r in rows if not r["新順序"]]
        self.assertEqual(len(ordered), 5)
        self.assertEqual([r["新順序"] for r in ordered], ["1", "2", "3", "4", "5"])
        for r in ordered:
            self.assertIn(r["可信度"], ("高", "中", "低"))
            self.assertTrue(r["排序依據"])
            self.assertTrue(os.path.isfile(os.path.join(self.out, r["新檔名"])))
        self.assertEqual(ordered[0]["可信度"], "高")
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["原始檔案"], "saved again/S__123.jpg")
        self.assertIn("重複檔", skipped[0]["排序依據"])

        with open(os.path.join(self.out, output.REPORT_JSON), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["duplicates"], [{"file": "saved again/S__123.jpg", "duplicate_of": "S__123.jpg"}])

    def test_reapply_manual_order_renames(self):
        self.run_pipeline()
        _result, summary = self.run_pipeline(manual_order=["b.jpg", "a.jpg"])
        self.assertEqual(summary["renamed"], 5)
        self.assertEqual(summary["copied"], 0)
        names = sorted(n for n in os.listdir(self.out) if n[:4].isdigit())
        self.assertEqual(names[:2], ["0001_b.jpg", "0002_a.jpg"])
        self.assertEqual(len(names), 5)
        self.assertEqual(read_report(self.out)[0]["手動調整"], "是")
        self.assertEqual(snapshot(self.inp), self.before)

    def test_itinerary_order_in_output(self):
        stops = parse_itinerary("小樽 → 札幌")
        self.run_pipeline(stops=stops, assignments={"b.jpg": 1, "a.jpg": 2})
        names = sorted(n for n in os.listdir(self.out) if n[:4].isdigit())
        self.assertEqual(names[:2], ["0001_b.jpg", "0002_a.jpg"])
        rows = read_report(self.out)
        self.assertEqual(rows[0]["行程站點"], "1. 小樽")
        self.assertEqual(rows[2]["行程站點"], "未對應")

    def test_refuses_output_inside_input(self):
        result = scan(self.inp)
        res = ordering.order(result.files)
        for bad in (self.inp, os.path.join(self.inp, "out"), self.tmp.name):
            with self.subTest(bad=bad), self.assertRaises(output.OutputError):
                output.apply(result, res, bad)
        self.assertEqual(snapshot(self.inp), self.before)

    def test_refuses_non_empty_foreign_folder(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "mine.txt"), "w") as fh:
            fh.write("keep me")
        result = scan(self.inp)
        with self.assertRaises(output.OutputError):
            output.apply(result, ordering.order(result.files), self.out)
        self.assertEqual(os.listdir(self.out), ["mine.txt"])

    def test_works_without_network(self):
        real_connect = socket.socket.connect

        def guarded(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1", "localhost"):
                raise AssertionError(f"network access attempted: {address}")
            return real_connect(sock, address)

        with mock.patch.object(socket.socket, "connect", guarded), mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("network access attempted")
        ):
            _result, summary = self.run_pipeline()
        self.assertEqual(summary["written"], 5)


if __name__ == "__main__":
    unittest.main()
