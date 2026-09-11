"""Phase 7 Human Governance API, exposed as a CLI (LLD Section 2.2).

No web framework stands here — nothing in this project has needed one
yet, and this phase's own scope is the API contract and the database's
own guarantees (see onepulse_common/human_governance.py), not an HTTP
server. A real deployment (Phase 8+/Next-scope) would put these same
functions behind Apigee/AKS per the Physical Architecture; this CLI is a
real, directly runnable front end to that same logic in the meantime.

Reviewer identity — a real, explicit shortcut, stated plainly: --actor-id
is trusted as given on the command line. There is no session, no token
verification, nothing stopping a caller from passing any actor_id that
exists in the `actors` table. A real auth integration must replace this
with a resolved Entra ID identity looked up by entra_object_id, not a
free-form CLI argument. `scripts/seed_dev_data.py` seeds exactly one
stand-in reviewer actor for local use.

Usage:
    python scripts/review_cli.py pending --program-id <uuid>
    python scripts/review_cli.py approve --report-id 1 --actor-id <uuid> [--notes "..."]
    python scripts/review_cli.py reject --report-id 1 --actor-id <uuid> --notes "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.human_governance import (
    ActorIdRequiredError,
    NotesRequiredError,
    approve_report,
    list_pending_reviews,
    reject_report,
)

load_dotenv()


def build_settings() -> PostgresSettings:
    return PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    )


async def _tenant_id_for_actor(conn, actor_id: str) -> str:
    """Migration Plan Phase 8: this CLI already trusts `--actor-id` as
    given (see the module docstring's own stated shortcut) — resolving
    the real tenant directly from `actors.tenant_id` is the honest,
    minimal fix for a tool with no real identity resolution of its own,
    not a second, independent scope-resolution mechanism to keep in
    sync with `core_api.security.get_current_actor`'s own (which
    deliberately resolves via `actor_scope`, since it can't trust a
    caller-supplied actor_id the way this CLI already does).
    """
    tenant_id = await conn.fetchval("SELECT tenant_id FROM actors WHERE actor_id = $1", actor_id)
    if tenant_id is None:
        raise SystemExit(f"No actors row for actor_id={actor_id!r}")
    return str(tenant_id)


async def _tenant_id_for_program(conn, program_id: str) -> str:
    tenant_id = await conn.fetchval(
        "SELECT pf.tenant_id FROM portfolios pf JOIN programs p ON p.portfolio_id = pf.portfolio_id "
        "WHERE p.program_id = $1",
        program_id,
    )
    if tenant_id is None:
        raise SystemExit(f"No program_id={program_id!r} found")
    return str(tenant_id)


async def run(args: argparse.Namespace) -> dict:
    client = await PostgresClient.connect(build_settings(), min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            if args.command == "pending":
                tenant_id = await _tenant_id_for_program(conn, args.program_id)
                return await list_pending_reviews(conn, args.program_id, tenant_id)
            if args.command == "approve":
                tenant_id = await _tenant_id_for_actor(conn, args.actor_id)
                return await approve_report(conn, args.report_id, args.actor_id, tenant_id, args.notes or "")
            if args.command == "reject":
                tenant_id = await _tenant_id_for_actor(conn, args.actor_id)
                return await reject_report(conn, args.report_id, args.actor_id, tenant_id, args.notes)
            raise ValueError(f"unknown command: {args.command}")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending_parser = subparsers.add_parser("pending", help="List reports awaiting review")
    pending_parser.add_argument("--program-id", required=True)

    approve_parser = subparsers.add_parser("approve", help="Approve a report")
    approve_parser.add_argument("--report-id", type=int, required=True)
    approve_parser.add_argument("--actor-id", required=True)
    approve_parser.add_argument("--notes", default="")

    reject_parser = subparsers.add_parser("reject", help="Reject a report")
    reject_parser.add_argument("--report-id", type=int, required=True)
    reject_parser.add_argument("--actor-id", required=True)
    reject_parser.add_argument("--notes", required=True)

    args = parser.parse_args()

    try:
        result = asyncio.run(run(args))
    except ActorIdRequiredError:
        print(json.dumps({"error": "actor_id_required"}))
        sys.exit(1)
    except NotesRequiredError:
        print(json.dumps({"error": "notes_required"}))
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
