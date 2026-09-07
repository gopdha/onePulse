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
"""

from __future__ import annotations

from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
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

    return SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)


async def hybrid_search(
    search_client: SearchClient,
    *,
    query_text: str,
    query_vector: list[float],
    program_id: str | None = None,
    top: int = 5,
) -> list[dict]:
    """Real hybrid (keyword + vector) search — BM25 keyword ranking and
    HNSW vector similarity fused by the service's own reciprocal-rank
    fusion, not a client-side blend.
    """
    vector_query = VectorizedQuery(vector=query_vector, k_nearest_neighbors=top, fields=VECTOR_FIELD_NAME)
    # OData string literals escape an embedded single quote by doubling it.
    filter_expr = f"program_id eq '{program_id.replace(chr(39), chr(39) * 2)}'" if program_id else None

    results = await search_client.search(
        search_text=query_text,
        vector_queries=[vector_query],
        filter=filter_expr,
        top=top,
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
