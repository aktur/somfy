"""Login With Amazon (LWA) token exchange for the Alexa Event Gateway."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"


def _post_form(fields: dict) -> dict:
    fields["client_id"] = os.environ["EVENT_GATEWAY_CLIENT_ID"]
    fields["client_secret"] = os.environ["EVENT_GATEWAY_CLIENT_SECRET"]
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(_LWA_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def exchange_auth_code(code: str) -> dict:
    """Exchange AcceptGrant authorization code for access + refresh tokens."""
    return _post_form({"grant_type": "authorization_code", "code": code})


def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an expired access token."""
    return _post_form({"grant_type": "refresh_token", "refresh_token": refresh_token})
