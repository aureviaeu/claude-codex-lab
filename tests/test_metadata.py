import os
import struct
import tempfile
import unittest
from datetime import datetime, timezone

from travelphotos import metadata
from tests.helpers import save_jpeg, save_mp4, save_png, scene


class ExifTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_jpeg_exif_datetime_original(self):
        path = save_jpeg(scene(1), os.path.join(self.dir, "a.jpg"), datetime(2024, 5, 3, 9, 15, 30))
        dt, source = metadata.embedded_datetime(path)
        self.assertEqual(dt, datetime(2024, 5, 3, 9, 15, 30))
        self.assertEqual(source, metadata.SOURCE_EXIF)

    def test_jpeg_without_exif(self):
        path = save_jpeg(scene(2), os.path.join(self.dir, "b.jpg"))
        self.assertEqual(metadata.embedded_datetime(path), (None, None))

    def test_png_without_exif(self):
        path = save_png(scene(3), os.path.join(self.dir, "c.png"))
        self.assertEqual(metadata.embedded_datetime(path), (None, None))

    def test_big_endian_tiff(self):
        stamp = b"2023:10:15 08:00:01\x00"
        # IFD0 with one ASCII DateTime entry pointing at offset 26.
        tiff = b"MM\x00*" + struct.pack(">I", 8) + struct.pack(">H", 1)
        tiff += struct.pack(">HHII", 0x0132, 2, len(stamp), 26) + struct.pack(">I", 0) + stamp
        self.assertEqual(metadata.parse_tiff_datetime(tiff), datetime(2023, 10, 15, 8, 0, 1))

    def test_garbage_is_ignored(self):
        self.assertIsNone(metadata.parse_tiff_datetime(b"not a tiff at all"))
        path = os.path.join(self.dir, "broken.jpg")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe1\x00")
        self.assertEqual(metadata.embedded_datetime(path), (None, None))

    def test_heic_exif_scan(self):
        stamp = b"2022:01:02 03:04:05\x00"
        tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
        tiff += struct.pack("<HHII", 0x0132, 2, len(stamp), 26) + struct.pack("<I", 0) + stamp
        path = os.path.join(self.dir, "x.heic")
        with open(path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100 + b"\x00\x00\x00\x06Exif\x00\x00" + tiff)
        self.assertEqual(metadata.embedded_datetime(path)[0], datetime(2022, 1, 2, 3, 4, 5))


class ContainerTests(unittest.TestCase):
    def test_mp4_mvhd_creation_time(self):
        with tempfile.TemporaryDirectory() as d:
            created = datetime(2024, 5, 3, 1, 0, 0, tzinfo=timezone.utc)
            path = save_mp4(os.path.join(d, "v.mp4"), created)
            dt, source = metadata.embedded_datetime(path)
            self.assertEqual(source, metadata.SOURCE_CONTAINER)
            self.assertEqual(dt, created.astimezone().replace(tzinfo=None))

    def test_mp4_zero_time_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            path = save_mp4(os.path.join(d, "v.mov"), None)
            self.assertEqual(metadata.embedded_datetime(path), (None, None))


class FilenameTests(unittest.TestCase):
    def test_patterns(self):
        cases = {
            "IMG_20231015_123456.jpg": datetime(2023, 10, 15, 12, 34, 56),
            "PXL_20231015_123456789.jpg": datetime(2023, 10, 15, 12, 34, 56, 789000),
            "2023-10-15 12.34.56.png": datetime(2023, 10, 15, 12, 34, 56),
            "Screenshot_2023-10-15-12-34-56.png": datetime(2023, 10, 15, 12, 34, 56),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(metadata.filename_datetime(name), expected)

    def test_epoch_milliseconds(self):
        expected = datetime.fromtimestamp(1697350000)
        self.assertEqual(metadata.filename_datetime("line_1697350000000.jpg"), expected)

    def test_no_time(self):
        for name in ("S__12345678.jpg", "IMG_0001.JPG", "20231399_999999.jpg", "photo.jpg"):
            with self.subTest(name=name):
                self.assertIsNone(metadata.filename_datetime(name))

    def test_media_kind(self):
        self.assertEqual(metadata.media_kind("a.JPG"), "photo")
        self.assertEqual(metadata.media_kind("a.heic"), "photo")
        self.assertEqual(metadata.media_kind("a.MOV"), "video")
        self.assertIsNone(metadata.media_kind("notes.txt"))


if __name__ == "__main__":
    unittest.main()
