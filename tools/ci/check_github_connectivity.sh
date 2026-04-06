#!/usr/bin/env bash
set -euo pipefail

DOMAINS=(
  "https://github.com"
  "https://api.github.com"
  "https://uploads.github.com"
  "https://raw.githubusercontent.com"
  "https://objects.githubusercontent.com"
  "https://codeload.github.com"
)

printf 'Proxy env:\n'
env | grep -Ei '^(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY|NO_PROXY|no_proxy)=' || true
printf '\n'

check_url() {
  local mode="$1"
  local url="$2"
  local code
  local rc=0

  if [[ "$mode" == "proxy" ]]; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' -I "$url") || rc=$?
  else
    code=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' -I "$url") || rc=$?
  fi

  if [[ $rc -eq 0 ]]; then
    printf '[%s] %-45s -> HTTP %s\n' "$mode" "$url" "$code"
  else
    printf '[%s] %-45s -> FAIL (curl rc=%s)\n' "$mode" "$url" "$rc"
  fi
}

printf '=== Through configured proxy ===\n'
for u in "${DOMAINS[@]}"; do
  check_url proxy "$u"
done

printf '\n=== Direct (no proxy) ===\n'
for u in "${DOMAINS[@]}"; do
  check_url direct "$u"
done

printf '\nDone. If proxy checks fail with 403 CONNECT, request allowlist from docs/network/github_proxy_allowlist.md\n'
