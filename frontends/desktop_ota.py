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
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = os.environ.get("GA_OTA_REPO", "ggandmee-cloud/GenericAgent-desktop")
ASSET = "GenericAgent-runtime.tar.gz"
TAG_PREFIX = "desktop-portable-"
# 用户数据/本机状态，覆盖更新永不写入
PROTECTED = (
    "mykey.py", "mykey.py.imported", "mykey.json", "auth.json",
    "temp/", "tmp/", "memory/", "tasks/", ".venv/", ".git/", ".streamlit/",
)
_UA = {"User-Agent": "GA-Desktop-OTA", "Accept": "application/vnd.github+json"}


def current_version(root: Path) -> str:
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except Exception:
        return "unknown"


def fetch_latest(repo: str = "") -> dict:
    # 不用 /releases/latest：它跳过 prerelease。扫最新 releases，取第一个带
    # runtime 资产的 desktop-portable-* 条目（列表按创建时间倒序）。
    url = f"https://api.github.com/repos/{repo or REPO}/releases?per_page=15"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20) as r:
        releases = json.loads(r.read().decode("utf-8"))
    data = {}
    fallback = {}
    for rel in releases if isinstance(releases, list) else []:
        if rel.get("draft") or not str(rel.get("tag_name") or "").startswith(TAG_PREFIX):
            continue
        names = {a.get("name") for a in rel.get("assets", [])}
        if ASSET in names:
            data = rel
            break
        fallback = fallback or rel
    data = data or fallback
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
    }


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


def _verify_sha(tar_path: Path, sha_url: str) -> None:
    req = urllib.request.Request(sha_url, headers={"User-Agent": _UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=20) as r:
        want = r.read().decode("utf-8").split()[0].strip().lower()
    got = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    if want and got != want:
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
            shutil.copy2(src, dst)
            updated += 1
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    return {"updated": updated, "skippedProtected": skipped}


def check(root: Path) -> dict:
    cur = current_version(root)
    latest = fetch_latest()
    available = bool(latest["assetUrl"]) and latest["version"] not in ("", cur)
    return {
        "ok": True, "current": cur, "latest": latest["version"], "tag": latest["tag"],
        "updateAvailable": available, "assetSize": latest["assetSize"],
        "publishedAt": latest["publishedAt"], "notes": latest["notes"],
    }


def apply(root: Path) -> dict:
    root = Path(root)
    cur = current_version(root)
    latest = fetch_latest()
    if not latest["assetUrl"]:
        raise ValueError("no runtime asset in the latest release")
    if latest["version"] == cur:
        return {"ok": True, "current": cur, "upToDate": True}
    fd, name = tempfile.mkstemp(prefix="ga-ota-", suffix=".tar.gz")
    os.close(fd)
    tmp = Path(name)
    try:
        _download(latest["assetUrl"], tmp)
        if latest["shaUrl"]:
            _verify_sha(tmp, latest["shaUrl"])
        res = apply_tarball(tmp, root, latest["version"])
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "current": latest["version"], "previous": cur, "restartRequired": True, **res}
