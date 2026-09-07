"""Tests for auth_proxy.py — Somfy API calls are mocked."""

import json
import time
import urllib.parse
from unittest.mock import patch

import jwt_util
import auth_proxy

SECRET = "test-secret-do-not-use-in-production"
MOCK_GINAITE_REFRESH = "mock-ginaite-refresh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(path, qs=None):
    return {
        "requestContext": {"http": {"method": "GET", "path": path}},
        "queryStringParameters": qs or {},
    }


def _post(path, body: dict):
    return {
        "requestContext": {"http": {"method": "POST", "path": path}},
        "body": urllib.parse.urlencode(body),
        "isBase64Encoded": False,
    }


def _make_code(redirect_uri="https://alexa.example.com/cb", ttl=60):
    return jwt_util.encode({
        "sub": "user@example.com",
        "gr": MOCK_GINAITE_REFRESH,
        "ruri": redirect_uri,
        "exp": int(time.time()) + ttl,
        "t": "code",
    }, SECRET)


def _make_refresh_token():
    return jwt_util.encode({
        "gr": MOCK_GINAITE_REFRESH,
        "exp": int(time.time()) + 3600,
        "t": "refresh",
    }, SECRET)


# ---------------------------------------------------------------------------
# GET /authorize — login form
# ---------------------------------------------------------------------------

def test_authorize_get_returns_html():
    resp = auth_proxy.handler(_get("/authorize", {"redirect_uri": "https://cb", "state": "s1"}), None)
    assert resp["statusCode"] == 200
    assert "text/html" in resp["headers"]["Content-Type"]
    assert "<form" in resp["body"]


def test_authorize_get_embeds_redirect_uri_and_state():
    resp = auth_proxy.handler(_get("/authorize", {"redirect_uri": "https://cb", "state": "mystate"}), None)
    assert "https://cb" in resp["body"]
    assert "mystate" in resp["body"]


def test_authorize_get_no_error_block_initially():
    resp = auth_proxy.handler(_get("/authorize"), None)
    assert 'class="error"' not in resp["body"]


# ---------------------------------------------------------------------------
# POST /authorize — authenticate and redirect
# ---------------------------------------------------------------------------

def _mock_sso_token():
    return "mock-sso-token"


def _mock_ginaite_token_from_sso(_):
    return ("mock-ginaite-access", MOCK_GINAITE_REFRESH)


def test_authorize_post_redirects_on_success():
    redirect_uri = "https://layla.amazon.com/api/skill/link/XXXX"
    with patch.object(auth_proxy.somfy, "_post_form", return_value={"access_token": "sso"}), \
         patch.object(auth_proxy.somfy, "ginaite_token_from_sso",
                      return_value=("access", MOCK_GINAITE_REFRESH)):
        resp = auth_proxy.handler(_post("/authorize", {
            "username": "user@example.com",
            "password": "secret",
            "redirect_uri": redirect_uri,
            "state": "state123",
        }), None)
    assert resp["statusCode"] == 302
    location = resp["headers"]["Location"]
    assert location.startswith(redirect_uri)
    assert "code=" in location
    assert "state=state123" in location


def test_authorize_post_code_contains_ginaite_refresh():
    redirect_uri = "https://alexa.example.com/cb"
    with patch.object(auth_proxy.somfy, "_post_form", return_value={"access_token": "sso"}), \
         patch.object(auth_proxy.somfy, "ginaite_token_from_sso",
                      return_value=("access", MOCK_GINAITE_REFRESH)):
        resp = auth_proxy.handler(_post("/authorize", {
            "username": "u@example.com", "password": "pw",
            "redirect_uri": redirect_uri, "state": "s",
        }), None)
    location = resp["headers"]["Location"]
    code = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["code"][0])
    claims = jwt_util.decode(code, SECRET)
    assert claims["gr"] == MOCK_GINAITE_REFRESH
    assert claims["t"] == "code"


def test_authorize_post_bad_credentials_shows_error():
    with patch.object(auth_proxy.somfy, "_post_form", side_effect=Exception("401")):
        resp = auth_proxy.handler(_post("/authorize", {
            "username": "bad@example.com", "password": "wrong",
            "redirect_uri": "https://cb", "state": "s",
        }), None)
    assert resp["statusCode"] == 200
    assert 'class="error"' in resp["body"]


def test_authorize_post_missing_fields_shows_error():
    resp = auth_proxy.handler(_post("/authorize", {"redirect_uri": "https://cb", "state": "s"}), None)
    assert 'class="error"' in resp["body"]
    assert resp["statusCode"] == 200


# ---------------------------------------------------------------------------
# POST /token — authorization_code grant
# ---------------------------------------------------------------------------

def test_token_exchange_code_returns_access_and_refresh():
    redirect_uri = "https://alexa.example.com/cb"
    code = _make_code(redirect_uri)
    resp = auth_proxy.handler(_post("/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["token_type"] == "Bearer"
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["expires_in"] == auth_proxy.TOKEN_TTL


def test_token_exchange_access_token_contains_ginaite_refresh():
    redirect_uri = "https://alexa.example.com/cb"
    code = _make_code(redirect_uri)
    resp = auth_proxy.handler(_post("/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }), None)
    access = json.loads(resp["body"])["access_token"]
    claims = jwt_util.decode(access, SECRET)
    assert claims["gr"] == MOCK_GINAITE_REFRESH
    assert claims["t"] == "access"


def test_token_exchange_expired_code_returns_error():
    code = _make_code(ttl=-1)
    resp = auth_proxy.handler(_post("/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://alexa.example.com/cb",
    }), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "invalid_grant"


def test_token_exchange_redirect_uri_mismatch_returns_error():
    code = _make_code("https://correct.example.com/cb")
    resp = auth_proxy.handler(_post("/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://wrong.example.com/cb",
    }), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# POST /token — refresh_token grant
# ---------------------------------------------------------------------------

def test_token_refresh_issues_new_access_token():
    refresh = _make_refresh_token()
    resp = auth_proxy.handler(_post("/token", {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    claims = jwt_util.decode(body["access_token"], SECRET)
    assert claims["gr"] == MOCK_GINAITE_REFRESH


def test_token_refresh_wrong_type_returns_error():
    wrong = _make_code()  # code token, not refresh
    resp = auth_proxy.handler(_post("/token", {
        "grant_type": "refresh_token",
        "refresh_token": wrong,
    }), None)
    assert resp["statusCode"] == 400


def test_token_unsupported_grant_returns_error():
    resp = auth_proxy.handler(_post("/token", {"grant_type": "password"}), None)
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "unsupported_grant_type"


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------

def test_unknown_path_returns_404():
    resp = auth_proxy.handler(_get("/unknown"), None)
    assert resp["statusCode"] == 404
