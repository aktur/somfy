"""Scheduled Lambda: polls Somfy motion/contact sensor states and sends Alexa ChangeReports."""

from __future__ import annotations

import time
import urllib.parse

import event_gateway
import somfy
import token_store


def lambda_handler(event, context):
    ginaite_refresh = token_store.get_ginaite_refresh()
    if not ginaite_refresh:
        print("[poller] No Ginaite refresh token in SSM — AcceptGrant not yet received.")
        return

    try:
        ginaite_access, new_refresh = somfy.refresh_ginaite(ginaite_refresh)
    except Exception as exc:
        print(f"[poller] Ginaite refresh failed: {exc}")
        return

    if new_refresh != ginaite_refresh:
        token_store.save_ginaite_refresh(new_refresh)

    try:
        sites = somfy.list_sites(ginaite_access)
    except Exception as exc:
        print(f"[poller] list_sites failed: {exc}")
        return

    seen_site_oids: set[str] = set()
    for site in sites:
        site_oid = site["site_oid"]
        if site_oid in seen_site_oids:
            continue
        seen_site_oids.add(site_oid)

        try:
            site_token = somfy.scoped_token(new_refresh, site_oid)
            devices = somfy.get_devices(site_token)
            _check_site(site_oid, devices)
        except Exception as exc:
            print(f"[poller] Error checking site {site_oid}: {exc}")


def _encode_endpoint_id(site_oid: str, device_url: str) -> str:
    return urllib.parse.quote(f"{site_oid}|{device_url}", safe="").replace("%", ".")


_LUX_CHANGE_THRESHOLD = 50.0


def _check_site(site_oid: str, devices: list[dict]) -> None:
    for device in devices:
        stype = somfy.sensor_type(device)
        if stype not in (
            somfy.MOTION_SENSOR_TYPE,
            somfy.CONTACT_SENSOR_TYPE,
            somfy.LIGHT_SENSOR_TYPE,
            somfy.TEMPERATURE_SENSOR_TYPE,
        ):
            continue

        states = {s["name"]: s["value"] for s in device.get("states", [])}
        if states.get("core:StatusState") == "unavailable":
            continue

        device_url = device["deviceURL"]
        endpoint_id = _encode_endpoint_id(site_oid, device_url)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        if stype == somfy.LIGHT_SENSOR_TYPE:
            print(f"[poller] LightSensor found: {device.get('label', device_url)} states={list(states.keys())}")
            _check_lux(endpoint_id, states, ts)
            continue

        if stype == somfy.TEMPERATURE_SENSOR_TYPE:
            _check_temperature(endpoint_id, states, ts)
            continue

        if stype == somfy.MOTION_SENSOR_TYPE:
            occupancy = states.get("core:OccupancyState", "")
            new_state = "DETECTED" if occupancy == "personInside" else "NOT_DETECTED"
        else:
            contact = states.get("core:ContactState", "closed")
            new_state = "DETECTED" if contact == "open" else "NOT_DETECTED"

        stored = token_store.get_sensor_state(endpoint_id)
        old_state = stored["state"] if stored else None

        if new_state != old_state:
            print(f"[poller] state change: {endpoint_id} {old_state!r} → {new_state!r}")
            try:
                event_gateway.send_change_report(endpoint_id, stype, new_state, ts)
            except Exception as exc:
                print(f"[poller] ChangeReport failed for {endpoint_id}: {exc}")

        token_store.save_sensor_state(endpoint_id, new_state, ts)


_TEMPERATURE_CHANGE_THRESHOLD = 0.5  # °C


def _check_temperature(endpoint_id: str, states: dict, ts: str) -> None:
    raw = states.get("core:TemperatureState")
    if raw is None:
        return

    new_temp = round(float(raw), 1)
    stored = token_store.get_sensor_state(endpoint_id)
    old_temp = round(float(stored["state"]), 1) if stored and stored["state"] is not None else None

    if old_temp is None or abs(new_temp - old_temp) >= _TEMPERATURE_CHANGE_THRESHOLD:
        if old_temp is not None:
            print(f"[poller] temperature change: {endpoint_id} {old_temp} → {new_temp}")
        try:
            event_gateway.send_temperature_change_report(endpoint_id, new_temp, ts)
        except Exception as exc:
            print(f"[poller] Temperature ChangeReport failed for {endpoint_id}: {exc}")

    token_store.save_sensor_state(endpoint_id, str(new_temp), ts)


def _check_lux(endpoint_id: str, states: dict, ts: str) -> None:
    raw = states.get("core:LuminanceState") if "core:LuminanceState" in states \
        else states.get("core:SunShineState")
    if raw is None:
        return

    new_lux = float(raw)
    stored = token_store.get_sensor_state(endpoint_id)
    old_lux = float(stored["state"]) if stored and stored["state"] is not None else None

    if old_lux is None or abs(new_lux - old_lux) >= _LUX_CHANGE_THRESHOLD:
        if old_lux is not None:
            print(f"[poller] lux change: {endpoint_id} {old_lux} → {new_lux}")
        try:
            event_gateway.send_lux_change_report(endpoint_id, new_lux, ts)
        except Exception as exc:
            print(f"[poller] Lux ChangeReport failed for {endpoint_id}: {exc}")

    token_store.save_sensor_state(endpoint_id, str(new_lux), ts)
