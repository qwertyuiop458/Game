#!/usr/bin/env bash
set -euo pipefail

APK_PATH="${1:-ru.playsoftware.j2meloader-101.apk}"
JAR_PATH="${2:-240x320-rus-zombie-infection.jar}"
ARTIFACT_DIR="${3:-.artifacts/emulator}"
PACKAGE_NAME="ru.playsoftware.j2meloader"

mkdir -p "$ARTIFACT_DIR"

log() { printf '[run-j2me] %s\n' "$*"; }

require_file() {
  local p="$1"
  if [[ ! -f "$p" ]]; then
    log "Missing required file: $p"
    exit 1
  fi
}

center_from_bounds() {
  local bounds="$1"
  python3 - <<'PY' "$bounds"
import re
import sys
b = sys.argv[1]
m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
if not m:
    raise SystemExit(1)
x1, y1, x2, y2 = map(int, m.groups())
print((x1 + x2) // 2, (y1 + y2) // 2)
PY
}

find_bounds_by_text() {
  local text="$1"
  local dump_path="$ARTIFACT_DIR/window_dump.xml"
  adb shell uiautomator dump /sdcard/window_dump.xml >/dev/null 2>&1 || return 1
  adb pull /sdcard/window_dump.xml "$dump_path" >/dev/null 2>&1 || return 1
  python3 - <<'PY' "$dump_path" "$text"
import re
import sys
from xml.etree import ElementTree as ET

path, needle = sys.argv[1], sys.argv[2].lower()
root = ET.parse(path).getroot()
for node in root.iter('node'):
    txt = (node.attrib.get('text') or '') + ' ' + (node.attrib.get('content-desc') or '')
    if needle in txt.lower():
        b = node.attrib.get('bounds', '')
        if re.fullmatch(r"\[\d+,\d+\]\[\d+,\d+\]", b):
            print(b)
            raise SystemExit(0)
raise SystemExit(1)
PY
}

tap_text_if_present() {
  local needle="$1"
  local bounds
  if bounds="$(find_bounds_by_text "$needle")"; then
    local center
    center="$(center_from_bounds "$bounds")"
    local x y
    read -r x y <<<"$center"
    log "Tap by text '$needle' at bounds $bounds => ($x,$y)"
    adb shell input tap "$x" "$y"
    return 0
  fi
  return 1
}

collect_artifacts() {
  set +e
  adb logcat -d >"$ARTIFACT_DIR/logcat.txt" 2>/dev/null
  adb exec-out screencap -p >"$ARTIFACT_DIR/screen-final.png" 2>/dev/null
  adb shell dumpsys window windows >"$ARTIFACT_DIR/dumpsys-window.txt" 2>/dev/null
  adb shell dumpsys activity activities >"$ARTIFACT_DIR/dumpsys-activities.txt" 2>/dev/null
  set -e
}

require_file "$APK_PATH"
require_file "$JAR_PATH"

adb start-server
adb wait-for-device

log "Disable animations"
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0

log "Install emulator APK: $APK_PATH"
adb install -r "$APK_PATH"

log "Push JAR into shared storage"
adb shell mkdir -p /sdcard/Download
adb push "$JAR_PATH" /sdcard/Download/game.jar

log "Clear previous logs"
adb logcat -c

log "Launch app via launcher intent"
adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1
sleep 4

log "Try ACTION_VIEW file intent"
adb shell am start \
  -a android.intent.action.VIEW \
  -d "file:///sdcard/Download/game.jar" \
  -t "application/java-archive" || true
sleep 4

log "Try tapping common import/open labels if visible"
tap_text_if_present "Import" || true
tap_text_if_present "Open" || true
tap_text_if_present "game.jar" || true
sleep 3

log "Try launching game entry if it appears"
tap_text_if_present "game" || true
tap_text_if_present "240x320" || true
sleep 3

collect_artifacts
log "Artifacts saved to $ARTIFACT_DIR"
