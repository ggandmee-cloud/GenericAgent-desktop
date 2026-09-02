#!/usr/bin/env python3
"""Probe-first install of the TokenPlan plugin from a GAnet-style manifest."""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "frontends"))
sys.path.insert(0, str(ROOT / "extras" / "ga-tokenplan-import"))

from pack_release import build_release, plugin_version  # noqa: E402
import tokenplan_plugin as tp  # noqa: E402


STUB_PLUGIN = '''\
def start_subscription_portal(*, open_browser=True, **_):
    return {"ok": True, "stub": True, "open_browser": open_browser}

start_subscription_portal.__plugin_version__ = "9.9.9"

def apply_profile_to_mykey(*, snippet="", **_):
    return {"ok": True, "stub_apply": True, "snippet": snippet}

try:
    import agentmain
    agentmain.start_subscription_portal = start_subscription_portal
except Exception:
    pass
'''

# 无版本属性 = 存量旧插件（min_version 探测应拒绝并触发重装）
STUB_PLUGIN_LEGACY = '''\
def start_subscription_portal(*, open_browser=True, **_):
    return {"ok": True, "stub": True, "legacy": True}

try:
    import agentmain
    agentmain.start_subscription_portal = start_subscription_portal
except Exception:
    pass
'''


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def _serve(directory: Path):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: _Handler(*a, directory=str(directory), **k))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[:2]
    return httpd, f"http://{host}:{port}"


def _wipe_imports():
    for name in list(sys.modules):
        if (
            name in {"agentmain", "plugins", "plugins.subscription_portal", "plugins.hooks"}
            or name.startswith("ga_tokenplan_import")
        ):
            sys.modules.pop(name, None)


class TokenplanPluginTests(unittest.TestCase):
    def setUp(self):
        self._old_env = {k: os.environ.get(k) for k in (
            "GA_ROOT", "GENERICAGENT_ROOT", "GA_TOKENPLAN_PLUGIN_MANIFEST", "GA_OTA_FEED",
            "GA_MYKEY_PATH", "GENERICAGENT_MYKEY", "GA_TOKENPLAN_IMPORT_DUAL",
        )}
        self.td = Path(tempfile.mkdtemp(prefix="ga-tp-plugin-"))
        (self.td / "plugins").mkdir()
        (self.td / "plugins" / "__init__.py").write_text("#\n", encoding="utf-8")
        (self.td / "agentmain.py").write_text("# test agentmain\n", encoding="utf-8")
        os.environ["GA_ROOT"] = str(self.td)
        os.environ["GA_TOKENPLAN_IMPORT_DUAL"] = "0"
        os.environ.pop("GA_MYKEY_PATH", None)
        os.environ.pop("GENERICAGENT_MYKEY", None)
        os.environ.pop("GA_TOKENPLAN_PLUGIN_MANIFEST", None)
        os.environ.pop("GA_OTA_FEED", None)
        _wipe_imports()
        self._httpd = None

    def tearDown(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        _wipe_imports()
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil_rm = __import__("shutil").rmtree
        shutil_rm(self.td, ignore_errors=True)

    def _start_http(self, directory: Path) -> str:
        self._httpd, base = _serve(directory)
        return base

    def test_probe_miss_on_empty_root(self):
        self.assertIsNone(tp.probe_start(self.td))
        st = tp.probe_status(self.td)
        self.assertFalse(st["installed"])
        self.assertTrue(st["available"])
        self.assertIsNone(st["source"])

    def test_probe_plugin_file(self):
        (self.td / "plugins" / "subscription_portal.py").write_text(STUB_PLUGIN, encoding="utf-8")
        fn = tp.probe_start(self.td)
        self.assertTrue(callable(fn))
        self.assertEqual(tp.probe_source(self.td), "plugin")
        self.assertEqual(fn()["stub"], True)

    def test_probe_extras_without_plugin_file(self):
        extras = self.td / "extras" / "ga-tokenplan-import" / "ga_tokenplan_import"
        extras.mkdir(parents=True)
        (extras / "__init__.py").write_text("#\n", encoding="utf-8")
        (extras.parent / "__init__.py").write_text("#\n", encoding="utf-8")
        (extras / "subscription_portal.py").write_text(STUB_PLUGIN, encoding="utf-8")
        fn = tp.probe_start(self.td)
        self.assertTrue(callable(fn))
        self.assertEqual(tp.probe_source(self.td), "extras")

    def test_pack_and_install_from_manifest(self):
        packed = self.td / "packed"
        public = self._start_http(packed)
        man = build_release(packed, public)
        os.environ["GA_TOKENPLAN_PLUGIN_MANIFEST"] = f"{public}/plugin-manifest.json"
        dest = tp.install_from_manifest(self.td, man)
        self.assertTrue(dest.is_file())
        self.assertIn("start_subscription_portal", dest.read_text(encoding="utf-8"))
        fn = tp.probe_start(self.td)
        self.assertTrue(callable(fn))

    def test_ensure_probe_first_skips_download(self):
        (self.td / "plugins" / "subscription_portal.py").write_text(STUB_PLUGIN, encoding="utf-8")
        hits = {"n": 0}

        def boom(*_a, **_k):
            hits["n"] += 1
            raise AssertionError("should not fetch when probe hits")

        orig = tp.fetch_manifest
        tp.fetch_manifest = boom  # type: ignore
        try:
            fn = tp.ensure_start(self.td)
        finally:
            tp.fetch_manifest = orig
        self.assertEqual(hits["n"], 0)
        self.assertTrue(callable(fn))

    def test_probe_rejects_outdated_plugin(self):
        (self.td / "plugins" / "subscription_portal.py").write_text(STUB_PLUGIN_LEGACY, encoding="utf-8")
        # 无版本属性 = 旧版：默认探测按未安装处理，宽松探测仍可拿到
        self.assertIsNone(tp.probe_start(self.td))
        fn = tp.probe_start(self.td, min_version=False)
        self.assertTrue(callable(fn))
        st = tp.probe_status(self.td)
        self.assertFalse(st["installed"])

    def test_ensure_upgrades_outdated_plugin(self):
        (self.td / "plugins" / "subscription_portal.py").write_text(STUB_PLUGIN_LEGACY, encoding="utf-8")
        packed = self.td / "packed"
        public = self._start_http(packed)
        build_release(packed, public)
        os.environ["GA_TOKENPLAN_PLUGIN_MANIFEST"] = f"{public}/plugin-manifest.json"
        fn = tp.ensure_start(self.td)
        self.assertTrue(callable(fn))
        # 旧插件已被 manifest 里打包的真实插件覆盖（带版本号）
        text = (self.td / "plugins" / "subscription_portal.py").read_text(encoding="utf-8")
        self.assertIn("PLUGIN_VERSION", text)
        self.assertNotIn("legacy", text)

    def test_ensure_falls_back_to_outdated_when_reinstall_fails(self):
        (self.td / "plugins" / "subscription_portal.py").write_text(STUB_PLUGIN_LEGACY, encoding="utf-8")
        os.environ["GA_TOKENPLAN_PLUGIN_MANIFEST"] = "http://127.0.0.1:9/nope.json"  # 不可达
        fn = tp.ensure_start(self.td)
        self.assertTrue(callable(fn))
        self.assertEqual(fn()["legacy"], True)

    def test_ensure_apply_returns_writer(self):
        (self.td / "plugins" / "subscription_portal.py").write_text(STUB_PLUGIN, encoding="utf-8")
        apply_fn = tp.ensure_apply(self.td)
        self.assertTrue(callable(apply_fn))
        self.assertEqual(apply_fn(snippet="X")["stub_apply"], True)

    def test_ensure_downloads_on_miss(self):
        packed = self.td / "packed"
        public = self._start_http(packed)
        build_release(packed, public)
        os.environ["GA_TOKENPLAN_PLUGIN_MANIFEST"] = f"{public}/plugin-manifest.json"
        self.assertIsNone(tp.probe_start(self.td))
        fn = tp.ensure_start(self.td)
        self.assertTrue(callable(fn))
        self.assertTrue((self.td / "plugins" / "subscription_portal.py").is_file())

    def test_sha256_mismatch_rejected(self):
        packed = self.td / "packed"
        public = self._start_http(packed)
        man = build_release(packed, public)
        man["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "sha256"):
            tp.install_from_manifest(self.td, man)

    def test_size_mismatch_rejected(self):
        packed = self.td / "packed"
        public = self._start_http(packed)
        man = build_release(packed, public)
        man["size"] = man["size"] + 1
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            tp.install_from_manifest(self.td, man)

    def test_zip_slip_rejected(self):
        zpath = self.td / "evil.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("../subscription_portal.py", STUB_PLUGIN)
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            tp._extract_plugin_py(zpath)

    def test_feed_plugin_field_fallback(self):
        packed = self.td / "packed"
        public = self._start_http(packed)
        man = build_release(packed, public)
        feed = {
            "version": "0.0.0",
            "plugin": man,
        }
        (packed / "latest.json").write_text(json.dumps(feed), encoding="utf-8")
        os.environ["GA_TOKENPLAN_PLUGIN_MANIFEST"] = f"{public}/missing.json"
        os.environ["GA_OTA_FEED"] = f"{public}/latest.json"
        # dedicated URL 404s; fetch_manifest should still read plugin from the feed
        # because _manifest_urls uses env MANIFEST first then stops. Force empty env
        # and only feed:
        os.environ.pop("GA_TOKENPLAN_PLUGIN_MANIFEST")
        os.environ["GA_OTA_FEED"] = f"{public}/latest.json"
        # DEFAULT_MANIFEST will 404 on the real network or fail; patch urls
        orig = tp._manifest_urls
        tp._manifest_urls = lambda: [f"{public}/nope.json", f"{public}/latest.json"]  # type: ignore
        try:
            got = tp.fetch_manifest()
        finally:
            tp._manifest_urls = orig
        self.assertEqual(got["sha256"], man["sha256"])
        self.assertEqual(got["version"], plugin_version())

    def test_pack_sha_matches_file(self):
        packed = self.td / "packed"
        man = build_release(packed, "https://example.test/files")
        zpath = packed / f"ga-tokenplan-import-{man['version']}.zip"
        self.assertEqual(hashlib.sha256(zpath.read_bytes()).hexdigest(), man["sha256"])
        self.assertEqual(zpath.stat().st_size, man["size"])
        self.assertEqual(man["install_path"], "plugins/subscription_portal.py")
        self.assertEqual(man["component"], "ga-tokenplan-import")


if __name__ == "__main__":
    unittest.main()
