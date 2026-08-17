#!/usr/bin/env python3
"""Local + remote probe for the TokenPlan import plugin (no HTTP server)."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import tokenplan_plugin  # noqa: E402


def _valid_manifest(**over):
    data = {
        "schema": 1,
        "component": tokenplan_plugin.COMPONENT,
        "version": "0.1.0",
        "url": "https://plan.khrey.com/releases/plugin/tokenplan-0.1.0.zip",
        "sha256": "a" * 64,
        "size": 1234,
        "install_path": "plugins/subscription_portal.py",
    }
    data.update(over)
    return data


class LocalProbeTests(unittest.TestCase):
    def test_this_tree_has_plugin(self):
        root = HERE.parent
        r = tokenplan_plugin.probe_local(root)
        self.assertTrue(r["installed"], r)
        self.assertTrue(r["available"], r)
        self.assertTrue(r["plugin_path"])
        self.assertTrue(r["extras_path"])
        self.assertIsNotNone(tokenplan_plugin.local_starter(root))

    def test_empty_tree_not_installed(self):
        with tempfile.TemporaryDirectory(prefix="ga-tp-probe-") as td:
            root = Path(td)
            (root / "plugins").mkdir()
            r = tokenplan_plugin.probe_local(root)
            self.assertFalse(r["installed"])
            self.assertFalse(r["available"])
            self.assertEqual(r["source"], None)
            self.assertTrue(r["error"])
            self.assertIsNone(tokenplan_plugin.local_starter(root))

    def test_extras_without_plugin_stub(self):
        with tempfile.TemporaryDirectory(prefix="ga-tp-probe-") as td:
            root = Path(td)
            extras = root / tokenplan_plugin.EXTRAS_FILE
            extras.parent.mkdir(parents=True)
            extras.write_text("# extras only\n", encoding="utf-8")
            r = tokenplan_plugin.probe_local(root)
            self.assertFalse(r["installed"])
            self.assertIn("extras present", r["error"])
            self.assertTrue(r["extras_path"])


class ManifestParseTests(unittest.TestCase):
    def test_valid(self):
        r = tokenplan_plugin.parse_manifest(_valid_manifest(), src="mem")
        self.assertTrue(r["ok"])
        self.assertTrue(r["available"])
        self.assertEqual(r["version"], "0.1.0")
        self.assertEqual(r["sha256"], "a" * 64)
        self.assertEqual(r["size"], 1234)

    def test_bad_sha_and_component(self):
        r = tokenplan_plugin.parse_manifest(
            _valid_manifest(sha256="zzz", component="other"), src="mem"
        )
        self.assertFalse(r["ok"])
        self.assertFalse(r["available"])
        self.assertIn("sha256", r["error"])
        self.assertIn("component", r["error"])

    def test_missing_url(self):
        r = tokenplan_plugin.parse_manifest(_valid_manifest(url=""), src="mem")
        self.assertFalse(r["available"])
        self.assertIn("url", r["error"])


class RemoteProbeTests(unittest.TestCase):
    def setUp(self):
        tokenplan_plugin.clear_remote_cache()
        self._old = os.environ.get("GA_TOKENPLAN_PLUGIN_PROBE_CACHE")
        os.environ["GA_TOKENPLAN_PLUGIN_PROBE_CACHE"] = "0"

    def tearDown(self):
        tokenplan_plugin.clear_remote_cache()
        if self._old is None:
            os.environ.pop("GA_TOKENPLAN_PLUGIN_PROBE_CACHE", None)
        else:
            os.environ["GA_TOKENPLAN_PLUGIN_PROBE_CACHE"] = self._old

    def test_fetch_ok(self):
        payload = json.dumps(_valid_manifest()).encode()

        class _R:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("tokenplan_plugin.urllib.request.urlopen", return_value=_R()):
            r = tokenplan_plugin.probe_remote("https://example.test/manifest.json")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["available"])
        self.assertEqual(r["version"], "0.1.0")

    def test_http_404(self):
        import urllib.error

        err = urllib.error.HTTPError(
            "https://example.test/manifest.json", 404, "Not Found", hdrs=None, fp=io.BytesIO()
        )
        with patch("tokenplan_plugin.urllib.request.urlopen", side_effect=err):
            r = tokenplan_plugin.probe_remote("https://example.test/manifest.json")
        self.assertFalse(r["ok"])
        self.assertFalse(r["available"])
        self.assertIn("404", r["error"])


class CombinedProbeTests(unittest.TestCase):
    def test_skip_remote(self):
        r = tokenplan_plugin.probe(HERE.parent, remote=False)
        self.assertTrue(r["available"])
        self.assertEqual(r["remote"]["error"], "skipped")
        self.assertFalse(r["remote"]["available"])


if __name__ == "__main__":
    unittest.main()
