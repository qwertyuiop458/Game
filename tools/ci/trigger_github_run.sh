#!/usr/bin/env bash
set -euo pipefail

# Trigger GitHub Actions workflow_dispatch from CLI using only curl.
# Requires:
#   - GH_TOKEN env var with repo/workflow scope
#   - REPO env var in owner/repo format
# Optional:
#   - WORKFLOW_FILE (default: run-apk.yml)
#   - REF (default: main)
#   - APK_SOURCE, JAR_SOURCE, STRICT_MODE

: "${GH_TOKEN:?Set GH_TOKEN with Actions permission}"
: "${REPO:?Set REPO as owner/repo}"

WORKFLOW_FILE="${WORKFLOW_FILE:-run-apk.yml}"
REF="${REF:-main}"
APK_SOURCE="${APK_SOURCE:-ru.playsoftware.j2meloader-101.apk}"
JAR_SOURCE="${JAR_SOURCE:-240x320-rus-zombie-infection.jar}"
STRICT_MODE="${STRICT_MODE:-true}"

api_url="https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches"

payload=$(cat <<JSON
{
  "ref": "${REF}",
  "inputs": {
    "apk_source": "${APK_SOURCE}",
    "jar_source": "${JAR_SOURCE}",
    "strict_mode": "${STRICT_MODE}"
  }
}
JSON
)

curl -fL -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "${api_url}" \
  -d "${payload}"

echo "Triggered workflow '${WORKFLOW_FILE}' on '${REPO}' ref='${REF}'"
