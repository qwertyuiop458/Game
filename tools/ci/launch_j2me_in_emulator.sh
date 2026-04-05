#!/usr/bin/env bash
set -euo pipefail

APK_SOURCE="${1:-ru.playsoftware.j2meloader-101.apk}"
JAR_SOURCE="${2:-240x320-rus-zombie-infection.jar}"
ARTIFACT_DIR="${3:-.artifacts/emulator}"
PACKAGE_NAME="ru.playsoftware.j2meloader"
JAR_DEVICE_PATH="/sdcard/Download/game.jar"
STRICT_MODE="${STRICT_MODE:-1}"

mkdir -p "$ARTIFACT_DIR"

log() { printf '[run-j2me] %s\n' "$*"; }

ADB_BIN=""

write_fallback_log() {
  local message="$1"
  local fallback_log="$ARTIFACT_DIR/fallback.log"
  {
    echo "[run-j2me] preflight failure"
    echo "message=$message"
    echo "hint=Install adb or configure ANDROID_SDK_ROOT/platform-tools"
    echo "hint=If GitHub/API calls fail, run tools/ci/check_github_connectivity.sh"
  } >"$fallback_log"

  if [[ -x "tools/ci/check_github_connectivity.sh" ]]; then
    bash tools/ci/check_github_connectivity.sh >>"$fallback_log" 2>&1 || true
  fi

  log "Fallback details written to $fallback_log"
}

bootstrap_adb() {
  local ensure_script="tools/ci/ensure_adb.sh"
  if [[ ! -x "$ensure_script" ]]; then
    write_fallback_log "Missing $ensure_script"
    return 1
  fi

  local resolved
  if resolved="$(bash "$ensure_script" "$ARTIFACT_DIR/adb-bootstrap")"; then
    ADB_BIN="$resolved"
    log "Using adb: $ADB_BIN"
    return 0
  fi

  write_fallback_log "adb unavailable after bootstrap attempts"
  return 1
}

adb() {
  "$ADB_BIN" "$@"
}

is_url() {
  [[ "$1" =~ ^https?:// ]]
}

prepare_source() {
  local source="$1"
  local out_name="$2"
  local out_path="$ARTIFACT_DIR/$out_name"

  if is_url "$source"; then
    log "Download $source -> $out_path"
    curl -fL --retry 3 --retry-delay 2 "$source" -o "$out_path"
    printf '%s' "$out_path"
    return 0
  fi

  if [[ -f "$source" ]]; then
    printf '%s' "$source"
    return 0
  fi

  log "Missing required file or URL is invalid: $source"
  exit 1
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

grant_storage_permissions() {
  set +e
  adb shell pm grant "$PACKAGE_NAME" android.permission.READ_EXTERNAL_STORAGE >/dev/null 2>&1
  adb shell pm grant "$PACKAGE_NAME" android.permission.WRITE_EXTERNAL_STORAGE >/dev/null 2>&1
  set -e
}

resolve_launcher_activity() {
  adb shell cmd package resolve-activity --brief "$PACKAGE_NAME" \
    | tr -d '\r' \
    | awk 'NF{last=$0} END{print last}'
}

launch_package() {
  local activity
  activity="$(resolve_launcher_activity || true)"

  if [[ -n "$activity" && "$activity" == *"/"* ]]; then
    log "Launch via explicit activity: $activity"
    adb shell am start -W -n "$activity" || true
  else
    log "Fallback launch via monkey"
    adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 || true
  fi
}

try_open_jar_via_intents() {
  adb shell am start -W \
    -a android.intent.action.VIEW \
    -d "file://$JAR_DEVICE_PATH" \
    -t "application/java-archive" || true

  adb shell am start -W \
    -a android.intent.action.VIEW \
    -d "file://$JAR_DEVICE_PATH" \
    -t "application/octet-stream" || true
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
    echo "apk_source=$APK_SOURCE"
    echo "jar_source=$JAR_SOURCE"
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
    echo "- apk source: \\`$APK_SOURCE\\`"
    echo "- jar source: \\`$JAR_SOURCE\\`"
    echo "- apk path: \\`$APK_PATH\\`"
    echo "- jar path: \\`$JAR_PATH\\`"
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

  if grep -Eiq "(game\.jar|$expected_jar_name|midlet|javax\.microedition|j2me|load jar|install midlet)" "$dump_file" "$log_file" 2>/dev/null; then
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

bootstrap_adb

APK_PATH="$(prepare_source "$APK_SOURCE" emulator.apk)"
JAR_PATH="$(prepare_source "$JAR_SOURCE" game.jar)"

adb start-server
adb wait-for-device

log "Disable animations"
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0

log "Install emulator APK: $APK_PATH"
adb install -r "$APK_PATH"
grant_storage_permissions

log "Push JAR into shared storage"
adb shell mkdir -p /sdcard/Download
adb push "$JAR_PATH" "$JAR_DEVICE_PATH"

log "Clear previous logs"
adb logcat -c

log "Launch app"
launch_package
sleep 4

log "Try opening JAR via intents"
try_open_jar_via_intents
sleep 4

log "Try tapping common import/open labels if visible"
tap_text_if_present "Import" || true
tap_text_if_present "Open" || true
tap_text_if_present "Start" || true
tap_text_if_present "Run" || true
tap_text_if_present "Импорт" || true
tap_text_if_present "Открыть" || true
tap_text_if_present "Запустить" || true
tap_text_if_present "game.jar" || true
tap_text_if_present "Download" || true
sleep 3

log "Try launching game entry if it appears"
tap_text_if_present "game" || true
tap_text_if_present "240x320" || true
tap_text_if_present "zombie" || true
sleep 3

collect_artifacts
assert_outcome
log "Artifacts saved to $ARTIFACT_DIR"
