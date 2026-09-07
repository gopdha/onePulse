"""Shared plumbing for OnePulse's single-page Streamlit UI (Home.py).

Redesigned (Task 19) from a 3-page app (Home/Review/Chat) into one
script — Streamlit's multi-page auto-navigation is gone along with the
`pages/` directory that triggered it; this module's helpers are what
used to be duplicated across those pages' own inline query functions,
now shared by the sections within the single page.

NOT business logic — every real action (persist_report,
approve_report, reject_report, count_pending_reviews, get_report_detail,
list_recent_reports, the Chat Assistant's ask_question) is called
directly from onepulse_common. This module only adapts
Streamlit's synchronous, rerun-per-interaction execution model to those
real async functions, and holds the one Postgres connection-settings
constant every page needs — the same host/database/role convention every
other script in this project already uses (migrate.py, seed_dev_data.py,
review_cli.py, etc.).

Deliberate scope decision, stated plainly: this UI layer does not wire
the dual Application Insights + Arize observability every CLI agentic
entry point (run_pipeline.py, chat_cli.py) already carries. Not asked
for in this task, and skipping it avoids a real, known risk this project
has hit before (re-initializing a global OpenTelemetry TracerProvider on
every Streamlit script rerun, not just once per process). The CLI entry
points remain the observed real paths for the pipeline and chat agents;
this UI is presentation-first.

Run: streamlit run Home.py (from the repository root — every relative
path here, and in onepulse_common.pipeline, assumes that CWD, same as
every existing script in this project).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Coroutine, TypeVar

from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

load_dotenv()

T = TypeVar("T")

PG_SETTINGS = PostgresSettings(
    host="onepulse-pg-dev.postgres.database.azure.com",
    database="onepulse",
    role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
)


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Streamlit has no persistent event loop across reruns — each real
    async call runs its own, the same way every CLI script in this
    project already calls `asyncio.run(main())` once per invocation.
    """
    return asyncio.run(coro)


async def with_connection(fn, *args, **kwargs):
    """Opens one real Postgres connection, calls `fn(conn, *args,
    **kwargs)`, closes it. Every onepulse_common.human_governance /
    onepulse_common.pipeline function already takes `conn` as its first
    argument — this is the minimal adaptation the CORE RULE allows
    (wiring, not reimplementing): those functions' own signatures are
    unchanged.
    """
    client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            return await fn(conn, *args, **kwargs)
    finally:
        await client.close()


async def fetch_actors() -> list[dict]:
    async def _fetch(conn):
        rows = await conn.fetch(
            "SELECT actor_id, role, entra_object_id FROM actors ORDER BY created_at"
        )
        return [dict(row) for row in rows]

    return await with_connection(_fetch)


async def fetch_programs() -> list[dict]:
    """Real programs table, for the project selector (Task 23) — the
    same table `list_recent_reports`/`persist_report` already key off
    of, so a project only appears here once it's genuinely wired end to
    end (seeded via `scripts/seed_dev_data.py --program <name>`), not
    just present in Azure DevOps.
    """
    async def _fetch(conn):
        rows = await conn.fetch("SELECT program_id, name FROM programs ORDER BY name")
        return [dict(row) for row in rows]

    return await with_connection(_fetch)
