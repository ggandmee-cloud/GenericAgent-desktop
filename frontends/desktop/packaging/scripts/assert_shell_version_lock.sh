#!/usr/bin/env bash
# Fail the desktop release if shell version sources disagree.
# Usage: assert_shell_version_lock.sh [expected_version]
# If expected is omitted and GITHUB_REF is refs/tags/desktop-portable-X, use X.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"

expect="${1:-}"
if [[ -z "$expect" ]]; then
  ref="${GITHUB_REF:-}"
  if [[ "$ref" == refs/tags/desktop-portable-* ]]; then
    expect="${ref#refs/tags/desktop-portable-}"
  else
    expect="$(tr -d '[:space:]' < VERSION)"
  fi
fi
[[ -n "$expect" ]] || { echo "empty expected version" >&2; exit 2; }

tauri="$(python3 -c 'import json; print(json.load(open("frontends/desktop/src-tauri/tauri.conf.json"))["version"])')"
pkg="$(python3 -c 'import json; print(json.load(open("frontends/desktop/package.json"))["version"])')"
cargo="$(python3 -c '
import re
from pathlib import Path
t = Path("frontends/desktop/src-tauri/Cargo.toml").read_text()
m = re.search(r"(?m)^version\s*=\s*\"([^\"]+)\"", t)
print(m.group(1) if m else "")
')"
ver="$(tr -d '[:space:]' < VERSION)"

echo "version-lock expect=$expect tauri=$tauri package=$pkg cargo=$cargo VERSION=$ver"
fail=0
for pair in "tauri:$tauri" "package.json:$pkg" "Cargo.toml:$cargo" "VERSION:$ver"; do
  name="${pair%%:*}"
  val="${pair#*:}"
  if [[ "$val" != "$expect" ]]; then
    echo "MISMATCH $name=$val (want $expect)" >&2
    fail=1
  fi
done
[[ "$fail" -eq 0 ]] || exit 1
echo "OK shell version lock = $expect"
