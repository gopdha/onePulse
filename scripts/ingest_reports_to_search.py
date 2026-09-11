"""Real ingestion: Postgres (reports/findings, Phase 2's schema) -> the
real Azure AI Search index `onepulse-reports` on `onepulse-search-dev`.

Source of truth, confirmed before building this: index ONLY from
Postgres, never raw Azure DevOps or PPTX directly. Investigation and
Status Update Analysis already exist specifically to extract and
structure that raw data into `reports`/`findings`; re-ingesting the raw
sources here would duplicate their job and throw away the
already-synthesized, already-quality-gated work already sitting in
Postgres.

Two chunk levels (see onepulse_common/search_index.py's module
docstring for the real schema cross-check): one chunk per `reports` row
(`executive_summary`), one chunk per `findings` row (`title` + `evidence`
+ `status_label`, tagged with the real `source_item_ref` column).

Idempotent: every document's `id` is derived from its real primary key
(`report-<report_id>`, `finding-<finding_id>`), and upload uses
`merge_or_upload_documents` — safe to re-run.

Real prune step (ADR-029), run on every real ingest, not opt-in:
`merge_or_upload_documents` only ever adds or updates — it can never
remove a document Postgres no longer accounts for (a reclassified
report, a retired chunking scheme, a one-off test ingestion). ADR-022's
own claim that "AI Search is derived" from Postgres is only true if the
index can be reconciled back to Postgres's real current state, not
merely rebuilt additively — `prune_stale_documents` is what makes that
actually hold: it computes the real, full set of document IDs Postgres
says should exist and deletes anything in the index that isn't in it.

Run: python scripts/ingest_reports_to_search.py --target dev
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os

from azure.identity.aio import DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError
from dotenv import load_dotenv

from openai import RateLimitError

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.embeddings import build_embedding_client, embed_texts
from onepulse_common.search_index import build_index_client, build_index_definition, build_search_client

# Real limit hit live on the first full, unscoped reindex of this
# project's real corpus (963 texts in one call): the embedding
# deployment's GlobalStandard S0 tier rate-limits a single request.
# `embed_texts` itself (onepulse_common/embeddings.py) stays a plain,
# single real batch call — every other real caller only ever embeds one
# question at a time. Batching + retry belongs here, in the one caller
# that actually does bulk work.
EMBEDDING_BATCH_SIZE = 16
EMBEDDING_RETRY_SECONDS = 60

# The real, documented Azure AI Search per-request $top cap. A single
# search_text="*" listing call is only a complete enumeration of the
# index below this — at or beyond it, some real documents are silently
# missing from the page, and computing a prune set from that partial
# list risks deleting documents that are still genuinely valid (they
# just didn't fit on the page). See `prune_stale_documents`.
MAX_INDEX_LISTING_PAGE = 1000


class IndexListingTooLargeError(RuntimeError):
    """Raised when the real index has grown to (or past) Azure AI
    Search's own per-request $top cap — pruning refuses to proceed
    against a listing that can no longer be trusted to be complete,
    rather than silently computing a wrong (over-broad) deletion set.
    Real pagination ($skip, or an orderby-based keyset) needs to be
    added deliberately once the real corpus actually reaches this —
    not guessed at in advance for a scale this project isn't at.
    """

load_dotenv()

TARGETS: dict[str, PostgresSettings] = {
    "dev": PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    ),
}


def _to_datetimeoffset(value: dt.date) -> str:
    return dt.datetime.combine(value, dt.time.min, tzinfo=dt.timezone.utc).isoformat()


async def fetch_report_chunks(conn, report_ids: list[int] | None = None) -> list[dict]:
    # `report_ids`, when given, is a real, minimal scoping addition
    # (Migration Plan Phase 8) — indexing exactly one deliberate,
    # attributable set of report_ids. The separate, already-documented
    # "no filter at all" gap (Task 39/40) for the default, unfiltered
    # case is now half-closed: `is_test_fixture` (Task 49 follow-up)
    # excludes the real ~440-row test_human_governance.py debris from
    # ever being indexed, unconditionally, whether or not report_ids is
    # given.
    rows = await conn.fetch(
        """
        SELECT r.report_id, r.program_id, p.name AS program_name, r.week_of,
               r.rag_status, r.executive_summary
        FROM reports r
        JOIN programs p ON p.program_id = r.program_id
        WHERE ($1::bigint[] IS NULL OR r.report_id = ANY($1::bigint[])) AND NOT r.is_test_fixture
        ORDER BY r.report_id
        """,
        report_ids,
    )
    return [
        {
            "id": f"report-{r['report_id']}",
            "chunk_type": "report",
            "report_id": r["report_id"],
            "finding_id": None,
            "program_id": str(r["program_id"]),
            "program_name": r["program_name"],
            "week_of": _to_datetimeoffset(r["week_of"]),
            "rag_status": r["rag_status"],
            "source_item_ref": None,
            "title": f"Weekly status report — {r['program_name']} — {r['week_of'].isoformat()}",
            "content": r["executive_summary"],
        }
        for r in rows
    ]


async def fetch_finding_chunks(conn, report_ids: list[int] | None = None) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT f.finding_id, f.report_id, f.source_item_ref, f.title, f.status_label, f.evidence,
               r.program_id, p.name AS program_name, r.week_of, r.rag_status
        FROM findings f
        JOIN reports r ON r.report_id = f.report_id
        JOIN programs p ON p.program_id = r.program_id
        WHERE ($1::bigint[] IS NULL OR f.report_id = ANY($1::bigint[])) AND NOT r.is_test_fixture
        ORDER BY f.finding_id
        """,
        report_ids,
    )
    return [
        {
            "id": f"finding-{r['finding_id']}",
            "chunk_type": "finding",
            "report_id": r["report_id"],
            "finding_id": r["finding_id"],
            "program_id": str(r["program_id"]),
            "program_name": r["program_name"],
            "week_of": _to_datetimeoffset(r["week_of"]),
            "rag_status": r["rag_status"],
            "source_item_ref": r["source_item_ref"],
            "title": r["title"],
            "content": f"{r['title']} ({r['status_label']}): {r['evidence']}",
        }
        for r in rows
    ]


async def fetch_real_document_ids(conn) -> set[str]:
    """The full, real, unscoped set of document IDs that should exist in
    the index right now — every non-fixture report and finding,
    regardless of any `--report-ids` scoping this particular run's own
    upload used. Pruning is a global consistency operation (does the
    index match Postgres overall), not a per-batch one — a targeted
    ingest of three report_ids still prunes against the *complete* real
    state, not just those three.
    """
    report_rows = await conn.fetch("SELECT report_id FROM reports WHERE NOT is_test_fixture")
    finding_rows = await conn.fetch(
        "SELECT f.finding_id FROM findings f JOIN reports r ON r.report_id = f.report_id "
        "WHERE NOT r.is_test_fixture"
    )
    return {f"report-{r['report_id']}" for r in report_rows} | {
        f"finding-{r['finding_id']}" for r in finding_rows
    }


async def prune_stale_documents(search_client, real_ids: set[str]) -> int:
    """Deletes every document in the real index that the real, current
    Postgres state no longer accounts for. This is the property that
    makes ADR-022's "AI Search is derived" claim actually true — derived
    means reconcilable back to the source of truth, not just
    rebuildable-in-principle by adding whatever's missing.
    """
    results = await search_client.search(search_text="*", top=MAX_INDEX_LISTING_PAGE, select=["id"])
    index_ids = [doc["id"] async for doc in results]
    if len(index_ids) >= MAX_INDEX_LISTING_PAGE:
        raise IndexListingTooLargeError(
            f"Index listing returned {len(index_ids)} documents, at or beyond the real "
            f"{MAX_INDEX_LISTING_PAGE}-document Azure AI Search per-request cap — refusing to prune "
            "against a listing that can no longer be trusted to be complete."
        )

    stale_ids = set(index_ids) - real_ids
    if not stale_ids:
        print("Prune: no stale documents found — index already matches Postgres.")
        return 0

    result = await search_client.delete_documents(documents=[{"id": i} for i in stale_ids])
    failed = [r for r in result if not r.succeeded]
    print(f"Pruned {len(result) - len(failed)}/{len(result)} stale document(s): {sorted(stale_ids)}")
    for f in failed:
        print(f"  FAILED TO PRUNE: {f.key} — {f.error_message}")
    return len(result) - len(failed)


async def embed_all(embedding_client, texts: list[str]) -> list[list[float]]:
    """Embeds every real text in fixed-size batches, retrying a rate-limited
    batch after the real cooldown rather than failing the whole run. Real,
    observed constraint: the embedding deployment's GlobalStandard S0 tier
    rejects one oversized single-shot call for this project's real corpus
    size; it accepts the identical content split into smaller batches.
    """
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        while True:
            try:
                vectors.extend(await embed_texts(embedding_client, batch))
                break
            except RateLimitError:
                print(
                    f"Embedding batch {start}-{start + len(batch)}: rate limited, "
                    f"retrying in {EMBEDDING_RETRY_SECONDS}s."
                )
                await asyncio.sleep(EMBEDDING_RETRY_SECONDS)
    return vectors


async def ingest(settings: PostgresSettings, report_ids: list[int] | None = None) -> None:
    pg_client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    search_credential = DefaultAzureCredential()
    try:
        async with pg_client.pool.acquire() as conn:
            report_chunks = await fetch_report_chunks(conn, report_ids)
            finding_chunks = await fetch_finding_chunks(conn, report_ids)
            # Unscoped, regardless of report_ids — see fetch_real_document_ids's own docstring.
            real_ids = await fetch_real_document_ids(conn)

        chunks = report_chunks + finding_chunks
        print(f"Fetched {len(report_chunks)} report chunk(s), {len(finding_chunks)} finding chunk(s) from Postgres.")

        index_client = build_index_client(search_credential)
        try:
            try:
                await index_client.get_index(build_index_definition().name)
                print(f"Index '{build_index_definition().name}' already exists — updating in place.")
            except ResourceNotFoundError:
                print(f"Index '{build_index_definition().name}' does not exist — creating it.")
            await index_client.create_or_update_index(build_index_definition())
        finally:
            await index_client.close()

        if chunks:
            embedding_client = build_embedding_client(search_credential)
            try:
                vectors = await embed_all(embedding_client, [c["content"] for c in chunks])
            finally:
                await embedding_client.close()

            for chunk, vector in zip(chunks, vectors):
                chunk["content_vector"] = vector
        else:
            print("Nothing new to upload for this run's own scope.")

        search_client = build_search_client(search_credential)
        try:
            if chunks:
                result = await search_client.merge_or_upload_documents(documents=chunks)
                failed = [r for r in result if not r.succeeded]
                print(f"Uploaded {len(result) - len(failed)}/{len(result)} document(s) to the real index.")
                for f in failed:
                    print(f"  FAILED: {f.key} — {f.error_message}")

            # Real prune step (ADR-029) — runs every time, regardless of
            # whether this run's own upload was scoped or empty, since
            # it reconciles against the FULL real Postgres state, not
            # just this run's own batch.
            await prune_stale_documents(search_client, real_ids)
        finally:
            await search_client.close()
    finally:
        await pg_client.close()
        await search_credential.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    parser.add_argument(
        "--report-ids",
        type=int,
        nargs="+",
        default=None,
        help="Real, deliberate scoping (Migration Plan Phase 8): index only these report_ids. "
        "Omit for the existing, unfiltered, whole-table behavior.",
    )
    args = parser.parse_args()
    await ingest(TARGETS[args.target], args.report_ids)


if __name__ == "__main__":
    asyncio.run(main())
