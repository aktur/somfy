"""OAuth2 authorization-code proxy for the Somfy TaHoma Alexa skill.

Wraps Somfy's password-grant-only OAuth2 in a standard authorization code flow
that Alexa account linking can use.  Deployed as a Lambda Function URL.

Endpoints:
  GET  /authorize  — render Somfy login form
  POST /authorize  — authenticate and redirect back with a signed code
  POST /token      — exchange code / refresh_token for a JWT access_token
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse

import jwt_util
import somfy

CODE_TTL = 60
TOKEN_TTL = 3600
REFRESH_TTL = 90 * 24 * 3600


def handler(event, context):
    http = event["requestContext"]["http"]
    method, path = http["method"], http["path"]

    if path == "/authorize" and method == "GET":
        return _authorize_form(event)
    if path == "/authorize" and method == "POST":
        return _authorize_submit(event)
    if path == "/token" and method == "POST":
        return _token(event)
    return {"statusCode": 404, "body": "Not found"}


# ---------------------------------------------------------------------------
# /authorize  GET — show login form
# ---------------------------------------------------------------------------

def _authorize_form(event):
    qs = event.get("queryStringParameters") or {}
    return _html_response(_login_html(
        redirect_uri=qs.get("redirect_uri", ""),
        state=qs.get("state", ""),
        error=None,
    ))


# ---------------------------------------------------------------------------
# /authorize  POST — authenticate and redirect
# ---------------------------------------------------------------------------

def _authorize_submit(event):
    params = _parse_body(event)
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    username = params.get("username", "").strip()
    password = params.get("password", "")

    if not username or not password:
        return _html_response(_login_html(redirect_uri, state, "Email and password are required."))

    try:
        sso = somfy._post_form(somfy.SOMFY_SSO_URL, {
            "grant_type": "password",
            "client_id": somfy.CLIENT_ID,
            "client_secret": somfy.CLIENT_SECRET,
            "username": username,
            "password": password,
        })["access_token"]
        _, ginaite_refresh = somfy.ginaite_token_from_sso(sso)
    except Exception:
        return _html_response(_login_html(redirect_uri, state, "Login failed. Check your Somfy credentials."))

    secret = os.environ["JWT_SECRET"]
    code = jwt_util.encode({
        "sub": username,
        "gr": ginaite_refresh,
        "ruri": redirect_uri,
        "exp": int(time.time()) + CODE_TTL,
        "t": "code",
    }, secret)

    location = (f"{redirect_uri}"
                f"?code={urllib.parse.quote(code, safe='')}"
                f"&state={urllib.parse.quote(state, safe='')}")
    return {"statusCode": 302, "headers": {"Location": location}}


# ---------------------------------------------------------------------------
# /token  POST — exchange code or refresh_token
# ---------------------------------------------------------------------------

def _token(event):
    params = _parse_body(event)
    grant = params.get("grant_type", "")
    if grant == "authorization_code":
        return _exchange_code(params)
    if grant == "refresh_token":
        return _exchange_refresh(params)
    return _token_error("unsupported_grant_type")


def _exchange_code(params):
    secret = os.environ["JWT_SECRET"]
    try:
        claims = jwt_util.decode(params.get("code", ""), secret)
        if claims.get("t") != "code":
            raise ValueError("Not a code token")
        if claims.get("ruri") != params.get("redirect_uri", ""):
            raise ValueError("redirect_uri mismatch")
    except ValueError as exc:
        return _token_error("invalid_grant", str(exc))
    return _issue_tokens(claims["gr"], secret)


def _exchange_refresh(params):
    secret = os.environ["JWT_SECRET"]
    try:
        claims = jwt_util.decode(params.get("refresh_token", ""), secret)
        if claims.get("t") != "refresh":
            raise ValueError("Not a refresh token")
    except ValueError as exc:
        return _token_error("invalid_grant", str(exc))
    return _issue_tokens(claims["gr"], secret)


def _issue_tokens(ginaite_refresh: str, secret: str) -> dict:
    now = int(time.time())
    access_token = jwt_util.encode(
        {"gr": ginaite_refresh, "exp": now + TOKEN_TTL, "t": "access"}, secret
    )
    refresh_token = jwt_util.encode(
        {"gr": ginaite_refresh, "exp": now + REFRESH_TTL, "t": "refresh"}, secret
    )
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL,
            "refresh_token": refresh_token,
        }),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_body(event) -> dict:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    return dict(urllib.parse.parse_qsl(body))


def _html_response(html: str) -> dict:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": html,
    }


def _token_error(error: str, description: str = "") -> dict:
    body: dict = {"error": error}
    if description:
        body["error_description"] = description
    return {
        "statusCode": 400,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Somfy TaHoma — Link Account</title>
<style>
  *,*::before,*::after{{box-sizing:border-box}}
  body{{font-family:system-ui,sans-serif;background:#f5f5f5;display:flex;
        align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px}}
  .card{{background:#fff;border-radius:12px;padding:2rem;width:100%;max-width:360px;
          box-shadow:0 2px 16px rgba(0,0,0,.1)}}
  h1{{font-size:1.1rem;margin:0 0 1.5rem;color:#111}}
  label{{display:block;font-size:.8rem;font-weight:600;color:#555;margin-bottom:.3rem}}
  input{{width:100%;padding:.65rem .8rem;border:1px solid #ddd;border-radius:8px;
          font-size:.95rem;margin-bottom:1rem;outline:none}}
  input:focus{{border-color:#0066cc;box-shadow:0 0 0 3px rgba(0,102,204,.15)}}
  button{{width:100%;padding:.75rem;background:#0066cc;color:#fff;border:none;
           border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer}}
  button:hover{{background:#0052a3}}
  .error{{background:#fff0f0;border:1px solid #fcc;color:#c00;border-radius:8px;
           padding:.65rem .8rem;font-size:.85rem;margin-bottom:1rem}}
</style>
</head>
<body>
<div class="card">
  <h1>Link your Somfy account</h1>
  {error_block}
  <form method="post">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <label for="u">Somfy account email</label>
    <input id="u" type="email" name="username" autocomplete="email" required autofocus>
    <label for="p">Password</label>
    <input id="p" type="password" name="password" autocomplete="current-password" required>
    <button type="submit">Link account</button>
  </form>
</div>
</body>
</html>
"""


def _login_html(redirect_uri: str, state: str, error: str | None) -> str:
    error_block = f'<div class="error">{error}</div>' if error else ""
    return _LOGIN_HTML.format(
        redirect_uri=redirect_uri.replace('"', "&quot;"),
        state=state.replace('"', "&quot;"),
        error_block=error_block,
    )
