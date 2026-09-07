# Somfy TaHoma Tooling

Scripts and an Alexa Smart Home Skill for Somfy TaHoma, with support for **multiple locations** — the key feature missing from the official "TaHoma by Somfy" Alexa skill.

---

## Repository layout

```
├── list-devices.sh          # CLI: list all devices from a TaHoma gateway
├── env.sh                   # Local credentials (gitignored)
├── overkiz-root-ca-2048.crt # TLS CA cert for local gateway API
└── alexa-skill/
    ├── lambda/
    │   ├── handler.py       # Lambda entry point — Alexa directive routing
    │   ├── alexa.py         # Alexa Smart Home response builders
    │   └── somfy.py         # Somfy cloud auth + Overkiz API calls
    ├── tests/
    │   ├── test_alexa.py
    │   └── test_handler.py
    ├── template.yaml        # AWS SAM deployment template
    ├── skill-manifest.json  # Alexa Developer Console skill manifest
    └── requirements-dev.txt # pytest (dev only, no runtime deps)
```

---

## Background — why this exists

The official Somfy TaHoma Alexa skill works only for a single installation. If you have TaHoma boxes in two locations (e.g. a primary home and a holiday home), the skill can control only one of them. This project solves that by authenticating through Somfy's **Ginaite / BOB** multi-site API — the same backend the mobile app uses — and exposing all roller shutters from all sites as Alexa endpoints.

### Auth flow (Ginaite multi-site)

```
Somfy Accounts (SSO)
  └─ password grant → SSO access token
       └─ Ginaite token exchange → Ginaite access + refresh tokens
            └─ BOB site directory → list of {site_oid, name, gateway_id}
                 └─ Ginaite refresh + ?siteOID= → site-scoped Overkiz token
                      └─ Overkiz API (ha101-1.overkiz.com) → device control
```

### Closure convention

TaHoma and Alexa use opposite conventions:

| Value | TaHoma | Alexa |
|-------|--------|-------|
| 0     | open   | closed |
| 100   | closed | open   |

The Lambda inverts every value on the way in and out.

---

## `list-devices.sh`

Lists all devices connected to a local TaHoma gateway with their full names (fetched from the cloud because the gateway firmware truncates names to 16 ASCII characters).

### Setup

```sh
cp env.sh.example env.sh   # or create env.sh manually
# edit env.sh with your credentials
source env.sh
```

`env.sh` format (gitignored):

```sh
export SOMFY_GATEWAY=gateway-XXXX-XXXX-XXXX.local
export SOMFY_TOKEN=<local-developer-mode-token>
export SOMFY_PORT=8443
export SOMFY_USER=you@example.com
export SOMFY_PASS=yourpassword
```

The local developer mode token is generated in the TaHoma app under **Settings → TaHoma Developer Mode**.

### Usage

```sh
source env.sh
./list-devices.sh
```

First run fetches full device names from the cloud and caches them in `device-names.json`. Subsequent runs use the cache. Delete `device-names.json` to force a refresh.

---

## Alexa Smart Home Skill

A Smart Home skill that exposes all roller shutters from all your TaHoma installations as Alexa endpoints. Devices are discovered per-site and named `<Site> - <Device label>` (Polish/accented characters transliterated to ASCII).

### Capabilities per device

| Interface | Instance | Purpose |
|-----------|----------|---------|
| `Alexa.PowerController` | — | Open (TurnOn) / Close (TurnOff) |
| `Alexa.RangeController` | `Blind.Lift` | Set or adjust opening percentage |
| `Alexa.EndpointHealth` | — | Connectivity reporting |

Both controllers carry **semantic annotations** (`Alexa.Actions.Open/Close/Raise/Lower`) so Alexa's voice model maps "open/close" utterances to the correct directives.

### Voice commands (after room assignment)

```
"Alexa, close the [device name]"
"Alexa, open the [device name]"
"Alexa, set the [device name] to 50 percent"
"Alexa, raise the [device name] by 20 percent"
```

Room-context commands ("Alexa, close the blind" without a name) require the skill to be certified and published by Amazon — they do not work in the development/testing stage.

---

## Deployment

### Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) (`brew install aws-sam-cli`)
- AWS CLI configured (`aws configure`)
- An Alexa Developer account at [developer.amazon.com](https://developer.amazon.com)

### 1 — Create the Alexa skill

1. Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask)
2. Create a new skill → **Smart Home** → **Start from scratch**
3. Note the **Skill ID** (`amzn1.ask.skill.XXXX`)

### 2 — Deploy the Lambda

```sh
cd alexa-skill
sam build
sam deploy --guided
# Enter: AlexaSkillId and the deployment region when prompted
```

`sam deploy --guided` saves answers to `samconfig.toml`. Future deploys:

```sh
sam build && sam deploy
```

### 3 — Wire the Lambda ARN into the skill

Copy the `FunctionArn` from the SAM deploy output and paste it into the Alexa Developer Console under **Smart Home → Default endpoint**.

### 4 — Configure account linking

Somfy's OAuth2 server does not support third-party redirect URIs, so this project includes its own OAuth2 authorization proxy deployed alongside the skill Lambda. It shows a Somfy login form, authenticates the user via Somfy's password grant, and issues a signed JWT containing the Ginaite refresh token. The skill Lambda decodes that JWT on every invocation.

After `sam deploy` completes, the `AuthProxyUrl` output contains the proxy's base URL (a Lambda Function URL). In the Alexa Developer Console under **Account Linking**:

| Field | Value |
|-------|-------|
| Authorization URI | `<AuthProxyUrl>/authorize` |
| Access Token URI | `<AuthProxyUrl>/token` |
| Client ID | *(any string, e.g. `somfy-alexa`)* |
| Client Secret | *(any string — the JWT secret secures tokens, not this)* |
| Client Authentication Scheme | Credentials in request body |
| Scope | *(leave empty)* |

Before deploying, generate a `JwtSecret` — a random 32-byte hex string shared between the auth proxy Lambda and the skill Lambda:

```sh
openssl rand -hex 32
```

Pass this as the `JwtSecret` parameter during `sam deploy --guided`. Both Lambdas receive it as the `JWT_SECRET` environment variable.

### 5 — Discover devices

In the Alexa app: **Devices → + → Add Device → Other** or say "Alexa, discover devices".

---

## Development

### Run tests

```sh
cd alexa-skill
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

All 52 tests run in under 0.1 s with no network access — every Somfy API call is mocked.

### View Lambda logs

```sh
sam logs --stack-name somfy-tahoma-app --tail
```

### Remove deployed infrastructure

```sh
sam delete
```

---

## How it works — code tour

| File | Responsibility |
|------|---------------|
| `somfy.py` | Auth (SSO → Ginaite → BOB → scoped token), device queries, `setClosure` commands. Pure stdlib — no third-party dependencies. |
| `alexa.py` | Builds Alexa Smart Home response envelopes. Stateless pure functions. |
| `handler.py` | `lambda_handler` entry point. Routes directives to the right handler. Encodes `site_oid\|device_url` into Alexa endpoint IDs so every directive carries the site context without a database. |

### Endpoint ID encoding

Each Alexa endpoint ID encodes `<site_oid>|<device_url>` (percent-encoded, `%` replaced with `.` for Alexa compatibility). This means control directives (`PowerController`, `RangeController`, `ReportState`) can mint a site-scoped token directly from the endpoint ID without a lookup table.
