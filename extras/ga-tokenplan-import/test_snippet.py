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


class CallbackServerSecurityTests(unittest.TestCase):
    """34134 写入面收口：GET 永不写入；POST 凭 Origin 白名单。"""

    @classmethod
    def setUpClass(cls):
        import ga_tokenplan_import.subscription_portal as sp
        cls.sp = sp
        cls.base = sp.ensure_callback_server(port=0)  # port=0 → 随机可用端口，避免占用冲突
        cls.url = f"http://127.0.0.1:{sp.PORT}/"

    @classmethod
    def tearDownClass(cls):
        cls.sp.stop_callback_server()

    def setUp(self):
        self.root = Path(os.environ["GA_ROOT"])
        self.mykey = self.root / "mykey.py"
        self.mykey.write_text("# mykey.py\nfoo = 1\n", encoding="utf-8")

    def _req(self, method, url, data=None, headers=None):
        import json as _json
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        req = Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, _json.loads(r.read().decode())
        except HTTPError as e:
            return e.code, _json.loads(e.read().decode())

    def test_get_never_writes(self):
        code, body = self._req("GET", self.url + "?snippet=evil%3D1")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["version"], self.sp.PLUGIN_VERSION)
        self.assertNotIn("evil", self.mykey.read_text(encoding="utf-8"))

    def test_post_without_origin_writes(self):
        code, body = self._req("POST", self.url, data=b"snippet=ok_local%3D1",
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertIn("ok_local", self.mykey.read_text(encoding="utf-8"))

    def test_post_with_evil_origin_forbidden(self):
        code, body = self._req("POST", self.url, data=b"snippet=evil2%3D1",
                               headers={"Content-Type": "application/x-www-form-urlencoded",
                                        "Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual(body["error"], "origin_forbidden")
        self.assertNotIn("evil2", self.mykey.read_text(encoding="utf-8"))

    def test_post_with_portal_origin_allowed(self):
        code, body = self._req("POST", self.url, data=b"snippet=ok_portal%3D1",
                               headers={"Content-Type": "application/x-www-form-urlencoded",
                                        "Origin": "https://plan.khrey.com"})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertIn("ok_portal", self.mykey.read_text(encoding="utf-8"))


class RootTests(unittest.TestCase):
    def test_extras_layout_resolves_running_tree(self):
        from ga_tokenplan_import.subscription_portal import _ga_root
        extras_root = Path(__file__).resolve().parents[2]
        self.assertTrue((extras_root / "agentmain.py").is_file())
        saved = {k: os.environ.pop(k, None) for k in ("GA_ROOT", "GENERICAGENT_ROOT")}
        try:
            self.assertEqual(_ga_root(), extras_root)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
