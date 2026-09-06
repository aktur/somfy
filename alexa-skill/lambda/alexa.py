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
