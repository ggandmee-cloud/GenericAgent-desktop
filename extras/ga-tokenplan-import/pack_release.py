#!/usr/bin/env python3
"""Build the TokenPlan plugin zip + GAnet-style manifest for plan.khrey.com.

Usage:
  python3 extras/ga-tokenplan-import/pack_release.py --out-dir dist/plugin \\
      --public-base https://plan.khrey.com/desktop/files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

COMPONENT = "ga-tokenplan-import"
INSTALL_PATH = "plugins/subscription_portal.py"
HERE = Path(__file__).resolve().parent
SRC = HERE / "ga_tokenplan_import" / "subscription_portal.py"


def plugin_version() -> str:
    text = (HERE / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def build_release(out_dir: Path, public_base: str) -> dict:
    if not SRC.is_file():
        raise SystemExit(f"missing plugin source: {SRC}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    version = plugin_version()
    zip_name = f"{COMPONENT}-{version}.zip"
    zip_path = out_dir / zip_name
    payload = SRC.read_bytes()
    info = zipfile.ZipInfo("subscription_portal.py")
    info.date_time = (2026, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(info, payload)
    raw = zip_path.read_bytes()
    base = public_base.rstrip("/")
    manifest = {
        "schema": 1,
        "component": COMPONENT,
        "version": version,
        "url": f"{base}/{zip_name}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "install_path": INSTALL_PATH,
    }
    (out_dir / "plugin-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", required=True, help="directory for zip + plugin-manifest.json")
    p.add_argument(
        "--public-base",
        default="https://plan.khrey.com/desktop/files",
        help="public directory URL that will host the zip",
    )
    args = p.parse_args(argv)
    man = build_release(Path(args.out_dir), args.public_base)
    print(json.dumps(man, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
