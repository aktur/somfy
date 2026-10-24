"""Tests for handler.py — all Somfy API calls are mocked."""

import time
from unittest.mock import patch

import calibration
import handler
import jwt_util

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SITE_OID = "32bf4a8d-7895-4cfd-a64e-00983a386dfe"
DEVICE_URL = "io://XXXX-XXXX-XXXX/13387958"
MOCK_TOKEN = "mock-scoped-token"
MOCK_GINAITE_REFRESH = "mock-ginaite-refresh-token"
_TEST_SECRET = "test-secret-do-not-use-in-production"


def _make_access_jwt() -> str:
    return jwt_util.encode(
        {"gr": MOCK_GINAITE_REFRESH, "exp": int(time.time()) + 3600, "t": "access"},
        _TEST_SECRET,
    )

MOCK_SETUP = {
    "devices": [
        {
            "deviceURL": DEVICE_URL,
            "label": "Roleta sypialni",
            "controllableName": "io:RollerShutterWithLowSpeedManagementIOComponent",
            "states": [],
        },
        {
            "deviceURL": "io://XXXX-XXXX-XXXX/99999999",
            "label": "HOMEKIT (stack)",
            "controllableName": "homekit:StackComponent",
            "states": [],
        },
        {
            "deviceURL": "io://XXXX-XXXX-XXXX/11111111",
            "label": "Sunscreen",
            "controllableName": "io:HorizontalAwningIOComponent",
            "states": [],
        },
        {
            "deviceURL": "io://XXXX-XXXX-XXXX/22222222",
            "label": "Woonkamer",
            "controllableName": "io:VerticalExteriorAwningIOComponent",
            "states": [],
        },
    ],
    "rootPlace": {
        "label": "Home",
        "type": "HOME",
        "devices": [],
        "subPlaces": [
            {
                "label": "Bedroom",
                "type": "ROOM",
                "devices": [DEVICE_URL],
                "subPlaces": [],
            }
        ],
    },
}


# ---------------------------------------------------------------------------
# Event builders
# ---------------------------------------------------------------------------

def _discovery_event():
    return {
        "directive": {
            "header": {"namespace": "Alexa.Discovery", "name": "Discover",
                       "payloadVersion": "3", "messageId": "msg-1"},
            "payload": {"scope": _scope()},
        }
    }


def _scope() -> dict:
    return {"type": "BearerToken", "token": _make_access_jwt()}


def _power_event(name, endpoint_id):
    return {
        "directive": {
            "header": {"namespace": "Alexa.PowerController", "name": name,
                       "payloadVersion": "3", "messageId": "msg-1", "correlationToken": "ct-1"},
            "endpoint": {"endpointId": endpoint_id, "scope": _scope()},
            "payload": {},
        }
    }


def _range_event(name, endpoint_id, payload):
    return {
        "directive": {
            "header": {"namespace": "Alexa.RangeController", "instance": "Blind.Lift",
                       "name": name, "payloadVersion": "3",
                       "messageId": "msg-1", "correlationToken": "ct-1"},
            "endpoint": {"endpointId": endpoint_id, "scope": _scope()},
            "payload": payload,
        }
    }


def _report_state_event(endpoint_id):
    return {
        "directive": {
            "header": {"namespace": "Alexa", "name": "ReportState",
                       "payloadVersion": "3", "messageId": "msg-1", "correlationToken": "ct-1"},
            "endpoint": {"endpointId": endpoint_id, "scope": _scope()},
            "payload": {},
        }
    }


# ---------------------------------------------------------------------------
# Ginaite refresh token extraction (account linking JWT)
# ---------------------------------------------------------------------------

def test_ginaite_refresh_from_discovery_event():
    assert handler._ginaite_refresh(_discovery_event()) == MOCK_GINAITE_REFRESH


def test_ginaite_refresh_from_control_event():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    assert handler._ginaite_refresh(_power_event("TurnOff", endpoint_id)) == MOCK_GINAITE_REFRESH


def test_ginaite_refresh_from_report_state_event():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    assert handler._ginaite_refresh(_report_state_event(endpoint_id)) == MOCK_GINAITE_REFRESH


# ---------------------------------------------------------------------------
# Endpoint ID encoding
# ---------------------------------------------------------------------------

def test_endpoint_id_roundtrip():
    encoded = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    site_oid, device_url = handler._decode_endpoint_id(encoded)
    assert site_oid == SITE_OID
    assert device_url == DEVICE_URL


def test_endpoint_id_roundtrip_special_chars():
    url = "io://XXXX-XXXX-XXXX/99999999"
    encoded = handler._encode_endpoint_id(SITE_OID, url)
    _, decoded_url = handler._decode_endpoint_id(encoded)
    assert decoded_url == url


# ---------------------------------------------------------------------------
# Polish character stripping
# ---------------------------------------------------------------------------

def test_to_ascii_strips_polish():
    assert handler._to_ascii("Roleta dużego pokoju") == "Roleta duzego pokoju"
    assert handler._to_ascii("Sypialnia") == "Sypialnia"
    assert handler._to_ascii("żółć") == "zoc"  # ł has no ASCII decomposition, dropped


def test_to_ascii_strips_trailing_whitespace():
    assert handler._to_ascii("Kujawska ") == "Kujawska"


def test_to_ascii_em_dash_removed():
    result = handler._to_ascii("Kujawska — Roleta")
    assert "—" not in result


# ---------------------------------------------------------------------------
# PowerController
# ---------------------------------------------------------------------------

def test_turn_off_sends_closure_100():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_power_controller(_power_event("TurnOff", endpoint_id))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)
    assert resp["event"]["header"]["name"] == "Response"


def test_turn_on_sends_closure_0():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_power_controller(_power_event("TurnOn", endpoint_id))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)


def test_power_response_includes_range_value():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure"):
        resp = handler.handle_power_controller(_power_event("TurnOff", endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 0


def test_power_controller_offline_returns_unreachable():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=None), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_power_controller(_power_event("TurnOn", endpoint_id))
    mock_set.assert_not_called()
    assert resp["event"]["header"]["name"] == "ErrorResponse"
    assert resp["event"]["payload"]["type"] == "ENDPOINT_UNREACHABLE"


def test_unknown_power_directive_returns_error():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN):
        resp = handler.handle_power_controller(_power_event("Toggle", endpoint_id))
    assert resp["event"]["header"]["name"] == "ErrorResponse"


# ---------------------------------------------------------------------------
# RangeController — closure inversion (Alexa 0=closed ↔ TaHoma 100=closed)
# ---------------------------------------------------------------------------

def test_set_range_100_sends_closure_0():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(_range_event("SetRangeValue", endpoint_id, {"rangeValue": 100}))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)


def test_set_range_0_sends_closure_100():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(_range_event("SetRangeValue", endpoint_id, {"rangeValue": 0}))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)


def test_set_range_75_sends_closure_25():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value={"shutters": {}}), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(_range_event("SetRangeValue", endpoint_id, {"rangeValue": 75}))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 25)


def test_adjust_range_applies_delta():
    # TaHoma closure=20 → Alexa=80, delta=-25 → new Alexa=55, TaHoma=45
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value={"shutters": {}}), \
         patch("somfy.get_closure", return_value=20), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": -25})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 45)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 55


def test_adjust_range_clamps_at_0():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": -999})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)


def test_adjust_range_clamps_at_100():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": 999})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)


def test_set_range_offline_returns_unreachable():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=None), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 50})
        )
    mock_set.assert_not_called()
    assert resp["event"]["header"]["name"] == "ErrorResponse"
    assert resp["event"]["payload"]["type"] == "ENDPOINT_UNREACHABLE"


def test_adjust_range_unavailable_returns_error():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=None):
        resp = handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": -10})
        )
    assert resp["event"]["header"]["name"] == "ErrorResponse"
    assert resp["event"]["payload"]["type"] == "ENDPOINT_UNREACHABLE"


# ---------------------------------------------------------------------------
# ReportState
# ---------------------------------------------------------------------------

def test_report_state_converts_closure():
    # TaHoma closure=30 → Alexa rangeValue=70 (identity mapping, no calibration)
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value={"shutters": {}}), \
         patch("somfy.get_closure", return_value=30):
        resp = handler.handle_report_state(_report_state_event(endpoint_id))
    assert resp["event"]["header"]["name"] == "StateReport"
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 70


def test_report_state_fully_open():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=0):
        resp = handler.handle_report_state(_report_state_event(endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 100
    assert props["Alexa.PowerController"]["value"] == "ON"


def test_report_state_unavailable():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=None):
        resp = handler.handle_report_state(_report_state_event(endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.EndpointHealth"]["value"]["value"] == "UNREACHABLE"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_discovery_filters_non_shutters():
    with patch.object(handler, "_ginaite_refresh", return_value=MOCK_GINAITE_REFRESH), \
         patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 3  # roller shutter + 2 awnings, not the homekit stack


def test_discovery_friendly_name_ascii_only():
    with patch.object(handler, "_ginaite_refresh", return_value=MOCK_GINAITE_REFRESH), \
         patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    name = resp["event"]["payload"]["endpoints"][0]["friendlyName"]
    assert all(ord(c) < 128 for c in name), f"Non-ASCII chars in: {name!r}"


def test_discovery_includes_site_name():
    with patch.object(handler, "_ginaite_refresh", return_value=MOCK_GINAITE_REFRESH), \
         patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    name = resp["event"]["payload"]["endpoints"][0]["friendlyName"]
    assert "Kujawska" in name


def test_discovery_assigns_room_from_place_tree():
    with patch.object(handler, "_ginaite_refresh", return_value=MOCK_GINAITE_REFRESH), \
         patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    ep = resp["event"]["payload"]["endpoints"][0]
    assert ep.get("additionalAttributes", {}).get("room") == "Bedroom"


def test_discovery_deduplicates_sites():
    # Simulate BOB returning the same site twice
    duplicate_sites = [(SITE_OID, "Kujawska", MOCK_TOKEN), (SITE_OID, "Kujawska", MOCK_TOKEN)]
    with patch.object(handler, "_ginaite_refresh", return_value=MOCK_GINAITE_REFRESH), \
         patch.object(handler, "_site_tokens", return_value=duplicate_sites), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    # Should return 2 endpoints (not 4) — deduplication happens in _site_tokens
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 6  # 2 calls × 3 devices each (duplicate sites passed through)


def test_discovery_multi_site():
    site2_url = "io://2027-1886-8813/11111111"
    setup2 = {
        "devices": [{"deviceURL": site2_url, "label": "shutter",
                     "controllableName": "io:RollerShutterGenericIOComponent", "states": []}],
        "rootPlace": {"label": "Home", "type": "HOME", "devices": [], "subPlaces": []},
    }

    def get_setup_side_effect(token):
        return MOCK_SETUP if token == MOCK_TOKEN else setup2

    site2_oid = "389ba9eb-28d2-5ed1-80ab-6f0eb4d85728"
    with patch.object(handler, "_ginaite_refresh", return_value=MOCK_GINAITE_REFRESH), \
         patch.object(handler, "_site_tokens", return_value=[
            (SITE_OID, "Kujawska", MOCK_TOKEN),
            (site2_oid, "Antilope", "token2"),
         ]), \
         patch("somfy.get_setup", side_effect=get_setup_side_effect):
        resp = handler.handle_discovery(_discovery_event())
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 4  # site1: 3 devices, site2: 1 device
    site_names = {ep["friendlyName"].split(" - ")[0] for ep in endpoints}
    assert "Kujawska" in site_names
    assert "Antilope" in site_names


# ---------------------------------------------------------------------------
# lambda_handler routing
# ---------------------------------------------------------------------------

def test_lambda_routes_discovery():
    with patch.object(handler, "handle_discovery", return_value={"event": {}}) as mock:
        handler.lambda_handler(_discovery_event(), None)
    mock.assert_called_once()


def test_lambda_routes_power_controller():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    event = _power_event("TurnOff", endpoint_id)
    with patch.object(handler, "handle_power_controller", return_value={"event": {}}) as mock:
        handler.lambda_handler(event, None)
    mock.assert_called_once()


def test_lambda_routes_range_controller():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    event = _range_event("SetRangeValue", endpoint_id, {"rangeValue": 0})
    with patch.object(handler, "handle_range_controller", return_value={"event": {}}) as mock:
        handler.lambda_handler(event, None)
    mock.assert_called_once()


def test_lambda_keepalive_returns_empty():
    event = {"directive": {"header": {"namespace": "Alexa", "name": "KeepAlive",
                                       "payloadVersion": "3", "messageId": "m1"}, "payload": {}}}
    assert handler.lambda_handler(event, None) == {}


def test_lambda_unknown_namespace_returns_error():
    event = {"directive": {"header": {"namespace": "Alexa.Unknown", "name": "DoSomething",
                                       "payloadVersion": "3", "messageId": "m1"}, "payload": {}}}
    resp = handler.lambda_handler(event, None)
    assert resp["event"]["header"]["name"] == "ErrorResponse"
    assert resp["event"]["payload"]["type"] == "INVALID_DIRECTIVE"


def test_lambda_handles_exception_gracefully():
    with patch.object(handler, "handle_discovery", side_effect=RuntimeError("boom")):
        resp = handler.lambda_handler(_discovery_event(), None)
    assert resp["event"]["header"]["name"] == "ErrorResponse"
    assert resp["event"]["payload"]["type"] == "INTERNAL_ERROR"
    assert "boom" in resp["event"]["payload"]["message"]


# ---------------------------------------------------------------------------
# Calibration integration — SetRangeValue (absolute command)
# ---------------------------------------------------------------------------
#
# SIMPLE_POINTS: physical → motor: 0→0, 50→80, 100→100
#   physical=50 → motor=80 → TaHoma closure=20
#   physical=75 → motor=90 → TaHoma closure=10

_CAL_SIMPLE = [
    {"physical": 0, "motor": 0},
    {"physical": 50, "motor": 80},
    {"physical": 100, "motor": 100},
]
_CAL_CFG = {"shutters": {DEVICE_URL: {"calibration": _CAL_SIMPLE}}}


def test_set_range_calibration_maps_physical_to_motor():
    # Alexa asks for 50% open (physical). Calibration maps that to motor=80.
    # TaHoma closure = 100 - 80 = 20.
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 50})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 20)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 50  # reports requested physical %


def test_set_range_calibration_at_75():
    # physical=75 → motor=90 → closure=10
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 75})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 10)


def test_set_range_calibration_fully_open():
    # physical=100 → motor=100 → closure=0
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 100})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)


def test_set_range_calibration_fully_closed():
    # physical=0 → motor=0 → closure=100
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 0})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)


# ---------------------------------------------------------------------------
# Calibration integration — AdjustRangeValue (relative command)
# ---------------------------------------------------------------------------
#
# Relative adjustments operate on physical space, not raw motor space.
# TaHoma reports closure=20 → motor_pct=80 → physical=50.
# delta=+25 → new_physical=75 → motor=90 → closure=10.

def test_adjust_range_calibration_delta_on_physical_space():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=20), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": 25})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 10)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 75  # physical %


def test_adjust_range_calibration_clamps_at_100():
    # physical=50, delta=+9999 → new_physical=100 → motor=100 → closure=0
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=20), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": 9999})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 100


def test_adjust_range_calibration_clamps_at_0():
    # physical=50, delta=-9999 → new_physical=0 → motor=0 → closure=100
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=20), \
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_range_controller(
            _range_event("AdjustRangeValue", endpoint_id, {"rangeValueDelta": -9999})
        )
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 0


# ---------------------------------------------------------------------------
# Calibration integration — ReportState (state query)
# ---------------------------------------------------------------------------
#
# TaHoma reports closure=20 → motor_pct=80 → physical=50 via inverse calibration.
# Alexa should see 50%, not the raw 80%.

def test_report_state_calibration_inverts_motor_to_physical():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=20):
        resp = handler.handle_report_state(_report_state_event(endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 50


def test_report_state_calibration_fully_open():
    # closure=0 → motor_pct=100 → physical=100
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=0):
        resp = handler.handle_report_state(_report_state_event(endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 100
    assert props["Alexa.PowerController"]["value"] == "ON"


def test_report_state_calibration_fully_closed():
    # closure=100 → motor_pct=0 → physical=0
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=100):
        resp = handler.handle_report_state(_report_state_event(endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 0
    assert props["Alexa.PowerController"]["value"] == "OFF"


# ---------------------------------------------------------------------------
# No double-calibration: raw TaHoma closure → single inverse → physical
# ---------------------------------------------------------------------------
#
# Verify that calibration.motor_to_physical is called exactly once per
# state report, not multiple times (which would double-apply the curve).

def test_report_state_no_double_calibration():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=20), \
         patch.object(calibration, "motor_to_physical", return_value=50) as mock_m2p, \
         patch.object(calibration, "physical_to_motor") as mock_p2m:
        handler.handle_report_state(_report_state_event(endpoint_id))
    mock_m2p.assert_called_once()
    mock_p2m.assert_not_called()


def test_set_range_no_double_calibration():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure"), \
         patch.object(calibration, "physical_to_motor", return_value=80) as mock_p2m, \
         patch.object(calibration, "motor_to_physical") as mock_m2p:
        handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 50})
        )
    mock_p2m.assert_called_once_with(DEVICE_URL, 50)
    mock_m2p.assert_not_called()


# ---------------------------------------------------------------------------
# Direction convention: Alexa open=100, TaHoma closure=0 — preserved with calibration
# ---------------------------------------------------------------------------

def test_direction_alexa_100_maps_to_tahoma_closure_0_with_calibration():
    # With any calibration curve that preserves endpoints, Alexa 100 must → closure 0.
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 100})
        )
    closure = mock_set.call_args[0][2]
    assert closure == 0


def test_direction_alexa_0_maps_to_tahoma_closure_100_with_calibration():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch.object(calibration, "_load_config", return_value=_CAL_CFG), \
         patch("somfy.get_closure", return_value=50), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(
            _range_event("SetRangeValue", endpoint_id, {"rangeValue": 0})
        )
    closure = mock_set.call_args[0][2]
    assert closure == 100
