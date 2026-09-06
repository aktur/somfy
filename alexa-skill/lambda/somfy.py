"""Somfy cloud auth (Ginaite multi-site) + Overkiz API calls."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

SOMFY_SSO_URL = "https://accounts.somfy.com/oauth/oauth/v2/token/jwt"
GINAITE_URL = (
    "https://ginaite-prod.ovkube.net/realms/somfy-tahoma"
    "/protocol/openid-connect/token"
)
BOB_API = "https://backoffice-service.ovkube.net/site-api/public/v1"
OVERKIZ_API = "https://ha101-1.overkiz.com/enduser-mobile-web/enduserAPI"

# Public client — same credentials the TaHoma mobile app uses
CLIENT_ID = (
    "0d8e920c-1478-11e7-a377-02dd59bd3041"
    "_1ewvaqmclfogo4kcsoo0c8k4kso884owg08sg8c40sk4go4ksg"
)
CLIENT_SECRET = "12k73w1n540g8o4cokg0cw84cog840k84cwggscwg884004kgk"

ROLLER_SHUTTER_TYPE = "RollerShutter"


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _get_json(url: str, token: str) -> dict | list:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _post_json(url: str, token: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _jwt_payload(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    return json.loads(base64.b64decode(payload))


def ginaite_token_from_sso(sso_token: str) -> tuple[str, str]:
    """Exchange a Somfy SSO token for a Ginaite token. Returns (access, refresh)."""
    resp = _post_form(GINAITE_URL, {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": CLIENT_ID,
        "subject_token": sso_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "subject_issuer": "somfy-customer",
    })
    return resp["access_token"], resp["refresh_token"]


def scoped_token(ginaite_refresh: str, site_oid: str) -> str:
    """Mint a site-scoped Overkiz token for the given siteOID."""
    resp = _post_form(f"{GINAITE_URL}?siteOID={site_oid}", {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": ginaite_refresh,
    })
    return resp["access_token"]


def list_sites(ginaite_access: str) -> list[dict]:
    """Return all sites from BOB: [{site_oid, name, gateway_id}, ...]."""
    sites = []
    resp = _get_json(f"{BOB_API}/sites?withGateways=true&limit=20", ginaite_access)
    for site in resp.get("results", []):
        for sub in site.get("subSites", []):
            for gw in sub.get("gateways", []):
                sites.append({
                    "site_oid": site["siteOID"],
                    "name": site.get("name", site["siteOID"]),
                    "gateway_id": gw["gatewayId"],
                })
    return sites


def get_devices(site_token: str) -> list[dict]:
    """Return all devices for a site-scoped token."""
    return _get_json(f"{OVERKIZ_API}/setup/devices", site_token)


def get_setup(site_token: str) -> dict:
    """Return full setup (devices + places) for a site-scoped token."""
    return _get_json(f"{OVERKIZ_API}/setup", site_token)


def send_command(site_token: str, device_url: str, command: str, params: list) -> dict:
    """Send a single command to a device."""
    return _post_json(f"{OVERKIZ_API}/exec/apply", site_token, {
        "label": f"{command} via Alexa",
        "actions": [{"deviceURL": device_url, "commands": [{"name": command, "parameters": params}]}],
    })


def set_closure(site_token: str, device_url: str, closure: int) -> dict:
    """Set closure 0 (open) … 100 (closed)."""
    return send_command(site_token, device_url, "setClosure", [closure])


def get_closure(site_token: str, device_url: str) -> int | None:
    """Return current closure percentage, or None if unavailable."""
    devices = get_devices(site_token)
    for dev in devices:
        if dev["deviceURL"] == device_url:
            for state in dev.get("states", []):
                if state["name"] == "core:ClosureState":
                    return int(state["value"])
    return None


def is_roller_shutter(device: dict) -> bool:
    return ROLLER_SHUTTER_TYPE in device.get("controllableName", "")
