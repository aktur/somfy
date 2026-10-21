"""Tests for somfy.py helpers that don't require real network calls."""

from unittest.mock import patch

import somfy

DEVICE_URL = "io://XXXX-XXXX-XXXX/13387958"
OTHER_URL = "io://XXXX-XXXX-XXXX/99999999"
TOKEN = "mock-token"


def _device(url, states):
    return {"deviceURL": url, "states": [{"name": k, "value": v} for k, v in states.items()]}


# ---------------------------------------------------------------------------
# get_closure — offline / status state
# ---------------------------------------------------------------------------

def test_get_closure_returns_value_when_available():
    devices = [_device(DEVICE_URL, {"core:ClosureState": 30})]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) == 30


def test_get_closure_returns_none_when_status_unavailable():
    # TaHoma marks the device offline; last cached closure value must be ignored.
    devices = [_device(DEVICE_URL, {
        "core:StatusState": "unavailable",
        "core:ClosureState": 30,  # stale cached value — must not be used
    })]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) is None


def test_get_closure_returns_value_when_status_available():
    devices = [_device(DEVICE_URL, {
        "core:StatusState": "available",
        "core:ClosureState": 50,
    })]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) == 50


def test_get_closure_returns_none_when_device_not_found():
    devices = [_device(OTHER_URL, {"core:ClosureState": 10})]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) is None


def test_get_closure_returns_none_when_no_closure_state():
    devices = [_device(DEVICE_URL, {"core:StatusState": "available"})]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) is None


def test_get_closure_prefers_closure_state_over_target():
    devices = [_device(DEVICE_URL, {
        "core:ClosureState": 30,
        "core:TargetClosureState": 50,
    })]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) == 30


def test_get_closure_falls_back_to_target_closure_state():
    devices = [_device(DEVICE_URL, {"core:TargetClosureState": 70})]
    with patch("somfy.get_devices", return_value=devices):
        assert somfy.get_closure(TOKEN, DEVICE_URL) == 70
