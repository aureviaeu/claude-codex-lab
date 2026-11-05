"""Tests for the one-click launcher (docs/decisions/0007-one-click-launcher.md)."""

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("bootstrap", os.path.join(ROOT, "launcher", "bootstrap.py"))
bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap)


def _has_ensurepip() -> bool:
    return importlib.util.find_spec("ensurepip") is not None


class StampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.venv = os.path.join(self.tmp.name, ".venv")
        os.makedirs(self.venv)
        self.req = os.path.join(self.tmp.name, "requirements.txt")
        with open(self.req, "w", encoding="utf-8") as fh:
            fh.write("Pillow>=10\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write_stamp(self, value):
        with open(os.path.join(self.venv, bootstrap.STAMP_NAME), "w", encoding="utf-8") as fh:
            fh.write(value + "\n")

    def test_install_needed_until_stamp_matches(self):
        self.assertTrue(bootstrap.needs_install(self.venv, self.req))
        self.write_stamp(bootstrap.requirements_digest(self.req))
        self.assertFalse(bootstrap.needs_install(self.venv, self.req))

    def test_changed_requirements_trigger_install(self):
        self.write_stamp(bootstrap.requirements_digest(self.req))
        with open(self.req, "a", encoding="utf-8") as fh:
            fh.write("something-new\n")
        self.assertTrue(bootstrap.needs_install(self.venv, self.req))

    def test_venv_python_path(self):
        expected = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
        self.assertEqual(bootstrap.venv_python(self.venv), os.path.join(self.venv, *expected))

    def test_old_python_is_refused_with_message(self):
        with mock.patch.object(bootstrap.sys, "version_info", (3, 9, 18)), mock.patch.object(
            bootstrap, "ensure_env"
        ) as ensure, mock.patch("sys.stderr") as err:
            self.assertEqual(bootstrap.main(["--prepare-only"]), 2)
        ensure.assert_not_called()
        text = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertIn("3.10", text)
        self.assertIn("python.org", text)

    def test_pip_failure_is_reported(self):
        with mock.patch.object(bootstrap, "_env_usable", return_value=True), mock.patch.object(
            bootstrap.subprocess, "call", return_value=1
        ):
            with self.assertRaises(bootstrap.LaunchError) as ctx:
                bootstrap.ensure_env(self.tmp.name, log=lambda *_: None)
        self.assertIn("網路", str(ctx.exception))
        self.assertTrue(bootstrap.needs_install(self.venv, self.req))


@unittest.skipUnless(_has_ensurepip(), "this Python has no ensurepip, so it cannot create environments")
class FreshEnvironmentTests(unittest.TestCase):
    """Simulates a clean computer: an empty project folder with no .venv yet."""

    def test_first_run_installs_second_run_does_not(self):
        with tempfile.TemporaryDirectory() as root:
            # No packages to download, so the test works offline.
            with open(os.path.join(root, "requirements.txt"), "w", encoding="utf-8") as fh:
                fh.write("# nothing\n")
            logs = []
            python = bootstrap.ensure_env(root, log=logs.append)
            self.assertTrue(os.path.isfile(python))
            self.assertTrue(python.startswith(os.path.join(root, ".venv")))
            self.assertTrue(any("建立執行環境" in m for m in logs))
            self.assertTrue(any("安裝" in m for m in logs))
            self.assertFalse(bootstrap.needs_install(os.path.join(root, ".venv"), os.path.join(root, "requirements.txt")))

            logs.clear()
            real_call = subprocess.call
            calls = []

            def spy(cmd, *a, **k):
                calls.append(cmd)
                return real_call(cmd, *a, **k)

            with mock.patch.object(bootstrap.subprocess, "call", side_effect=spy):
                self.assertEqual(bootstrap.ensure_env(root, log=logs.append), python)
            self.assertEqual(calls, [], "second run must not run pip install")
            self.assertEqual(logs, ["套件已安裝，直接啟動。"])


@unittest.skipIf(os.name == "nt", "POSIX start script")
class StartScriptTests(unittest.TestCase):
    """Runs start.sh with a controlled PATH to check how it finds Python."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_python(self, name, script):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n" + script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def run_start(self, *args):
        env = {"PATH": self.bin, "TRAVELPHOTOS_IN_TERMINAL": "1"}
        return subprocess.run(
            ["/bin/sh", os.path.join(ROOT, "start.sh"), *args],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_no_python_shows_chinese_help(self):
        done = self.run_start()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("找不到 Python 3.10 以上版本", done.stdout)
        self.assertIn("python.org", done.stdout)

    def test_old_python_shows_chinese_help(self):
        # Behaves like Python 3.9: the version check exits with 1.
        self.fake_python("python3", "exit 1\n")
        done = self.run_start()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("找不到 Python 3.10 以上版本", done.stdout)

    def test_good_python_runs_bootstrap(self):
        log = os.path.join(self.tmp.name, "args")
        self.fake_python("python3", f'if [ "$1" = "-c" ]; then exit 0; fi\necho "$@" > "{log}"\n')
        done = self.run_start("--port", "0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(log, encoding="utf-8") as fh:
            self.assertEqual(fh.read().split(), ["launcher/bootstrap.py", "--port", "0"])

    def test_start_files_are_executable(self):
        for name in ("start.sh", "start.command"):
            self.assertTrue(os.access(os.path.join(ROOT, name), os.X_OK), name)


class LauncherFilesTests(unittest.TestCase):
    def test_venv_is_ignored(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn(".venv/", fh.read().split())

    def test_windows_launcher_checks_version_and_uses_bootstrap(self):
        with open(os.path.join(ROOT, "start.bat"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("(3, 10)", text)
        self.assertIn(r"launcher\bootstrap.py", text)
        self.assertIn("找不到 Python 3.10 以上版本", text)

    def test_bootstrap_does_not_touch_global_packages(self):
        with open(os.path.join(ROOT, "launcher", "bootstrap.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("--user", text)
        self.assertNotIn("sys.executable, \"-m\", \"pip\"", text)
        # pip always runs with the private environment's interpreter
        self.assertIn('[python, "-m", "pip", "install"', text)

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_bat_uses_crlf_in_checkouts(self):
        done = subprocess.run(
            ["git", "check-attr", "eol", "start.bat"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertIn("eol: crlf", done.stdout)


if __name__ == "__main__":
    unittest.main()
