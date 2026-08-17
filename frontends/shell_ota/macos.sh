#!/usr/bin/env bash
# Shell OTA helper — macOS (system bash only). Arg1 = manifest.json absolute path.
set -euo pipefail
MANIFEST="${1:?manifest required}"
LOG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("logFile",""))' "$MANIFEST")"
[[ -n "$LOG" ]] || LOG="/tmp/ga-shell-ota.log"
exec >>"$LOG" 2>&1
log() { echo "[$(date '+%H:%M:%S')] $*"; }

eval "$(python3 - "$MANIFEST" <<'PY'
import json, shlex, sys
m = json.loads(open(sys.argv[1], encoding="utf-8").read())
def exp(k, v):
    print(f"{k}={shlex.quote(str(v))}")
exp("LIVE_APP", m.get("liveApp", ""))
exp("LIVE_RT", m.get("liveRuntimeApp", ""))
exp("NEW_SHELL", m.get("newShell", ""))
exp("NEW_RT", m.get("newRuntimeApp", ""))
exp("LAYOUT", m.get("layout", ""))
exp("SHELL_PID", m.get("pid", 0))
exp("BRIDGE_PID", m.get("bridgePid", 0))
exp("VERSION", m.get("version", ""))
exp("OLD_BUILD", m.get("oldBuildId", ""))
exp("BRIDGE_PORT", m.get("bridgePort", 14168))
exp("LOCK", m.get("lockFile", "/tmp/ga-shell-ota.lock"))
exp("WORK", m.get("workDir", ""))
prot = m.get("protected") or []
print("PROTECTED=(" + " ".join(shlex.quote(x) for x in prot) + ")")
PY
)"

PROT_DIR="$WORK/prot"
HASH_FILE="$WORK/prot_hashes.txt"
mkdir -p "$PROT_DIR"

if [[ -f "$LOCK" ]]; then
  op="$(cat "$LOCK" 2>/dev/null || true)"
  if [[ -n "$op" ]] && kill -0 "$op" 2>/dev/null; then
    log "lock held by $op"; exit 1
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

wait_dead() {
  local pid="$1" n="${2:-120}"
  [[ -n "$pid" && "$pid" != "0" ]] || return 0
  for _ in $(seq 1 "$n"); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  return 1
}
wait_dead "$SHELL_PID" 120 || { log "shell still alive"; exit 1; }
wait_dead "$BRIDGE_PID" 60 || log "bridge still alive (continuing)"

free_port() {
  local port="$1" pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    log "killing listeners on $port: $pids"
    for p in $pids; do kill -9 "$p" 2>/dev/null || true; done
    sleep 0.4
  fi
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  [[ -z "$pids" ]] || { log "port $port busy"; exit 1; }
}
free_port "$BRIDGE_PORT"
free_port 19736
free_port 19737

is_protected() {
  local rel="$1" p
  for p in "${PROTECTED[@]}"; do
    if [[ "$p" == */ ]]; then
      local b="${p%/}"
      [[ "$rel" == "$b" || "$rel" == "$b"/* ]] && return 0
    else
      [[ "$rel" == "$p" ]] && return 0
    fi
  done
  return 1
}

snapshot() {
  : > "$HASH_FILE"
  local name src dst
  for name in "${PROTECTED[@]}"; do
    src="$LIVE_RT/${name%/}"
    [[ -e "$src" || -L "$src" ]] || continue
    dst="$PROT_DIR/${name%/}"
    mkdir -p "$(dirname "$dst")"
    if [[ -f "$src" && ! -L "$src" ]]; then
      shasum -a 256 "$src" | awk '{print $1}' | while read -r h; do echo "${name%/} $h" >> "$HASH_FILE"; done
    fi
    if mv "$src" "$dst" 2>/dev/null; then
      log "snap mv ${name%/}"
    else
      ditto "$src" "$dst"
      rm -rf "$src"
      log "snap copy ${name%/}"
    fi
  done
}

restore() {
  local name src dst
  for name in "${PROTECTED[@]}"; do
    src="$PROT_DIR/${name%/}"
    [[ -e "$src" || -L "$src" ]] || continue
    dst="$LIVE_RT/${name%/}"
    mkdir -p "$(dirname "$dst")"
    rm -rf "$dst"
    if mv "$src" "$dst" 2>/dev/null; then
      log "restore mv ${name%/}"
    else
      ditto "$src" "$dst"
      log "restore copy ${name%/}"
    fi
  done
}

verify() {
  [[ -s "$HASH_FILE" ]] || return 0
  while read -r name want; do
    [[ -z "$name" ]] && continue
    local f="$LIVE_RT/$name"
    [[ -f "$f" ]] || { log "missing $name"; return 1; }
    local got
    got="$(shasum -a 256 "$f" | awk '{print $1}')"
    [[ "$got" == "$want" ]] || { log "hash mismatch $name"; return 1; }
  done < "$HASH_FILE"
  return 0
}

overlay_dir() {
  local src="$1" dst="$2"
  [[ -d "$src" ]] || return 0
  mkdir -p "$dst"
  local f rel
  while IFS= read -r -d '' f; do
    [[ -f "$f" || -L "$f" ]] || continue
    rel="${f#"$src"/}"
    is_protected "$rel" && continue
    mkdir -p "$(dirname "$dst/$rel")"
    rm -f "$dst/$rel"
    cp -p "$f" "$dst/$rel"
  done < <(find "$src" \( -type f -o -type l \) -print0)
}

rollback() {
  log "ROLLBACK"
  if [[ -e "${LIVE_APP}.ota-bak" ]]; then
    rm -rf "$LIVE_APP"
    mv "${LIVE_APP}.ota-bak" "$LIVE_APP"
  fi
  if [[ "$LAYOUT" == "mac-embedded" ]]; then
    LIVE_RT="$LIVE_APP/Contents/Resources/runtime/app"
  fi
  restore || true
  open "$LIVE_APP" || true
}

log "snapshot from $LIVE_RT"
snapshot

log "swap $NEW_SHELL -> $LIVE_APP"
rm -rf "${LIVE_APP}.ota-bak"
mv "$LIVE_APP" "${LIVE_APP}.ota-bak"
ditto "$NEW_SHELL" "$LIVE_APP"

if [[ "$LAYOUT" == "mac-embedded" ]]; then
  LIVE_RT="$LIVE_APP/Contents/Resources/runtime/app"
fi
mkdir -p "$LIVE_RT"

if [[ "$LAYOUT" == "mac-portable" && -n "$NEW_RT" && -d "$NEW_RT" ]]; then
  log "overlay runtime"
  overlay_dir "$NEW_RT" "$LIVE_RT"
fi

log "restore PROTECTED"
restore
verify || { rollback; exit 1; }

# SHELL_VERSION before codesign
SV_DIR="$(dirname "$LIVE_RT")"
echo "$VERSION" > "$SV_DIR/SHELL_VERSION"

log "xattr + ad-hoc sign"
xattr -cr "$LIVE_APP" || true
codesign --force --deep --sign - "$LIVE_APP" || true

log "open"
open "$LIVE_APP"

ok=0
for _ in $(seq 1 60); do
  sleep 1
  body="$(curl -fsS --max-time 2 "http://127.0.0.1:${BRIDGE_PORT}/identity" 2>/dev/null || true)"
  [[ -n "$body" ]] || continue
  bid="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("build_id",""))' "$body" 2>/dev/null || true)"
  if [[ -n "$OLD_BUILD" ]]; then
    if [[ -n "$bid" && "$bid" != "$OLD_BUILD" ]]; then ok=1; break; fi
    log "waiting new build (got=$bid)"
  else
    ok=1; break
  fi
done
[[ "$ok" -eq 1 ]] || { log "identity check failed"; rollback; exit 1; }

log "OK remove bak"
rm -rf "${LIVE_APP}.ota-bak"
exit 0
