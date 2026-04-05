#!/usr/bin/env bash
set -euo pipefail

# Prints absolute path to adb on success.
# Priority order:
#   1) vendored platform-tools in repo (offline)
#   2) existing PATH
#   3) Android SDK paths
#   4) apt install
#   5) download platform-tools

WORK_DIR="${1:-.artifacts/adb-bootstrap}"
LOG_FILE="$WORK_DIR/ensure_adb.log"
mkdir -p "$WORK_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENDORED_PT_DIR="$SCRIPT_DIR/vendor/platform-tools"
VENDORED_PT_ZIP="$SCRIPT_DIR/vendor/platform-tools-latest-linux.zip"

log() {
  printf '[ensure-adb] %s\n' "$*" | tee -a "$LOG_FILE" >&2
}

# === VENDORING (highest-priority, offline) ===
if [[ -x "$VENDORED_PT_DIR/adb" ]]; then
  log "Found vendored platform-tools directory: $VENDORED_PT_DIR"
  printf '%s\n' "$VENDORED_PT_DIR/adb"
  exit 0
fi

if [[ -f "$VENDORED_PT_ZIP" ]]; then
  if command -v unzip >/dev/null 2>&1; then
    vendored_extract_root="$WORK_DIR/vendor-platform-tools"
    mkdir -p "$vendored_extract_root"
    log "Found vendored zip: $VENDORED_PT_ZIP (extracting)"
    if unzip -o "$VENDORED_PT_ZIP" -d "$vendored_extract_root" >>"$LOG_FILE" 2>&1; then
      if [[ -x "$vendored_extract_root/platform-tools/adb" ]]; then
        printf '%s\n' "$vendored_extract_root/platform-tools/adb"
        exit 0
      fi
    fi
    log "Vendored zip was found, but adb was not produced after extraction"
  else
    log "Vendored zip exists but unzip is unavailable"
  fi
fi

if command -v adb >/dev/null 2>&1; then
  command -v adb
  exit 0
fi

for candidate in \
  "${ANDROID_SDK_ROOT:-}/platform-tools/adb" \
  "${ANDROID_HOME:-}/platform-tools/adb" \
  "$HOME/Android/Sdk/platform-tools/adb"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    log "Found adb in SDK path: $candidate"
    printf '%s\n' "$candidate"
    exit 0
  fi
done

if command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
  log "Trying apt-get install adb"
  if sudo apt-get update >>"$LOG_FILE" 2>&1 && sudo apt-get install -y adb >>"$LOG_FILE" 2>&1; then
    if command -v adb >/dev/null 2>&1; then
      command -v adb
      exit 0
    fi
  else
    log "apt-get path failed (see $LOG_FILE)"
  fi
fi

if command -v curl >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then
  url="https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
  zip_path="$WORK_DIR/platform-tools.zip"
  extract_dir="$WORK_DIR/platform-tools"
  log "Trying platform-tools download: $url"
  if curl -fL --retry 2 "$url" -o "$zip_path" >>"$LOG_FILE" 2>&1 && unzip -o "$zip_path" -d "$WORK_DIR" >>"$LOG_FILE" 2>&1; then
    candidate="$extract_dir/adb"
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      exit 0
    fi
  else
    log "platform-tools download failed (see $LOG_FILE)"
  fi
fi

log "adb is unavailable"
exit 1
