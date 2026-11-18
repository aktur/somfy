"""DynamoDB-backed token and sensor-state storage for the Somfy Alexa skill.

Single table, two item types (single-table design):
  PK=user_id  SK="tokens"              → ginaite_refresh, eg_access_token, eg_refresh_token, eg_expires_at
  PK=user_id  SK="sensor|{endpoint_id}"→ state, ts
"""

from __future__ import annotations

import os
import time

import boto3
from boto3.dynamodb.conditions import Key

_TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "somfy-alexa-skill")
_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    return _table


# ---------------------------------------------------------------------------
# Event Gateway (Alexa LWA) tokens — per user
# ---------------------------------------------------------------------------

def get_event_gateway_tokens(user_id: str) -> dict:
    resp = _get_table().get_item(Key={"user_id": user_id, "SK": "tokens"})
    item = resp.get("Item", {})
    return {
        "access_token": item.get("eg_access_token"),
        "refresh_token": item.get("eg_refresh_token"),
        "expires_at": int(item["eg_expires_at"]) if "eg_expires_at" in item else 0,
    }


def save_event_gateway_tokens(user_id: str, access_token: str, refresh_token: str | None, expires_in_seconds: int) -> None:
    expires_at = int(time.time() * 1000) + expires_in_seconds * 1000
    updates = {
        "eg_access_token": access_token,
        "eg_expires_at": expires_at,
    }
    if refresh_token:
        updates["eg_refresh_token"] = refresh_token
    _update_tokens(user_id, updates)


def clear_event_gateway_tokens(user_id: str) -> None:
    _get_table().update_item(
        Key={"user_id": user_id, "SK": "tokens"},
        UpdateExpression="REMOVE eg_access_token, eg_refresh_token, eg_expires_at",
    )


# ---------------------------------------------------------------------------
# Ginaite (Somfy) refresh token — per user
# ---------------------------------------------------------------------------

def get_ginaite_refresh(user_id: str) -> str | None:
    resp = _get_table().get_item(
        Key={"user_id": user_id, "SK": "tokens"},
        ProjectionExpression="ginaite_refresh",
    )
    return resp.get("Item", {}).get("ginaite_refresh")


def save_ginaite_refresh(user_id: str, token: str) -> None:
    _update_tokens(user_id, {"ginaite_refresh": token})


# ---------------------------------------------------------------------------
# Sensor states — per user, per endpoint
# ---------------------------------------------------------------------------

def get_sensor_state(user_id: str, endpoint_id: str) -> dict | None:
    """Return {"state": str, "ts": str} or None if never seen."""
    resp = _get_table().get_item(Key={"user_id": user_id, "SK": f"sensor|{endpoint_id}"})
    item = resp.get("Item")
    if item:
        return {"state": item["state"], "ts": item["ts"]}
    return None


def save_sensor_state(user_id: str, endpoint_id: str, state_value: str, time_of_sample: str) -> None:
    _get_table().put_item(Item={
        "user_id": user_id,
        "SK": f"sensor|{endpoint_id}",
        "state": state_value,
        "ts": time_of_sample,
    })


# ---------------------------------------------------------------------------
# User management — used by the poller and RevokeGrant
# ---------------------------------------------------------------------------

def list_users() -> list[dict]:
    """Return all user token items (one per linked user), each with user_id and token fields."""
    result = _get_table().scan(
        FilterExpression=Key("SK").eq("tokens"),
    )
    return result.get("Items", [])


def delete_user(user_id: str) -> None:
    """Delete all DynamoDB items for a user (called on RevokeGrant)."""
    table = _get_table()
    result = table.query(KeyConditionExpression=Key("user_id").eq(user_id))
    with table.batch_writer() as batch:
        for item in result.get("Items", []):
            batch.delete_item(Key={"user_id": item["user_id"], "SK": item["SK"]})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_tokens(user_id: str, attrs: dict) -> None:
    """Upsert named attributes on the tokens item for user_id."""
    sets = ", ".join(f"#k{i} = :v{i}" for i, _ in enumerate(attrs))
    names = {f"#k{i}": k for i, k in enumerate(attrs)}
    values = {f":v{i}": v for i, v in enumerate(attrs.values())}
    _get_table().update_item(
        Key={"user_id": user_id, "SK": "tokens"},
        UpdateExpression=f"SET {sets}",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
