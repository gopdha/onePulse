"""Real service-to-service authentication and identity resolution for
the core API (Migration Plan Phase 2, ADR-017).

Two distinct, deliberately separate real checks, not one:

1. Service-token validation (`verify_service_token`) — proves the
   *caller* is really the BFF, not anyone who can reach this port. A
   real Bearer JWT, validated for real: signature against the tenant's
   live JWKS (fetched once, cached — `PyJWT`'s own `PyJWKClient`),
   issuer, audience, and expiry. Not a shared secret, not a trusted
   header — a real token acquired against this project's own real Entra
   App Registration (`onepulse-core-api`, `az ad app create`, see
   CLAUDE.md Task 41 for the full real setup and the real consent
   propagation delay found live along the way).

2. Actor resolution (`resolve_actor`) — proves *who the request is on
   behalf of*, and is a completely separate question from #1. ADR-017's
   open question, now answered: the core API receives an Entra object
   ID (via the `X-Onepulse-Entra-Object-Id` header, not the JSON body —
   identity is auth-plane metadata, not a domain field) and resolves it
   against the real `actors` table itself. The core API NEVER accepts
   an `actor_id` — the internal primary key — from anything external.
   Under the alternative (trusting a BFF-supplied actor_id), a BFF bug
   becomes privilege escalation everywhere; under this one, the BFF can
   only assert *who* the user is, and *what they may do* is always
   computed by the component that owns the data.

No real reviewer authentication exists yet (Phase 8) — the object ID
arriving here is currently always the BFF's own stubbed value, forwarded
unchanged from `ONEPULSE_STUB_ENTRA_OBJECT_ID`. Nothing about this
module's own real logic changes when Phase 8 lands: it already resolves
whatever object ID it's given against `actors` for real. Only the BFF's
own source of that value changes then, not this module and not the
shape of what it receives.
"""

from __future__ import annotations

import os

import asyncpg
import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from jwt import PyJWKClient

# Real bug found live (2026-09-10): this module reads env vars at
# import time to build the JWKS URL below. `core_api/main.py` imports
# this module before its own `load_dotenv()` call runs, so without this,
# TENANT_ID was empty on every real startup, producing a malformed JWKS
# URL (a real 404 from login.microsoftonline.com, not a made-up
# scenario) and rejecting every genuinely valid token. `load_dotenv()`
# is safe to call more than once (idempotent), so this doesn't assume
# anything about import order elsewhere.
load_dotenv()

TENANT_ID = os.environ.get("ONEPULSE_ENTRA_TENANT_ID", "")
CORE_API_APP_ID = os.environ.get("ONEPULSE_CORE_API_APP_ID", "")
CORE_API_IDENTIFIER_URI = os.environ.get("ONEPULSE_CORE_API_IDENTIFIER_URI", "")

# Real, live Microsoft-hosted JWKS endpoint for this tenant — the same
# real signing keys that issued the token, fetched (and cached by
# PyJWKClient) rather than trusted blind. Works for both v1 and v2
# tokens; this project's real tokens are v1 (issuer sts.windows.net —
# the app registration was never opted into accessTokenAcceptedVersion
# 2), validated against `_V1_ISSUER` below accordingly.
_JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
_V1_ISSUER = f"https://sts.windows.net/{TENANT_ID}/"

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_JWKS_URI)
    return _jwks_client


class ActorNotFoundError(Exception):
    """Raised when a resolved Entra object ID has no matching real
    `actors` row — a real, honest failure, not silently defaulted to
    some placeholder identity.
    """

    def __init__(self, entra_object_id: str) -> None:
        self.entra_object_id = entra_object_id
        super().__init__(f"No actors row for entra_object_id={entra_object_id!r}")


async def verify_service_token(authorization: str = Header(...)) -> dict:
    """Real FastAPI dependency: extracts the Bearer token, validates its
    real signature (against the tenant's live JWKS), audience (must be
    this core API's own identifier URI — proves the token was issued
    *for this service*, not merely *by this tenant*), and issuer (must
    be this real tenant's v1 STS issuer). Raises 401 on any failure —
    each real, distinct failure reason is preserved in the exception
    detail rather than collapsed into one generic message, since a
    wrong-audience token and an expired token are different real
    problems with different fixes.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "missing_bearer_token"})
    token = authorization.removeprefix("Bearer ").strip()

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CORE_API_IDENTIFIER_URI,
            issuer=_V1_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"error": "token_expired"})
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail={"error": "invalid_audience"})
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail={"error": "invalid_issuer"})
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail={"error": "invalid_token", "detail": str(exc)})

    return claims


async def resolve_actor(conn: asyncpg.Connection, entra_object_id: str) -> dict:
    """The real ADR-017 resolution: given an Entra object ID (never an
    internal actor_id), looks up the real `actors` row and returns its
    real `actor_id`/`role` — the only place in the core API an internal
    actor_id is ever produced, always derived here, never accepted as
    input.
    """
    row = await conn.fetchrow(
        "SELECT actor_id, role FROM actors WHERE entra_object_id = $1", entra_object_id
    )
    if row is None:
        raise ActorNotFoundError(entra_object_id)
    return dict(row)


async def get_entra_object_id(
    x_onepulse_entra_object_id: str = Header(..., alias="X-Onepulse-Entra-Object-Id")
) -> str:
    """Real FastAPI dependency for routes that need to know who the
    request is on behalf of. A header, not a body field — identity is
    auth-plane metadata the BFF asserts, never a domain field a caller
    fills in as part of what they're asking for.
    """
    return x_onepulse_entra_object_id
