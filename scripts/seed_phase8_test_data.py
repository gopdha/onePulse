"""Migration Plan Phase 8 (ADR-027): real second-tenant data, plus the
real actor_scope rows Phase 8's own identity/RLS work needs to be
provable against, at all — with one tenant, a policy that filters
correctly and one that silently matches everything produce identical
results (this project's own fourth instance of "designed correctly,
documented confidently, never exercised," per Governance & Security
Reference §6).

Pure Postgres, as instructed: no second Azure DevOps project, no ADO
API calls at all. A couple of real blobs ARE uploaded to Azure Blob
Storage — a separate, unrelated Azure service to ADO — since one of
Phase 8's own required proofs ("cannot retrieve a SAS for a report
outside its scope") needs a real blob to test the SAS mechanism
against; nothing here touches Azure DevOps.

What this creates, all idempotent (safe to re-run):
  1. A real actor_scope row for the EXISTING Tenant-A stand-in reviewer
     (portfolio-level — this actor predates Phase 8 and, before this
     script, had no actor_scope at all; get_current_actor() would have
     403'd it).
  2. A real Tenant-A VISITOR actor + actor_scope (portfolio-level, same
     portfolio) — the identity used for the cross-tenant isolation
     proofs.
  3. A real second, fictional tenant/portfolio/program ("Meridian
     Health", no real Azure DevOps project behind it).
  4. A real Tenant-B OWNER actor + actor_scope (portfolio-level) — a
     positive control: proves the isolation mechanism actually shows
     data when correctly scoped, not merely "always empty" (which would
     trivially, uselessly pass the negative test even if broken).
  5. Two real reports + findings + untracked_items for Tenant B.
  6. One real report for Tenant A (a new row under the existing
     singleSlide program, a distant future week_of to avoid any real
     collision) — the positive-control counterpart for the SAS test.
  7. Two real tiny placeholder blobs uploaded to the existing `reports`
     blob container (Phase 8), one backing the Tenant-A test report,
     one backing a Tenant-B report — real `blob://` URIs written to
     `rendered_artifact_uri` for both.

Run: python scripts/seed_phase8_test_data.py --target dev
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os

from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from onepulse_common.blob_storage import upload_report_blob
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

TENANT_A_NAME = "OnePulse Dev Tenant"
TENANT_A_PORTFOLIO_NAME = "gopdha Portfolio"
TENANT_A_PROGRAM_NAME = "singleSlide"
TENANT_A_VISITOR_ENTRA_OBJECT_ID = "local-dev-tenant-a-visitor"

TENANT_B_NAME = "Meridian Health (fictional, Phase 8 test tenant)"
TENANT_B_PORTFOLIO_NAME = "Meridian Portfolio"
TENANT_B_PROGRAM_NAME = "Meridian Patient Portal"
TENANT_B_OWNER_ENTRA_OBJECT_ID = "local-dev-tenant-b-owner"

# A distant future Monday — real, deliberate, never collides with any
# real historical report for either tenant.
TENANT_A_TEST_WEEK_OF = dt.date(2030, 1, 7)
TENANT_B_WEEK_OF_1 = dt.date(2030, 1, 7)
TENANT_B_WEEK_OF_2 = dt.date(2030, 1, 14)

_PLACEHOLDER_PPTX_BYTES = (
    b"OnePulse Phase 8 test artifact -- not a real rendered .pptx, "
    b"only real enough to prove the SAS mechanism end to end."
)


async def _get_or_create_tenant(conn, name: str) -> str:
    tenant_id = await conn.fetchval("SELECT tenant_id FROM tenants WHERE name = $1", name)
    if tenant_id is None:
        tenant_id = await conn.fetchval("INSERT INTO tenants (name) VALUES ($1) RETURNING tenant_id", name)
        print(f"Created tenant: {tenant_id} ({name})")
    return str(tenant_id)


async def _get_or_create_portfolio(conn, tenant_id: str, name: str) -> str:
    portfolio_id = await conn.fetchval(
        "SELECT portfolio_id FROM portfolios WHERE tenant_id = $1 AND name = $2", tenant_id, name
    )
    if portfolio_id is None:
        portfolio_id = await conn.fetchval(
            "INSERT INTO portfolios (tenant_id, name) VALUES ($1, $2) RETURNING portfolio_id",
            tenant_id,
            name,
        )
        print(f"Created portfolio: {portfolio_id} ({name})")
    return str(portfolio_id)


async def _get_or_create_program(conn, portfolio_id: str, name: str, source_system_ref: str | None) -> str:
    program_id = await conn.fetchval(
        "SELECT program_id FROM programs WHERE portfolio_id = $1 AND name = $2", portfolio_id, name
    )
    if program_id is None:
        program_id = await conn.fetchval(
            "INSERT INTO programs (portfolio_id, name, source_system_ref) VALUES ($1, $2, $3) RETURNING program_id",
            portfolio_id,
            name,
            source_system_ref,
        )
        print(f"Created program: {program_id} ({name})")
    return str(program_id)


async def _get_or_create_actor(conn, tenant_id: str, role: str, entra_object_id: str) -> str:
    actor_id = await conn.fetchval("SELECT actor_id FROM actors WHERE entra_object_id = $1", entra_object_id)
    if actor_id is None:
        actor_id = await conn.fetchval(
            "INSERT INTO actors (tenant_id, role, entra_object_id) VALUES ($1, $2, $3) RETURNING actor_id",
            tenant_id,
            role,
            entra_object_id,
        )
        print(f"Created actor: {actor_id} (role={role}, entra_object_id={entra_object_id})")
    return str(actor_id)


async def _get_or_create_portfolio_scope(conn, actor_id: str, portfolio_id: str) -> None:
    existing = await conn.fetchval(
        "SELECT scope_id FROM actor_scope WHERE actor_id = $1 AND portfolio_id = $2", actor_id, portfolio_id
    )
    if existing is None:
        await conn.execute(
            "INSERT INTO actor_scope (actor_id, portfolio_id) VALUES ($1, $2)", actor_id, portfolio_id
        )
        print(f"Created actor_scope: actor={actor_id} -> portfolio={portfolio_id}")


async def _seed_report(
    conn, tenant_id: str, program_id: str, week_of: dt.date, executive_summary: str, findings: list[dict]
) -> int:
    existing = await conn.fetchval(
        "SELECT report_id FROM reports WHERE program_id = $1 AND week_of = $2", program_id, week_of
    )
    if existing is not None:
        print(f"Report already exists for program={program_id} week_of={week_of}: report_id={existing}")
        return int(existing)

    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        report_id = await conn.fetchval(
            """
            INSERT INTO reports (program_id, week_of, rag_status, quality_gate_outcome, executive_summary, attempts)
            VALUES ($1, $2, 'Amber', 'approved', $3, 1)
            RETURNING report_id
            """,
            program_id,
            week_of,
            executive_summary,
        )
        for f in findings:
            await conn.execute(
                """
                INSERT INTO findings (report_id, source_item_ref, title, status_label, evidence)
                VALUES ($1, $2, $3, $4, $5)
                """,
                report_id,
                f["source_item_ref"],
                f["title"],
                f["status_label"],
                f["evidence"],
            )
    print(f"Created report: {report_id} (program={program_id}, week_of={week_of})")
    return int(report_id)


async def _set_rendered_artifact_uri(conn, report_id: int, tenant_id: str, uri: str) -> None:
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        await conn.execute("UPDATE reports SET rendered_artifact_uri = $1 WHERE report_id = $2", uri, report_id)
    print(f"Set rendered_artifact_uri for report {report_id}: {uri}")


async def seed(settings: PostgresSettings) -> None:
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    credential = DefaultAzureCredential()
    try:
        async with client.pool.acquire() as conn:
            # --- Tenant A: backfill the existing stand-in reviewer's scope,
            # and add a real visitor actor. ---
            tenant_a_id = await _get_or_create_tenant(conn, TENANT_A_NAME)
            tenant_a_portfolio_id = await _get_or_create_portfolio(conn, tenant_a_id, TENANT_A_PORTFOLIO_NAME)
            tenant_a_program_id = await _get_or_create_program(
                conn, tenant_a_portfolio_id, TENANT_A_PROGRAM_NAME, None
            )

            standin_actor_id = await conn.fetchval(
                "SELECT actor_id FROM actors WHERE entra_object_id = 'local-dev-standin-reviewer'"
            )
            if standin_actor_id is None:
                raise SystemExit("Run scripts/seed_dev_data.py --target dev first (stand-in reviewer missing).")
            await _get_or_create_portfolio_scope(conn, str(standin_actor_id), tenant_a_portfolio_id)

            visitor_actor_id = await _get_or_create_actor(
                conn, tenant_a_id, "visitor", TENANT_A_VISITOR_ENTRA_OBJECT_ID
            )
            await _get_or_create_portfolio_scope(conn, visitor_actor_id, tenant_a_portfolio_id)

            # --- Tenant B: a real second, fictional tenant. ---
            tenant_b_id = await _get_or_create_tenant(conn, TENANT_B_NAME)
            tenant_b_portfolio_id = await _get_or_create_portfolio(conn, tenant_b_id, TENANT_B_PORTFOLIO_NAME)
            tenant_b_program_id = await _get_or_create_program(
                conn, tenant_b_portfolio_id, TENANT_B_PROGRAM_NAME, None
            )

            owner_b_actor_id = await _get_or_create_actor(
                conn, tenant_b_id, "owner", TENANT_B_OWNER_ENTRA_OBJECT_ID
            )
            await _get_or_create_portfolio_scope(conn, owner_b_actor_id, tenant_b_portfolio_id)

            # --- Real seeded reports, Tenant B (fictional content, no ADO). ---
            report_b1 = await _seed_report(
                conn,
                tenant_b_id,
                tenant_b_program_id,
                TENANT_B_WEEK_OF_1,
                "Meridian Patient Portal is on track this week: the appointment-scheduling "
                "module shipped to staging, and the insurance-verification integration is "
                "in active development with no blockers reported.",
                [
                    {
                        "source_item_ref": "MER-101",
                        "title": "Appointment scheduling module",
                        "status_label": "On Track",
                        "evidence": "Deployed to staging on schedule; QA sign-off received.",
                    },
                    {
                        "source_item_ref": "MER-102",
                        "title": "Insurance verification integration",
                        "status_label": "On Track",
                        "evidence": "API contract finalized with the third-party verification vendor.",
                    },
                ],
            )
            report_b2 = await _seed_report(
                conn,
                tenant_b_id,
                tenant_b_program_id,
                TENANT_B_WEEK_OF_2,
                "Meridian Patient Portal: the patient records migration is blocked on a "
                "real data-schema mismatch with the legacy EHR vendor, needing a decision "
                "from the Meridian data governance board before work can resume.",
                [
                    {
                        "source_item_ref": "MER-103",
                        "title": "Patient records migration",
                        "status_label": "Blocked",
                        "evidence": "Legacy EHR export uses a field schema incompatible with the new portal's "
                        "patient model; escalated to the Meridian data governance board.",
                    },
                ],
            )

            # --- Real seeded report, Tenant A (SAS positive-control counterpart). ---
            report_a1 = await _seed_report(
                conn,
                tenant_a_id,
                tenant_a_program_id,
                TENANT_A_TEST_WEEK_OF,
                "Phase 8 test report for the real SAS-download positive-control proof — "
                "not a real pipeline run.",
                [],
            )

        # --- Real blob uploads, outside any Postgres transaction. ---
        uri_a = await upload_report_blob(
            credential, f"phase8-test-tenant-a-report-{report_a1}.txt", _PLACEHOLDER_PPTX_BYTES
        )
        async with client.pool.acquire() as conn:
            await _set_rendered_artifact_uri(conn, report_a1, tenant_a_id, uri_a)

        uri_b = await upload_report_blob(
            credential, f"phase8-test-tenant-b-report-{report_b1}.txt", _PLACEHOLDER_PPTX_BYTES
        )
        async with client.pool.acquire() as conn:
            await _set_rendered_artifact_uri(conn, report_b1, tenant_b_id, uri_b)

        print("\nDone. Real identities for testing:")
        print(f"  Tenant A visitor: entra_object_id={TENANT_A_VISITOR_ENTRA_OBJECT_ID!r}")
        print(f"  Tenant B owner:   entra_object_id={TENANT_B_OWNER_ENTRA_OBJECT_ID!r}")
        print(f"  Tenant A test report (SAS positive control): report_id={report_a1}")
        print(f"  Tenant B reports: report_id={report_b1}, report_id={report_b2}")
    finally:
        await credential.close()
        await client.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    args = parser.parse_args()
    await seed(TARGETS[args.target])


if __name__ == "__main__":
    asyncio.run(main())
