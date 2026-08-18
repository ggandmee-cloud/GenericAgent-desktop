"""Desktop OTA: overlay-update the runtime source from GitHub Releases.

Feed = latest release of GA_OTA_REPO; payload = the platform-neutral source
tarball `GenericAgent-runtime.tar.gz` published by CI. Apply never touches
user data (mykey/temp/memory/...); the Tauri shell binary is NOT updated here,
only the Python + static tree it runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = os.environ.get("GA_OTA_REPO", "ggandmee-cloud/GenericAgent-desktop")
# Feeds on plan.khrey.com (hosted packages, CDN-close). The runtime feed is the
# CI fast lane (mirrored the moment the runtime tarball is built); latest.json
# follows once every shell build finishes. GitHub Releases is the source of
# truth and is probed whenever the feeds offer nothing new, so a stale or
# broken mirror can never pin clients to an old version.
FEED_URL = os.environ.get("GA_OTA_FEED", "https://plan.khrey.com/desktop/latest.json")
# Note: under /desktop/files/ on purpose - that is the plan server's wildcard
# static route, so no server-side route change is needed for this file.
RUNTIME_FEED_URL = os.environ.get(
    "GA_OTA_RUNTIME_FEED", "https://plan.khrey.com/desktop/files/runtime-latest.json")
ASSET = "GenericAgent-runtime.tar.gz"
TAG_PREFIX = "desktop-portable-"
# 用户数据/本机状态，覆盖更新永不写入
PROTECTED = (
    "mykey.py", "mykey.py.imported", "mykey.json", "auth.json",
    "temp/", "tmp/", "memory/", "tasks/", ".venv/", ".git/", ".streamlit/",
    "plugins/subscription_portal.py",
)
_UA = {"User-Agent": "GA-Desktop-OTA", "Accept": "application/vnd.github+json"}


def current_version(root: Path) -> str:
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except Exception:
        return "unknown"


def _release_payload(data: dict) -> dict:
    tag = str(data.get("tag_name") or "")
    version = tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else tag
    assets = {a.get("name"): a for a in data.get("assets", []) if a.get("name")}
    asset = assets.get(ASSET) or {}
    sha = assets.get(ASSET + ".sha256") or {}
    return {
        "tag": tag,
        "version": version,
        "publishedAt": data.get("published_at") or "",
        "notes": str(data.get("body") or "")[:2000],
        "assetUrl": asset.get("browser_download_url") or "",
        "assetSize": int(asset.get("size") or 0),
        "shaUrl": sha.get("browser_download_url") or "",
        "sha256": "",
    }


def _feed_payload(data: dict) -> dict:
    """Map plan.khrey.com /desktop/latest.json → internal release shape."""
    rt = data.get("runtime") or {}
    tag = str(data.get("tag") or "")
    version = str(data.get("version") or "")
    if not version and tag.startswith(TAG_PREFIX):
        version = tag[len(TAG_PREFIX):]
    return {
        "tag": tag or (TAG_PREFIX + version if version else ""),
        "version": version,
        "publishedAt": str(data.get("publishedAt") or ""),
        "notes": str(data.get("notes") or "")[:2000],
        "assetUrl": str(rt.get("url") or ""),
        "assetSize": int(rt.get("size") or 0),
        "shaUrl": "",
        "sha256": str(rt.get("sha256") or ""),
    }


def _api_json(url: str, timeout: int = 20):
    headers = dict(_UA)
    if "github.com" not in url:
        headers = {"User-Agent": _UA["User-Agent"], "Accept": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ver_key(v: str):
    """'0.1.17' -> comparable tuple; non-numeric parts never beat numeric ones."""
    return tuple((0, int(p)) if p.isdigit() else (1, p)
                 for p in re.split(r"[.\-+]", (v or "").strip()) if p != "")


def _newer(a: str, b: str) -> bool:
    """True when version a is strictly newer than b (junk never wins)."""
    try:
        return _ver_key(a) > _ver_key(b)
    except Exception:
        return False


def _github_latest(repo: str = "") -> dict:
    """Newest desktop-portable release on GitHub that carries the runtime asset."""
    repo = repo or REPO
    try:
        latest = _api_json(f"https://api.github.com/repos/{repo}/releases/latest", timeout=8)
        if (isinstance(latest, dict)
                and not latest.get("draft")
                and str(latest.get("tag_name") or "").startswith(TAG_PREFIX)
                and any(a.get("name") == ASSET for a in latest.get("assets", []))):
            return _release_payload(latest)
    except Exception:
        pass

    try:
        releases = _api_json(f"https://api.github.com/repos/{repo}/releases?per_page=30", timeout=8)
    except Exception:
        return _release_payload({})
    candidates = []
    for rel in releases if isinstance(releases, list) else []:
        if rel.get("draft") or not str(rel.get("tag_name") or "").startswith(TAG_PREFIX):
            continue
        names = {a.get("name") for a in rel.get("assets", [])}
        key = rel.get("published_at") or rel.get("created_at") or ""
        if ASSET in names:
            candidates.append((key, 1, rel))
        else:
            candidates.append((key, 0, rel))
    if not candidates:
        return _release_payload({})
    # Prefer entries that have the runtime asset; then newest published_at.
    candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return _release_payload(candidates[0][2])


def fetch_latest(repo: str = "", current: str = "") -> dict:
    """Newest runtime across all sources (see the note next to FEED_URL).

    The feeds are read first (fast, CDN-close). GitHub is consulted only when
    they offer nothing newer than `current`: the up-to-date check stays fast
    where GitHub is slow, yet a lagging mirror can never hide a release."""
    best = _release_payload({})
    for url in (RUNTIME_FEED_URL, FEED_URL):
        u = (url or "").strip()
        if not u:
            continue
        try:
            data = _api_json(u)
            out = _feed_payload(data if isinstance(data, dict) else {})
            if (out.get("assetUrl") and out.get("version")
                    and _newer(out["version"], best.get("version") or "")):
                best = out
        except Exception:
            pass

    if best.get("assetUrl") and current and _newer(best.get("version") or "", current):
        return best  # the feeds already offer an update: no need to wake GitHub

    gh = _github_latest(repo)
    if gh.get("assetUrl") and _newer(gh.get("version") or "", best.get("version") or ""):
        return gh
    return best if best.get("assetUrl") else gh


def _is_protected(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    for p in PROTECTED:
        if p.endswith("/"):
            if rel == p[:-1] or rel.startswith(p):
                return True
        elif rel == p:
            return True
    return False


def _download(url: str, dst: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)


def _verify_sha(tar_path: Path, sha_url: str = "", want: str = "") -> None:
    if not want and sha_url:
        req = urllib.request.Request(sha_url, headers={"User-Agent": _UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=20) as r:
            want = r.read().decode("utf-8").split()[0].strip().lower()
    want = (want or "").strip().lower()
    if not want:
        return
    got = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    if got != want:
        raise ValueError(f"sha256 mismatch: got {got[:12]}…, want {want[:12]}…")


def apply_tarball(tar_path: Path, root: Path, version: str) -> dict:
    """Extract to a staging dir, then overlay-copy into root (no deletions).

    Protected paths are never written; VERSION is stamped last so a torn run
    keeps reporting the old version and can be re-applied.
    """
    root = Path(root)
    updated = skipped = 0
    with tempfile.TemporaryDirectory(prefix="ga-ota-") as td:
        with tarfile.open(tar_path, "r:gz") as tf:
            for m in tf.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise ValueError(f"unsafe path in tarball: {m.name}")
            try:
                tf.extractall(td, filter="data")
            except TypeError:  # python < 3.12 without tarfile filters
                tf.extractall(td)
        stage = Path(td)
        entries = [p for p in stage.iterdir() if p.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir() and not (stage / "agentmain.py").exists():
            stage = entries[0]
        if not (stage / "agentmain.py").exists():
            raise ValueError("tarball does not look like a GA runtime (agentmain.py missing)")
        for src in stage.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(stage).as_posix()
            if _is_protected(rel):
                skipped += 1
                continue
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            # copy2 follows existing symlinks and would write through them into
            # an external tree; replace the link with a real file instead.
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            shutil.copy2(src, dst)
            updated += 1
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    return {"updated": updated, "skippedProtected": skipped}


def check(root: Path) -> dict:
    cur = current_version(root)
    latest = fetch_latest(current=cur)
    # Strictly newer only: a lagging feed must not offer a downgrade to a
    # machine that is already ahead of the mirrors.
    available = bool(latest["assetUrl"]) and bool(latest["version"]) and (
        cur in ("", "unknown") or _newer(latest["version"], cur))
    return {
        "ok": True, "current": cur, "latest": latest["version"], "tag": latest["tag"],
        "updateAvailable": available, "assetSize": latest["assetSize"],
        "publishedAt": latest["publishedAt"], "notes": latest["notes"],
    }


def apply(root: Path) -> dict:
    root = Path(root)
    cur = current_version(root)
    latest = fetch_latest(current=cur)
    if not latest["assetUrl"]:
        raise ValueError("no runtime asset in the latest release")
    if cur not in ("", "unknown") and not _newer(latest["version"], cur):
        return {"ok": True, "current": cur, "upToDate": True}
    fd, name = tempfile.mkstemp(prefix="ga-ota-", suffix=".tar.gz")
    os.close(fd)
    tmp = Path(name)
    try:
        _download(latest["assetUrl"], tmp)
        _verify_sha(tmp, sha_url=latest.get("shaUrl") or "", want=latest.get("sha256") or "")
        res = apply_tarball(tmp, root, latest["version"])
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "current": latest["version"], "previous": cur, "restartRequired": True, **res}
