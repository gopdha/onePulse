"""Real service-to-service authentication and identity resolution for
the core API (Migration Plan Phase 2, ADR-017; extended for real
reviewer identity/roles/scope in Phase 8, ADR-027).

Three distinct, deliberately separate real checks, not one:

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

3. Role/scope resolution (`get_current_actor`) — real as of Phase 8: a
   single FastAPI dependency every route depends on, resolving role
   (owner/visitor, see `onepulse_common.roles`), the real tenant this
   actor's own `actor_scope` resolves to (the identical join `reports`'
   own `tenant_isolation` RLS policy performs — not `actors.tenant_id`
   directly, so the RLS setter and the RLS policy can never disagree),
   and the real set of `program_id`s this actor is authorized to see.
   **Deliberately resolved fresh on every single request, with no
   session-lifetime cache of any kind** — revoking access by deleting an
   `actor_scope` row must take effect on the very next request, which is
   the one real advantage a server-side session model has over a
   browser-held token that can't be invalidated server-side; caching
   this resolution for any period would give that advantage back.

No real reviewer authentication for the BFF's *own* sign-in exists in
this module — that's Container Apps' Easy Auth (Phase 7) plus `bff`'s
own real Entra-object-id extraction (`bff/main.py`). What lands here is
already a platform-verified Entra object ID (or, only for local dev
with no Easy Auth in front, `ONEPULSE_STUB_ENTRA_OBJECT_ID`) — this
module's own real logic doesn't change based on which; it already
resolves whatever object ID it's given against `actors` for real.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import asyncpg
import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException, Request
from jwt import PyJWKClient

from onepulse_common.roles import is_owner_role

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

# Migration Plan Phase 6: a real Application permission (app role),
# `Service.Access`, added to this App Registration and assigned only to
# id-onepulse-bff-dev's service principal. Before this, `verify_service_
# token` validated signature/audience/issuer but not WHO within this
# tenant was calling — any principal able to acquire a token for this
# API's audience would pass. Checking `roles` closes that: a valid
# token that lacks this specific app role is a real, distinct 403, not
# silently accepted.
REQUIRED_APP_ROLE = os.environ.get("ONEPULSE_CORE_API_REQUIRED_APP_ROLE", "Service.Access")

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

    if REQUIRED_APP_ROLE not in claims.get("roles", []):
        raise HTTPException(status_code=403, detail={"error": "missing_app_role", "required": REQUIRED_APP_ROLE})

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


async def resolve_tenant_id(conn: asyncpg.Connection, actor_id: str) -> str | None:
    """Migration Plan Phase 8: the real tenant this actor's own
    `actor_scope` resolves to, via the IDENTICAL join `reports`' own
    `tenant_isolation` RLS policy performs (`actor_scope` ->
    portfolio_id/program_id -> `portfolios.tenant_id`) — deliberately
    NOT `actors.tenant_id` directly, so the value this module sets via
    `SET LOCAL app.current_tenant_id` and the value the RLS policy
    itself checks against can never structurally disagree.

    Returns `None` when the actor has no `actor_scope` row at all — a
    real, clean "no access" case (an `actors` row exists, but nothing
    authorizes it to see anything yet), not an error.
    """
    row = await conn.fetchrow(
        """
        SELECT pf.tenant_id
        FROM actor_scope s
        JOIN portfolios pf ON pf.portfolio_id = COALESCE(
            s.portfolio_id,
            (SELECT p.portfolio_id FROM programs p WHERE p.program_id = s.program_id)
        )
        WHERE s.actor_id = $1
        LIMIT 1
        """,
        actor_id,
    )
    return str(row["tenant_id"]) if row else None


async def resolve_authorized_program_ids(conn: asyncpg.Connection, actor_id: str) -> frozenset[str]:
    """Migration Plan Phase 8: every real `program_id` this actor may
    see — via a direct `program_id` scope row, or every program under a
    `portfolio_id` scope row. This is the real, program-granular half of
    "scope" that tenant-level RLS alone cannot express (an actor scoped
    to one program within a multi-program tenant must not see that
    tenant's *other* programs either) — checked explicitly at each route
    that accepts a `programId`/derives one from a `report_id`, alongside
    RLS's own tenant-level filter, not instead of it.
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT p.program_id
        FROM actor_scope s
        JOIN programs p ON p.program_id = s.program_id OR p.portfolio_id = s.portfolio_id
        WHERE s.actor_id = $1
        """,
        actor_id,
    )
    return frozenset(str(r["program_id"]) for r in rows)


@dataclass(frozen=True)
class CurrentActor:
    """Migration Plan Phase 8: the complete real identity/role/scope
    resolution for one request — `actor_id` (real, internal, never
    caller-supplied), `role` (real `actors.role`, owner-tier or
    'visitor' — see `onepulse_common.roles.is_owner_role`), `tenant_id`
    (for `SET LOCAL app.current_tenant_id`), and `authorized_program_ids`
    (for the real, additional program-level scope check every
    `programId`-accepting route performs).
    """

    actor_id: str
    role: str
    tenant_id: str
    authorized_program_ids: frozenset[str]

    @property
    def is_owner(self) -> bool:
        return is_owner_role(self.role)


_NO_ACCESS_DETAIL = {
    "error": "no_access",
    "message": "This identity is authenticated but not provisioned for OnePulse. Ask a "
    "platform admin to provision access.",
}


async def get_current_actor(
    request: Request,
    x_onepulse_entra_object_id: str = Header(..., alias="X-Onepulse-Entra-Object-Id"),
) -> CurrentActor:
    """The real Migration Plan Phase 8 dependency every route in this
    service depends on. Deliberately does its own, separate, short-lived
    pool acquisition rather than sharing a route's own connection — this
    resolution has nothing to do with any one route's later transaction,
    and keeping it self-contained means no route needs to thread a
    connection through this function just to use it.

    Raises a real, clean `403` (never a stack trace, never a silent
    default scope) for both real "no access" shapes this phase names
    explicitly: no matching `actors` row at all (the common case —
    anyone the URL is shared with before being provisioned), and an
    `actors` row with no `actor_scope` at all (provisioned but not yet
    scoped to anything).
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        try:
            actor = await resolve_actor(conn, x_onepulse_entra_object_id)
        except ActorNotFoundError:
            raise HTTPException(status_code=403, detail=_NO_ACCESS_DETAIL)
        actor_id = str(actor["actor_id"])
        tenant_id = await resolve_tenant_id(conn, actor_id)
        if tenant_id is None:
            raise HTTPException(status_code=403, detail=_NO_ACCESS_DETAIL)
        program_ids = await resolve_authorized_program_ids(conn, actor_id)
    return CurrentActor(
        actor_id=actor_id, role=actor["role"], tenant_id=tenant_id, authorized_program_ids=program_ids
    )
