"""TokenPlan import plugin: probe locally, then install from plan.khrey.com.

Same shape as GenericAgent PR #768 (GAnet): the plugin is not shipped in the
desktop runtime. Frontends first try to import it; only a miss fetches the
official manifest (size + SHA-256) and drops `plugins/subscription_portal.py`.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.request import Request, urlopen

COMPONENT = "ga-tokenplan-import"
INSTALL_PATH = "plugins/subscription_portal.py"
DEFAULT_MANIFEST = "https://plan.khrey.com/desktop/plugin-manifest.json"
DEFAULT_FEED = "https://plan.khrey.com/desktop/latest.json"
# 已装插件低于该版本视为未安装 → 走 manifest 强制重装。1.1.0 = 废 GET 写入 + Origin 白名单，
# 安全修复必须触达存量用户（probe 命中即返回的旧行为把他们永远留在了漏洞版）。
MIN_PLUGIN_VERSION = "1.1.0"
MAX_BYTES = 2 * 1024 * 1024
_UA = {"User-Agent": "GA-Desktop-TokenPlan", "Accept": "application/json"}
_lock = threading.Lock()


def _ver_tuple(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3]) or (0,)


def _fn_version(fn) -> str:
    return str(getattr(fn, "__plugin_version__", "") or "")


def _fn_meets_min(fn) -> bool:
    return _ver_tuple(_fn_version(fn)) >= _ver_tuple(MIN_PLUGIN_VERSION)


def _log(msg: str) -> None:
    sys.stderr.write(f"[tokenplan-plugin] {msg}\n")


def _ga_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root).expanduser().resolve()
    for envk in ("GA_ROOT", "GENERICAGENT_ROOT"):
        v = os.environ.get(envk)
        if v:
            return Path(v).expanduser().resolve()
    here = Path(__file__).resolve()
    # frontends/tokenplan_plugin.py → repo root
    return here.parent.parent


def _plugin_file(root: Path) -> Path:
    return root / "plugins" / "subscription_portal.py"


def _extras_dir(root: Path) -> Path:
    return root / "extras" / "ga-tokenplan-import"


def _get_start(mod: Any) -> Optional[Callable]:
    fn = getattr(mod, "start_subscription_portal", None)
    return fn if callable(fn) else None


def _import_agentmain(root: Path):
    parent = str(root)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    if "agentmain" in sys.modules:
        return sys.modules["agentmain"]
    try:
        return importlib.import_module("agentmain")
    except Exception:
        return None


def probe_start(root: Optional[Path] = None, *, min_version: bool = True) -> Optional[Callable]:
    """Return start_subscription_portal if it is already loadable. No network.

    min_version=True（默认）时，版本低于 MIN_PLUGIN_VERSION 的旧插件按未安装处理，
    让 ensure_start 走 manifest 重装——否则安全修复永远到不了已装用户。
    """
    fn = _probe_start_any(root)
    if fn and min_version and not _fn_meets_min(fn):
        _log(f"plugin version {_fn_version(fn) or 'unknown'} < {MIN_PLUGIN_VERSION}, treating as missing")
        return None
    return fn


def _probe_start_any(root: Optional[Path] = None) -> Optional[Callable]:
    root = _ga_root(root)
    am = _import_agentmain(root)
    fn = _get_start(am) if am is not None else None
    if fn:
        return fn

    plugin = _plugin_file(root)
    if plugin.is_file():
        try:
            if "plugins.subscription_portal" in sys.modules:
                importlib.reload(sys.modules["plugins.subscription_portal"])
            else:
                importlib.import_module("plugins.subscription_portal")
            am = sys.modules.get("agentmain") or am
            fn = _get_start(am) if am is not None else None
            if fn:
                return fn
            mod = sys.modules.get("plugins.subscription_portal")
            fn = _get_start(mod) if mod is not None else None
            if fn:
                return fn
        except Exception as e:
            _log(f"plugin import failed: {e}")

    extras = _extras_dir(root)
    extras_src = extras / "ga_tokenplan_import" / "subscription_portal.py"
    if extras_src.is_file():
        extra_path = str(extras)
        if extra_path not in sys.path:
            sys.path.insert(0, extra_path)
        try:
            if "ga_tokenplan_import.subscription_portal" in sys.modules:
                importlib.reload(sys.modules["ga_tokenplan_import.subscription_portal"])
            else:
                importlib.import_module("ga_tokenplan_import.subscription_portal")
            am = sys.modules.get("agentmain") or am
            fn = _get_start(am) if am is not None else None
            if fn:
                return fn
            mod = sys.modules.get("ga_tokenplan_import.subscription_portal")
            fn = _get_start(mod) if mod is not None else None
            if fn:
                return fn
        except Exception as e:
            _log(f"extras import failed: {e}")
    return None


def probe_source(root: Optional[Path] = None) -> Optional[str]:
    """On-disk source for the plugin. Prefers plugins/ over extras/ over a prior import."""
    root = _ga_root(root)
    if _plugin_file(root).is_file():
        return "plugin"
    if (_extras_dir(root) / "ga_tokenplan_import" / "subscription_portal.py").is_file():
        return "extras"
    am = sys.modules.get("agentmain")
    if _get_start(am):
        return "agentmain"
    return None


def probe_status(root: Optional[Path] = None) -> dict:
    """Probe only. `available` is true if installed or we can fetch from the server."""
    root = _ga_root(root)
    fn = probe_start(root)
    source = probe_source(root) if fn else None
    return {
        "installed": bool(fn),
        "available": True,  # desktop can always attempt the official manifest
        "source": source,
        "version": _fn_version(fn) if fn else "",
    }


def _http_json(url: str, timeout: int = 20) -> dict:
    req = Request(url, headers=_UA)
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if len(raw) > MAX_BYTES:
        raise ValueError("manifest too large")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest is not an object")
    return data


def _http_download(url: str, dst: Path, timeout: int = 60) -> None:
    req = Request(url, headers={"User-Agent": _UA["User-Agent"]})
    with urlopen(req, timeout=timeout) as r, open(dst, "wb") as f:
        got = 0
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            got += len(chunk)
            if got > MAX_BYTES:
                raise ValueError(f"plugin zip exceeds {MAX_BYTES} bytes")
            f.write(chunk)


def _manifest_urls() -> list[str]:
    env = (os.environ.get("GA_TOKENPLAN_PLUGIN_MANIFEST") or "").strip()
    if env:
        return [env]
    feed = (os.environ.get("GA_OTA_FEED") or DEFAULT_FEED).strip()
    return [DEFAULT_MANIFEST, feed]


def fetch_manifest() -> dict:
    """GAnet-style plugin manifest: url / sha256 / size / install_path.

    Tries `plugin-manifest.json` first, then `plugin` inside desktop latest.json.
    """
    last_err: Optional[Exception] = None
    for url in _manifest_urls():
        try:
            data = _http_json(url)
        except Exception as e:
            last_err = e
            continue
        plugin = data.get("plugin") if isinstance(data.get("plugin"), dict) else data
        if str(plugin.get("url") or "") and str(plugin.get("sha256") or ""):
            return plugin
        last_err = ValueError(f"no plugin payload in {url}")
    raise last_err or RuntimeError("plugin manifest unavailable")


def _validate_manifest(man: dict) -> dict:
    url = str(man.get("url") or "").strip()
    sha = str(man.get("sha256") or "").strip().lower()
    size = int(man.get("size") or 0)
    install_path = str(man.get("install_path") or INSTALL_PATH).replace("\\", "/").strip()
    if not url:
        raise ValueError("manifest missing url")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("manifest sha256 is invalid")
    if size <= 0 or size > MAX_BYTES:
        raise ValueError(f"manifest size out of range: {size}")
    if install_path != INSTALL_PATH:
        raise ValueError(f"refusing install_path {install_path!r}")
    component = str(man.get("component") or COMPONENT)
    if component and component != COMPONENT:
        raise ValueError(f"unexpected component {component!r}")
    return {
        "url": url,
        "sha256": sha,
        "size": size,
        "install_path": install_path,
        "version": str(man.get("version") or ""),
        "component": component or COMPONENT,
    }


def _extract_plugin_py(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        names = []
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or info.is_dir():
                continue
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe path in zip: {name}")
            names.append(name)
        want = [n for n in names if Path(n).name == "subscription_portal.py"]
        if not want:
            raise ValueError("zip does not contain subscription_portal.py")
        # Prefer a top-level file; otherwise the first match.
        want.sort(key=lambda n: n.count("/"))
        data = zf.read(want[0])
        if not data or len(data) > MAX_BYTES:
            raise ValueError("plugin file empty or too large")
        return data


def install_from_manifest(root: Optional[Path] = None, man: Optional[dict] = None) -> Path:
    """Download, verify, and write plugins/subscription_portal.py. Returns dest path."""
    root = _ga_root(root)
    spec = _validate_manifest(man if man is not None else fetch_manifest())
    dest = root / spec["install_path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ga-tokenplan-plugin-") as td:
        zpath = Path(td) / "plugin.zip"
        _http_download(spec["url"], zpath)
        raw = zpath.read_bytes()
        if len(raw) != spec["size"]:
            raise ValueError(f"size mismatch: got {len(raw)}, want {spec['size']}")
        got = hashlib.sha256(raw).hexdigest()
        if got != spec["sha256"]:
            raise ValueError(f"sha256 mismatch: got {got[:12]}…, want {spec['sha256'][:12]}…")
        py = _extract_plugin_py(zpath)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(py)
        os.replace(tmp, dest)
    _log(f"installed {dest} ({spec.get('version') or 'unknown'})")
    return dest


def _flush_plugin_modules() -> None:
    for name in list(sys.modules):
        if name == "plugins.subscription_portal" or name.startswith("ga_tokenplan_import"):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()


def ensure_start(root: Optional[Path] = None) -> Callable:
    """Probe first; download from the official manifest on a miss or an outdated install."""
    root = _ga_root(root)
    with _lock:
        fn = probe_start(root)
        if fn:
            return fn
        try:
            install_from_manifest(root)
        except Exception as e:
            # 重装失败（离线/manifest 未更新）：有旧版可用时降级放行并告警，胜过彻底不可用
            fn = _probe_start_any(root)
            if fn:
                _log(f"reinstall failed ({e}); falling back to installed version {_fn_version(fn) or 'unknown'}")
                return fn
            raise
        _flush_plugin_modules()
        fn = probe_start(root)
        if fn:
            return fn
        # 装上了但 manifest 仍是旧版：接受并告警，等服务端镜像更新后下次升级
        fn = _probe_start_any(root)
        if not fn:
            raise RuntimeError("plugin installed but start_subscription_portal is missing")
        _log(f"manifest still serves {_fn_version(fn) or 'unknown'} < {MIN_PLUGIN_VERSION}; using it anyway")
        return fn


def ensure_apply(root: Optional[Path] = None) -> Callable:
    """Return the plugin's apply_profile_to_mykey (installing the plugin if needed).

    取自 start fn 的模块 globals：无论 fn 来自 plugins/ 还是 extras/，写入逻辑
    （<TOKENPLAN> 块合并 + 双写目标）都跟着同一模块走。
    """
    fn = ensure_start(root)
    apply_fn = None
    try:
        apply_fn = fn.__globals__.get("apply_profile_to_mykey")
    except Exception:
        apply_fn = None
    if not callable(apply_fn):
        raise RuntimeError("plugin lacks apply_profile_to_mykey")
    return apply_fn
