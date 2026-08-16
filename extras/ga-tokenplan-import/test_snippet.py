#!/usr/bin/env python3
"""Snippet replace/prepend without starting the HTTP server."""
from __future__ import annotations

import os, tempfile, unittest
from pathlib import Path

os.environ["GA_ROOT"] = tempfile.mkdtemp(prefix="ga-tp-import-")
os.environ["GA_TOKENPLAN_IMPORT_DUAL"] = "0"
os.environ.pop("GA_MYKEY_PATH", None)
os.environ.pop("GENERICAGENT_MYKEY", None)

from ga_tokenplan_import.subscription_portal import BEGIN, END, apply_tokenplan_snippet  # noqa: E402


class SnippetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ["GA_ROOT"])
        self.mykey = self.root / "mykey.py"
        self.mykey.write_text("# mykey.py\nfoo = 1\n", encoding="utf-8")

    def test_prepend_then_replace(self):
        r = apply_tokenplan_snippet("native_oai_config_GA_TOKENPLAN_auto = {'apikey': 'sk-a'}")
        self.assertTrue(r["ok"])
        t = self.mykey.read_text(encoding="utf-8")
        self.assertIn(BEGIN, t)
        self.assertIn("sk-a", t)
        self.assertIn("foo = 1", t)
        self.assertEqual(r["mode"], "prepend")

        r2 = apply_tokenplan_snippet(f"{BEGIN}\nnative_oai_config_GA_TOKENPLAN_auto = {{'apikey': 'sk-b'}}\n{END}\n")
        t2 = self.mykey.read_text(encoding="utf-8")
        self.assertEqual(r2["mode"], "replace")
        self.assertIn("sk-b", t2)
        self.assertNotIn("sk-a", t2)
        self.assertIn("foo = 1", t2)
        self.assertEqual(t2.count(BEGIN), 1)


if __name__ == "__main__":
    unittest.main()
