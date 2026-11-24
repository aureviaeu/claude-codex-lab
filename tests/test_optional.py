"""The require-all switch (#31): in CI a missing browser or model fails the run."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.optional import ENV_REQUIRE_ALL, needs, skip_or_fail


def _run(case_class) -> unittest.TestResult:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case_class)
    result = unittest.TestResult()
    suite.run(result)
    return result


def _make(available):
    class Case(unittest.TestCase):
        def test_something(self):
            pass

    return needs(available, "thing missing")(Case)


def _make_inline():
    class Case(unittest.TestCase):
        def test_something(self):
            skip_or_fail(self, "thing missing")

    return Case


class RequireAllTests(unittest.TestCase):
    def test_missing_environment_is_skipped_by_default(self):
        with mock.patch.dict(os.environ, {ENV_REQUIRE_ALL: ""}):
            for case in (_make(False), _make_inline()):
                result = _run(case)
                self.assertEqual(len(result.skipped), 1)
                self.assertTrue(result.wasSuccessful())

    def test_missing_environment_fails_when_all_tests_are_required(self):
        with mock.patch.dict(os.environ, {ENV_REQUIRE_ALL: "1"}):
            for case in (_make(False), _make_inline()):
                result = _run(case)
                self.assertEqual(result.skipped, [])
                self.assertFalse(result.wasSuccessful())
                problems = result.errors + result.failures
                self.assertIn("thing missing", problems[0][1])

    def test_present_environment_runs_either_way(self):
        for value in ("", "1"):
            with mock.patch.dict(os.environ, {ENV_REQUIRE_ALL: value}):
                result = _run(_make(True))
                self.assertEqual((result.testsRun, result.skipped), (1, []))
                self.assertTrue(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
