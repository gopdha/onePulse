"""Conversational Access (LLD Section 2.3) — the "Later"-scope Chat
Assistant, pulled forward as a CLI tool per explicit user direction
rather than the deferred full Temporal/Kafka-triggered feature.

Same agent pattern as every other real agent in this project
(`scripts/run_pipeline.py`): a real `agent_framework.Agent` +
`FoundryChatClient`, with a `FunctionTool` wrapping a real capability —
here, a real hybrid Azure AI Search query — not a raw prompt hoping the
model already knows about past reports. Connected Agents (Foundry's
dynamic routing) was considered and deliberately not used: a single
agent with one retrieval tool is the more honest fit for one
well-scoped capability, not genuinely multi-agent routing.

Evidence discipline, the same standard Investigation already follows:
every answer must cite a real row (`report_id` always; `source_item_ref`
+ finding title additionally, for finding-level evidence). If the real
retrieved chunks don't actually address the question, the honest answer
is that it wasn't found in any generated report — never a fallback to
the model's own general knowledge or a live Azure DevOps lookup. This
assistant answers questions about the archive of what's already been
reported, nothing else.

Real, stated shortcut, not hidden: LLD Section 2.3 requires resolving
`actorId`'s authorized scope server-side as a mandatory retrieval
filter, via `actor_scope` (Phase 2's schema). No code anywhere in this
project yet resolves `actor_scope` — Now-scope has never needed
authorization logic before this. `program_id` is accepted here directly
as a filter argument instead, the same class of shortcut as Phase 7's
CLI-supplied `actor_id` (`onepulse_common/human_governance.py`). A real
auth integration must replace this by looking up the caller's real
`actor_scope` rows and deriving the allowed `program_id`/`portfolio_id`
set from them — never trust a caller-supplied `program_id` as
authorization.
"""

from __future__ import annotations

import json

from agent_framework import Agent, FunctionTool
from agent_framework.foundry import FoundryChatClient
from azure.search.documents.aio import SearchClient
from openai import AsyncAzureOpenAI

from onepulse_common.embeddings import embed_texts
from onepulse_common.search_index import hybrid_search

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer"},
                    "program_name": {"type": "string"},
                    "week_of": {"type": "string"},
                    "source_item_ref": {"type": ["string", "null"]},
                    "finding_title": {"type": ["string", "null"]},
                },
                "required": ["report_id", "program_name", "week_of", "source_item_ref", "finding_title"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "citations"],
    "additionalProperties": False,
}

SEARCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The search query, in the user's own words."},
        "top": {
            "type": "integer",
            "description": "How many chunks to retrieve. Defaults to 5 if omitted.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

CHAT_INSTRUCTIONS = """You are the OnePulse Chat Assistant (Conversational Access, LLD Section 2.3).
You answer questions about the ARCHIVE of status reports OnePulse has already generated and quality-gated. You do not have live Azure DevOps access and must never guess, infer from general knowledge, or fabricate an answer.

For every question:
1. Call the search_reports tool at least once with a real query derived from the question. Never answer without calling it first.
2. Read the real chunks it returns. Each chunk is either report-level (chunk_type "report", carrying an executive summary) or finding-level (chunk_type "finding", carrying one specific work item's evidence, tagged with source_item_ref).
3. If the retrieved chunks genuinely answer the question, write a grounded answer using ONLY their content, and cite every chunk you drew on: report_id, program_name, and week_of always; source_item_ref and finding_title additionally for any finding-level chunk you used (set both to null for a report-level-only citation).
4. If the retrieved chunks do NOT actually address the question — even if the tool returned some results, real search always returns its closest matches, not necessarily relevant ones — say so honestly: state plainly that this was not found in any generated report. Do not cite chunks that don't truly support your answer, and return an empty citations list in that case.
Respond only with JSON matching the required schema."""


def build_search_tool(search_client: SearchClient, embedding_client: AsyncAzureOpenAI, program_id: str | None) -> FunctionTool:
    async def search_reports(query: str, top: int = 5) -> str:
        vectors = await embed_texts(embedding_client, [query])
        chunks = await hybrid_search(
            search_client,
            query_text=query,
            query_vector=vectors[0],
            program_id=program_id,
            top=top,
        )
        return json.dumps(chunks, default=str)

    return FunctionTool(
        name="search_reports",
        description=(
            "Searches the real archive of already-generated OnePulse status reports (report-level "
            "executive summaries and finding-level per-work-item evidence) using hybrid keyword + "
            "vector search. Returns the real matching chunks, most relevant first."
        ),
        input_model=SEARCH_TOOL_SCHEMA,
        func=search_reports,
    )


async def ask_question(
    chat_client: FoundryChatClient,
    search_client: SearchClient,
    embedding_client: AsyncAzureOpenAI,
    question: str,
    program_id: str | None = None,
) -> dict:
    tool = build_search_tool(search_client, embedding_client, program_id)

    async with Agent(
        client=chat_client,
        name="onepulse-chat-assistant",
        instructions=CHAT_INSTRUCTIONS,
        tools=[tool],
        default_options={"response_format": CHAT_SCHEMA},
    ) as agent:
        result = await agent.run(question)

    return json.loads(result.text)
