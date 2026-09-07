"""Minimal JWT HS256 — stdlib only, no third-party dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

_HEADER = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_dec(s: str) -> bytes:
    pad = "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode(payload: dict, secret: str) -> str:
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    msg = f"{_HEADER}.{body}".encode()
    sig = _b64url(hmac.new(secret.encode(), msg, hashlib.sha256).digest())
    return f"{_HEADER}.{body}.{sig}"


def decode(token: str, secret: str) -> dict:
    try:
        header, body, sig = token.split(".")
    except ValueError:
        raise ValueError("Malformed token")
    msg = f"{header}.{body}".encode()
    expected = _b64url(hmac.new(secret.encode(), msg, hashlib.sha256).digest())
    if not hmac.compare_digest(sig.encode(), expected.encode()):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64url_dec(body))
    if payload.get("exp", float("inf")) < time.time():
        raise ValueError("Token expired")
    return payload
