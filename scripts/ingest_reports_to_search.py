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

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.embeddings import build_embedding_client, embed_texts
from onepulse_common.search_index import build_index_client, build_index_definition, build_search_client

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


async def fetch_report_chunks(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT r.report_id, r.program_id, p.name AS program_name, r.week_of,
               r.rag_status, r.executive_summary
        FROM reports r
        JOIN programs p ON p.program_id = r.program_id
        ORDER BY r.report_id
        """
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


async def fetch_finding_chunks(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT f.finding_id, f.report_id, f.source_item_ref, f.title, f.status_label, f.evidence,
               r.program_id, p.name AS program_name, r.week_of, r.rag_status
        FROM findings f
        JOIN reports r ON r.report_id = f.report_id
        JOIN programs p ON p.program_id = r.program_id
        ORDER BY f.finding_id
        """
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


async def ingest(settings: PostgresSettings) -> None:
    pg_client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    search_credential = DefaultAzureCredential()
    try:
        async with pg_client.pool.acquire() as conn:
            report_chunks = await fetch_report_chunks(conn)
            finding_chunks = await fetch_finding_chunks(conn)

        chunks = report_chunks + finding_chunks
        print(f"Fetched {len(report_chunks)} report chunk(s), {len(finding_chunks)} finding chunk(s) from Postgres.")

        if not chunks:
            print("Nothing to ingest.")
            return

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

        embedding_client = build_embedding_client(search_credential)
        try:
            vectors = await embed_texts(embedding_client, [c["content"] for c in chunks])
        finally:
            await embedding_client.close()

        for chunk, vector in zip(chunks, vectors):
            chunk["content_vector"] = vector

        search_client = build_search_client(search_credential)
        try:
            result = await search_client.merge_or_upload_documents(documents=chunks)
            failed = [r for r in result if not r.succeeded]
            print(f"Uploaded {len(result) - len(failed)}/{len(result)} document(s) to the real index.")
            if failed:
                for f in failed:
                    print(f"  FAILED: {f.key} — {f.error_message}")
        finally:
            await search_client.close()
    finally:
        await pg_client.close()
        await search_credential.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    args = parser.parse_args()
    await ingest(TARGETS[args.target])


if __name__ == "__main__":
    asyncio.run(main())
