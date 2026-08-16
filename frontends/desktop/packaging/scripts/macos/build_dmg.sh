#!/usr/bin/env bash
# Build a self-contained macOS DMG from this checkout (arm64 or x86_64).
# Usage (from repo root):
#   bash frontends/desktop/packaging/scripts/macos/build_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
DESKTOP="$ROOT/frontends/desktop"
OUT="${GA_DMG_OUT:-$ROOT/artifacts/macos/out}"
STAGE="$ROOT/artifacts/macos/dmg-stage"
RUNTIME_SRC="$ROOT/artifacts/macos/runtime-src"

log() { printf '==> %s\n' "$*"; }

cd "$ROOT"
rm -rf "$STAGE" "$RUNTIME_SRC"
mkdir -p "$OUT" "$STAGE" "$RUNTIME_SRC"

if [[ ! -d "$DESKTOP/node_modules/@tauri-apps/cli" ]]; then
  log "npm install"
  (cd "$DESKTOP" && npm install)
fi

log "tauri build --bundles app"
(cd "$DESKTOP" && npm run tauri -- build --bundles app)

APP_SRC="$(find "$DESKTOP/src-tauri/target/release/bundle/macos" -maxdepth 1 -name '*.app' -type d | head -n 1)"
[[ -n "$APP_SRC" ]] || { echo "No .app found" >&2; exit 1; }
log "app: $APP_SRC"

log "download embedded CPython 3.12"
ARCH="$(uname -m)"
case "$ARCH" in
  arm64) PBS_ARCH="aarch64-apple-darwin" ;;
  x86_64) PBS_ARCH="x86_64-apple-darwin" ;;
  *) echo "unsupported arch $ARCH" >&2; exit 1 ;;
esac
PBS_URL="$(python3 - <<PY
import json, urllib.request
api="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
data=json.load(urllib.request.urlopen(api, timeout=60))
arch="${PBS_ARCH}"
for a in data.get("assets", []):
    name=a.get("name","")
    if "cpython-3.12" in name and arch in name and name.endswith("install_only.tar.gz") and "stripped" not in name:
        print(a["browser_download_url"]); break
else:
    raise SystemExit("no python-build-standalone asset")
PY
)"
log "$PBS_URL"
curl -L --fail --retry 3 -o /tmp/pbs-macos.tar.gz "$PBS_URL"
tar -xzf /tmp/pbs-macos.tar.gz -C "$RUNTIME_SRC"
PY="$RUNTIME_SRC/python/bin/python3"
"$PY" --version

log "offline wheels"
mkdir -p "$RUNTIME_SRC/wheels"
"$PY" -m pip download --dest "$RUNTIME_SRC/wheels" \
  "requests>=2.28" "beautifulsoup4>=4.12" "bottle>=0.12" "simple-websocket-server>=0.4" "aiohttp>=3.9" psutil \
  fastapi uvicorn websockets pydantic setuptools wheel

cp "$DESKTOP/packaging/scripts/macos/install_macos.sh" "$RUNTIME_SRC/install_macos.sh"
chmod +x "$RUNTIME_SRC/install_macos.sh"

log "copy runtime app (no secrets / build junk)"
mkdir -p "$RUNTIME_SRC/app"
tar \
  --exclude='.git' --exclude='.github' \
  --exclude='frontends/desktop/src-tauri' \
  --exclude='frontends/desktop/node_modules' \
  --exclude='frontends/desktop/packaging' --exclude='docs' \
  --exclude='assets/demo' --exclude='assets/images' \
  --exclude='assets/GenericAgent_Technical_Report.pdf' \
  --exclude='artifacts' \
  --exclude='*/node_modules' --exclude='*/target' \
  --exclude='*/.venv' --exclude='.venv' \
  --exclude='*/__pycache__' --exclude='*.pyc' \
  --exclude='mykey.py' --exclude='temp' --exclude='tmp' \
  --exclude='.DS_Store' \
  -C "$ROOT" -cf - . | tar -xf - -C "$RUNTIME_SRC/app"
test -f "$RUNTIME_SRC/app/agentmain.py"
test -f "$RUNTIME_SRC/app/plugins/subscription_portal.py"
test -f "$RUNTIME_SRC/app/extras/ga-tokenplan-import/ga_tokenplan_import/subscription_portal.py"

DMG_APP="$STAGE/GenericAgent.app"
ditto "$APP_SRC" "$DMG_APP"
mkdir -p "$DMG_APP/Contents/Resources"
ditto "$RUNTIME_SRC" "$DMG_APP/Contents/Resources/runtime"
codesign --force --deep --sign - "$DMG_APP" || true
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/open_anyway.command" <<'EOF'
#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="/Applications/GenericAgent.app"
if [[ ! -d "$TARGET" ]]; then
  TARGET="$DIR/GenericAgent.app"
fi
xattr -cr "$TARGET" 2>/dev/null || true
osascript -e 'display dialog "GenericAgent 已处理完成。请将 GenericAgent.app 拖入 Applications 后启动。" buttons {"OK"} default button "OK"' >/dev/null 2>&1 || true
EOF
chmod +x "$STAGE/open_anyway.command"

cat > "$STAGE/readme.txt" <<'EOF'
GenericAgent Desktop（本仓桌面版）

安装
1. 把 GenericAgent.app 拖进 Applications
2. 从「应用程序」打开
3. 设置 / 模型菜单里的 GA Token 会打开 https://plan.khrey.com/

若提示无法验证开发者：双击 open_anyway.command，或右键 App → 打开。
EOF

DMG="$OUT/GenericAgent-Desktop-macOS.dmg"
log "hdiutil $DMG"
rm -f "$DMG"
hdiutil create -volname "GenericAgent Desktop" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
shasum -a 256 "$DMG" | tee "$DMG.sha256"
ls -lh "$DMG"
log "done: $DMG"
