"""Optional GenericAgent plugin: TokenPlan key import (127.0.0.1:34134).

Drop this file into `$GA_ROOT/plugins/subscription_portal.py` (or `ga-tokenplan-import
install`). Open-source GenericAgent has no such file; desktop/stapp probe
`getattr(agentmain, "start_subscription_portal", None)` and hide the entry.
"""
from __future__ import annotations

import json, os, re, sys, threading, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

INVITE_CODE = "ljq"
PORTAL_URL = "https://tokenplan.gaagent.ai"
HOST, PORT = "127.0.0.1", 34134
BEGIN, END = "########### <TOKENPLAN>", "########### </TOKENPLAN>"
_RE = re.compile(r"###########\s*<TOKENPLAN>\s*\n.*?###########\s*</TOKENPLAN>\s*\n?", re.S)
_lock, _httpd, _last = threading.Lock(), None, None


def _ga_root() -> Path:
    for envk in ("GA_ROOT", "GENERICAGENT_ROOT"):
        v = os.environ.get(envk)
        if v:
            return Path(v).expanduser().resolve()
    here = Path(__file__).resolve()
    if here.parent.name == "plugins":
        return here.parent.parent
    return Path.home() / "GA" / "GenericAgent"


def is_available():
    return True


def get_last_result():
    return _last


def callback_base_url():
    return f"http://{HOST}:{PORT}"


def _mykey_write_targets():
    """App 包内 mykey + 本机常见开发树 mykey（双写，避免 TUI/源码树看不到导入）。"""
    out, seen = [], set()

    def add(p):
        try:
            p = Path(p).expanduser().resolve()
        except Exception:
            return
        if p in seen:
            return
        seen.add(p)
        out.append(p)

    add(_ga_root() / "mykey.py")
    for envk in ("GA_MYKEY_PATH", "GENERICAGENT_MYKEY"):
        if os.environ.get(envk):
            add(os.environ[envk])
    # 默认双写本机开发树；测试/单目标安装设 GA_TOKENPLAN_IMPORT_DUAL=0
    if os.environ.get("GA_TOKENPLAN_IMPORT_DUAL", "1") != "0":
        for p in (Path.home() / "GA" / "GenericAgent" / "mykey.py", Path.home() / "GenericAgent" / "mykey.py"):
            if p.exists():
                add(p)
    return out


def apply_tokenplan_snippet(snippet: str) -> dict:
    s = (snippet or "").replace("\r\n", "\n").strip()
    if not s:
        raise ValueError("empty snippet")
    # 仅按 marker 判断是否已包区；变量名含 TOKENPLAN 子串不再误判
    if BEGIN not in s:
        s = f"{BEGIN}\n{s}\n{END}"
    if not s.endswith("\n"):
        s += "\n"
    written, modes = [], []
    for p in _mykey_write_targets():
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# mykey.py\n", encoding="utf-8")
        t = p.read_text(encoding="utf-8")
        t2, mode = (_RE.sub(s, t, 1), "replace") if _RE.search(t) else (s + t, "prepend")
        p.write_text(t2, encoding="utf-8")
        written.append(str(p))
        modes.append(mode)
    try:
        sys.modules.pop("mykey", None)
        import llmcore
        llmcore._mykey_mtime = None  # type: ignore
    except Exception:
        pass
    return {"ok": True, "path": written[0] if written else "", "paths": written, "mode": modes[0] if modes else "", "modes": modes}


def apply_profile_to_mykey(*, snippet="", **_):
    """仅接受服务端 TOKENPLAN snippet；无 key-only 兜底。"""
    if not (snippet or "").strip():
        raise ValueError("need snippet")
    return apply_tokenplan_snippet(snippet)


def _v(d, *ks):
    for k in ks:
        x = d.get(k, "")
        x = x[0] if isinstance(x, list) and x else x
        if x:
            return x
    return ""


class _H(BaseHTTPRequestHandler):
    def log_message(self, f, *a):
        sys.stderr.write(f"[sp] {f % a}\n")

    def _cors(self):
        for k, v in (
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type"),
        ):
            self.send_header(k, v)

    def _j(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self._cors()
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        if "json" in (self.headers.get("Content-Type") or "").lower():
            try:
                return json.loads(raw.decode() or "{}")
            except Exception:
                return {}
        return {k: (v[0] if v else "") for k, v in parse_qs(raw.decode(), keep_blank_values=True).items()}

    def _apply(self, d):
        global _last
        try:
            _last = apply_profile_to_mykey(snippet=_v(d, "snippet", "block"))
            self._j(200, _last)
        except Exception as e:
            _last = {"ok": False, "error": str(e)}
            self._j(400, _last)

    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items() if v}
        (self._apply(q) if any(q.get(k) for k in ("snippet", "block")) else self._j(200, {"ok": True, "port": PORT}))

    def do_POST(self):
        d = self._body()
        for k, v in parse_qs(urlparse(self.path).query).items():
            d.setdefault(k, v[0] if v else "")
        self._apply(d)


def ensure_callback_server(port=None):
    global _httpd, PORT
    if port:
        PORT = int(port)
    with _lock:
        if _httpd:
            return callback_base_url()
        _httpd = HTTPServer((HOST, PORT), _H)
        threading.Thread(target=_httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
        return callback_base_url()


def stop_callback_server():
    global _httpd
    with _lock:
        if _httpd:
            try:
                _httpd.shutdown()
                _httpd.server_close()
            except Exception:
                pass
            _httpd = None


def start_subscription_portal(*, open_browser=True, nonce=None, extra_query=None, port=None):
    base = ensure_callback_server(port)
    nonce = nonce or uuid.uuid4().hex
    q = {"cb": nonce, "client": "ga"}
    if INVITE_CODE:
        q["invite"] = INVITE_CODE
    if extra_query:
        for k, v in extra_query.items():
            if v is not None:
                q[k] = str(v)
    url = f"{PORTAL_URL}{'&' if '?' in PORTAL_URL else '?'}{urlencode(q)}"
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            sys.stderr.write(f"[sp] browser: {e}\n")
    return {"ok": True, "portal_url": url, "callback_url": base + "/", "nonce": nonce, "port": PORT}


start = start_subscription_portal

# 前端探测点：有插件才有此属性（开源包无文件则无入口）
try:
    import agentmain
    agentmain.start_subscription_portal = start_subscription_portal
except Exception:
    pass
