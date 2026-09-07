"""Seeds exactly one real tenant/portfolio/program row, per Build Plan
Scoping Notes: "The full Tenant -> Portfolio -> Program schema is
created now, exactly as specified in Low-Level Design... for now, one
real tenant, portfolio, and program row is sufficient." Active RLS
enforcement across multiple tenants remains Next-scope (NFR-1) — this
is deliberately not a multi-tenant seed.

Program name matches the real Azure DevOps project this whole pipeline
has been investigating against (singleSlide, org gopdha) — a real
anchor, not a placeholder, so any future work wiring run_pipeline.py's
output into these tables has a real program_id to attach to.

Idempotent: safe to re-run, does nothing if the row already exists.

Run: python scripts/seed_dev_data.py --target dev
"""

from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

load_dotenv()

TARGETS: dict[str, PostgresSettings] = {
    "dev": PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    ),
}

TENANT_NAME = "OnePulse Dev Tenant"
PORTFOLIO_NAME = "gopdha Portfolio"
DEFAULT_PROGRAM_NAME = "singleSlide"
DEFAULT_SOURCE_SYSTEM_REF = "https://dev.azure.com/gopdha/singleSlide"

# Phase 7's explicit, stated shortcut: no real auth system yet, so the
# reviewer identity backing scripts/review_cli.py is this one seeded
# actor row, not a resolved Entra ID session. entra_object_id is a
# recognizable placeholder, not a real object ID — a real auth
# integration must replace this row's role with one resolved from an
# actual verified token, not reuse this fixed id.
STANDIN_REVIEWER_ENTRA_OBJECT_ID = "local-dev-standin-reviewer"
STANDIN_REVIEWER_ROLE = "program_lead"


async def seed(settings: PostgresSettings, program_name: str, source_system_ref: str) -> None:
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            tenant_id = await conn.fetchval(
                "SELECT tenant_id FROM tenants WHERE name = $1", TENANT_NAME
            )
            if tenant_id is None:
                tenant_id = await conn.fetchval(
                    "INSERT INTO tenants (name) VALUES ($1) RETURNING tenant_id", TENANT_NAME
                )
                print(f"Created tenant: {tenant_id} ({TENANT_NAME})")
            else:
                print(f"Tenant already exists: {tenant_id} ({TENANT_NAME})")

            portfolio_id = await conn.fetchval(
                "SELECT portfolio_id FROM portfolios WHERE tenant_id = $1 AND name = $2",
                tenant_id,
                PORTFOLIO_NAME,
            )
            if portfolio_id is None:
                portfolio_id = await conn.fetchval(
                    "INSERT INTO portfolios (tenant_id, name) VALUES ($1, $2) RETURNING portfolio_id",
                    tenant_id,
                    PORTFOLIO_NAME,
                )
                print(f"Created portfolio: {portfolio_id} ({PORTFOLIO_NAME})")
            else:
                print(f"Portfolio already exists: {portfolio_id} ({PORTFOLIO_NAME})")

            program_id = await conn.fetchval(
                "SELECT program_id FROM programs WHERE portfolio_id = $1 AND name = $2",
                portfolio_id,
                program_name,
            )
            if program_id is None:
                program_id = await conn.fetchval(
                    "INSERT INTO programs (portfolio_id, name, source_system_ref) VALUES ($1, $2, $3) "
                    "RETURNING program_id",
                    portfolio_id,
                    program_name,
                    source_system_ref,
                )
                print(f"Created program: {program_id} ({program_name})")
            else:
                print(f"Program already exists: {program_id} ({program_name})")

            actor_id = await conn.fetchval(
                "SELECT actor_id FROM actors WHERE entra_object_id = $1",
                STANDIN_REVIEWER_ENTRA_OBJECT_ID,
            )
            if actor_id is None:
                actor_id = await conn.fetchval(
                    "INSERT INTO actors (tenant_id, role, entra_object_id) VALUES ($1, $2, $3) "
                    "RETURNING actor_id",
                    tenant_id,
                    STANDIN_REVIEWER_ROLE,
                    STANDIN_REVIEWER_ENTRA_OBJECT_ID,
                )
                print(f"Created stand-in reviewer actor: {actor_id} ({STANDIN_REVIEWER_ROLE})")
            else:
                print(f"Stand-in reviewer actor already exists: {actor_id} ({STANDIN_REVIEWER_ROLE})")
    finally:
        await client.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    parser.add_argument("--program", default=DEFAULT_PROGRAM_NAME, help="Real program name to register (Task 23: e.g. 'Leave Tracker').")
    parser.add_argument(
        "--source-system-ref",
        default=None,
        help="Real source system URL. Defaults to https://dev.azure.com/gopdha/<program> when omitted.",
    )
    args = parser.parse_args()
    source_system_ref = args.source_system_ref or f"https://dev.azure.com/gopdha/{args.program}"
    await seed(TARGETS[args.target], args.program, source_system_ref)


if __name__ == "__main__":
    asyncio.run(main())
