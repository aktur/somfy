"""Alexa Smart Home Skill — Lambda entry point.

Directive routing:
  Alexa.Discovery        → handle_discovery
  Alexa.PowerController  → handle_power_controller  (open/close)
  Alexa.RangeController  → handle_range_controller  (set/adjust percentage)
  Alexa / ReportState    → handle_report_state
  Alexa / KeepAlive      → empty response
"""

import logging
import os
import unicodedata
import urllib.parse

import alexa
import somfy

logger = logging.getLogger()
logger.setLevel(logging.WARNING)


def _to_ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").strip()


def lambda_handler(event, context):
    namespace = event["directive"]["header"]["namespace"]
    name = event["directive"]["header"].get("name", "")

    try:
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
        return alexa.error_response(event, "INTERNAL_ERROR", str(exc))

    return alexa.error_response(event, "INVALID_DIRECTIVE", f"Unknown: {namespace}/{name}")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _site_tokens() -> list[tuple[str, str, str]]:
    """Return [(site_oid, site_name, scoped_access_token), ...] for all sites."""
    user = os.environ["SOMFY_USER"]
    password = os.environ["SOMFY_PASS"]

    sso = somfy._post_form(somfy.SOMFY_SSO_URL, {
        "grant_type": "password",
        "client_id": somfy.CLIENT_ID,
        "client_secret": somfy.CLIENT_SECRET,
        "username": user,
        "password": password,
    })["access_token"]

    ginaite_access, ginaite_refresh = somfy.ginaite_token_from_sso(sso)
    sites = somfy.list_sites(ginaite_access)

    # BOB sometimes returns the same site multiple times — deduplicate by site_oid
    seen: set[str] = set()
    unique = [s for s in sites if not (s["site_oid"] in seen or seen.add(s["site_oid"]))]

    return [
        (s["site_oid"], s["name"], somfy.scoped_token(ginaite_refresh, s["site_oid"]))
        for s in unique
    ]


def _site_token(site_oid: str) -> str:
    """Mint a scoped token for a single known site_oid."""
    user = os.environ["SOMFY_USER"]
    password = os.environ["SOMFY_PASS"]

    sso = somfy._post_form(somfy.SOMFY_SSO_URL, {
        "grant_type": "password",
        "client_id": somfy.CLIENT_ID,
        "client_secret": somfy.CLIENT_SECRET,
        "username": user,
        "password": password,
    })["access_token"]

    _, ginaite_refresh = somfy.ginaite_token_from_sso(sso)
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

def handle_discovery(event):
    endpoints = []
    for site_oid, site_name, token in _site_tokens():
        setup = somfy.get_setup(token)
        place_map = _build_place_map(setup)
        for device in setup.get("devices", []):
            if not somfy.is_roller_shutter(device):
                continue
            device_url = device["deviceURL"]
            label = device.get("label") or device_url
            friendly_name = _to_ascii(f"{site_name} - {label}")
            room = place_map.get(device_url)
            endpoint_id = _encode_endpoint_id(site_oid, device_url)
            endpoints.append(alexa._endpoint(endpoint_id, friendly_name, room))

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
# PowerController  (open = TurnOn, close = TurnOff)
# ---------------------------------------------------------------------------

def handle_power_controller(event):
    directive = event["directive"]
    name = directive["header"]["name"]
    site_oid, device_url = _decode_endpoint_id(directive["endpoint"]["endpointId"])
    token = _site_token(site_oid)

    if name == "TurnOn":
        somfy.set_closure(token, device_url, 0)    # TaHoma 0 = fully open
        return alexa.power_response(event, "ON")
    if name == "TurnOff":
        somfy.set_closure(token, device_url, 100)  # TaHoma 100 = fully closed
        return alexa.power_response(event, "OFF")

    return alexa.error_response(event, "INVALID_DIRECTIVE", f"Unknown PowerController: {name}")


# ---------------------------------------------------------------------------
# RangeController  (Alexa 0=closed … 100=open, TaHoma inverted)
# ---------------------------------------------------------------------------

def handle_range_controller(event):
    directive = event["directive"]
    name = directive["header"]["name"]
    site_oid, device_url = _decode_endpoint_id(directive["endpoint"]["endpointId"])
    token = _site_token(site_oid)

    if name == "SetRangeValue":
        alexa_value = int(directive["payload"]["rangeValue"])
        somfy.set_closure(token, device_url, 100 - alexa_value)
        return alexa.range_response(event, alexa_value)

    if name == "AdjustRangeValue":
        delta = int(directive["payload"]["rangeValueDelta"])
        current = somfy.get_closure(token, device_url)
        if current is None:
            return alexa.error_response(event, "ENDPOINT_UNREACHABLE", "Could not read device state")
        new_alexa = max(0, min(100, (100 - current) + delta))
        somfy.set_closure(token, device_url, 100 - new_alexa)
        return alexa.range_response(event, new_alexa)

    return alexa.error_response(event, "INVALID_DIRECTIVE", f"Unknown RangeController: {name}")


# ---------------------------------------------------------------------------
# ReportState
# ---------------------------------------------------------------------------

def handle_report_state(event):
    site_oid, device_url = _decode_endpoint_id(event["directive"]["endpoint"]["endpointId"])
    token = _site_token(site_oid)
    closure = somfy.get_closure(token, device_url)
    if closure is None:
        return alexa.state_report(event, 0, available=False)
    return alexa.state_report(event, 100 - closure)
