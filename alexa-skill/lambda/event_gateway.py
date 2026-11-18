"""Alexa Event Gateway client — sends proactive ChangeReport events."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

import lwa
import token_store

_EXPIRY_SAFETY_MARGIN_MS = 5 * 60 * 1000
_BASE_URL = os.environ.get("EVENT_GATEWAY_BASE_URL", "https://api.eu.amazonalexa.com")


def get_valid_access_token(user_id: str, force_refresh: bool = False) -> str:
    tokens = token_store.get_event_gateway_tokens(user_id)
    if (
        not force_refresh
        and tokens["access_token"]
        and time.time() * 1000 < tokens["expires_at"] - _EXPIRY_SAFETY_MARGIN_MS
    ):
        return tokens["access_token"]

    if tokens["refresh_token"]:
        refreshed = lwa.refresh_access_token(tokens["refresh_token"])
        token_store.save_event_gateway_tokens(
            user_id,
            refreshed["access_token"],
            refreshed.get("refresh_token") or tokens["refresh_token"],
            int(refreshed["expires_in"]),
        )
        return refreshed["access_token"]

    raise RuntimeError(
        "No valid Event Gateway credentials. Disable and re-enable the skill to obtain a new AcceptGrant."
    )


def _http_post(payload: dict, access_token: str) -> int:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{_BASE_URL}/v3/events", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _build_change_report(endpoint_id: str, access_token: str, change_props: list, context_props: list) -> dict:
    return {
        "context": {"properties": context_props},
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "ChangeReport",
                "messageId": str(uuid.uuid4()),
                "payloadVersion": "3",
            },
            "endpoint": {
                "scope": {"type": "BearerToken", "token": access_token},
                "endpointId": endpoint_id,
            },
            "payload": {
                "change": {
                    "cause": {"type": "PHYSICAL_INTERACTION"},
                    "properties": change_props,
                }
            },
        },
    }


def _post_with_retry(user_id: str, payload: dict) -> int:
    access_token = payload["event"]["endpoint"]["scope"]["token"]
    status = _http_post(payload, access_token)
    if status == 401:
        access_token = get_valid_access_token(user_id, force_refresh=True)
        payload["event"]["endpoint"]["scope"]["token"] = access_token
        status = _http_post(payload, access_token)
    return status


def send_change_report(
    user_id: str,
    endpoint_id: str,
    sensor_type: str,
    detection_state: str,
    time_of_sample: str,
) -> None:
    """Send a ChangeReport for a motion or contact sensor."""
    if sensor_type == "MotionSensor":
        namespace = "Alexa.MotionSensor"
    elif sensor_type == "ContactSensor":
        namespace = "Alexa.ContactSensor"
    else:
        raise ValueError(f"ChangeReport not supported for sensor_type: {sensor_type}")

    access_token = get_valid_access_token(user_id)
    health_prop = {
        "namespace": "Alexa.EndpointHealth",
        "name": "connectivity",
        "value": {"value": "OK"},
        "timeOfSample": time_of_sample,
        "uncertaintyInMilliseconds": 0,
    }
    change_prop = {
        "namespace": namespace,
        "name": "detectionState",
        "value": detection_state,
        "timeOfSample": time_of_sample,
        "uncertaintyInMilliseconds": 0,
    }
    payload = _build_change_report(endpoint_id, access_token, [change_prop], [health_prop])

    status = _post_with_retry(user_id, payload)
    if status not in (200, 202):
        raise RuntimeError(f"Event Gateway rejected ChangeReport: HTTP {status}")

    print(
        f"[event_gateway] ChangeReport sent: endpointId={endpoint_id}"
        f" state={detection_state} status={status}"
    )


def send_temperature_change_report(
    user_id: str,
    endpoint_id: str,
    celsius: float,
    time_of_sample: str,
) -> None:
    """Send a ChangeReport for a temperature sensor."""
    access_token = get_valid_access_token(user_id)
    health_prop = {
        "namespace": "Alexa.EndpointHealth",
        "name": "connectivity",
        "value": {"value": "OK"},
        "timeOfSample": time_of_sample,
        "uncertaintyInMilliseconds": 0,
    }
    change_prop = {
        "namespace": "Alexa.TemperatureSensor",
        "name": "temperature",
        "value": {"value": celsius, "scale": "CELSIUS"},
        "timeOfSample": time_of_sample,
        "uncertaintyInMilliseconds": 0,
    }
    payload = _build_change_report(endpoint_id, access_token, [change_prop], [health_prop])

    status = _post_with_retry(user_id, payload)
    if status not in (200, 202):
        raise RuntimeError(f"Event Gateway rejected temperature ChangeReport: HTTP {status}")

    print(
        f"[event_gateway] Temperature ChangeReport sent: endpointId={endpoint_id}"
        f" celsius={celsius} status={status}"
    )


