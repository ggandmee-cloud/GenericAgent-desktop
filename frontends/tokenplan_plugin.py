"""TokenPlan import plugin: probe local install, then the release manifest.

Mirrors lsdefine/GenericAgent#768 (GAnet): the plugin itself can live on a
release server; the desktop first *probes* before any download/install.

  1. probe_local()  — try import plugins.subscription_portal / hooked starter
  2. probe_remote() — GET the published manifest (size + sha256 + url)
  3. probe()        — combine; GET /subscription-portal returns this

Download/install is intentionally not implemented here.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

COMPONENT = "tokenplan-import-plugin"
PLUGIN_FILE = Path("plugins") / "subscription_portal.py"
EXTRAS_FILE = (
    Path("extras") / "ga-tokenplan-import" / "ga_tokenplan_import" / "subscription_portal.py"
)
DEFAULT_MANIFEST_URL = "https://plan.khrey.com/releases/plugin/tokenplan/manifest.json"
_UA = {"User-Agent": "GA-Desktop-TokenPlan-Probe", "Accept": "application/json"}

_remote_cache: tuple[float, dict] | None = None


def manifest_url() -> str:
    return (
        os.environ.get("GA_TOKENPLAN_PLUGIN_MANIFEST") or DEFAULT_MANIFEST_URL
    ).strip()


def _timeout() -> float:
    try:
        return max(0.5, float(os.environ.get("GA_TOKENPLAN_PLUGIN_PROBE_TIMEOUT") or 5))
    except ValueError:
        return 5.0


def _cache_ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("GA_TOKENPLAN_PLUGIN_PROBE_CACHE") or 60))
    except ValueError:
        return 60.0


def _ensure_root(ga_root: Path | str | None) -> Path:
    if ga_root:
        return Path(ga_root).expanduser().resolve()
    for envk in ("GA_ROOT", "GENERICAGENT_ROOT"):
        v = os.environ.get(envk)
        if v:
            return Path(v).expanduser().resolve()
    return Path.cwd().resolve()


def _put_root_on_path(root: Path) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _starter_from(obj: Any) -> Optional[Callable]:
    fn = getattr(obj, "start_subscription_portal", None)
    return fn if callable(fn) else None


def probe_local(ga_root: Path | str | None = None) -> dict:
    """Try the in-tree plugin the same way GAnet frontends try `plugins.ganet`.

    Availability is per `ga_root`: a plugin imported from another tree in this
    process does not count as installed here.
    """
    root = _ensure_root(ga_root)
    plugin_path = root / PLUGIN_FILE
    extras_path = root / EXTRAS_FILE
    extras = str(extras_path) if extras_path.is_file() else ""

    if not plugin_path.is_file():
        return {
            "installed": False,
            "available": False,
            "source": None,
            "plugin_path": "",
            "extras_path": extras,
            "error": (
                "extras present, plugins/subscription_portal.py missing"
                if extras
                else "plugin not installed"
            ),
        }

    _put_root_on_path(root)
    starter = None
    source = None
    error = ""

    am = sys.modules.get("agentmain")
    if am is not None:
        starter = _starter_from(am)
        if starter:
            source = "hook"

    if starter is None:
        try:
            mod = importlib.import_module("plugins.subscription_portal")
            starter = _starter_from(mod)
            if starter:
                source = "plugin"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

    return {
        "installed": bool(starter),
        "available": bool(starter),
        "source": source,
        "plugin_path": str(plugin_path),
        "extras_path": extras,
        "error": "" if starter else error,
    }


def local_starter(ga_root: Path | str | None = None) -> Optional[Callable]:
    if not probe_local(ga_root).get("available"):
        return None
    am = sys.modules.get("agentmain")
    if am is not None:
        fn = _starter_from(am)
        if fn:
            return fn
    mod = sys.modules.get("plugins.subscription_portal")
    if mod is not None:
        return _starter_from(mod)
    return None


def _empty_remote(*, ok: bool, error: str = "") -> dict:
    return {
        "ok": ok,
        "available": False,
        "version": "",
        "url": "",
        "sha256": "",
        "size": 0,
        "install_path": "",
        "component": "",
        "manifest_url": manifest_url(),
        "error": error,
    }


def parse_manifest(data: Any, *, src: str = "") -> dict:
    """Validate a GAnet-style plugin manifest. Missing/invalid → available=false."""
    if not isinstance(data, dict):
        return _empty_remote(ok=False, error="manifest is not an object")
    version = str(data.get("version") or "").strip()
    url = str(data.get("url") or "").strip()
    sha256 = str(data.get("sha256") or "").strip().lower()
    install_path = str(data.get("install_path") or PLUGIN_FILE.as_posix()).strip()
    component = str(data.get("component") or "").strip()
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    errs = []
    if not version:
        errs.append("missing version")
    if not url:
        errs.append("missing url")
    if not sha256 or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        errs.append("invalid sha256")
    if component and component != COMPONENT:
        errs.append(f"component mismatch: {component}")
    if errs:
        out = _empty_remote(ok=False, error="; ".join(errs))
        out["version"] = version
        out["url"] = url
        out["sha256"] = sha256
        out["size"] = size
        out["install_path"] = install_path
        out["component"] = component
        if src:
            out["manifest_url"] = src
        return out
    return {
        "ok": True,
        "available": True,
        "version": version,
        "url": url,
        "sha256": sha256,
        "size": size,
        "install_path": install_path,
        "component": component or COMPONENT,
        "manifest_url": src or manifest_url(),
        "error": "",
    }


def fetch_manifest(url: str | None = None, *, timeout: float | None = None) -> dict:
    src = (url or manifest_url()).strip()
    if not src:
        return _empty_remote(ok=False, error="empty manifest url")
    req = urllib.request.Request(src, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout if timeout is not None else _timeout()) as r:
        raw = r.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return _empty_remote(ok=False, error=f"invalid json: {e}")
    return parse_manifest(data, src=src)


def probe_remote(url: str | None = None, *, timeout: float | None = None, use_cache: bool = True) -> dict:
    """Read the published plugin manifest. 404 / timeout is not a local failure."""
    global _remote_cache
    src = (url or manifest_url()).strip()
    ttl = _cache_ttl()
    now = time.monotonic()
    if use_cache and ttl > 0 and url is None and _remote_cache is not None:
        ts, cached = _remote_cache
        if now - ts < ttl and cached.get("manifest_url") == src:
            return dict(cached)
    try:
        out = fetch_manifest(src, timeout=timeout)
    except urllib.error.HTTPError as e:
        out = _empty_remote(ok=False, error=f"HTTP {e.code}")
        out["manifest_url"] = src
    except urllib.error.URLError as e:
        out = _empty_remote(ok=False, error=f"url error: {e.reason}")
        out["manifest_url"] = src
    except TimeoutError:
        out = _empty_remote(ok=False, error="timeout")
        out["manifest_url"] = src
    except Exception as e:
        out = _empty_remote(ok=False, error=f"{type(e).__name__}: {e}")
        out["manifest_url"] = src
    if use_cache and ttl > 0 and url is None:
        _remote_cache = (now, dict(out))
    return out


def clear_remote_cache() -> None:
    global _remote_cache
    _remote_cache = None


def probe(ga_root: Path | str | None = None, *, remote: bool = True) -> dict:
    local = probe_local(ga_root)
    out = {
        "available": local["available"],
        "installed": local["installed"],
        "source": local["source"],
        "plugin_path": local["plugin_path"],
        "extras_path": local["extras_path"],
        "error": local["error"],
    }
    if remote:
        out["remote"] = probe_remote()
    else:
        skipped = _empty_remote(ok=False, error="skipped")
        out["remote"] = skipped
    return out
