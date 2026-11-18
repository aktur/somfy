"""Tests for token_store.py — DynamoDB backed with moto."""

import os
import time

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("DYNAMODB_TABLE", "somfy-alexa-skill")

import token_store  # noqa: E402  (must come after env var is set)

TABLE_NAME = "somfy-alexa-skill"
USER_A = "alice@example.com"
USER_B = "bob@example.com"
ENDPOINT_1 = "site1.7Cio.3A.2F.2F1234.2F111"
ENDPOINT_2 = "site1.7Cio.3A.2F.2F1234.2F222"


@pytest.fixture(autouse=True)
def ddb_table():
    """Create a fresh DynamoDB table for each test and reset the module-level cache."""
    with mock_aws():
        boto3.resource("dynamodb").create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "SK",      "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "SK",      "KeyType": "RANGE"},
            ],
        )
        token_store._table = None  # reset cached table reference
        yield
        token_store._table = None


# ---------------------------------------------------------------------------
# Ginaite refresh token
# ---------------------------------------------------------------------------

def test_ginaite_refresh_missing_returns_none():
    assert token_store.get_ginaite_refresh(USER_A) is None


def test_save_and_get_ginaite_refresh():
    token_store.save_ginaite_refresh(USER_A, "refresh-abc")
    assert token_store.get_ginaite_refresh(USER_A) == "refresh-abc"


def test_ginaite_refresh_isolated_per_user():
    token_store.save_ginaite_refresh(USER_A, "refresh-a")
    token_store.save_ginaite_refresh(USER_B, "refresh-b")
    assert token_store.get_ginaite_refresh(USER_A) == "refresh-a"
    assert token_store.get_ginaite_refresh(USER_B) == "refresh-b"


def test_save_ginaite_refresh_overwrites():
    token_store.save_ginaite_refresh(USER_A, "old")
    token_store.save_ginaite_refresh(USER_A, "new")
    assert token_store.get_ginaite_refresh(USER_A) == "new"


# ---------------------------------------------------------------------------
# Event Gateway tokens
# ---------------------------------------------------------------------------

def test_event_gateway_tokens_missing_returns_defaults():
    tokens = token_store.get_event_gateway_tokens(USER_A)
    assert tokens["access_token"] is None
    assert tokens["refresh_token"] is None
    assert tokens["expires_at"] == 0


def test_save_and_get_event_gateway_tokens():
    token_store.save_event_gateway_tokens(USER_A, "access-1", "refresh-1", 3600)
    tokens = token_store.get_event_gateway_tokens(USER_A)
    assert tokens["access_token"] == "access-1"
    assert tokens["refresh_token"] == "refresh-1"
    assert tokens["expires_at"] > time.time() * 1000


def test_save_event_gateway_tokens_no_refresh_preserves_existing():
    token_store.save_event_gateway_tokens(USER_A, "access-1", "refresh-1", 3600)
    token_store.save_event_gateway_tokens(USER_A, "access-2", None, 3600)
    tokens = token_store.get_event_gateway_tokens(USER_A)
    assert tokens["access_token"] == "access-2"
    assert tokens["refresh_token"] == "refresh-1"  # preserved


def test_clear_event_gateway_tokens():
    token_store.save_event_gateway_tokens(USER_A, "access-1", "refresh-1", 3600)
    token_store.clear_event_gateway_tokens(USER_A)
    tokens = token_store.get_event_gateway_tokens(USER_A)
    assert tokens["access_token"] is None
    assert tokens["refresh_token"] is None
    assert tokens["expires_at"] == 0


def test_event_gateway_tokens_isolated_per_user():
    token_store.save_event_gateway_tokens(USER_A, "access-a", "refresh-a", 3600)
    token_store.save_event_gateway_tokens(USER_B, "access-b", "refresh-b", 3600)
    assert token_store.get_event_gateway_tokens(USER_A)["access_token"] == "access-a"
    assert token_store.get_event_gateway_tokens(USER_B)["access_token"] == "access-b"


# ---------------------------------------------------------------------------
# Sensor states
# ---------------------------------------------------------------------------

def test_sensor_state_missing_returns_none():
    assert token_store.get_sensor_state(USER_A, ENDPOINT_1) is None


def test_save_and_get_sensor_state():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "2026-11-18T10:00:00.000Z")
    result = token_store.get_sensor_state(USER_A, ENDPOINT_1)
    assert result == {"state": "DETECTED", "ts": "2026-11-18T10:00:00.000Z"}


def test_sensor_state_overwrites():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "2026-11-18T10:00:00.000Z")
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "NOT_DETECTED", "2026-11-18T10:01:00.000Z")
    result = token_store.get_sensor_state(USER_A, ENDPOINT_1)
    assert result["state"] == "NOT_DETECTED"


def test_sensor_states_isolated_per_user():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "ts-a")
    token_store.save_sensor_state(USER_B, ENDPOINT_1, "NOT_DETECTED", "ts-b")
    assert token_store.get_sensor_state(USER_A, ENDPOINT_1)["state"] == "DETECTED"
    assert token_store.get_sensor_state(USER_B, ENDPOINT_1)["state"] == "NOT_DETECTED"


def test_sensor_states_isolated_per_endpoint():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "ts1")
    token_store.save_sensor_state(USER_A, ENDPOINT_2, "21.5", "ts2")
    assert token_store.get_sensor_state(USER_A, ENDPOINT_1)["state"] == "DETECTED"
    assert token_store.get_sensor_state(USER_A, ENDPOINT_2)["state"] == "21.5"


def test_save_sensor_state_without_ts_preserves_existing_ts():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "2026-11-18T10:00:00.000Z")
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED")  # no ts — same state, no change
    result = token_store.get_sensor_state(USER_A, ENDPOINT_1)
    assert result["ts"] == "2026-11-18T10:00:00.000Z"
    assert result["state"] == "DETECTED"


def test_save_sensor_state_stores_friendly_name():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "NOT_DETECTED", "ts1", "Rain-1")
    table = token_store._get_table()
    item = table.get_item(Key={"user_id": USER_A, "SK": f"sensor|{ENDPOINT_1}"})["Item"]
    assert item["name"] == "Rain-1"


def test_save_sensor_state_friendly_name_updated_independently():
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "ts1", "Old Name")
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", None, "New Name")
    table = token_store._get_table()
    item = table.get_item(Key={"user_id": USER_A, "SK": f"sensor|{ENDPOINT_1}"})["Item"]
    assert item["name"] == "New Name"
    assert item["ts"] == "ts1"  # ts not touched


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

def test_list_users_empty():
    assert token_store.list_users() == []


def test_list_users_returns_token_items_only():
    token_store.save_ginaite_refresh(USER_A, "refresh-a")
    token_store.save_ginaite_refresh(USER_B, "refresh-b")
    # Also write sensor states — these must NOT appear in list_users
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "ts")
    users = token_store.list_users()
    assert len(users) == 2
    user_ids = {u["user_id"] for u in users}
    assert user_ids == {USER_A, USER_B}


def test_list_users_contains_ginaite_refresh():
    token_store.save_ginaite_refresh(USER_A, "refresh-a")
    users = token_store.list_users()
    assert users[0]["ginaite_refresh"] == "refresh-a"


# ---------------------------------------------------------------------------
# delete_user
# ---------------------------------------------------------------------------

def test_delete_user_removes_tokens_and_sensor_states():
    token_store.save_ginaite_refresh(USER_A, "refresh-a")
    token_store.save_event_gateway_tokens(USER_A, "access", "refresh", 3600)
    token_store.save_sensor_state(USER_A, ENDPOINT_1, "DETECTED", "ts")

    token_store.delete_user(USER_A)

    assert token_store.get_ginaite_refresh(USER_A) is None
    assert token_store.get_sensor_state(USER_A, ENDPOINT_1) is None
    assert token_store.list_users() == []


def test_delete_user_does_not_affect_other_users():
    token_store.save_ginaite_refresh(USER_A, "refresh-a")
    token_store.save_ginaite_refresh(USER_B, "refresh-b")

    token_store.delete_user(USER_A)

    assert token_store.get_ginaite_refresh(USER_A) is None
    assert token_store.get_ginaite_refresh(USER_B) == "refresh-b"
