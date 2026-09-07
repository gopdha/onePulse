"""Postgres client authenticated via Microsoft Entra ID — no static
password, ever, anywhere.

See Physical Architecture Section 4's revision note for why this project
uses Azure Database for PostgreSQL Flexible Server rather than Neon:
Flexible Server validates an Entra ID access token directly as the
connection password; Neon's Postgres roles are password-only and cannot
do this.

The role connecting here (`ONEPULSE_PG_ROLE`) must already exist as an
Entra-ID-mapped, non-admin Postgres role, created via
`pgaadauth_create_principal_with_oid`. This module does not create that
role; it only authenticates as whichever one `ONEPULSE_PG_ROLE` names —
and which role that is depends on who's connecting, not just which
environment:

- In AKS, `ONEPULSE_PG_ROLE=app_role` — mapped to that environment's
  workload managed identity object ID (scripts/bootstrap/create_app_role.sql).
- Running locally against onepulse-pg-dev,
  `ONEPULSE_PG_ROLE=app_role_local_dev` — mapped to an Entra group, not
  to app_role's object ID, because a developer's personal `az login`
  session presents a token for a *different* object ID than the
  workload identity's, and Entra role mapping is a strict 1:1 binding
  (scripts/bootstrap/create_app_role_local_dev.sql). Setting
  `ONEPULSE_PG_ROLE=app_role` locally will authenticate-fail — this is
  expected, not a bug in this module.
- `app_role_local_dev` exists on onepulse-pg-dev only, never on
  Staging or Production.
"""

from __future__ import annotations

import asyncpg
from azure.identity.aio import DefaultAzureCredential

from onepulse_common.config import PostgresSettings

# The fixed Entra ID resource identifier Postgres-scoped tokens are
# issued for — confirmed against Microsoft Learn
# (security-connect-with-managed-identity); not specific to any one
# server or environment.
POSTGRES_TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


class PostgresClient:
    """Owns both the connection pool and the credential used to
    authenticate it, so both can be closed together.
    """

    def __init__(self, pool: asyncpg.Pool, credential: DefaultAzureCredential) -> None:
        self._pool = pool
        self._credential = credential

    @property
    def pool(self) -> asyncpg.Pool:
        return self._pool

    async def close(self) -> None:
        await self._pool.close()
        await self._credential.close()

    @classmethod
    async def connect(
        cls,
        settings: PostgresSettings,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ) -> "PostgresClient":
        """Open a pool whose connections authenticate via Entra ID.

        asyncpg invokes the `password` callable once per new physical
        connection the pool opens, not once at pool creation — so a
        token nearing its ~1hr expiry never blocks a new connection. An
        already-established connection is unaffected by a token
        expiring later: Postgres validates the token only at initial
        authentication, not on every query.
        """
        credential = DefaultAzureCredential()

        async def password() -> str:
            token = await credential.get_token(POSTGRES_TOKEN_SCOPE)
            return token.token

        try:
            pool = await asyncpg.create_pool(
                host=settings.host,
                port=settings.port,
                database=settings.database,
                user=settings.role_name,
                password=password,
                ssl="require",
                min_size=min_size,
                max_size=max_size,
            )
        except Exception:
            await credential.close()
            raise

        return cls(pool, credential)
