"""Alexa Smart Home response builders."""

from __future__ import annotations

import time
import uuid


def _header(namespace: str, name: str, correlation_token: str | None = None) -> dict:
    h = {
        "namespace": namespace,
        "name": name,
        "messageId": str(uuid.uuid4()),
        "payloadVersion": "3",
    }
    if correlation_token:
        h["correlationToken"] = correlation_token
    return h


def _endpoint(
    endpoint_id: str,
    label: str,
    room: str | None,
    description: str = "Somfy TaHoma Roller Shutter",
    cookie: dict[str, str] | None = None,
) -> dict:
    ep = {
        "endpointId": endpoint_id,
        "manufacturerName": "Somfy",
        "friendlyName": label,
        "description": description,
        "displayCategories": ["INTERIOR_BLIND"],
        "capabilities": [
            {
                "type": "AlexaInterface",
                "interface": "Alexa",
                "version": "3",
            },
            {
                "type": "AlexaInterface",
                "interface": "Alexa.PowerController",
                "version": "3",
                "properties": {
                    "supported": [{"name": "powerState"}],
                    "proactivelyReported": False,
                    "retrievable": True,
                },
                "semantics": {
                    "actionMappings": [
                        {
                            "@type": "ActionsToDirective",
                            "actions": ["Alexa.Actions.Open", "Alexa.Actions.Raise"],
                            "directive": {"name": "TurnOn"},
                        },
                        {
                            "@type": "ActionsToDirective",
                            "actions": ["Alexa.Actions.Close", "Alexa.Actions.Lower"],
                            "directive": {"name": "TurnOff"},
                        },
                    ],
                    "stateMappings": [
                        {"@type": "StatesToValue", "states": ["Alexa.States.Open"], "value": "ON"},
                        {"@type": "StatesToValue", "states": ["Alexa.States.Closed"], "value": "OFF"},
                    ],
                },
            },
            {
                "type": "AlexaInterface",
                "interface": "Alexa.RangeController",
                "version": "3",
                "instance": "Blind.Lift",
                "properties": {
                    "supported": [{"name": "rangeValue"}],
                    "proactivelyReported": False,
                    "retrievable": True,
                },
                "capabilityResources": {
                    "friendlyNames": [
                        {"@type": "asset", "value": {"assetId": "Alexa.Setting.Opening"}},
                    ]
                },
                "configuration": {
                    "supportedRange": {"minimumValue": 0, "maximumValue": 100, "precision": 1},
                    "unitOfMeasure": "Alexa.Unit.Percent",
                },
                "semantics": {
                    "actionMappings": [
                        {
                            "@type": "ActionsToDirective",
                            "actions": ["Alexa.Actions.Open", "Alexa.Actions.Raise"],
                            "directive": {"name": "SetRangeValue", "payload": {"rangeValue": 100}},
                        },
                        {
                            "@type": "ActionsToDirective",
                            "actions": ["Alexa.Actions.Close", "Alexa.Actions.Lower"],
                            "directive": {"name": "SetRangeValue", "payload": {"rangeValue": 0}},
                        },
                    ],
                    "stateMappings": [
                        {
                            "@type": "StatesToRange",
                            "states": ["Alexa.States.Open"],
                            "range": {"minimumValue": 1, "maximumValue": 100},
                        },
                        {"@type": "StatesToValue", "states": ["Alexa.States.Closed"], "value": 0},
                    ],
                },
            },
            {
                "type": "AlexaInterface",
                "interface": "Alexa.EndpointHealth",
                "version": "3",
                "properties": {
                    "supported": [{"name": "connectivity"}],
                    "proactivelyReported": False,
                    "retrievable": True,
                },
            },
        ],
    }
    if room:
        ep["additionalAttributes"] = {"room": room}
    if cookie:
        ep["cookie"] = cookie
    return ep


def discovery_response(endpoints: list[dict]) -> dict:
    return {
        "event": {
            "header": _header("Alexa.Discovery", "Discover.Response"),
            "payload": {"endpoints": endpoints},
        }
    }


def _all_properties(range_value: int, available: bool = True, uncertainty_ms: int = 500) -> list:
    return [
        {
            "namespace": "Alexa.PowerController",
            "name": "powerState",
            "value": "ON" if range_value > 0 else "OFF",
            "timeOfSample": _now(),
            "uncertaintyInMilliseconds": uncertainty_ms,
        },
        {
            "namespace": "Alexa.RangeController",
            "instance": "Blind.Lift",
            "name": "rangeValue",
            "value": range_value,
            "timeOfSample": _now(),
            "uncertaintyInMilliseconds": uncertainty_ms,
        },
        {
            "namespace": "Alexa.EndpointHealth",
            "name": "connectivity",
            "value": {"value": "OK" if available else "UNREACHABLE"},
            "timeOfSample": _now(),
            "uncertaintyInMilliseconds": uncertainty_ms,
        },
    ]


def power_response(event: dict, power_state: str) -> dict:
    directive = event["directive"]
    range_value = 100 if power_state == "ON" else 0
    return {
        "context": {"properties": _all_properties(range_value)},
        "event": {
            "header": _header("Alexa", "Response", directive["header"].get("correlationToken")),
            "endpoint": directive["endpoint"],
            "payload": {},
        },
    }


def range_response(event: dict, range_value: int) -> dict:
    directive = event["directive"]
    return {
        "context": {"properties": _all_properties(range_value)},
        "event": {
            "header": _header("Alexa", "Response", directive["header"].get("correlationToken")),
            "endpoint": directive["endpoint"],
            "payload": {},
        },
    }


def state_report(event: dict, range_value: int, available: bool = True) -> dict:
    directive = event["directive"]
    return {
        "context": {"properties": _all_properties(range_value, available, uncertainty_ms=2000)},
        "event": {
            "header": _header("Alexa", "StateReport", directive["header"].get("correlationToken")),
            "endpoint": directive["endpoint"],
            "payload": {},
        },
    }


_SENSOR_CONFIG: dict[str, dict] = {
    "MotionSensor": {
        "description": "Somfy Motion Sensor",
        "category": "MOTION_SENSOR",
        "capability": {
            "type": "AlexaInterface",
            "interface": "Alexa.MotionSensor",
            "version": "3",
            "properties": {
                "supported": [{"name": "detectionState"}],
                "proactivelyReported": False,
                "retrievable": True,
            },
        },
    },
    "ContactSensor": {
        "description": "Somfy Contact Sensor",
        "category": "CONTACT_SENSOR",
        "capability": {
            "type": "AlexaInterface",
            "interface": "Alexa.ContactSensor",
            "version": "3",
            "properties": {
                "supported": [{"name": "detectionState"}],
                "proactivelyReported": False,
                "retrievable": True,
            },
        },
    },
    "TemperatureSensor": {
        "description": "Somfy Temperature Sensor",
        "category": "TEMPERATURE_SENSOR",
        "capability": {
            "type": "AlexaInterface",
            "interface": "Alexa.TemperatureSensor",
            "version": "3",
            "properties": {
                "supported": [{"name": "temperature"}],
                "proactivelyReported": False,
                "retrievable": True,
            },
        },
    },
    "LightSensor": {
        "description": "Somfy Light Sensor",
        "category": "OTHER",
        "capability": {
            "type": "AlexaInterface",
            "interface": "Alexa.RangeController",
            "instance": "Sensor.Illuminance",
            "version": "3",
            "properties": {
                "supported": [{"name": "rangeValue"}],
                "proactivelyReported": False,
                "retrievable": True,
                "nonControllable": True,
            },
            "capabilityResources": {
                "friendlyNames": [
                    {"@type": "text", "value": {"text": "Brightness", "locale": "en-US"}},
                ]
            },
            "configuration": {
                "supportedRange": {"minimumValue": 0, "maximumValue": 100000, "precision": 1},
            },
        },
    },
}


def sensor_endpoint(
    endpoint_id: str,
    label: str,
    room: str | None,
    sensor_type: str,
) -> dict:
    cfg = _SENSOR_CONFIG[sensor_type]
    ep = {
        "endpointId": endpoint_id,
        "manufacturerName": "Somfy",
        "friendlyName": label,
        "description": cfg["description"],
        "displayCategories": [cfg["category"]],
        "capabilities": [
            {"type": "AlexaInterface", "interface": "Alexa", "version": "3"},
            cfg["capability"],
            {
                "type": "AlexaInterface",
                "interface": "Alexa.EndpointHealth",
                "version": "3",
                "properties": {
                    "supported": [{"name": "connectivity"}],
                    "proactivelyReported": False,
                    "retrievable": True,
                },
            },
        ],
        "cookie": {"sensor_type": sensor_type},
    }
    if room:
        ep["additionalAttributes"] = {"room": room}
    return ep


def _sensor_properties(
    sensor_type: str,
    states: dict | None,
    uncertainty_ms: int = 2000,
) -> list:
    available = states is not None
    props: list = [{
        "namespace": "Alexa.EndpointHealth",
        "name": "connectivity",
        "value": {"value": "OK" if available else "UNREACHABLE"},
        "timeOfSample": _now(),
        "uncertaintyInMilliseconds": uncertainty_ms,
    }]
    if not available:
        return props

    if sensor_type == "MotionSensor":
        occupancy = states.get("core:OccupancyState", "")
        props.append({
            "namespace": "Alexa.MotionSensor",
            "name": "detectionState",
            "value": "DETECTED" if occupancy == "personInside" else "NOT_DETECTED",
            "timeOfSample": _now(),
            "uncertaintyInMilliseconds": uncertainty_ms,
        })
    elif sensor_type == "ContactSensor":
        contact = states.get("core:ContactState", "closed")
        props.append({
            "namespace": "Alexa.ContactSensor",
            "name": "detectionState",
            "value": "DETECTED" if contact == "open" else "NOT_DETECTED",
            "timeOfSample": _now(),
            "uncertaintyInMilliseconds": uncertainty_ms,
        })
    elif sensor_type == "TemperatureSensor":
        temp = states.get("core:TemperatureState")
        if temp is not None:
            props.append({
                "namespace": "Alexa.TemperatureSensor",
                "name": "temperature",
                "value": {"value": float(temp), "scale": "CELSIUS"},
                "timeOfSample": _now(),
                "uncertaintyInMilliseconds": uncertainty_ms,
            })
    elif sensor_type == "LightSensor":
        # Somfy io: sensors may report lux (core:LuminanceState) or sunshine
        # percentage (core:SunShineState) depending on the hardware model.
        raw = states.get("core:LuminanceState") if "core:LuminanceState" in states \
            else states.get("core:SunShineState")
        if raw is not None:
            props.append({
                "namespace": "Alexa.RangeController",
                "instance": "Sensor.Illuminance",
                "name": "rangeValue",
                "value": float(raw),
                "timeOfSample": _now(),
                "uncertaintyInMilliseconds": uncertainty_ms,
            })

    return props


def sensor_state_report(event: dict, sensor_type: str, states: dict | None) -> dict:
    directive = event["directive"]
    return {
        "context": {"properties": _sensor_properties(sensor_type, states)},
        "event": {
            "header": _header("Alexa", "StateReport", directive["header"].get("correlationToken")),
            "endpoint": directive["endpoint"],
            "payload": {},
        },
    }


def error_response(event: dict, error_type: str, message: str) -> dict:
    directive = event.get("directive", {})
    return {
        "event": {
            "header": _header("Alexa", "ErrorResponse", directive.get("header", {}).get("correlationToken")),
            "endpoint": directive.get("endpoint", {}),
            "payload": {"type": error_type, "message": message},
        }
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
