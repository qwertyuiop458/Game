#!/usr/bin/env bash
set -euo pipefail

APK_PATH="${1:-ru.playsoftware.j2meloader-101.apk}"
JAR_PATH="${2:-240x320-rus-zombie-infection.jar}"
ARTIFACT_DIR="${3:-.artifacts/emulator}"
PACKAGE_NAME="ru.playsoftware.j2meloader"
JAR_DEVICE_PATH="/sdcard/Download/game.jar"
STRICT_MODE="${STRICT_MODE:-1}"

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
  adb shell pm list packages >"$ARTIFACT_DIR/packages.txt" 2>/dev/null
  set -e
}

write_result_summary() {
  local status="$1"
  local reason="$2"
  {
    echo "status=$status"
    echo "reason=$reason"
    echo "apk_path=$APK_PATH"
    echo "jar_path=$JAR_PATH"
    echo "jar_device_path=$JAR_DEVICE_PATH"
    echo "strict_mode=$STRICT_MODE"
  } >"$ARTIFACT_DIR/result.env"

  {
    echo "# J2ME CI run"
    echo ""
    echo "- status: **$status**"
    echo "- reason: $reason"
    echo "- apk: \\`$APK_PATH\\`"
    echo "- jar: \\`$JAR_PATH\\`"
    echo "- emulator path: \\`$JAR_DEVICE_PATH\\`"
  } >"$ARTIFACT_DIR/result.md"

  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    cat "$ARTIFACT_DIR/result.md" >>"$GITHUB_STEP_SUMMARY"
  fi
}

assert_outcome() {
  local expected_jar_name
  expected_jar_name="$(basename "$JAR_PATH" .jar | tr '[:upper:]' '[:lower:]')"
  local dump_file="$ARTIFACT_DIR/dumpsys-activities.txt"
  local log_file="$ARTIFACT_DIR/logcat.txt"

  local package_visible=0
  local jar_hint_visible=0

  if grep -qi "$PACKAGE_NAME" "$dump_file" 2>/dev/null; then
    package_visible=1
  fi

  if grep -Eiq "(game\.jar|$expected_jar_name|midlet|javax\.microedition|j2me)" "$dump_file" "$log_file" 2>/dev/null; then
    jar_hint_visible=1
  fi

  if [[ "$package_visible" == "1" && "$jar_hint_visible" == "1" ]]; then
    write_result_summary "success" "Detected J2ME loader activity and JAR/MIDlet hints in dumpsys/logcat"
    return 0
  fi

  write_result_summary "warning" "Could not prove JAR start from signals; inspect uploaded artifacts"
  if [[ "$STRICT_MODE" == "1" ]]; then
    log "Strict mode: failing because run confirmation signals are missing"
    return 1
  fi
  return 0
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
adb push "$JAR_PATH" "$JAR_DEVICE_PATH"

log "Clear previous logs"
adb logcat -c

log "Launch app via launcher intent"
adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1
sleep 4

log "Try ACTION_VIEW file intent"
adb shell am start \
  -a android.intent.action.VIEW \
  -d "file://$JAR_DEVICE_PATH" \
  -t "application/java-archive" || true
sleep 4

log "Try tapping common import/open labels if visible"
tap_text_if_present "Import" || true
tap_text_if_present "Open" || true
tap_text_if_present "game.jar" || true
tap_text_if_present "Download" || true
sleep 3

log "Try launching game entry if it appears"
tap_text_if_present "game" || true
tap_text_if_present "240x320" || true
tap_text_if_present "start" || true
sleep 3

collect_artifacts
assert_outcome
log "Artifacts saved to $ARTIFACT_DIR"
