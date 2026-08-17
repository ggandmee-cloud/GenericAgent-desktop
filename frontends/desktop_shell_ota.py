"""Desktop shell OTA: detect + download platform packages + spawn OS-temp helper.

Runtime OTA (desktop_ota.py) stays separate. This module never writes into the
install tree itself — the helper does that after the shell/bridge exit.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

import desktop_ota

FEED_URL = os.environ.get("GA_OTA_FEED", "https://plan.khrey.com/desktop/latest.json")
REPO = os.environ.get("GA_OTA_REPO", "ggandmee-cloud/GenericAgent-desktop")
TAG_PREFIX = "desktop-portable-"
_UA = {"User-Agent": "GA-Desktop-Shell-OTA", "Accept": "application/json"}

PLATFORM_KEYS = {
    "Windows": "windows",
    "Darwin": "macos",
    "Linux": "linux",
}


def parse_semver(raw: str) -> Optional[tuple]:
    s = (raw or "").strip()
    if s.startswith(("v", "V")):
        s = s[1:]
    parts = s.split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(x) for x in parts)
    except ValueError:
        return None


def is_newer(latest: str, current: str) -> Optional[bool]:
    """True if latest > current; False if <=; None if either unparsable."""
    a, b = parse_semver(latest), parse_semver(current)
    if a is None or b is None:
        return None
    return a > b


def _api_json(url: str) -> Any:
    headers = dict(_UA)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_feed() -> dict:
    feed = (FEED_URL or "").strip()
    if feed:
        try:
            data = _api_json(feed)
            if isinstance(data, dict) and data.get("version"):
                return data
        except Exception:
            pass
    # fallback: GitHub latest release → synthesize platforms from assets
    try:
        rel = _api_json(f"https://api.github.com/repos/{REPO}/releases/latest")
    except Exception:
        return {}
    if not isinstance(rel, dict) or rel.get("draft"):
        return {}
    tag = str(rel.get("tag_name") or "")
    ver = tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else tag
    assets = {a.get("name"): a for a in rel.get("assets", []) if a.get("name")}
    def _asset(name: str) -> dict:
        a = assets.get(name) or {}
        return {
            "name": name,
            "url": a.get("browser_download_url") or "",
            "size": int(a.get("size") or 0),
            "sha256": "",
        }
    return {
        "version": ver,
        "tag": tag,
        "publishedAt": rel.get("published_at") or "",
        "notes": str(rel.get("body") or "")[:2000],
        "platforms": {
            "windows": _asset("GenericAgent-Desktop-Windows-Portable.zip"),
            "macos": _asset("GenericAgent-Desktop-macOS.dmg"),
            "linux": _asset("GenericAgent-Desktop-Linux-Portable.tar.gz"),
        },
        "runtime": _asset("GenericAgent-runtime.tar.gz"),
        "_source": "github",
    }


def platform_key() -> str:
    return PLATFORM_KEYS.get(platform.system(), "")


def detect_layout(bundle_anchor: Path, current_exe: Path) -> dict:
    """Return layout metadata for the running install.

    bundle_anchor matches Tauri bundle_anchor_dir(): Resources/ for embedded
    macOS, or the folder that contains runtime/ (and often the .app / exe).
    """
    anchor = Path(bundle_anchor).resolve()
    exe = Path(current_exe).resolve()
    out = {
        "layout": "",
        "liveApp": "",
        "liveRuntimeApp": "",
        "relaunch": "",
        "shellBlocked": "",
        "anchor": str(anchor),
        "exe": str(exe),
    }
    exe_s = str(exe)
    if "AppTranslocation" in exe_s or "/private/var/folders/" in exe_s and "AppTranslocation" in exe_s:
        out["shellBlocked"] = "translocation"
        return out

    # macOS: walk up to .app
    app = None
    for p in [exe, *exe.parents]:
        if p.suffix == ".app":
            app = p
            break

    if platform.system() == "Darwin" and app is not None:
        embedded = app / "Contents" / "Resources" / "runtime" / "app"
        sibling = app.parent / "runtime" / "app"
        if embedded.is_dir() and (embedded / "agentmain.py").exists():
            out["layout"] = "mac-embedded"
            out["liveApp"] = str(app)
            out["liveRuntimeApp"] = str(embedded)
            out["relaunch"] = str(app)
        elif sibling.is_dir() and (sibling / "agentmain.py").exists():
            out["layout"] = "mac-portable"
            out["liveApp"] = str(app)
            out["liveRuntimeApp"] = str(sibling)
            out["relaunch"] = str(app)
        else:
            out["layout"] = "mac-embedded"
            out["liveApp"] = str(app)
            out["liveRuntimeApp"] = str(embedded)
            out["relaunch"] = str(app)
    elif platform.system() == "Windows":
        # Portable: GenericAgent.exe next to runtime/
        pkg = exe.parent
        rt = pkg / "runtime" / "app"
        out["layout"] = "win-portable"
        out["liveApp"] = str(exe)
        out["liveRuntimeApp"] = str(rt if rt.is_dir() else (anchor / "app"))
        out["relaunch"] = str(exe)
    else:
        # Linux AppImage: $APPIMAGE is the real file; current_exe may be mount
        appimage = os.environ.get("APPIMAGE") or ""
        if appimage:
            pkg = Path(appimage).resolve().parent
            out["layout"] = "linux-appimage"
            out["liveApp"] = str(Path(appimage).resolve())
            out["relaunch"] = str(Path(appimage).resolve())
        else:
            pkg = exe.parent
            out["layout"] = "linux-appimage"
            out["liveApp"] = str(exe)
            out["relaunch"] = str(exe)
        rt = (pkg / "runtime" / "app")
        if not rt.is_dir():
            rt = Path(anchor) / "app"
        out["liveRuntimeApp"] = str(rt)

    # write permission / translocation
    live = Path(out["liveApp"]) if out["liveApp"] else None
    if live and "AppTranslocation" in str(live):
        out["shellBlocked"] = "translocation"
        return out
    check_dir = live.parent if live and live.suffix == ".app" else (live.parent if live else anchor)
    try:
        check_dir.mkdir(parents=True, exist_ok=True)
        probe = check_dir / f".ga_ota_write_probe_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        out["shellBlocked"] = "readonly"
    return out


def read_shell_version(bundle_anchor: Path, baked: str = "") -> str:
    """Prefer baked Tauri version, else SHELL_VERSION next to runtime."""
    if baked and parse_semver(baked):
        return baked.strip()
    anchor = Path(bundle_anchor)
    for cand in (
        anchor / "SHELL_VERSION",
        anchor.parent / "SHELL_VERSION",
        anchor / "app" / "SHELL_VERSION",
    ):
        try:
            v = cand.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return baked.strip() if baked else ""


def check(
    *,
    bundle_anchor: Path,
    current_exe: Path,
    shell_baked: str = "",
    shell_pid: int = 0,
) -> dict:
    layout = detect_layout(bundle_anchor, current_exe)
    cur = read_shell_version(bundle_anchor, shell_baked)
    feed = fetch_feed()
    latest = str(feed.get("version") or "")
    pk = platform_key()
    plat = (feed.get("platforms") or {}).get(pk) or {}
    asset_url = str(plat.get("url") or "")
    sha = str(plat.get("sha256") or "")
    sha_source = "feed" if sha else ""
    if feed.get("_source") == "github":
        sha_source = "github" if sha else ""

    newer = is_newer(latest, cur) if latest and cur else None
    shell_unknown = parse_semver(cur) is None or parse_semver(latest) is None
    feed_older = bool(newer is False and latest and cur and parse_semver(latest) and parse_semver(cur)
                      and parse_semver(latest) < parse_semver(cur))
    blocked = layout.get("shellBlocked") or ""
    shell_update = bool(
        not blocked
        and not shell_unknown
        and newer is True
        and asset_url
        and sha
    )

    # runtime channel (unchanged semantics) — caller merges
    return {
        "ok": True,
        "shellCurrent": cur or "unknown",
        "shellLatest": latest,
        "shellUpdateAvailable": shell_update,
        "shellBlocked": blocked,
        "shellUnknown": shell_unknown,
        "feedOlder": feed_older,
        "shaSource": sha_source or ("feed-only" if asset_url and not sha else ""),
        "layout": layout.get("layout") or "",
        "liveApp": layout.get("liveApp") or "",
        "liveRuntimeApp": layout.get("liveRuntimeApp") or "",
        "assetUrl": asset_url,
        "assetSize": int(plat.get("size") or 0),
        "assetSha256": sha,
        "assetName": str(plat.get("name") or ""),
        "tag": str(feed.get("tag") or ""),
        "publishedAt": str(feed.get("publishedAt") or ""),
        "notes": str(feed.get("notes") or "")[:2000],
        "shellPid": int(shell_pid or 0),
    }


def _download(url: str, dst: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _github_asset_sha(name: str, tag: str) -> str:
    """Best-effort fetch of release sidecar sha; empty if unavailable."""
    if not tag:
        return ""
    try:
        rel = _api_json(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
    except Exception:
        return ""
    assets = {a.get("name"): a for a in (rel.get("assets") or []) if a.get("name")}
    # direct .sha256 sidecar
    side = assets.get(name + ".sha256")
    if side and side.get("browser_download_url"):
        try:
            req = urllib.request.Request(
                side["browser_download_url"],
                headers={"User-Agent": _UA["User-Agent"]},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8").split()[0].strip().lower()
        except Exception:
            pass
    # SHA256SUMS-* files
    for key, a in assets.items():
        if not str(key).startswith("SHA256SUMS"):
            continue
        url = a.get("browser_download_url") or ""
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read().decode("utf-8")
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[-1].endswith(name):
                    return parts[0].strip().lower()
        except Exception:
            continue
    return ""


def helper_source_path() -> Path:
    here = Path(__file__).resolve().parent
    sysname = platform.system()
    names = {
        "Darwin": ("macos.sh",),
        "Windows": ("windows.cmd", "windows.ps1"),
        "Linux": ("linux.sh",),
    }.get(sysname)
    if not names:
        raise RuntimeError(f"unsupported OS for shell OTA: {sysname}")
    base_candidates = [
        here / "shell_ota",  # shipped in GenericAgent-runtime.tar.gz
        here / "desktop" / "packaging" / "scripts" / "shell_ota",
        here.parent / "frontends" / "desktop" / "packaging" / "scripts" / "shell_ota",
    ]
    for base in base_candidates:
        primary = base / names[0]
        if primary.is_file():
            return primary
    raise FileNotFoundError(
        "shell OTA helper missing — install a build that includes "
        "frontends/desktop/packaging/scripts/shell_ota/ (chicken-egg: manual install once)"
    )


def _copy_helper_bundle(work: Path) -> Path:
    """Copy helper script(s) into work; return path to the entry script."""
    src = helper_source_path()
    dst = work / src.name
    shutil.copy2(src, dst)
    # Windows: also need windows.ps1 beside the .cmd
    if src.suffix.lower() == ".cmd":
        ps1 = src.with_name("windows.ps1")
        if ps1.is_file():
            shutil.copy2(ps1, work / "windows.ps1")
    if not sys.platform.startswith("win"):
        dst.chmod(dst.stat().st_mode | 0o755)
    return dst


def _extract_package(archive: Path, dest: Path, layout: str) -> tuple[Path, Optional[Path]]:
    """Extract platform archive into dest; return (new_shell_path, new_runtime_app or None)."""
    dest.mkdir(parents=True, exist_ok=True)
    if layout.startswith("mac"):
        # DMG: attach and copy .app out
        if archive.suffix.lower() == ".dmg":
            mount = dest / "mnt"
            mount.mkdir(parents=True, exist_ok=True)
            subprocess.check_call(
                ["hdiutil", "attach", str(archive), "-nobrowse", "-readonly", "-mountpoint", str(mount)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                apps = list(mount.glob("*.app"))
                if not apps:
                    raise RuntimeError("DMG has no .app")
                new_app = dest / apps[0].name
                subprocess.check_call(["ditto", str(apps[0]), str(new_app)])
            finally:
                subprocess.call(
                    ["hdiutil", "detach", str(mount), "-quiet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            rt = new_app / "Contents" / "Resources" / "runtime" / "app"
            return new_app, (rt if rt.is_dir() else None)
        # zip portable
        subprocess.check_call(["ditto", "-x", "-k", str(archive), str(dest)])
        apps = list(dest.rglob("*.app"))
        if not apps:
            raise RuntimeError("portable archive has no .app")
        new_app = apps[0]
        rt = new_app.parent / "runtime" / "app"
        if not rt.is_dir():
            rt = new_app / "Contents" / "Resources" / "runtime" / "app"
        return new_app, (rt if rt.is_dir() else None)

    if layout == "win-portable":
        # zip
        import zipfile
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest)
        exes = list(dest.rglob("GenericAgent.exe"))
        if not exes:
            raise RuntimeError("windows zip missing GenericAgent.exe")
        exe = exes[0]
        rt = exe.parent / "runtime" / "app"
        return exe, (rt if rt.is_dir() else None)

    # linux tar.gz
    import tarfile
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest)
    images = list(dest.rglob("GenericAgent.AppImage"))
    if not images:
        raise RuntimeError("linux package missing GenericAgent.AppImage")
    img = images[0]
    rt = img.parent / "runtime" / "app"
    return img, (rt if rt.is_dir() else None)


def prepare_and_spawn(
    *,
    bundle_anchor: Path,
    current_exe: Path,
    shell_baked: str,
    shell_pid: int,
    old_build_id: str = "",
) -> dict:
    """Download, verify, extract to OS temp, copy helper, spawn detached. Does not exit."""
    st = check(
        bundle_anchor=bundle_anchor,
        current_exe=current_exe,
        shell_baked=shell_baked,
        shell_pid=shell_pid,
    )
    if st.get("shellBlocked"):
        raise PermissionError(f"shell blocked: {st['shellBlocked']}")
    if st.get("shellUnknown"):
        raise ValueError("shell version unknown — cannot update automatically")
    if not st.get("shellUpdateAvailable"):
        raise ValueError("no shell update available")
    if not st.get("assetSha256"):
        raise ValueError("feed missing sha256 — refuse download")

    want = st["assetSha256"].strip().lower()
    tag = st.get("tag") or ""
    gh = _github_asset_sha(st.get("assetName") or "", tag)
    sha_source = "feed"
    if gh:
        if gh != want:
            raise ValueError(f"sha256 feed/github mismatch: feed={want[:12]} github={gh[:12]}")
        sha_source = "feed+github"
    else:
        sha_source = "feed-only"

    work = Path(tempfile.mkdtemp(prefix=f"ga-shell-ota-{shell_pid or os.getpid()}-"))
    archive = work / (st.get("assetName") or "package.bin")
    _download(st["assetUrl"], archive)
    got = _sha256_file(archive)
    if got != want:
        raise ValueError(f"sha256 mismatch: got {got[:12]} want {want[:12]}")

    extract_dir = work / "extract"
    new_shell, new_rt = _extract_package(archive, extract_dir, st["layout"])

    helper_dst = _copy_helper_bundle(work)

    log_file = work / "helper.log"
    lock_file = Path(tempfile.gettempdir()) / "ga-shell-ota.lock"
    manifest = {
        "pid": int(shell_pid or 0),
        "bridgePid": os.getpid(),
        "layout": st["layout"],
        "liveApp": st["liveApp"],
        "liveRuntimeApp": st["liveRuntimeApp"],
        "newShell": str(new_shell),
        "newRuntimeApp": str(new_rt) if new_rt else "",
        "relaunch": st.get("liveApp") or "",
        "logFile": str(log_file),
        "lockFile": str(lock_file),
        "workDir": str(work),
        "version": st["shellLatest"],
        "oldBuildId": old_build_id or "",
        "bridgePort": int(os.environ.get("BRIDGE_PORT", "14168")),
        "protected": list(desktop_ota.PROTECTED),
        "shaSource": sha_source,
    }
    man_path = work / "manifest.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Spawn detached helper
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        subprocess.Popen(
            ["cmd.exe", "/c", str(helper_dst), str(man_path)],
            cwd=str(work),
            stdin=subprocess.DEVNULL,
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            ["/bin/bash", str(helper_dst), str(man_path)],
            cwd=str(work),
            stdin=subprocess.DEVNULL,
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    return {
        "ok": True,
        "exiting": True,
        "workDir": str(work),
        "logFile": str(log_file),
        "version": st["shellLatest"],
        "previous": st["shellCurrent"],
        "shaSource": sha_source,
        "layout": st["layout"],
    }
