"""Tests for calibration.py — piecewise-linear interpolation and validation."""

from unittest.mock import patch

import pytest

import calibration

# Two calibration curves that are easy to verify by hand:
#   physical → motor
#   0 → 0, 50 → 80, 100 → 100
# midpoints:
#   physical=25 → motor=40   (0 + 25*80/50)
#   physical=75 → motor=90   (80 + 25*20/50)
# inverse:
#   motor=40  → physical=25  (0 + 40*50/80)
#   motor=90  → physical=75  (50 + 10*50/20)
SIMPLE_POINTS = [
    {"physical": 0, "motor": 0},
    {"physical": 50, "motor": 80},
    {"physical": 100, "motor": 100},
]

DEVICE_A = "io://XXXX-XXXX-XXXX/11111111"
DEVICE_B = "io://XXXX-XXXX-XXXX/22222222"


def _cfg(shutters: dict) -> dict:
    return {"shutters": shutters}


def _cfg_a(points=None) -> dict:
    return _cfg({DEVICE_A: {"calibration": points or SIMPLE_POINTS}})


# ---------------------------------------------------------------------------
# Identity mapping (no calibration configured)
# ---------------------------------------------------------------------------

class TestIdentityMapping:
    def test_physical_to_motor_midpoint(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.physical_to_motor(DEVICE_A, 50) == 50

    def test_physical_to_motor_zero(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.physical_to_motor(DEVICE_A, 0) == 0

    def test_physical_to_motor_hundred(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.physical_to_motor(DEVICE_A, 100) == 100

    def test_motor_to_physical_midpoint(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.motor_to_physical(DEVICE_A, 50) == 50

    def test_motor_to_physical_zero(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.motor_to_physical(DEVICE_A, 0) == 0

    def test_motor_to_physical_hundred(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.motor_to_physical(DEVICE_A, 100) == 100


# ---------------------------------------------------------------------------
# Exact endpoints preserved
# ---------------------------------------------------------------------------

class TestEndpoints:
    def test_physical_to_motor_at_0(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 0) == 0

    def test_physical_to_motor_at_100(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 100) == 100

    def test_motor_to_physical_at_0(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, 0) == 0

    def test_motor_to_physical_at_100(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, 100) == 100


# ---------------------------------------------------------------------------
# Interpolation — forward (physical → motor)
# ---------------------------------------------------------------------------

class TestPhysicalToMotor:
    def test_at_calibration_point_50(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 50) == 80

    def test_midpoint_first_segment(self):
        # physical=25 → 0 + 25*(80-0)/(50-0) = 40
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 25) == 40

    def test_midpoint_second_segment(self):
        # physical=75 → 80 + 25*(100-80)/(100-50) = 90
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 75) == 90

    def test_quarter_first_segment(self):
        # physical=10 → 0 + 10*80/50 = 16
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 10) == 16


# ---------------------------------------------------------------------------
# Inverse interpolation (motor → physical)
# ---------------------------------------------------------------------------

class TestMotorToPhysical:
    def test_at_calibration_point_80(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, 80) == 50

    def test_midpoint_first_segment(self):
        # motor=40 → 0 + 40*(50-0)/(80-0) = 25
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, 40) == 25

    def test_midpoint_second_segment(self):
        # motor=90 → 50 + 10*(100-50)/(100-80) = 75
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, 90) == 75


# ---------------------------------------------------------------------------
# Clamping outside valid range
# ---------------------------------------------------------------------------

class TestClamping:
    def test_physical_below_zero_clamped(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, -10) == 0

    def test_physical_above_100_clamped(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.physical_to_motor(DEVICE_A, 110) == 100

    def test_motor_below_zero_clamped(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, -5) == 0

    def test_motor_above_100_clamped(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            assert calibration.motor_to_physical(DEVICE_A, 105) == 100

    def test_identity_clamp_below_zero(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.physical_to_motor(DEVICE_A, -5) == 0

    def test_identity_clamp_above_100(self):
        with patch.object(calibration, "_load_config", return_value=_cfg({})):
            assert calibration.physical_to_motor(DEVICE_A, 150) == 100


# ---------------------------------------------------------------------------
# Per-shutter independence
# ---------------------------------------------------------------------------

class TestPerShutterIndependence:
    def test_different_devices_different_results(self):
        points_b = [
            {"physical": 0, "motor": 0},
            {"physical": 50, "motor": 60},
            {"physical": 100, "motor": 100},
        ]
        cfg = _cfg({
            DEVICE_A: {"calibration": SIMPLE_POINTS},
            DEVICE_B: {"calibration": points_b},
        })
        with patch.object(calibration, "_load_config", return_value=cfg):
            motor_a = calibration.physical_to_motor(DEVICE_A, 50)
            motor_b = calibration.physical_to_motor(DEVICE_B, 50)
        assert motor_a == 80
        assert motor_b == 60
        assert motor_a != motor_b

    def test_uncalibrated_device_gets_identity(self):
        cfg = _cfg({DEVICE_A: {"calibration": SIMPLE_POINTS}})
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_B, 50) == 50


# ---------------------------------------------------------------------------
# Round-trip conversion
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_physical_roundtrip_at_calibration_points(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            for physical in (0, 50, 100):
                motor = calibration.physical_to_motor(DEVICE_A, physical)
                recovered = calibration.motor_to_physical(DEVICE_A, motor)
                assert abs(recovered - physical) <= 1, f"roundtrip failed at physical={physical}"

    def test_motor_roundtrip_at_calibration_points(self):
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            for motor in (0, 80, 100):
                physical = calibration.motor_to_physical(DEVICE_A, motor)
                recovered = calibration.physical_to_motor(DEVICE_A, physical)
                assert abs(recovered - motor) <= 1, f"roundtrip failed at motor={motor}"

    def test_roundtrip_intermediate(self):
        # physical=25 → motor=40 → physical=25
        with patch.object(calibration, "_load_config", return_value=_cfg_a()):
            motor = calibration.physical_to_motor(DEVICE_A, 25)
            assert motor == 40
            physical = calibration.motor_to_physical(DEVICE_A, motor)
            assert physical == 25


# ---------------------------------------------------------------------------
# Invalid calibration configurations
# ---------------------------------------------------------------------------

class TestValidation:
    def test_single_point_rejected(self):
        points = [{"physical": 0, "motor": 0}]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError, match="at least 2 points"):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_non_monotonic_physical_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"physical": 50, "motor": 40},
            {"physical": 30, "motor": 80},  # physical goes backwards
            {"physical": 100, "motor": 100},
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError, match="strictly increasing"):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_duplicate_physical_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"physical": 50, "motor": 40},
            {"physical": 50, "motor": 80},  # duplicate physical
            {"physical": 100, "motor": 100},
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError, match="strictly increasing"):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_non_monotonic_motor_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"physical": 50, "motor": 60},
            {"physical": 75, "motor": 50},  # motor goes backwards
            {"physical": 100, "motor": 100},
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError, match="strictly increasing"):
                calibration.physical_to_motor(DEVICE_A, 60)

    def test_physical_out_of_range_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"physical": 110, "motor": 100},  # physical > 100
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError, match="out of range"):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_motor_out_of_range_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"physical": 100, "motor": 120},  # motor > 100
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError, match="out of range"):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_missing_physical_key_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"motor": 100},  # missing 'physical'
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_missing_motor_key_rejected(self):
        points = [
            {"physical": 0, "motor": 0},
            {"physical": 100},  # missing 'motor'
        ]
        with patch.object(calibration, "_load_config", return_value=_cfg_a(points)):
            with pytest.raises(ValueError):
                calibration.physical_to_motor(DEVICE_A, 50)

    def test_empty_calibration_list_gives_identity(self):
        # Empty list → treated as missing calibration → identity
        cfg = _cfg({DEVICE_A: {"calibration": []}})
        with patch.object(calibration, "_load_config", return_value=cfg):
            # empty list is falsy, so _get_calibration returns None → identity
            assert calibration.physical_to_motor(DEVICE_A, 60) == 60

    def test_missing_calibration_key_gives_identity(self):
        cfg = _cfg({DEVICE_A: {}})  # no 'calibration' key
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_A, 60) == 60


# ---------------------------------------------------------------------------
# Wildcard fallback ('*' key)
# ---------------------------------------------------------------------------

class TestWildcard:
    OVERRIDE_POINTS = [
        {"physical": 0, "motor": 0},
        {"physical": 50, "motor": 60},
        {"physical": 100, "motor": 100},
    ]

    def test_wildcard_used_when_no_exact_match(self):
        cfg = _cfg({"*": {"calibration": SIMPLE_POINTS}})
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_A, 50) == 80

    def test_exact_match_overrides_wildcard(self):
        cfg = _cfg({
            "*": {"calibration": SIMPLE_POINTS},          # 50 → 80
            DEVICE_A: {"calibration": self.OVERRIDE_POINTS},  # 50 → 60
        })
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_A, 50) == 60

    def test_other_device_falls_back_to_wildcard(self):
        cfg = _cfg({
            "*": {"calibration": SIMPLE_POINTS},
            DEVICE_A: {"calibration": self.OVERRIDE_POINTS},
        })
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_B, 50) == 80

    def test_no_wildcard_no_exact_match_gives_identity(self):
        cfg = _cfg({DEVICE_A: {"calibration": SIMPLE_POINTS}})
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_B, 50) == 50

    def test_wildcard_inverse_mapping(self):
        cfg = _cfg({"*": {"calibration": SIMPLE_POINTS}})
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.motor_to_physical(DEVICE_A, 80) == 50

    def test_wildcard_forward_and_inverse_device_b(self):
        cfg = _cfg({"*": {"calibration": SIMPLE_POINTS}})
        with patch.object(calibration, "_load_config", return_value=cfg):
            assert calibration.physical_to_motor(DEVICE_B, 25) == 40
            assert calibration.motor_to_physical(DEVICE_B, 40) == 25


# ---------------------------------------------------------------------------
# Multi-point curve (5 points, matches task example shape)
# ---------------------------------------------------------------------------

class TestMultiPointCurve:
    FIVE_POINTS = [
        {"physical": 0, "motor": 0},
        {"physical": 25, "motor": 38},
        {"physical": 50, "motor": 65},
        {"physical": 75, "motor": 84},
        {"physical": 100, "motor": 100},
    ]

    def test_at_each_calibration_point(self):
        expected = {0: 0, 25: 38, 50: 65, 75: 84, 100: 100}
        with patch.object(calibration, "_load_config", return_value=_cfg_a(self.FIVE_POINTS)):
            for physical, motor in expected.items():
                assert calibration.physical_to_motor(DEVICE_A, physical) == motor

    def test_inverse_at_each_calibration_point(self):
        expected = {0: 0, 38: 25, 65: 50, 84: 75, 100: 100}
        with patch.object(calibration, "_load_config", return_value=_cfg_a(self.FIVE_POINTS)):
            for motor, physical in expected.items():
                assert calibration.motor_to_physical(DEVICE_A, motor) == physical
