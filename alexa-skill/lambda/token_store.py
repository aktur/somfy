"""SSM Parameter Store-backed token storage for the Somfy Alexa skill."""

from __future__ import annotations

import json
import os
import time

import boto3

_SSM_PREFIX = os.environ.get("SSM_PREFIX", "/somfy-alexa-skill")
_ssm = None


def _client():
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _get(name: str) -> str | None:
    try:
        resp = _client().get_parameter(
            Name=f"{_SSM_PREFIX}/{name}", WithDecryption=True
        )
        return resp["Parameter"]["Value"]
    except _client().exceptions.ParameterNotFound:
        return None


def _put(name: str, value: str, *, secure: bool = True) -> None:
    _client().put_parameter(
        Name=f"{_SSM_PREFIX}/{name}",
        Value=value,
        Type="SecureString" if secure else "String",
        Overwrite=True,
    )


def _delete(name: str) -> None:
    try:
        _client().delete_parameter(Name=f"{_SSM_PREFIX}/{name}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Event Gateway (Alexa LWA) tokens
# ---------------------------------------------------------------------------

def get_event_gateway_tokens() -> dict:
    access_token = _get("event-gateway/access_token")
    refresh_token = _get("event-gateway/refresh_token")
    expires_at = _get("event-gateway/expires_at")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": int(expires_at) if expires_at else 0,
    }


def save_event_gateway_tokens(access_token: str, refresh_token: str | None, expires_in_seconds: int) -> None:
    expires_at = int(time.time() * 1000) + expires_in_seconds * 1000
    _put("event-gateway/access_token", access_token)
    if refresh_token:
        _put("event-gateway/refresh_token", refresh_token)
    _put("event-gateway/expires_at", str(expires_at))


def clear_event_gateway_tokens() -> None:
    for name in ("event-gateway/access_token", "event-gateway/refresh_token", "event-gateway/expires_at"):
        _delete(name)


# ---------------------------------------------------------------------------
# Ginaite (Somfy) refresh token — used by the poller
# ---------------------------------------------------------------------------

def get_ginaite_refresh() -> str | None:
    return _get("ginaite/refresh_token")


def save_ginaite_refresh(token: str) -> None:
    _put("ginaite/refresh_token", token)


# ---------------------------------------------------------------------------
# Sensor states — used by the poller to detect changes
# ---------------------------------------------------------------------------

def _sensor_ssm_name(endpoint_id: str) -> str:
    # endpoint_id may contain '.' and alphanumerics — all valid in SSM paths
    return f"sensor-states/{endpoint_id}"


def get_sensor_state(endpoint_id: str) -> dict | None:
    """Return {"state": str, "ts": str} or None if never seen."""
    raw = _get(_sensor_ssm_name(endpoint_id))
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def save_sensor_state(endpoint_id: str, state_value: str, time_of_sample: str) -> None:
    _put(_sensor_ssm_name(endpoint_id), json.dumps({"state": state_value, "ts": time_of_sample}), secure=False)
