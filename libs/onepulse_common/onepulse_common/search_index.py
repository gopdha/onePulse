"""Real Azure AI Search index for the Chat Assistant's Retrieval Index
(Physical Architecture Section 4). Indexes ONLY from Postgres
(reports/findings — Phase 2's schema), never raw Azure DevOps or PPTX
directly: Investigation and Status Update Analysis already exist to
extract and structure that data; re-ingesting raw sources here would
duplicate their job and discard the already-synthesized,
already-quality-gated work sitting in Postgres.

Two chunk levels, confirmed against the real schema
(scripts/migrations/0001_initial_schema.sql) before implementing rather
than assumed from the LLD's abstract description:

- Report-level: one chunk per `reports` row — `executive_summary`,
  tagged with `report_id`, the program's real name (joined from
  `programs`, since `reports` itself only carries `program_id`),
  `week_of`, `rag_status`.
- Finding-level: one chunk per `findings` row — `title` + `evidence` +
  `status_label`, tagged with `report_id` AND the real
  `source_item_ref` column (the LLD's own supporting-tables summary
  calls this `work_item_id`, but the schema actually built in Phase 2,
  cross-checked against real Investigation output, names it
  `source_item_ref` — that real column is what's indexed here).

Real, checked API surface (azure-search-documents 12.0.0 — a newer major
version than this project has used before; verified live rather than
assumed to share 11.x's exact shapes): `SearchField`/`SearchIndex`/
`VectorSearchProfile`/`HnswAlgorithmConfiguration` field names
(`vector_search_dimensions`, `vector_search_profile_name`,
`algorithm_configuration_name`) were confirmed by reading the installed
package's real generated model source, not recalled from an older SDK
generation. Both `SearchIndexClient` and `SearchClient` (and their
`.aio` counterparts) accept a `TokenCredential`/`AsyncTokenCredential`
directly — Entra ID only, no admin/query API key anywhere, and local
auth (API keys) is disabled service-wide on `onepulse-search-dev`
(confirmed via a direct ARM PATCH — the CLI's own
`--disable-local-auth` rejected the change until `authOptions` was also
cleared).

Real recency scoring profile (ADR-029): a program under active,
repeated real investigation (Agentic AI Observability Platform's own
weekly re-investigation of the same ~115 committed items) produces many
finding-level chunks describing the same real work item across
different weeks — near-identical content, differing mainly in
`week_of` and, sometimes, status. Retrieved together, an older,
superseded chunk can rank close enough to the current one that the
model cites it with equal confidence — a retrieval-quality failure that
looks like the assistant working, which is what makes it worth fixing
at the ranking layer rather than trusting the model to sort it out
after the fact every time. `RECENCY_SCORING_PROFILE_NAME` biases
ranking toward more recent `week_of` values using Azure AI Search's own
real `FreshnessScoringFunction` — real history stays fully queryable
(nothing is excluded, unlike indexing only the latest report per
program, which was considered and rejected: LLD Section 2.3 frames this
assistant as an archive of what has already been reported, and
"how has this item's status changed over time" is a real, intended
question this system should stay able to answer). `interpolation=
"quadratic"` was chosen deliberately over the default `"linear"` — a
sharper, front-loaded preference for the most recent weeks specifically
targets the near-duplicate case (consecutive weekly snapshots of the
same item), rather than a gentle, evenly-graded preference across the
whole `boosting_duration` window.
"""

from __future__ import annotations

import datetime as dt

from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    FreshnessScoringFunction,
    FreshnessScoringParameters,
    HnswAlgorithmConfiguration,
    ScoringProfile,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from onepulse_common.embeddings import EMBEDDING_DIMENSIONS

SEARCH_ENDPOINT = "https://onepulse-search-dev.search.windows.net"
INDEX_NAME = "onepulse-reports"

_VECTOR_PROFILE_NAME = "onepulse-vector-profile"
_HNSW_ALGORITHM_NAME = "onepulse-hnsw"
VECTOR_FIELD_NAME = "content_vector"

RECENCY_SCORING_PROFILE_NAME = "recency_boost"
# Real, deliberate values, not defaults left unexamined: `boost=3.0`
# gives the freshest documents up to 3x their base relevance score —
# strong enough to reliably separate "this week" from "three weeks ago"
# for two otherwise near-identical chunks, without being so extreme
# that a genuinely more relevant older chunk can never surface at all
# (the boost multiplies, it doesn't replace, the underlying relevance
# score). `boosting_duration=90 days` — comfortably longer than this
# project's own real report cadence (weekly) or any real gap between
# runs seen so far, so a chunk stays eligible for the boost across
# several real weekly cycles, not just the single most recent one.


def build_index_client(credential: DefaultAzureCredential) -> SearchIndexClient:
    return SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)


def build_search_client(credential: DefaultAzureCredential) -> SearchClient:
    return SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential)


def build_index_definition() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="chunk_type", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="report_id", type=SearchFieldDataType.Int64, filterable=True, sortable=True),
        SimpleField(name="finding_id", type=SearchFieldDataType.Int64, filterable=True),
        SimpleField(name="program_id", type=SearchFieldDataType.String, filterable=True),
        SearchField(name="program_name", type=SearchFieldDataType.String, searchable=True, filterable=True),
        SimpleField(
            name="week_of", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True
        ),
        SimpleField(name="rag_status", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_item_ref", type=SearchFieldDataType.String, filterable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name=VECTOR_FIELD_NAME,
            # Real bug found live: f-stringing the enum member directly
            # yields "Collection(SearchFieldDataType.SINGLE)" (its
            # Python name, from a plain Enum, not a str-mixin) rather
            # than the real wire value "Collection(Edm.Single)" the
            # service demands — confirmed by the service's own rejection
            # message. `.value` is required.
            type=f"Collection({SearchFieldDataType.Single.value})",
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=_VECTOR_PROFILE_NAME,
        ),
    ]

    vector_search = VectorSearch(
        profiles=[
            VectorSearchProfile(
                name=_VECTOR_PROFILE_NAME, algorithm_configuration_name=_HNSW_ALGORITHM_NAME
            )
        ],
        algorithms=[HnswAlgorithmConfiguration(name=_HNSW_ALGORITHM_NAME)],
    )

    recency_scoring_profile = ScoringProfile(
        name=RECENCY_SCORING_PROFILE_NAME,
        functions=[
            FreshnessScoringFunction(
                field_name="week_of",
                boost=3.0,
                interpolation="quadratic",
                parameters=FreshnessScoringParameters(boosting_duration=dt.timedelta(days=90)),
            )
        ],
    )

    return SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        scoring_profiles=[recency_scoring_profile],
    )


def _escape_odata_literal(value: str) -> str:
    return value.replace(chr(39), chr(39) * 2)


async def hybrid_search(
    search_client: SearchClient,
    *,
    query_text: str,
    query_vector: list[float],
    program_id: str | None = None,
    authorized_program_ids: frozenset[str] | None = None,
    top: int = 5,
) -> list[dict]:
    """Real hybrid (keyword + vector) search — BM25 keyword ranking and
    HNSW vector similarity fused by the service's own reciprocal-rank
    fusion, not a client-side blend.

    Migration Plan Phase 8 (ADR-027): `authorized_program_ids` is the
    real, mandatory retrieval filter LLD Section 2.3/ADR-022 always
    required and this project never built until now — the caller's
    resolved scope, never a caller-supplied value. When given, the real
    OData filter is `search.in(program_id, 'id1,id2,...')`, restricting
    every retrieved chunk (report- and finding-level alike) to programs
    the asker is actually authorized to see — this is what actually
    stands between a visitor and reports outside their scope, since
    filtering the model's *answer* after the fact would be too late (the
    model already saw the content). `program_id` narrows further within
    that set (a caller asking about one specific, already-authorized
    program); passing a `program_id` outside `authorized_program_ids` is
    the caller's own bug, not handled specially here — `core_api`'s own
    route validates that before ever calling this.
    """
    vector_query = VectorizedQuery(vector=query_vector, k_nearest_neighbors=top, fields=VECTOR_FIELD_NAME)
    filter_clauses = []
    if authorized_program_ids is not None:
        ids_csv = ",".join(_escape_odata_literal(pid) for pid in authorized_program_ids)
        filter_clauses.append(f"search.in(program_id, '{ids_csv}', ',')")
    if program_id:
        filter_clauses.append(f"program_id eq '{_escape_odata_literal(program_id)}'")
    filter_expr = " and ".join(filter_clauses) if filter_clauses else None

    results = await search_client.search(
        search_text=query_text,
        vector_queries=[vector_query],
        filter=filter_expr,
        top=top,
        # Explicit at the call site rather than a silent `default_scoring_profile`
        # on the index — see the module docstring's ADR-029 note.
        scoring_profile=RECENCY_SCORING_PROFILE_NAME,
        select=[
            "id",
            "chunk_type",
            "report_id",
            "finding_id",
            "program_name",
            "week_of",
            "rag_status",
            "source_item_ref",
            "title",
            "content",
        ],
    )

    chunks = []
    async for result in results:
        chunks.append(dict(result))
    return chunks
