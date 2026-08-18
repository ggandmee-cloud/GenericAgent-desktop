#!/usr/bin/env bash
# Mirror a GitHub desktop-portable-* Release onto plan.khrey.com DESKTOP_DIR.
#
# Required env:
#   GH_TOKEN              — read release assets (GITHUB_TOKEN is fine)
#   PLAN_KHREY_SSH_HOST
#   PLAN_KHREY_SSH_USER
#   PLAN_KHREY_SSH_KEY    — private key PEM (ed25519)
# Optional:
#   PLAN_KHREY_SSH_PORT   — default 22
#   PLAN_KHREY_DESKTOP_DIR — default /opt/tokenplan/data/desktop
#   PLAN_KHREY_PUBLIC_BASE — default https://plan.khrey.com/desktop/files
#   PLAN_KHREY_REPO       — default ggandmee-cloud/GenericAgent-desktop
#   PLAN_KHREY_CHOWN      — default agentga:agentga (empty = skip)
#
# Usage:
#   sync_plan_khrey_desktop.sh <tag> [--runtime-only] [--dry-run]
#
# --runtime-only is the CI fast lane: it needs only the (platform-neutral)
# runtime tarball, so it runs as soon as the Linux job uploads it and writes
# runtime-latest.json - runtime OTA never waits for, nor gets blocked by, the
# Windows/macOS shell builds. latest.json (installers, plugin, shell OTA) is
# untouched here and still comes from the full mirror afterwards.
set -euo pipefail

TAG="${1:-}"
DRY=0
RUNTIME_ONLY=0
shift || true
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --runtime-only) RUNTIME_ONLY=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done
[[ -n "$TAG" ]] || { echo "usage: $0 <tag> [--runtime-only] [--dry-run]" >&2; exit 2; }

REPO="${PLAN_KHREY_REPO:-ggandmee-cloud/GenericAgent-desktop}"
HOST="${PLAN_KHREY_SSH_HOST:?PLAN_KHREY_SSH_HOST required}"
USER="${PLAN_KHREY_SSH_USER:?PLAN_KHREY_SSH_USER required}"
KEY_RAW="${PLAN_KHREY_SSH_KEY:?PLAN_KHREY_SSH_KEY required}"
PORT="${PLAN_KHREY_SSH_PORT:-22}"
REMOTE_DIR="${PLAN_KHREY_DESKTOP_DIR:-/opt/tokenplan/data/desktop}"
PUBLIC_BASE="${PLAN_KHREY_PUBLIC_BASE:-https://plan.khrey.com/desktop/files}"
PUBLIC_BASE="${PUBLIC_BASE%/}"
CHOWN_TO="${PLAN_KHREY_CHOWN:-agentga:agentga}"

if [[ "$RUNTIME_ONLY" -eq 1 ]]; then
  REQUIRED=(GenericAgent-runtime.tar.gz)
else
  REQUIRED=(
    GenericAgent-Desktop-Windows-Portable.zip
    GenericAgent-Desktop-macOS.dmg
    GenericAgent-Desktop-Linux-Portable.tar.gz
    GenericAgent-runtime.tar.gz
  )
fi

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/ga-plan-khrey.XXXXXX")"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

KEY_FILE="$WORKDIR/id_ed25519"
PLAN_KHREY_SSH_KEY="$KEY_RAW" python3 - "$KEY_FILE" <<'PY'
import os, sys
from pathlib import Path
raw = os.environ["PLAN_KHREY_SSH_KEY"].replace("\r\n", "\n").replace("\r", "\n")
# gh / UI paste sometimes stores a single line with literal \n
if "BEGIN" in raw and "\n" not in raw.strip():
    raw = raw.replace("\\n", "\n")
elif "\\n-----" in raw or raw.count("\\n") > 3:
    raw = raw.replace("\\n", "\n")
if not raw.endswith("\n"):
    raw += "\n"
Path(sys.argv[1]).write_text(raw, encoding="utf-8")
PY
[[ -s "$KEY_FILE" ]] || { echo "empty SSH key" >&2; exit 1; }
chmod 600 "$KEY_FILE"

SSH=(ssh -i "$KEY_FILE" -p "$PORT" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
     -o BatchMode=yes -o ConnectTimeout=20)
RSYNC_SSH="ssh -i $KEY_FILE -p $PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes"

echo "==> wait for release assets on $REPO @ $TAG"
HAVE_FILE="$WORKDIR/have_assets.txt"
for _ in $(seq 1 60); do
  gh release view "$TAG" -R "$REPO" --json assets -q '.assets[].name' > "$HAVE_FILE" 2>/dev/null || : > "$HAVE_FILE"
  missing=0
  for f in "${REQUIRED[@]}"; do
    grep -qxF "$f" "$HAVE_FILE" || missing=1
  done
  [[ "$missing" -eq 0 ]] && break
  echo "   …assets incomplete ($(tr '\n' ' ' < "$HAVE_FILE" || echo none)), retry"
  sleep 10
done
missing=0
for f in "${REQUIRED[@]}"; do
  grep -qxF "$f" "$HAVE_FILE" || { echo "missing asset: $f" >&2; missing=1; }
done
[[ "$missing" -eq 0 ]] || exit 1

META_JSON="$WORKDIR/release.json"
gh release view "$TAG" -R "$REPO" --json tagName,publishedAt,body,assets > "$META_JSON"

echo "==> download assets"
mkdir -p "$WORKDIR/files"
(
  cd "$WORKDIR/files"
  gh release download "$TAG" -R "$REPO" \
    -p 'GenericAgent-Desktop-Windows-Portable.zip' \
    -p 'GenericAgent-Desktop-macOS.dmg' \
    -p 'GenericAgent-Desktop-Linux-Portable.tar.gz' \
    -p 'GenericAgent-runtime.tar.gz' \
    -p 'GenericAgent-runtime.tar.gz.sha256' \
    -p 'GenericAgent-Desktop-macOS.dmg.sha256' \
    -p 'SHA256SUMS-windows.txt' \
    -p 'SHA256SUMS-linux.txt' \
    || true
)
for f in "${REQUIRED[@]}"; do
  [[ -f "$WORKDIR/files/$f" ]] || { echo "download failed: $f" >&2; exit 1; }
done

if [[ "$RUNTIME_ONLY" -eq 1 ]]; then
  echo "==> build runtime-latest.json"
  python3 - "$WORKDIR" "$TAG" "$PUBLIC_BASE" "$META_JSON" <<'PY'
import hashlib, json, sys
from pathlib import Path

work, tag, base, meta_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3].rstrip("/"), Path(sys.argv[4])
meta = json.loads(meta_path.read_text(encoding="utf-8"))
name = "GenericAgent-runtime.tar.gz"
p = work / "files" / name
ver = tag[len("desktop-portable-"):] if tag.startswith("desktop-portable-") else tag
body = (meta.get("body") or "").strip()
lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
out = {
    "version": ver,
    "tag": tag,
    "publishedAt": meta.get("publishedAt") or "",
    "notes": (lines[0][:240] if lines else f"GenericAgent Desktop {ver}"),
    "runtime": {
        "name": name,
        "url": f"{base}/{name}",
        "size": p.stat().st_size,
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    },
}
(work / "runtime-latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"version": ver, "runtime_sha": out["runtime"]["sha256"][:16]}))
PY

  if [[ "$DRY" -eq 1 ]]; then
    echo "==> dry-run (runtime-only): would rsync to ${USER}@${HOST}:${REMOTE_DIR}/"
    ls -lh "$WORKDIR/files/GenericAgent-runtime.tar.gz"
    cat "$WORKDIR/runtime-latest.json"
    exit 0
  fi

  echo "==> rsync runtime → ${USER}@${HOST}:${REMOTE_DIR}/"
  "${SSH[@]}" "${USER}@${HOST}" "mkdir -p '$REMOTE_DIR'"
  # Tarball (and sidecar) land first; the feed pointer goes last so a reader
  # can never see a runtime-latest.json whose payload is still uploading.
  rsync -av --checksum -e "$RSYNC_SSH" \
    "$WORKDIR/files/GenericAgent-runtime.tar.gz" \
    "${USER}@${HOST}:${REMOTE_DIR}/"
  if [[ -f "$WORKDIR/files/GenericAgent-runtime.tar.gz.sha256" ]]; then
    rsync -av -e "$RSYNC_SSH" \
      "$WORKDIR/files/GenericAgent-runtime.tar.gz.sha256" \
      "${USER}@${HOST}:${REMOTE_DIR}/"
  fi
  rsync -av --checksum -e "$RSYNC_SSH" \
    "$WORKDIR/runtime-latest.json" \
    "${USER}@${HOST}:${REMOTE_DIR}/"

  if [[ -n "$CHOWN_TO" ]]; then
    "${SSH[@]}" "${USER}@${HOST}" "chown -R '$CHOWN_TO' '$REMOTE_DIR' && chmod 755 '$REMOTE_DIR' && chmod 644 '$REMOTE_DIR'/*"
  fi

  echo "==> verify public runtime feed"
  # Served via the /desktop/files/ wildcard route: no plan-server route change needed.
  curl -fsS "${PUBLIC_BASE}/runtime-latest.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["version"], d["tag"], d["runtime"]["sha256"][:16])'
  echo "OK fast-lane mirrored $TAG runtime → plan.khrey.com/desktop/"
  exit 0
fi

echo "==> pack TokenPlan plugin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
python3 "$REPO_ROOT/extras/ga-tokenplan-import/pack_release.py" \
  --out-dir "$WORKDIR/files" \
  --public-base "$PUBLIC_BASE"
mv "$WORKDIR/files/plugin-manifest.json" "$WORKDIR/plugin-manifest.json"
PLUGIN_ZIP="$(ls "$WORKDIR/files"/ga-tokenplan-import-*.zip | head -1)"
[[ -n "$PLUGIN_ZIP" && -f "$PLUGIN_ZIP" ]] || { echo "plugin zip missing after pack" >&2; exit 1; }

echo "==> build latest.json"
python3 - "$WORKDIR" "$TAG" "$PUBLIC_BASE" "$META_JSON" "$WORKDIR/plugin-manifest.json" <<'PY'
import hashlib, json, re, sys
from pathlib import Path

work, tag, base, meta_path, plugin_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3].rstrip("/"), Path(sys.argv[4]), Path(sys.argv[5])
files = work / "files"
meta = json.loads(meta_path.read_text(encoding="utf-8"))
plugin = json.loads(plugin_path.read_text(encoding="utf-8"))

def sha_of(name: str) -> str:
    p = files / name
    return hashlib.sha256(p.read_bytes()).hexdigest()

def size_of(name: str) -> int:
    return (files / name).stat().st_size

def asset(name: str) -> dict:
    return {
        "name": name,
        "url": f"{base}/{name}",
        "size": size_of(name),
        "sha256": sha_of(name),
    }

ver = tag
if tag.startswith("desktop-portable-"):
    ver = tag[len("desktop-portable-"):]
body = (meta.get("body") or "").strip()
# Prefer a short first non-empty line as notes; keep EN parallel if present.
lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
notes = lines[0][:240] if lines else f"GenericAgent Desktop {ver}"
notes_en = notes
for ln in lines:
    if re.search(r"[A-Za-z]{3,}", ln) and "GenericAgent" in ln:
        notes_en = ln[:240]
        break

out = {
    "version": ver,
    "tag": tag,
    "publishedAt": meta.get("publishedAt") or "",
    "notes": notes,
    "notes_en": notes_en,
    "runtime": asset("GenericAgent-runtime.tar.gz"),
    "platforms": {
        "windows": asset("GenericAgent-Desktop-Windows-Portable.zip"),
        "macos": asset("GenericAgent-Desktop-macOS.dmg"),
        "linux": asset("GenericAgent-Desktop-Linux-Portable.tar.gz"),
    },
    "plugin": plugin,
}
(work / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({
    "version": ver,
    "tag": tag,
    "runtime_sha": out["runtime"]["sha256"][:16],
    "plugin": plugin.get("version"),
    "plugin_sha": str(plugin.get("sha256") or "")[:16],
}, ensure_ascii=False))
PY

if [[ "$DRY" -eq 1 ]]; then
  echo "==> dry-run: would rsync to ${USER}@${HOST}:${REMOTE_DIR}/"
  ls -lh "$WORKDIR/files"
  cat "$WORKDIR/latest.json"
  cat "$WORKDIR/plugin-manifest.json"
  exit 0
fi

echo "==> rsync → ${USER}@${HOST}:${REMOTE_DIR}/"
"${SSH[@]}" "${USER}@${HOST}" "mkdir -p '$REMOTE_DIR'"
rsync -av --checksum -e "$RSYNC_SSH" \
  "$WORKDIR/files/GenericAgent-Desktop-Windows-Portable.zip" \
  "$WORKDIR/files/GenericAgent-Desktop-macOS.dmg" \
  "$WORKDIR/files/GenericAgent-Desktop-Linux-Portable.tar.gz" \
  "$WORKDIR/files/GenericAgent-runtime.tar.gz" \
  "$PLUGIN_ZIP" \
  "$WORKDIR/latest.json" \
  "$WORKDIR/plugin-manifest.json" \
  "${USER}@${HOST}:${REMOTE_DIR}/"

# Keep optional sidecar if present
if [[ -f "$WORKDIR/files/GenericAgent-runtime.tar.gz.sha256" ]]; then
  rsync -av -e "$RSYNC_SSH" \
    "$WORKDIR/files/GenericAgent-runtime.tar.gz.sha256" \
    "${USER}@${HOST}:${REMOTE_DIR}/"
fi

if [[ -n "$CHOWN_TO" ]]; then
  "${SSH[@]}" "${USER}@${HOST}" "chown -R '$CHOWN_TO' '$REMOTE_DIR' && chmod 755 '$REMOTE_DIR' && chmod 644 '$REMOTE_DIR'/*"
fi

echo "==> verify public feed"
curl -fsS "${PUBLIC_BASE%/files}/latest.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("plugin") or {}; print(d["version"], d["tag"], d["runtime"]["sha256"][:16], p.get("version"), str(p.get("sha256") or "")[:16])'
# plugin-manifest.json: the top-level path is a dedicated route in the plan
# server's Go router and has regressed to 404 before while the uploaded file
# itself served fine under /files/. The mirror's deliverable is the upload -
# verify loudly, but never let a server routing regression paint the whole
# release red after everything already synced.
if ! curl -fsS "${PUBLIC_BASE%/files}/plugin-manifest.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("plugin", d["version"], d["sha256"][:16], d["url"])'; then
  echo "WARN: ${PUBLIC_BASE%/files}/plugin-manifest.json not served (plan server route regression?)"
  curl -fsS "${PUBLIC_BASE}/plugin-manifest.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("plugin (files/ fallback)", d["version"], d["sha256"][:16], d["url"])' \
    || echo "WARN: files/plugin-manifest.json also unreachable - check the upload"
fi
echo "OK mirrored $TAG → plan.khrey.com/desktop/"
