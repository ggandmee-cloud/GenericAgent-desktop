"""Install / remove the TokenPlan import plugin into a GenericAgent tree.

The open-source GA loader only auto-imports `plugins/*.py`. This CLI drops
(or unlinks) `subscription_portal.py` there. Core GA stays untouched:
desktop/stapp already probe `getattr(agentmain, "start_subscription_portal")`.
"""
from __future__ import annotations

import argparse, os, shutil, sys
from pathlib import Path

PLUGIN_NAME = "subscription_portal.py"
_SRC = Path(__file__).resolve().parent / "subscription_portal.py"

DEFAULT_ROOTS = (
    Path("/Applications/GenericAgent.app/Contents/Resources/runtime/app"),
    Path.home() / "GA" / "GenericAgent",
    Path.home() / "GA" / "GenericAgent_ui",
)


def _looks_like_ga(root: Path) -> bool:
    return (root / "agentmain.py").is_file() and (root / "plugins").is_dir()


def _dest(root: Path) -> Path:
    return root / "plugins" / PLUGIN_NAME


def detect_roots(explicit: list[str] | None) -> list[Path]:
    if explicit:
        out = []
        for raw in explicit:
            p = Path(raw).expanduser().resolve()
            if not _looks_like_ga(p):
                raise SystemExit(f"not a GenericAgent root: {p}")
            out.append(p)
        return out
    env = os.environ.get("GA_ROOT") or os.environ.get("GENERICAGENT_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if not _looks_like_ga(p):
            raise SystemExit(f"GA_ROOT is not a GenericAgent root: {p}")
        return [p]
    found: list[Path] = []
    cwd = Path.cwd().resolve()
    if _looks_like_ga(cwd):
        found.append(cwd)
    for p in DEFAULT_ROOTS:
        rp = p.resolve()
        if _looks_like_ga(rp) and rp not in found:
            found.append(rp)
    if not found:
        raise SystemExit("no GenericAgent root found; pass --ga-root or run from a clone")
    return found


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return False


def install(root: Path, *, link: bool) -> str:
    dest = _dest(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        if _same_file(dest, _SRC) and dest.is_symlink() == link:
            return f"already {'linked' if dest.is_symlink() else 'installed'}: {dest}"
        if dest.is_symlink():
            dest.unlink()
        else:
            bak = dest.with_name(dest.name + ".bak-before-optional-pkg")
            dest.replace(bak)
    if link:
        dest.symlink_to(_SRC)
        return f"linked {dest} → {_SRC}"
    shutil.copy2(_SRC, dest)
    return f"copied {_SRC} → {dest}"


def uninstall(root: Path) -> str:
    dest = _dest(root)
    if not dest.exists() and not dest.is_symlink():
        return f"absent: {dest}"
    dest.unlink()
    return f"removed {dest}"


def status(root: Path) -> str:
    dest = _dest(root)
    if dest.is_symlink():
        return f"linked {dest} → {dest.resolve()}"
    if dest.is_file():
        return f"copied {dest} ({dest.stat().st_size} B)"
    return f"absent: {dest}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ga-tokenplan-import", description=__doc__)
    p.add_argument("cmd", choices=("install", "uninstall", "status"))
    p.add_argument("--ga-root", action="append", help="GenericAgent root (repeatable). Default: detect local trees")
    p.add_argument("--link", action="store_true", help="symlink instead of copy (install only)")
    p.add_argument("--copy", action="store_true", help="copy the plugin file (install default)")
    args = p.parse_args(argv)
    roots = detect_roots(args.ga_root)
    link = bool(args.link) and not args.copy
    for root in roots:
        if args.cmd == "install":
            print(install(root, link=link))
        elif args.cmd == "uninstall":
            print(uninstall(root))
        else:
            print(status(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
