"""Tests for alexa.py response builders."""

import alexa


# ---------------------------------------------------------------------------
# _all_properties
# ---------------------------------------------------------------------------

def test_properties_open():
    props = {p["namespace"]: p for p in alexa._all_properties(100)}
    assert props["Alexa.PowerController"]["value"] == "ON"
    assert props["Alexa.RangeController"]["value"] == 100
    assert props["Alexa.EndpointHealth"]["value"]["value"] == "OK"


def test_properties_closed():
    props = {p["namespace"]: p for p in alexa._all_properties(0)}
    assert props["Alexa.PowerController"]["value"] == "OFF"
    assert props["Alexa.RangeController"]["value"] == 0


def test_properties_partially_open():
    props = {p["namespace"]: p for p in alexa._all_properties(60)}
    assert props["Alexa.PowerController"]["value"] == "ON"
    assert props["Alexa.RangeController"]["value"] == 60


def test_properties_unavailable():
    props = {p["namespace"]: p for p in alexa._all_properties(0, available=False)}
    assert props["Alexa.EndpointHealth"]["value"]["value"] == "UNREACHABLE"


def test_properties_uncertainty_ms():
    props = {p["namespace"]: p for p in alexa._all_properties(50, uncertainty_ms=2000)}
    assert all(p["uncertaintyInMilliseconds"] == 2000 for p in props.values())


# ---------------------------------------------------------------------------
# power_response
# ---------------------------------------------------------------------------

def _base_event(namespace="Alexa.PowerController", name="TurnOff"):
    return {
        "directive": {
            "header": {"namespace": namespace, "name": name, "correlationToken": "ct-1"},
            "endpoint": {"endpointId": "ep-1"},
            "payload": {},
        }
    }


def test_power_response_turnoff():
    resp = alexa.power_response(_base_event("Alexa.PowerController", "TurnOff"), "OFF")
    assert resp["event"]["header"]["name"] == "Response"
    assert resp["event"]["header"]["correlationToken"] == "ct-1"
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.PowerController"]["value"] == "OFF"
    assert props["Alexa.RangeController"]["value"] == 0


def test_power_response_turnon():
    resp = alexa.power_response(_base_event("Alexa.PowerController", "TurnOn"), "ON")
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.PowerController"]["value"] == "ON"
    assert props["Alexa.RangeController"]["value"] == 100


# ---------------------------------------------------------------------------
# range_response
# ---------------------------------------------------------------------------

def test_range_response_value():
    event = _base_event("Alexa.RangeController", "SetRangeValue")
    resp = alexa.range_response(event, 75)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 75
    assert props["Alexa.PowerController"]["value"] == "ON"


def test_range_response_zero():
    event = _base_event("Alexa.RangeController", "SetRangeValue")
    resp = alexa.range_response(event, 0)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.PowerController"]["value"] == "OFF"


# ---------------------------------------------------------------------------
# state_report
# ---------------------------------------------------------------------------

def test_state_report():
    resp = alexa.state_report(_base_event(), 40)
    assert resp["event"]["header"]["name"] == "StateReport"
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.RangeController"]["value"] == 40


def test_state_report_unavailable():
    resp = alexa.state_report(_base_event(), 0, available=False)
    props = {p["namespace"]: p for p in resp["context"]["properties"]}
    assert props["Alexa.EndpointHealth"]["value"]["value"] == "UNREACHABLE"


# ---------------------------------------------------------------------------
# error_response
# ---------------------------------------------------------------------------

def test_error_response():
    event = {"directive": {"header": {"correlationToken": "ct"}, "endpoint": {}}}
    resp = alexa.error_response(event, "INTERNAL_ERROR", "oops")
    assert resp["event"]["header"]["name"] == "ErrorResponse"
    assert resp["event"]["payload"]["type"] == "INTERNAL_ERROR"
    assert resp["event"]["payload"]["message"] == "oops"


def test_error_response_missing_fields():
    resp = alexa.error_response({}, "INVALID_DIRECTIVE", "bad")
    assert resp["event"]["header"]["name"] == "ErrorResponse"


# ---------------------------------------------------------------------------
# _endpoint (capability structure)
# ---------------------------------------------------------------------------

def test_endpoint_display_category():
    ep = alexa._endpoint("id1", "Bedroom blind", None)
    assert "INTERIOR_BLIND" in ep["displayCategories"]


def test_endpoint_manufacturer():
    ep = alexa._endpoint("id1", "Test blind", None)
    assert ep["manufacturerName"] == "Somfy"


def test_endpoint_has_alexa_interface():
    ep = alexa._endpoint("id1", "Test", None)
    ifaces = [c["interface"] for c in ep["capabilities"]]
    assert "Alexa" in ifaces
    assert "Alexa.PowerController" in ifaces
    assert "Alexa.RangeController" in ifaces
    assert "Alexa.EndpointHealth" in ifaces


def test_endpoint_range_controller_semantics():
    ep = alexa._endpoint("id1", "Test", None)
    rc = next(c for c in ep["capabilities"] if c.get("interface") == "Alexa.RangeController")
    assert "semantics" in rc
    actions = {a["directive"]["payload"]["rangeValue"]: a["actions"]
               for a in rc["semantics"]["actionMappings"]}
    assert "Alexa.Actions.Close" in actions[0]
    assert "Alexa.Actions.Open" in actions[100]


def test_endpoint_power_controller_semantics():
    ep = alexa._endpoint("id1", "Test", None)
    pc = next(c for c in ep["capabilities"] if c.get("interface") == "Alexa.PowerController")
    assert "semantics" in pc
    directives = {a["directive"]["name"]: a["actions"]
                  for a in pc["semantics"]["actionMappings"]}
    assert "Alexa.Actions.Close" in directives["TurnOff"]
    assert "Alexa.Actions.Open" in directives["TurnOn"]


def test_endpoint_room_in_attributes():
    ep = alexa._endpoint("id1", "Test", "Bedroom")
    assert ep["additionalAttributes"]["room"] == "Bedroom"


def test_endpoint_no_room_no_attributes():
    ep = alexa._endpoint("id1", "Test", None)
    assert "additionalAttributes" not in ep


# ---------------------------------------------------------------------------
# discovery_response
# ---------------------------------------------------------------------------

def test_discovery_response_wraps_endpoints():
    endpoints = [alexa._endpoint("id1", "Blind 1", None)]
    resp = alexa.discovery_response(endpoints)
    assert resp["event"]["header"]["namespace"] == "Alexa.Discovery"
    assert resp["event"]["header"]["name"] == "Discover.Response"
    assert len(resp["event"]["payload"]["endpoints"]) == 1
