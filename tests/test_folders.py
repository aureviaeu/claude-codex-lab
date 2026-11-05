import json
import os
import re
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import quote

from travelphotos import folders
from travelphotos import server as srv
from tests import test_server


class FolderModuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "Beta"))
        os.makedirs(os.path.join(self.root, "alpha", "inner"))
        os.makedirs(os.path.join(self.root, ".hidden"))
        with open(os.path.join(self.root, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("file contents must never be returned")

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_only_visible_folders_sorted(self):
        listing = folders.list_folders(self.root)
        self.assertEqual(listing["path"], os.path.abspath(self.root))
        self.assertEqual([f["name"] for f in listing["folders"]], ["alpha", "Beta"])
        self.assertEqual(listing["folders"][0]["path"], os.path.join(os.path.abspath(self.root), "alpha"))
        self.assertEqual(listing["parent"], os.path.dirname(os.path.abspath(self.root)))

    def test_empty_path_is_home(self):
        with mock.patch.dict(os.environ, {"HOME": self.root, "USERPROFILE": self.root}):
            listing = folders.list_folders("")
        self.assertEqual(listing["path"], os.path.abspath(self.root))
        self.assertEqual(listing["home"], os.path.abspath(self.root))

    def test_root_has_no_parent(self):
        root = os.path.abspath(os.sep)
        self.assertIsNone(folders.list_folders(root)["parent"])

    def test_missing_and_file_paths(self):
        with self.assertRaisesRegex(folders.FolderError, "找不到資料夾"):
            folders.list_folders(os.path.join(self.root, "missing"))
        with self.assertRaisesRegex(folders.FolderError, "不是資料夾"):
            folders.list_folders(os.path.join(self.root, "secret.txt"))

    def test_permission_denied_is_a_readable_error(self):
        target = os.path.join(self.root, "alpha")
        with mock.patch("travelphotos.folders.os.scandir", side_effect=PermissionError(13, "denied")):
            with self.assertRaisesRegex(folders.FolderError, "沒有權限讀取"):
                folders.list_folders(target)

    def test_make_folder(self):
        listing = folders.make_folder(self.root, "  2024 北海道-排序 ")
        created = os.path.join(os.path.abspath(self.root), "2024 北海道-排序")
        self.assertTrue(os.path.isdir(created))
        self.assertEqual(listing["path"], created)
        self.assertEqual(listing["folders"], [])
        with self.assertRaisesRegex(folders.FolderError, "同名"):
            folders.make_folder(self.root, "alpha")

    def test_make_folder_rejects_bad_names(self):
        for name in ["", "  ", ".", "..", "a/b", "a\\b", "../escape", "x:y", "trail."]:
            with self.assertRaises(folders.FolderError, msg=name):
                folders.make_folder(self.root, name)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root), "escape")))
        self.assertEqual(sorted(os.listdir(self.root)), [".hidden", "Beta", "alpha", "secret.txt"])


class FolderApiTests(unittest.TestCase):
    request = classmethod(test_server.ServerTests.request.__func__)  # same HTTP helper

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        os.makedirs(os.path.join(cls.root, "trip"))
        with open(os.path.join(cls.root, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("TOPSECRET-CONTENT")
        cls.server, cls.url, cls.state = srv.create_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        page = cls.request("GET", "/")[2].decode("utf-8")
        cls.token = re.search(r'name="token" content="([^"]+)"', page).group(1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def list_path(self):
        return "/api/folders?path=" + quote(self.root)

    def test_requires_token(self):
        self.assertEqual(self.request("GET", self.list_path())[0], 403)
        self.assertEqual(self.request("GET", self.list_path(), token="wrong")[0], 403)
        status, _h, _d = self.request("POST", "/api/mkdir", {"parent": self.root, "name": "x"})
        self.assertEqual(status, 403)
        status, _h, _d = self.request("POST", "/api/mkdir", {"parent": self.root, "name": "x"}, token="wrong")
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(os.path.join(self.root, "x")))

    def test_rejects_foreign_host(self):
        status, _h, _d = self.request("GET", self.list_path(), token=self.token, host=f"evil.example:{self.port}")
        self.assertEqual(status, 403)
        status, _h, _d = self.request(
            "POST", "/api/mkdir", {"parent": self.root, "name": "y"}, token=self.token, host="evil.example"
        )
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(os.path.join(self.root, "y")))

    def test_returns_folders_only(self):
        status, _h, raw = self.request("GET", self.list_path(), token=self.token)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual(set(data), {"path", "parent", "home", "roots", "folders"})
        self.assertIn({"name": "trip", "path": os.path.join(self.root, "trip")}, data["folders"])
        for entry in data["folders"]:
            self.assertEqual(set(entry), {"name", "path"})
            self.assertTrue(os.path.isdir(entry["path"]))
        self.assertNotIn(b"secret.txt", raw)
        self.assertNotIn(b"TOPSECRET", raw)

    def test_errors_are_400_with_message(self):
        status, _h, raw = self.request("GET", "/api/folders?path=" + quote(os.path.join(self.root, "nope")), token=self.token)
        self.assertEqual(status, 400)
        self.assertIn("找不到資料夾", json.loads(raw)["error"])
        with mock.patch("travelphotos.folders.os.scandir", side_effect=PermissionError(13, "denied")):
            status, _h, raw = self.request("GET", self.list_path(), token=self.token)
        self.assertEqual(status, 400)
        self.assertIn("沒有權限", json.loads(raw)["error"])

    def test_mkdir(self):
        status, _h, raw = self.request("POST", "/api/mkdir", {"parent": self.root, "name": "out"}, token=self.token)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["path"], os.path.join(self.root, "out"))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "out")))
        status, _h, raw = self.request("POST", "/api/mkdir", {"parent": self.root, "name": "../out2"}, token=self.token)
        self.assertEqual(status, 400)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root), "out2")))


if __name__ == "__main__":
    unittest.main()
