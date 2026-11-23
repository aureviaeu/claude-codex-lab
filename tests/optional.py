"""Tests that need an optional environment: a browser, the real models.

On a computer without that environment these tests are skipped, so
`scripts/test.sh` still passes there. CI installs the environment and sets
TRAVELPHOTOS_REQUIRE_ALL_TESTS=1: then a missing environment fails the run
instead of skipping, so a broken install cannot turn the run green with the
browser or model tests left out. See docs/decisions/0012-full-tests-in-ci.md.
"""

from __future__ import annotations

import os
import unittest

ENV_REQUIRE_ALL = "TRAVELPHOTOS_REQUIRE_ALL_TESTS"


def require_all() -> bool:
    return os.environ.get(ENV_REQUIRE_ALL, "") == "1"


def needs(available, reason: str):
    """Class decorator: skip without the environment, fail in a require-all run."""
    if available or not require_all():
        return unittest.skipUnless(available, reason)

    def fail_instead(cls):
        def setUpClass(klass):
            raise AssertionError(f"{ENV_REQUIRE_ALL}=1 but this environment is missing: {reason}")

        cls.setUpClass = classmethod(setUpClass)
        return cls

    return fail_instead


def skip_or_fail(test: unittest.TestCase, reason: str) -> None:
    """In a test body: skip without the environment, fail in a require-all run."""
    if require_all():
        test.fail(f"{ENV_REQUIRE_ALL}=1 but this environment is missing: {reason}")
    test.skipTest(reason)
