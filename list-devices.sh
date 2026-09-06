#!/usr/bin/env bash
set -euo pipefail

# Somfy TaHoma — List all connected devices
# Usage: ./list-devices.sh [gateway-pin] [bearer-token]
#   or set SOMFY_GATEWAY and SOMFY_TOKEN env vars

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACERT="$SCRIPT_DIR/overkiz-root-ca-2048.crt"

# --- Config (override via env or positional args) ---
GATEWAY="${SOMFY_GATEWAY:-}"
TOKEN="${SOMFY_TOKEN:-}"
PORT="${SOMFY_PORT:-8443}"

[[ $# -ge 1 ]] && GATEWAY="$1"
[[ $# -ge 2 ]] && TOKEN="$2"

BASE_URL="https://${GATEWAY}:${PORT}/enduser-mobile-web/1/enduserAPI"

# --- Helpers ---
die() { echo "ERROR: $*" >&2; exit 1; }

curl_opts=(
  --silent
  --fail
  --show-error
  -H "accept: application/json"
  -H "Authorization: Bearer ${TOKEN}"
)

# Use bundled CA cert if available, otherwise skip TLS verification with a warning
if [[ -f "$CACERT" ]]; then
  curl_opts+=(--cacert "$CACERT")
else
  echo "WARNING: CA cert not found at $CACERT — skipping TLS verification" >&2
  curl_opts+=(-k)
fi

# --- Fetch devices ---
echo "Querying ${BASE_URL}/setup/devices ..."
echo

response=$(curl "${curl_opts[@]}" "${BASE_URL}/setup/devices") \
  || die "Request failed. Check gateway address and token."

# --- Output ---
if command -v jq &>/dev/null; then
  device_count=$(echo "$response" | jq 'length')
  echo "Found ${device_count} device(s):"
  echo

  echo "$response" | jq -r '.[] | {
    name:      ((.states // [] | map(select(.name == "core:NameState")) | first | .value) // .label),
    label:     .label,
    url:       .deviceURL,
    type:      .controllableName,
    available: .available,
    states:    (.states // [] | map(select(.name | test("core:OnOff|core:TargetClosure|core:Status"; "i")) | "\(.name | split(":")[1]): \(.value)") | join(", "))
  } | "[\(if .available then "✓" else "✗" end)] \(.name)
      URL:    \(.url)
      Type:   \(.type)
      States: \(if .states == "" then "(none)" else .states end)
"'
else
  # No jq — just pretty-print raw JSON
  echo "TIP: install jq for formatted output"
  echo
  echo "$response"
fi
