"""Per-shutter position calibration: piecewise-linear interpolation between
physical opening percentage and raw TaHoma motor percentage.

Both scales run 0 (closed) → 100 (open); the Alexa/TaHoma direction flip
stays in handler.py and is unrelated to this module.

Configuration is read from calibration.json in the same directory.
"""

from __future__ import annotations

import json
import os

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "calibration.json")
_config: dict | None = None


def _load_config() -> dict:
    global _config
    if _config is None:
        try:
            with open(_CONFIG_FILE) as f:
                _config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _config = {}
    return _config


def _get_calibration(device_url: str) -> list[dict] | None:
    """Return validated calibration points for a device, or None for identity mapping."""
    config = _load_config()
    shutter = config.get("shutters", {}).get(device_url)
    if not shutter:
        return None
    points = shutter.get("calibration")
    if not points:
        return None
    _validate(points)
    return points


def _validate(points: list[dict]) -> None:
    if len(points) < 2:
        raise ValueError("Calibration requires at least 2 points")
    for i, pt in enumerate(points):
        if not isinstance(pt.get("physical"), (int, float)):
            raise ValueError(f"Missing or non-numeric 'physical' at index {i}")
        if not isinstance(pt.get("motor"), (int, float)):
            raise ValueError(f"Missing or non-numeric 'motor' at index {i}")
        if not (0 <= pt["physical"] <= 100):
            raise ValueError(f"physical {pt['physical']} out of range [0,100] at index {i}")
        if not (0 <= pt["motor"] <= 100):
            raise ValueError(f"motor {pt['motor']} out of range [0,100] at index {i}")
    for i in range(1, len(points)):
        if points[i]["physical"] <= points[i - 1]["physical"]:
            raise ValueError(
                f"physical values must be strictly increasing; "
                f"got {points[i]['physical']} at index {i} (prev {points[i-1]['physical']})"
            )
        if points[i]["motor"] <= points[i - 1]["motor"]:
            raise ValueError(
                f"motor values must be strictly increasing; "
                f"got {points[i]['motor']} at index {i} (prev {points[i-1]['motor']})"
            )


def _lerp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation: map x from the xs scale to the ys scale."""
    x = max(xs[0], min(xs[-1], x))
    for i in range(1, len(xs)):
        if x <= xs[i]:
            p1, p2 = xs[i - 1], xs[i]
            m1, m2 = ys[i - 1], ys[i]
            return m1 + (x - p1) * (m2 - m1) / (p2 - p1)
    return ys[-1]


def physical_to_motor(device_url: str, physical_pct: float) -> int:
    """Convert physical opening % to motor opening %. Returns rounded integer.

    With no calibration configured, returns the clamped identity value.
    """
    points = _get_calibration(device_url)
    if points is None:
        return round(max(0.0, min(100.0, physical_pct)))
    xs = [p["physical"] for p in points]
    ys = [p["motor"] for p in points]
    return round(_lerp(physical_pct, xs, ys))


def motor_to_physical(device_url: str, motor_pct: float) -> int:
    """Convert motor opening % to physical opening %. Returns rounded integer.

    With no calibration configured, returns the clamped identity value.
    """
    points = _get_calibration(device_url)
    if points is None:
        return round(max(0.0, min(100.0, motor_pct)))
    xs = [p["motor"] for p in points]
    ys = [p["physical"] for p in points]
    return round(_lerp(motor_pct, xs, ys))
