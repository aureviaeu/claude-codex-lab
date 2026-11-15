"""#27: colour contrast of the page, light and dark, read from style.css.

WCAG 2.1 AA: normal text at least 4.5:1, non-text marks at least 3:1.
"""

from __future__ import annotations

import os
import re
import unittest

CSS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "travelphotos", "static", "style.css")


def _read():
    with open(CSS, encoding="utf-8") as fh:
        return fh.read()


def _vars(block: str) -> dict:
    return {k: v.lower() for k, v in re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,6})", block)}


def themes() -> dict:
    css = _read()
    light = _vars(re.search(r"^:root\s*\{(.*?)\}", css, re.S | re.M).group(1))
    dark_block = re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{(.*?)\}", css, re.S).group(1)
    return {"light": light, "dark": {**light, **_vars(dark_block)}}


def _rgb(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]


def _lum(h: str) -> float:
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in _rgb(h)]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def rules(selector_pattern: str) -> list[str]:
    """Bodies of CSS rules whose selector list matches the pattern."""
    css = re.sub(r"/\*.*?\*/", "", _read(), flags=re.S)
    return [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if re.search(selector_pattern, sel)]


class ContrastTests(unittest.TestCase):
    TEXT = ("text", "muted", "accent", "high", "medium", "low")  # text colours used on the page
    BACKGROUNDS = ("card", "bg")  # cards and the inner boxes (photo items, inputs)

    def test_text_on_every_background_both_themes(self):
        for name, t in themes().items():
            for fg in self.TEXT:
                for bg in self.BACKGROUNDS:
                    with self.subTest(theme=name, fg=fg, bg=bg):
                        self.assertGreaterEqual(contrast(t[fg], t[bg]), 4.5)

    def test_primary_button_text(self):
        t = themes()
        self.assertEqual(t["light"]["on-accent"], "#fff", "light mode keeps white text")
        self.assertAlmostEqual(contrast(t["light"]["on-accent"], t["light"]["accent"]), 5.17, places=2)
        for name, tt in t.items():
            with self.subTest(theme=name):
                self.assertGreaterEqual(contrast(tt["on-accent"], tt["accent"]), 4.5)

    def test_nothing_on_the_accent_uses_hard_coded_white(self):
        for body in rules(r"."):
            if re.search(r"background(-color)?:\s*var\(--accent\)", body):
                self.assertRegex(body, r"color:\s*var\(--on-accent\)", body)
                self.assertNotRegex(body, r"color:\s*(#fff\b|#ffffff\b|white\b)", body)

    def test_left_out_photos_keep_their_text_readable(self):
        bodies = rules(r"\.face-out")
        self.assertTrue(bodies)
        for sel_body in rules(r"\.item\.face-out\s*$") + rules(r"\.item\.face-out\s*,"):
            self.assertNotRegex(sel_body, r"\b(opacity|filter)\s*:", "the card and its text are not dimmed")
        for body in rules(r"face-out\s+(?!img)[^,]*$"):
            self.assertNotRegex(body, r"\b(opacity|filter)\s*:", "only the picture may be dimmed")
        self.assertTrue(rules(r"\.face-out\s+img\.thumb"), "the picture is dimmed instead")

    def test_left_out_photos_have_a_dashed_border_with_enough_contrast(self):
        body = " ".join(rules(r"\.item\.face-out\s*$"))
        self.assertRegex(body, r"border:\s*2px dashed var\(--low\)")
        for name, t in themes().items():
            with self.subTest(theme=name):
                self.assertGreaterEqual(contrast(t["low"], t["bg"]), 3.0)
                self.assertGreaterEqual(contrast(t["low"], t["card"]), 3.0)

    def test_left_out_photos_also_say_so_in_words(self):
        with open(os.path.join(os.path.dirname(CSS), "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("fb.textContent = `${f.face.label}：${f.face.reason}`", js)


if __name__ == "__main__":
    unittest.main()
