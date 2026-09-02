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

# 探测器(tokenplan_plugin)按此判断是否需要强制升级已装插件——安全修复必须递增。
# 与 pyproject.toml 的 version 保持一致（manifest 版本 == 模块版本）。
PLUGIN_VERSION = "1.1.0"

INVITE_CODE = os.environ.get("GA_TOKENPLAN_INVITE", "ljq")
PORTAL_URL = os.environ.get("GA_TOKENPLAN_URL", "https://plan.khrey.com/").rstrip("/") + "/"
HOST, PORT = "127.0.0.1", 34134
BEGIN, END = "########### <TOKENPLAN>", "########### </TOKENPLAN>"
_RE = re.compile(r"###########\s*<TOKENPLAN>\s*\n.*?###########\s*</TOKENPLAN>\s*\n?", re.S)
_lock, _httpd, _last = threading.Lock(), None, None


def _allowed_origins() -> set:
    """写入端 Origin 白名单：门户自身 + GA_TOKENPLAN_EXTRA_ORIGINS（逗号分隔）。"""
    out = set()
    try:
        p = urlparse(PORTAL_URL)
        if p.scheme and p.netloc:
            out.add(f"{p.scheme}://{p.netloc}")
    except Exception:
        pass
    out.add("https://plan.khrey.com")
    for o in (os.environ.get("GA_TOKENPLAN_EXTRA_ORIGINS") or "").split(","):
        o = o.strip().rstrip("/")
        if o:
            out.add(o)
    return out


def _ga_root() -> Path:
    for envk in ("GA_ROOT", "GENERICAGENT_ROOT"):
        v = os.environ.get(envk)
        if v:
            return Path(v).expanduser().resolve()
    here = Path(__file__).resolve()
    if here.parent.name == "plugins":
        return here.parent.parent
    # extras/ga-tokenplan-import/ga_tokenplan_import/this.py → running GA root
    pkg = here.parent
    if pkg.name == "ga_tokenplan_import":
        extras = pkg.parent.parent
        if extras.name == "extras" and (extras.parent / "agentmain.py").is_file():
            return extras.parent
    try:
        import agentmain
        am = Path(getattr(agentmain, "__file__", "") or "").resolve().parent
        if (am / "agentmain.py").is_file():
            return am
    except Exception:
        pass
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

    def _req_origin(self) -> str:
        return (self.headers.get("Origin") or "").strip().rstrip("/")

    def _origin_ok(self) -> bool:
        """写入守卫：浏览器跨域 POST 必带 Origin → 白名单卡死；
        无 Origin（curl / 桥接本机调用）放行——本机进程本就能直接写文件，不属浏览器威胁面。"""
        o = self._req_origin()
        return (not o) or (o in _allowed_origins())

    def _cors(self):
        # 只对白名单 Origin 反射 CORS；其余不发（浏览器读不到响应，POST 也会被 _origin_ok 拒）
        o = self._req_origin()
        if o and o in _allowed_origins():
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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
        # GET 永不写入：snippet 会被 import 执行，GET 写入曾构成 no-referrer <img> 驱动的
        # drive-by RCE（无 Origin/Referer 可查）。GET 只保留探测语义。
        self._j(200, {"ok": True, "port": PORT, "version": PLUGIN_VERSION})

    def do_POST(self):
        if not self._origin_ok():
            self._j(403, {"ok": False, "error": "origin_forbidden"})
            return
        d = self._body()
        for k, v in parse_qs(urlparse(self.path).query).items():
            d.setdefault(k, v[0] if v else "")
        self._apply(d)


def ensure_callback_server(port=None):
    global _httpd, PORT
    if port is not None:
        PORT = int(port)
    with _lock:
        if _httpd:
            return callback_base_url()
        _httpd = HTTPServer((HOST, PORT), _H)
        PORT = _httpd.server_address[1]  # port=0（测试用随机端口）时回填实际端口
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
# 版本随函数走：探测器无论从 agentmain 还是模块拿到 fn 都能读到，用于强制升级判定
start_subscription_portal.__plugin_version__ = PLUGIN_VERSION

# 前端探测点：有插件才有此属性（开源包无文件则无入口）
try:
    import agentmain
    agentmain.start_subscription_portal = start_subscription_portal
except Exception:
    pass
