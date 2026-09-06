#!/usr/bin/env bash
set -euo pipefail

# Somfy TaHoma — List all connected devices
# Usage: ./list-devices.sh [gateway-pin] [bearer-token]
#   or set SOMFY_GATEWAY, SOMFY_TOKEN, SOMFY_USER, SOMFY_PASS env vars

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACERT="$SCRIPT_DIR/overkiz-root-ca-2048.crt"
NAME_MAP="$SCRIPT_DIR/device-names.json"

# --- Helpers ---
die() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" &>/dev/null || die "'$1' is required but not installed."; }
need curl; need jq; need python3

# --- Config (override via env or positional args) ---
GATEWAY="${SOMFY_GATEWAY:-${1:-}}"
TOKEN="${SOMFY_TOKEN:-${2:-}}"
PORT="${SOMFY_PORT:-8443}"

[[ -n "$GATEWAY" ]] || die "Set SOMFY_GATEWAY env var or pass gateway hostname as first argument"
[[ -n "$TOKEN"   ]] || die "Set SOMFY_TOKEN env var or pass developer token as second argument"

BASE_URL="https://${GATEWAY}:${PORT}/enduser-mobile-web/1/enduserAPI"

# Extract PIN from gateway hostname (gateway-XXXX-XXXX-XXXX.local -> XXXX-XXXX-XXXX)
GW_PIN=$(echo "$GATEWAY" | grep -oE '[0-9]+-[0-9]+-[0-9]+')

# Somfy cloud constants (Ginaite multi-site auth, from pyoverkiz PR #2168)
SOMFY_SSO_URL="https://accounts.somfy.com/oauth/oauth/v2/token/jwt"
GINAITE_URL="https://ginaite-prod.ovkube.net/realms/somfy-tahoma/protocol/openid-connect/token"
BOB_API="https://backoffice-service.ovkube.net/site-api/public/v1"
OVERKIZ_API="https://ha101-1.overkiz.com/enduser-mobile-web/enduserAPI"
CLIENT_ID="0d8e920c-1478-11e7-a377-02dd59bd3041_1ewvaqmclfogo4kcsoo0c8k4kso884owg08sg8c40sk4go4ksg"
CLIENT_SECRET="12k73w1n540g8o4cokg0cw84cog840k84cwggscwg884004kgk"

# --- Build name map from Somfy cloud if not present ---
if [[ ! -f "$NAME_MAP" ]]; then
  echo "Name map not found. Fetching full device names from Somfy cloud..."
  echo

  SOMFY_USER="${SOMFY_USER:-}"
  SOMFY_PASS="${SOMFY_PASS:-}"
  if [[ -z "$SOMFY_USER" ]]; then read -rp  "Somfy account email: "    SOMFY_USER; fi
  if [[ -z "$SOMFY_PASS" ]]; then read -rsp "Somfy account password: " SOMFY_PASS; echo; fi

  # Step 1: SSO password grant (classic Somfy Accounts)
  echo "Authenticating (SSO)..."
  SSO_TOKEN=$(curl -s --fail -X POST "$SOMFY_SSO_URL" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=$CLIENT_ID" \
    --data-urlencode "client_secret=$CLIENT_SECRET" \
    --data-urlencode "username=$SOMFY_USER" \
    --data-urlencode "password=$SOMFY_PASS" \
    | jq -r '.access_token // empty') \
    || die "SSO login failed. Check credentials."
  [[ -n "$SSO_TOKEN" ]] || die "No SSO token returned."

  # Step 2: Exchange SSO token for Ginaite token (multi-site capable)
  echo "Exchanging token (Ginaite)..."
  GINAITE_RESP=$(curl -s --fail -X POST "$GINAITE_URL" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
    --data-urlencode "client_id=$CLIENT_ID" \
    --data-urlencode "subject_token=$SSO_TOKEN" \
    --data-urlencode "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
    --data-urlencode "subject_issuer=somfy-customer") \
    || die "Ginaite token exchange failed."

  GINAITE_TOKEN=$(echo "$GINAITE_RESP" | jq -r '.access_token // empty')
  REFRESH_TOKEN=$(echo "$GINAITE_RESP" | jq -r '.refresh_token // empty')
  [[ -n "$GINAITE_TOKEN" ]] || die "No Ginaite token returned."

  # Step 3: Find the siteOID for our gateway PIN via the BOB site directory
  echo "Looking up site for gateway $GW_PIN..."
  SITE_OID=$(curl -s "$BOB_API/sites?withGateways=true&limit=20" \
    -H "Authorization: Bearer $GINAITE_TOKEN" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
pin = '$GW_PIN'
for site in data.get('results', []):
    for sub in site.get('subSites', []):
        for gw in sub.get('gateways', []):
            if gw.get('gatewayId') == pin:
                print(site['siteOID'])
                sys.exit(0)
") || true

  [[ -n "$SITE_OID" ]] || die "Could not find siteOID for gateway $GW_PIN in your Somfy account."
  echo "Found site OID: $SITE_OID"

  # Step 4: Mint a site-scoped token
  echo "Minting site-scoped token..."
  SCOPED_TOKEN=$(curl -s --fail -X POST "${GINAITE_URL}?siteOID=${SITE_OID}" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=refresh_token" \
    --data-urlencode "client_id=$CLIENT_ID" \
    --data-urlencode "refresh_token=$REFRESH_TOKEN" \
    | jq -r '.access_token // empty') \
    || die "Failed to mint site-scoped token."
  [[ -n "$SCOPED_TOKEN" ]] || die "No site-scoped token returned."

  # Step 5: Fetch cloud setup — use 'label' field (full name), NOT core:NameState (firmware 16-char limit)
  echo "Fetching device labels from cloud setup..."
  curl -s --fail "$OVERKIZ_API/setup" \
    -H "Authorization: Bearer $SCOPED_TOKEN" \
    | jq '
      [ .devices[] | select(.deviceURL != null) | {
          key:   .deviceURL,
          value: (.label // .deviceURL)
        }
      ] | from_entries
    ' > "$NAME_MAP" || die "Cloud setup request failed."

  mapped=$(jq 'length' "$NAME_MAP")
  echo "Saved $mapped device name(s) to $NAME_MAP"
  echo
fi

# --- Fetch local devices ---
local_curl_opts=(--silent --fail --show-error
  -H "accept: application/json"
  -H "Authorization: Bearer ${TOKEN}")

if [[ -f "$CACERT" ]]; then
  local_curl_opts+=(--cacert "$CACERT")
else
  echo "WARNING: CA cert not found — skipping TLS verification" >&2
  local_curl_opts+=(-k)
fi

echo "Querying ${BASE_URL}/setup/devices ..."
echo

response=$(curl "${local_curl_opts[@]}" "${BASE_URL}/setup/devices") \
  || die "Request failed. Check gateway address and token."

# --- Output ---
device_count=$(echo "$response" | jq 'length')
echo "Found ${device_count} device(s):"
echo

echo "$response" | jq -r --slurpfile names "$NAME_MAP" '
  ($names[0]) as $map |
  .[] | {
    name:      ($map[.deviceURL] // .label),
    url:       .deviceURL,
    type:      .controllableName,
    available: .available,
    states:    (.states // [] | map(select(.name | test("core:OnOff|core:TargetClosure|core:Status|core:Closure"; "i")) | "\(.name | split(":")[1]): \(.value)") | join(", "))
  } | "[\(if .available then "✓" else "✗" end)] \(.name)
      URL:    \(.url)
      Type:   \(.type)
      States: \(if .states == "" then "(none)" else .states end)
"'
