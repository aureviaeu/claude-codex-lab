"""Static checks on the page's CSS and JS (#12).

These run without a browser too, so they guard the fix for the photo-folder picker showing
「在這裡建立資料夾」: an author `display` rule on `.picker-new` beat the
`hidden` attribute that app.js sets for the photo-folder picker.
"""

import os
import re
import unittest

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "travelphotos", "static")


def _read(name: str) -> str:
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


class HiddenAttributeTests(unittest.TestCase):
    def test_hidden_attribute_beats_author_display_rules(self):
        css = re.sub(r"/\*.*?\*/", "", _read("style.css"), flags=re.S)
        rule = re.search(r"(?:^|[}\s])\[hidden\]\s*\{([^}]*)\}", css)
        self.assertIsNotNone(rule, "style.css needs a [hidden] rule")
        self.assertRegex(rule.group(1), r"display\s*:\s*none\s*!important")

    def test_create_folder_row_is_hidden_by_default_and_only_shown_for_output(self):
        html = _read("index.html")
        self.assertRegex(html, r'<div id="picker-new"[^>]*\bhidden\b')
        js = _read("app.js")
        self.assertIn('$("picker-new").hidden = !allowCreate;', js)
        self.assertIn('openPicker($("input-dir"), false)', js)
        self.assertIn('openPicker($("output-dir"), true)', js)


if __name__ == "__main__":
    unittest.main()
