"""Alexa Smart Home Skill — Lambda entry point.


Directive routing:
  Alexa.Discovery        → handle_discovery
  Alexa.PowerController  → handle_power_controller  (open/close)
  Alexa.RangeController  → handle_range_controller  (set/adjust percentage)
  Alexa / ReportState    → handle_report_state
  Alexa / KeepAlive      → empty response
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import urllib.parse

import alexa
import calibration
import event_gateway
import jwt_util
import lwa
import somfy
import token_store

logger = logging.getLogger()
logger.setLevel(logging.WARNING)


_NON_ALEXA = re.compile(r"[^a-zA-Z0-9 ']")


def _to_ascii(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = _NON_ALEXA.sub(" ", ascii_text)
    return " ".join(cleaned.split())


def lambda_handler(event, context):

    print(json.dumps(event))

    namespace = event["directive"]["header"]["namespace"]
    name = event["directive"]["header"].get("name", "")

    try:
        if namespace == "Alexa.Authorization" and name == "AcceptGrant":
            return handle_accept_grant(event)
        if namespace == "Alexa.Authorization" and name == "RevokeGrant":
            return handle_revoke_grant(event)
        if namespace == "Alexa.Discovery":
            return handle_discovery(event)
        if namespace == "Alexa.PowerController":
            return handle_power_controller(event)
        if namespace == "Alexa.RangeController":
            return handle_range_controller(event)
        if namespace == "Alexa" and name == "ReportState":
            return handle_report_state(event)
        if namespace == "Alexa" and name == "KeepAlive":
            return {}
    except Exception as exc:
        logger.exception("Unhandled error processing %s/%s", namespace, name)
        err_ns = "Alexa.Authorization" if namespace == "Alexa.Authorization" else "Alexa"
        err_type = "ACCEPT_GRANT_FAILED" if namespace == "Alexa.Authorization" else "INTERNAL_ERROR"
        return alexa.error_response(event, err_type, str(exc), namespace=err_ns)

    return alexa.error_response(event, "INVALID_DIRECTIVE", f"Unknown: {namespace}/{name}")


# ---------------------------------------------------------------------------
# AcceptGrant / RevokeGrant
# ---------------------------------------------------------------------------

def handle_accept_grant(event):
    directive = event["directive"]
    code = directive["payload"]["grant"]["code"]
    grantee_token = directive["payload"]["grantee"]["token"]

    claims = jwt_util.decode(grantee_token, os.environ["JWT_SECRET"])
    user_id = claims.get("sub", "")
    if not user_id:
        raise ValueError("AcceptGrant token missing 'sub' claim — user must re-link the skill")

    tokens = lwa.exchange_auth_code(code)
    token_store.save_event_gateway_tokens(
        user_id,
        tokens["access_token"],
        tokens.get("refresh_token"),
        int(tokens["expires_in"]),
    )
    token_store.save_ginaite_refresh(user_id, claims["gr"])

    print(f"[handler] AcceptGrant: tokens stored for user={user_id}")
    return {
        "event": {
            "header": alexa._header("Alexa.Authorization", "AcceptGrant.Response"),
            "payload": {},
        }
    }


def handle_revoke_grant(event):
    grantee_token = event["directive"]["payload"]["grantee"]["token"]
    try:
        claims = jwt_util.decode(grantee_token, os.environ["JWT_SECRET"])
        user_id = claims.get("sub", "")
    except Exception:
        user_id = ""
    if user_id:
        token_store.delete_user(user_id)
        print(f"[handler] RevokeGrant: user={user_id} deleted")
    else:
        print("[handler] RevokeGrant: could not identify user, no data deleted")
    return {
        "event": {
            "header": alexa._header("Alexa.Authorization", "RevokeGrant.Response"),
            "payload": {},
        }
    }


# ---------------------------------------------------------------------------
# Auth — JWT issued by auth proxy, contains Ginaite refresh token
# ---------------------------------------------------------------------------

def _jwt_claims(event: dict) -> dict:
    directive = event["directive"]
    scope = (directive.get("payload", {}).get("scope")
             or directive.get("endpoint", {}).get("scope", {}))
    return jwt_util.decode(scope["token"], os.environ["JWT_SECRET"])


def _ginaite_refresh(event: dict) -> str:
    """Decode the JWT the auth proxy issued and return the Ginaite refresh token."""
    return _jwt_claims(event)["gr"]


def _user_id(event: dict) -> str:
    """Return the user identity (Somfy email) from the JWT."""
    return _jwt_claims(event).get("sub", "")


def _site_tokens(ginaite_refresh: str) -> list[tuple[str, str, str]]:
    """Return [(site_oid, site_name, scoped_access_token), ...] for all sites."""
    ginaite_access, new_refresh = somfy.refresh_ginaite(ginaite_refresh)
    sites = somfy.list_sites(ginaite_access)

    # BOB sometimes returns the same site multiple times — deduplicate by site_oid
    seen: set[str] = set()
    unique = [s for s in sites if not (s["site_oid"] in seen or seen.add(s["site_oid"]))]

    return [
        (s["site_oid"], s["name"], somfy.scoped_token(new_refresh, s["site_oid"]))
        for s in unique
    ]


def _site_token(site_oid: str, ginaite_refresh: str) -> str:
    """Mint a site-scoped Overkiz token for a single known site_oid."""
    return somfy.scoped_token(ginaite_refresh, site_oid)


# ---------------------------------------------------------------------------
# Endpoint ID  (<site_oid>|<device_url>, percent-encoded then % → .)
# ---------------------------------------------------------------------------

def _encode_endpoint_id(site_oid: str, device_url: str) -> str:
    return urllib.parse.quote(f"{site_oid}|{device_url}", safe="").replace("%", ".")


def _decode_endpoint_id(endpoint_id: str) -> tuple[str, str]:
    decoded = urllib.parse.unquote(endpoint_id.replace(".", "%"))
    site_oid, device_url = decoded.split("|", 1)
    return site_oid, device_url


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _build_netatmo_home_map(devices: list[dict]) -> dict[str, str]:
    """Return {netatmo_station_id: home_label} for each netatmo .../home device."""
    result = {}
    for dev in devices:
        url = dev.get("deviceURL", "")
        if url.startswith("netatmo://") and url.endswith("/home"):
            station_id = url.split("//")[1].split("/")[0]
            result[station_id] = dev.get("label") or station_id
    return result


def _device_location(device_url: str, site_name: str, netatmo_homes: dict[str, str]) -> str:
    """Return the display location name for a device.

    Netatmo devices use their Netatmo home label (e.g. "Kujawska") so sensors
    from a station integrated into another site's gateway keep the right prefix.
    """
    if device_url.startswith("netatmo://"):
        station_id = device_url.split("//")[1].split("/")[0]
        return netatmo_homes.get(station_id, site_name)
    return site_name


def handle_discovery(event):
    endpoints = []
    for site_oid, site_name, token in _site_tokens(_ginaite_refresh(event)):
        setup = somfy.get_setup(token)
        place_map = _build_place_map(setup)
        netatmo_homes = _build_netatmo_home_map(setup.get("devices", []))
        for device in setup.get("devices", []):
            device_url = device["deviceURL"]
            label = device.get("label") or device_url
            location = _device_location(device_url, site_name, netatmo_homes)
            friendly_name = _to_ascii(f"{location} {label} by Multitahoma")
            room = place_map.get(device_url)
            endpoint_id = _encode_endpoint_id(site_oid, device_url)

            if somfy.is_supported_device(device):
                cookie = {"low_speed": "1"} if somfy.supports_low_speed(device) else None
                endpoints.append(alexa._endpoint(endpoint_id, friendly_name, room, cookie=cookie))
                continue

            stype = somfy.sensor_type(device)
            if stype:
                endpoints.append(alexa.sensor_endpoint(endpoint_id, friendly_name, room, stype))

    return alexa.discovery_response(endpoints)


def _build_place_map(setup: dict) -> dict[str, str]:
    place_map: dict[str, str] = {}
    _walk_places(setup.get("rootPlace", {}), None, place_map)
    return place_map


def _walk_places(place: dict, room_name: str | None, result: dict):
    if place.get("type") == "ROOM":
        room_name = place.get("label")
    for url in place.get("devices", []):
        if room_name:
            result[url] = room_name
    for child in place.get("subPlaces", []):
        _walk_places(child, room_name, result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _do_set_closure(token: str, device_url: str, closure: int, endpoint: dict) -> None:
    """Send setClosure or setClosureAndLinearSpeed depending on endpoint capability."""
    if endpoint.get("cookie", {}).get("low_speed") == "1":
        somfy.set_closure_low_speed(token, device_url, closure)
    else:
        somfy.set_closure(token, device_url, closure)


# ---------------------------------------------------------------------------
# PowerController  (open = TurnOn, close = TurnOff)
# ---------------------------------------------------------------------------

def handle_power_controller(event):
    directive = event["directive"]
    name = directive["header"]["name"]
    site_oid, device_url = _decode_endpoint_id(directive["endpoint"]["endpointId"])
    token = _site_token(site_oid, _ginaite_refresh(event))

    if name == "TurnOn":
        if somfy.get_closure(token, device_url) is None:
            return alexa.error_response(event, "ENDPOINT_UNREACHABLE", "Could not read device state")
        _do_set_closure(token, device_url, 0, directive["endpoint"])
        return alexa.power_response(event, "ON")
    if name == "TurnOff":
        if somfy.get_closure(token, device_url) is None:
            return alexa.error_response(event, "ENDPOINT_UNREACHABLE", "Could not read device state")
        _do_set_closure(token, device_url, 100, directive["endpoint"])
        return alexa.power_response(event, "OFF")

    return alexa.error_response(event, "INVALID_DIRECTIVE", f"Unknown PowerController: {name}")


# ---------------------------------------------------------------------------
# RangeController  (Alexa 0=closed … 100=open, TaHoma inverted)
# ---------------------------------------------------------------------------

def handle_range_controller(event):
    directive = event["directive"]
    name = directive["header"]["name"]
    site_oid, device_url = _decode_endpoint_id(directive["endpoint"]["endpointId"])
    token = _site_token(site_oid, _ginaite_refresh(event))

    if name == "SetRangeValue":
        if somfy.get_closure(token, device_url) is None:
            return alexa.error_response(event, "ENDPOINT_UNREACHABLE", "Could not read device state")
        alexa_value = int(directive["payload"]["rangeValue"])
        motor_pct = calibration.physical_to_motor(device_url, alexa_value)
        _do_set_closure(token, device_url, 100 - motor_pct, directive["endpoint"])
        return alexa.range_response(event, alexa_value)

    if name == "AdjustRangeValue":
        delta = int(directive["payload"]["rangeValueDelta"])
        current_closure = somfy.get_closure(token, device_url)
        if current_closure is None:
            return alexa.error_response(event, "ENDPOINT_UNREACHABLE", "Could not read device state")
        current_physical = calibration.motor_to_physical(device_url, 100 - current_closure)
        new_physical = max(0, min(100, current_physical + delta))
        new_motor = calibration.physical_to_motor(device_url, new_physical)
        _do_set_closure(token, device_url, 100 - new_motor, directive["endpoint"])
        return alexa.range_response(event, new_physical)

    return alexa.error_response(event, "INVALID_DIRECTIVE", f"Unknown RangeController: {name}")


# ---------------------------------------------------------------------------
# ReportState
# ---------------------------------------------------------------------------

def handle_report_state(event):
    site_oid, device_url = _decode_endpoint_id(event["directive"]["endpoint"]["endpointId"])
    token = _site_token(site_oid, _ginaite_refresh(event))

    stype = event["directive"]["endpoint"].get("cookie", {}).get("sensor_type")
    if stype:
        states = somfy.get_sensor_states(token, device_url)
        return alexa.sensor_state_report(event, stype, states)

    closure = somfy.get_closure(token, device_url)
    if closure is None:
        return alexa.state_report(event, 0, available=False)
    physical = calibration.motor_to_physical(device_url, 100 - closure)
    return alexa.state_report(event, physical)
