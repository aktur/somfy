"""Tests for handler.py — all Somfy API calls are mocked."""

from unittest.mock import patch

import handler

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

SITE_OID = "32bf4a8d-7895-4cfd-a64e-00983a386dfe"
DEVICE_URL = "io://XXXX-XXXX-XXXX/13387958"
MOCK_TOKEN = "mock-scoped-token"

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
            "payload": {"scope": {"type": "BearerToken", "token": "bearer"}},
        }
    }


def _power_event(name, endpoint_id):
    return {
        "directive": {
            "header": {"namespace": "Alexa.PowerController", "name": name,
                       "payloadVersion": "3", "messageId": "msg-1", "correlationToken": "ct-1"},
            "endpoint": {"endpointId": endpoint_id},
            "payload": {},
        }
    }


def _range_event(name, endpoint_id, payload):
    return {
        "directive": {
            "header": {"namespace": "Alexa.RangeController", "instance": "Blind.Lift",
                       "name": name, "payloadVersion": "3",
                       "messageId": "msg-1", "correlationToken": "ct-1"},
            "endpoint": {"endpointId": endpoint_id},
            "payload": payload,
        }
    }


def _report_state_event(endpoint_id):
    return {
        "directive": {
            "header": {"namespace": "Alexa", "name": "ReportState",
                       "payloadVersion": "3", "messageId": "msg-1", "correlationToken": "ct-1"},
            "endpoint": {"endpointId": endpoint_id},
            "payload": {},
        }
    }


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
         patch("somfy.set_closure") as mock_set:
        resp = handler.handle_power_controller(_power_event("TurnOff", endpoint_id))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)
    assert resp["event"]["header"]["name"] == "Response"


def test_turn_on_sends_closure_0():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_power_controller(_power_event("TurnOn", endpoint_id))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)


def test_power_response_includes_range_value():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.set_closure"):
        resp = handler.handle_power_controller(_power_event("TurnOff", endpoint_id))
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 0


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
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(_range_event("SetRangeValue", endpoint_id, {"rangeValue": 100}))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 0)


def test_set_range_0_sends_closure_100():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(_range_event("SetRangeValue", endpoint_id, {"rangeValue": 0}))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 100)


def test_set_range_75_sends_closure_25():
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
         patch("somfy.set_closure") as mock_set:
        handler.handle_range_controller(_range_event("SetRangeValue", endpoint_id, {"rangeValue": 75}))
    mock_set.assert_called_once_with(MOCK_TOKEN, DEVICE_URL, 25)


def test_adjust_range_applies_delta():
    # TaHoma closure=20 → Alexa=80, delta=-25 → new Alexa=55, TaHoma=45
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
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
    # TaHoma closure=30 → Alexa rangeValue=70
    endpoint_id = handler._encode_endpoint_id(SITE_OID, DEVICE_URL)
    with patch.object(handler, "_site_token", return_value=MOCK_TOKEN), \
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
    with patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 1  # only the roller shutter, not the homekit stack


def test_discovery_friendly_name_ascii_only():
    with patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    name = resp["event"]["payload"]["endpoints"][0]["friendlyName"]
    assert all(ord(c) < 128 for c in name), f"Non-ASCII chars in: {name!r}"


def test_discovery_includes_site_name():
    with patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    name = resp["event"]["payload"]["endpoints"][0]["friendlyName"]
    assert "Kujawska" in name


def test_discovery_assigns_room_from_place_tree():
    with patch.object(handler, "_site_tokens", return_value=[(SITE_OID, "Kujawska", MOCK_TOKEN)]), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    ep = resp["event"]["payload"]["endpoints"][0]
    assert ep.get("additionalAttributes", {}).get("room") == "Bedroom"


def test_discovery_deduplicates_sites():
    # Simulate BOB returning the same site twice
    duplicate_sites = [(SITE_OID, "Kujawska", MOCK_TOKEN), (SITE_OID, "Kujawska", MOCK_TOKEN)]
    with patch.object(handler, "_site_tokens", return_value=duplicate_sites), \
         patch("somfy.get_setup", return_value=MOCK_SETUP):
        resp = handler.handle_discovery(_discovery_event())
    # Should return 2 endpoints (not 4) — deduplication happens in _site_tokens
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 2  # 2 calls × 1 shutter each (duplicate sites passed through)


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
    with patch.object(handler, "_site_tokens", return_value=[
            (SITE_OID, "Kujawska", MOCK_TOKEN),
            (site2_oid, "Antilope", "token2"),
         ]), \
         patch("somfy.get_setup", side_effect=get_setup_side_effect):
        resp = handler.handle_discovery(_discovery_event())
    endpoints = resp["event"]["payload"]["endpoints"]
    assert len(endpoints) == 2
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
