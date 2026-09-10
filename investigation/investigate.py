"""OnePulse Investigation service (Migration Plan Phase 4, ADR-019/
ADR-020) -- the ADO MCP, Python + Node, real-per-item Work Item
Investigation logic (FR-1), moved here from `onepulse_common.pipeline`
(where it lived through Phase 3, alongside the Reporting-stage
functions it now never touches directly).

Real, load-bearing reason for this exact split, restated so the shape
doesn't drift later: a real full-scope run spends 302 of 378 real
seconds here (~80% of total runtime) -- every other stage finishes in
seconds. This is also the ONLY stage needing the Node runtime
(`@azure-devops/mcp`) and the ONLY real consumer of the ADO PAT. Both
facts are true of this module and nothing else in the codebase:
`onepulse_common.pipeline` (imported by core_api, bff, and the
Reporting service) has zero import of anything in this module, and this
module's own `package.json`/`node_modules` live under `investigation/`,
not the repo root -- see `investigation/main.py`'s own docstring for the
real queue-based service this logic now runs inside.

Unchanged in behavior from Phase 3 (Task 42), relocated only: every
docstring, every real bug-fix note, and every real regression test this
code already had stays true here. `onepulse_common.heartbeat` is the
one piece of the old shared machinery genuinely generic enough to still
be shared with the Reporting service's own agent-invoking functions --
see its own module docstring for why.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Callable

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.keyvault.secrets.aio import SecretClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from onepulse_common.heartbeat import heartbeat, noop_detail, noop_stage
from onepulse_common.mcp_bridge import build_mcp_function_tools

INVESTIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "work_item_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["On Track", "At Risk", "Blocked", "Needs Human Review"],
                    },
                    "evidence": {"type": "string"},
                },
                "required": ["work_item_id", "title", "status", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def _investigation_instructions(ado_project_name: str, scope_ids: list[int]) -> str:
    return f"""You are a Work Item Investigation agent for OnePulse (FR-1).
Your real scope for this run has already been determined deterministically, not by you: investigate ONLY these {len(scope_ids)} real work item(s) in the '{ado_project_name}' Azure DevOps project (Committed-tagged Features and their real children): {scope_ids}
Do not investigate any work item outside this exact list, and do not omit any work item from it.
For EVERY one of these {len(scope_ids)} work items:
1. Retrieve its real state, assignment, and any comments using the tools. Never guess or fabricate a work item or field value.
2. Classify it into exactly one of: "On Track", "At Risk", "Blocked", "Needs Human Review" — based only on the real evidence you retrieved.
3. Write a concise, specific evidence string citing the real data that grounds your classification (exact state value, comment content, staleness, missing assignment, etc.).
Respond only with JSON matching the required schema, with exactly one finding per given work item ID — {len(scope_ids)} findings total, no more, no fewer."""


def _committed_features_wiql(ado_project_name: str) -> str:
    """Task 28/Part 2's real, fixed scope-narrowing query: only Features
    tagged 'Committed' (ADO's real System.Tags field), scoped to the
    target project. No fallback to the whole project anywhere in this
    module — a project with zero matches is a real, honest "nothing in
    scope" state (see investigate()'s early return), not silently
    widened back to everything.
    """
    return (
        f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{ado_project_name}' "
        "AND [System.WorkItemType] = 'Feature' AND [System.Tags] CONTAINS 'Committed'"
    )


def _committed_children_wiql(ado_project_name: str, feature_ids: list[int]) -> str:
    """Real children of the given Features, via System.Parent — confirmed
    live against this org's actual data before assuming it (not every
    ADO process template structures hierarchy the same way): a real
    User Story's System.Parent field holds its real parent Feature's ID
    directly, and WHERE [System.Parent] IN (...) returns exactly its
    real children.
    """
    ids = ", ".join(str(i) for i in feature_ids)
    return (
        f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '{ado_project_name}' "
        f"AND [System.Parent] IN ({ids})"
    )


def _extract_work_item_ids(raw_tool_text: str) -> list[int]:
    """Parses the real MCP wit_query 'wiql' action result into a plain
    list of real work item IDs. Confirmed live against real data (not
    assumed): the tool wraps its JSON payload in
    `<<hash>> [UNTRUSTED WIQL QUERY RESULTS CONTENT ...] <<hash>>` /
    `<</hash>>` guard markers, with the real payload's `workItems` array
    holding `{"id": ..., "url": ...}` entries.
    """
    start = raw_tool_text.index("{")
    end = raw_tool_text.rindex("}") + 1
    parsed = json.loads(raw_tool_text[start:end])
    return [item["id"] for item in parsed.get("workItems", [])]


class GuardMarkerParseError(ValueError):
    """Raised by `_extract_work_item_fields` when a payload starts with
    `<<` (so looks guard-marker-wrapped) but the expected opening/closing
    tag structure can't actually be found — a real, named failure mode
    distinct from a generic `json.JSONDecodeError`, so a caller (or a
    human reading a log) can immediately tell "the wrapper shape wasn't
    what we expected" apart from "the JSON itself was malformed."
    """


def _extract_work_item_fields(raw_tool_text: str) -> list[dict]:
    """Parses the real MCP wit_work_item 'get_batch' action result — a
    JSON array of `{id, fields: {...}, url}` objects.

    Real bug found and fixed live (2026-09-09): Task 36's docstring here
    originally claimed this response carries "no guard markers wrapping
    it," confirmed against the server version live at the time. That is
    no longer true: the installed `@azure-devops/mcp` is spawned
    unpinned (`npx -y @azure-devops/mcp`, see `_ado_mcp_server_params`),
    and a newer real server version (confirmed live: 2.10.0, vs 2.9.0
    when Task 36 checked) now wraps this action's payload in the same
    `<<hash>> [UNTRUSTED ...] <<hash>>` guard markers `wit_query`
    already handles via `_extract_work_item_ids` — real upstream
    dependency drift, not a bug in this project's own recent changes.
    `json.loads(raw_tool_text)` directly then failed with
    `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` on
    every real `wit_work_item(get_batch, ...)` call, reproduced and
    confirmed via a direct raw-result dump against the real MCP server,
    not inferred from the exception alone.

    Unlike `_extract_work_item_ids`'s `{`/`}` bracket search, a naive
    `[`/`]` search here would incorrectly match the guard marker's own
    `[UNTRUSTED ...]` annotation text (which uses square brackets) —
    confirmed against the real captured payload. The real wrapper also
    has a genuine closing tag at the very end, `<</hash>>` (note the
    `/`, distinct from the opening `<<hash>>`) — a first attempt at this
    fix stripped only the leading wrapper and left that trailing tag
    attached, producing a *different* real error,
    `JSONDecodeError: Extra data`, on the exact same real payload;
    caught by re-running the real CLI reproduction after the first fix
    rather than assuming it was complete.

    Second real bug found and fixed (2026-09-09): the closing tag was
    originally located via a bare `text.rindex("<<")` — matching the
    LAST "<<" anywhere in the text. The wrapped payload's content is
    real Azure DevOps work item data, and a title is free text — nothing
    stops a real title from containing literal "<<"/">>" characters.
    Empirically verified this is not actually exploitable *while a real
    closing tag is present* (the closing tag is always textually last,
    so `rindex` still finds it correctly even with "<<"/">>" inside a
    title) — but the moment a closing tag is genuinely absent or
    malformed (a future server response shape, a truncated payload),
    `rindex("<<")` falls back to silently matching inside a title
    instead, truncating the JSON and raising a confusing, generic
    `JSONDecodeError: Unterminated string...` with no indication of what
    actually went wrong. Fixed by matching the closing tag against the
    *exact hash captured from the opening tag* (`<</{hash}>>`) rather
    than a bare `<<` — this removes the "closing tag happens to be
    textually last" coincidence entirely, rather than merely relying on
    it, and any failure to find the expected structure now raises a
    clear, named `GuardMarkerParseError` instead of an opaque
    `JSONDecodeError` pointing at the wrong root cause.
    """
    text = raw_tool_text.strip()
    if text.startswith("<<"):
        try:
            first_tag_end = text.index(">>") + 2
            opening_tag = text[:first_tag_end]
            tag_hash = opening_tag[2:-2]
            second_tag = f"<<{tag_hash}>>"
            second_tag_start = text.index(second_tag, first_tag_end)
            second_tag_end = second_tag_start + len(second_tag)
            closing_tag = f"<</{tag_hash}>>"
            closing_tag_start = text.rindex(closing_tag)
        except ValueError as exc:
            raise GuardMarkerParseError(
                f"Expected a '<<{{hash}}>> [...] <<{{hash}}>> ... <</{{hash}}>>' guard-marker-wrapped "
                f"payload but couldn't find the matching tag structure. Raw text (first 200 chars): "
                f"{raw_tool_text[:200]!r}"
            ) from exc
        text = text[second_tag_end:closing_tag_start].strip()
    items = json.loads(text)
    return [
        {
            "id": item["id"],
            "title": item["fields"].get("System.Title"),
            "state": item["fields"].get("System.State"),
            "parent": item["fields"].get("System.Parent"),
            "type": item["fields"].get("System.WorkItemType"),
        }
        for item in items
    ]


async def _query_committed_scope(
    mcp_session: ClientSession, ado_project_name: str, on_detail: Callable[[str], None]
) -> tuple[list[int], list[int]]:
    """Task 28/Part 2: the real committed-investigation scope, computed
    DETERMINISTICALLY in code, not left to the investigation agent's own
    judgment. Real motivation, not hypothetical: Task 27's stress test
    found the agent's own WIQL choices non-deterministic at real scale —
    one real run queried the whole project and silently returned zero
    findings; another made 465 individual tool calls for the same
    project. Fixing that here means exactly one real WIQL for Committed
    Features and exactly one real WIQL for their real children, both
    issued directly against the same open MCP session before the
    investigation Agent is even constructed, so the scope handed to the
    agent is fixed, small, and auditable up front.

    Returns `(feature_ids, child_ids)` separately, not one merged list
    (Task 36) — the split is needed to build the real Tower (Epic)
    hierarchy afterward; callers that just want the flat combined scope
    can still do `feature_ids + child_ids` themselves.
    """
    # Real gap found live (Migration Plan Phase 3 verification, 2026-09-09):
    # a real run against Agentic AI Observability Platform saw this exact
    # WIQL call take 37s with zero on_detail output in between — an
    # isolated re-run of the identical query moments later completed in
    # 1.1s with the correct real result, so this wasn't a code or parser
    # bug, just real, observed ADO API latency variance. Since neither
    # call here was wrapped in the same heartbeat mechanism `investigate`'s
    # own agent.run() calls already use, a slow real call here could
    # silently exceed the status table's real "no gap over 20s" bar
    # (ADR-021/Migration Plan Phase 3). Wrapped now — reusing the existing
    # mechanism, not inventing a second one.
    on_detail(f"· real tool call (deterministic scoping): wit_query(Committed Features in '{ado_project_name}')")
    async with heartbeat(on_detail, "Investigation scoping query"):
        features_result = await mcp_session.call_tool(
            "wit_query",
            {
                "action": "wiql",
                "project": ado_project_name,
                "wiql": _committed_features_wiql(ado_project_name),
                "top": 1000,
            },
        )
    feature_ids = _extract_work_item_ids(
        "\n".join(block.text for block in features_result.content if hasattr(block, "text"))
    )
    if not feature_ids:
        return [], []

    on_detail(
        f"· real tool call (deterministic scoping): wit_query(real children of {len(feature_ids)} "
        "Committed Feature(s) via System.Parent)"
    )
    async with heartbeat(on_detail, "Investigation scoping query"):
        children_result = await mcp_session.call_tool(
            "wit_query",
            {
                "action": "wiql",
                "project": ado_project_name,
                "wiql": _committed_children_wiql(ado_project_name, feature_ids),
                "top": 1000,
            },
        )
    child_ids = _extract_work_item_ids(
        "\n".join(block.text for block in children_result.content if hasattr(block, "text"))
    )
    return feature_ids, child_ids


async def _query_tower_hierarchy(
    mcp_session: ClientSession, feature_ids: list[int], child_ids: list[int], on_detail: Callable[[str], None]
) -> dict:
    """Task 36: the real, deterministic Tower (Epic) hierarchy and real
    delivery-state lookup, computed entirely independently of the
    Investigation agent's own narrative judgment — same discipline as
    `_query_committed_scope` above. Real motivation: the agent's FR-1
    classification (On Track/At Risk/Blocked/Needs Human Review) is a
    judgment about whether a Program Lead should worry about an item —
    not a measure of real delivery progress. Computing "N of M items
    delivered" needs each item's real ADO workflow state
    (`System.State`), which nothing upstream captures as structured
    data today; fetched here directly via one real `get_batch` call
    covering every committed-scope item (features + children), reusing
    the already-open MCP session `investigate()` owns.

    Returns `{"features": {id: {title, state, epic_id}}, "children":
    {id: {state, feature_id}}, "epics": {id: {title}}}`. `epics` is
    empty when no Committed Feature has a real Epic parent — the
    genuine, honest "no tower structure" case (Leave Tracker today) —
    callers use this to decide whether the Tower View applies at all,
    not a separate boolean flag.

    Real bug found and fixed live (Task 36 verification): a Feature's
    `System.Parent` is not reliably an Epic — singleSlide's Feature #8
    has `System.Parent = 10`, and #10 is a real Task, not an Epic
    (confirmed live via `az boards work-item show`), almost certainly
    stray/malformed data from this project's earliest seeding (Task 5),
    not a real tower structure. Treating any non-null parent as a tower
    would have wrongly forced singleSlide into the Tower View. The real,
    correct rule: a parent only counts as a tower Epic when its own
    `System.WorkItemType` is literally `"Epic"` — checked here via a
    second real field fetch, not inferred from the mere presence of a
    parent ID.
    """
    all_ids = feature_ids + child_ids
    on_detail(
        f"· real tool call (deterministic tower lookup): wit_work_item(get_batch, {len(all_ids)} "
        "item(s), fields=[System.Title, System.Parent, System.State])"
    )
    items_result = await mcp_session.call_tool(
        "wit_work_item",
        {"action": "get_batch", "ids": all_ids, "fields": ["System.Id", "System.Title", "System.Parent", "System.State"]},
    )
    raw_items = _extract_work_item_fields(
        "\n".join(block.text for block in items_result.content if hasattr(block, "text"))
    )

    feature_id_set = set(feature_ids)
    features: dict[int, dict] = {}
    children: dict[int, dict] = {}
    epic_ids: set[int] = set()
    for item in raw_items:
        if item["id"] in feature_id_set:
            features[item["id"]] = {"title": item["title"], "state": item["state"], "epic_id": item["parent"]}
            if item["parent"] is not None:
                epic_ids.add(item["parent"])
        else:
            children[item["id"]] = {"state": item["state"], "feature_id": item["parent"]}

    epics: dict[int, dict] = {}
    if epic_ids:
        on_detail(
            f"· real tool call (deterministic tower lookup): wit_work_item(get_batch, {len(epic_ids)} "
            "real Epic parent(s))"
        )
        epics_result = await mcp_session.call_tool(
            "wit_work_item",
            {"action": "get_batch", "ids": sorted(epic_ids), "fields": ["System.Id", "System.Title", "System.WorkItemType"]},
        )
        raw_epics = _extract_work_item_fields(
            "\n".join(block.text for block in epics_result.content if hasattr(block, "text"))
        )
        # Only a real Epic-typed parent counts as a tower — see docstring.
        epics = {item["id"]: {"title": item["title"]} for item in raw_epics if item["type"] == "Epic"}

    return {"features": features, "children": children, "epics": epics}


def load_ado_pat(raw_pat: str | None = None) -> str:
    raw_pat = raw_pat if raw_pat is not None else os.environ.get("ONEPULSE_ADO_PAT")
    if not raw_pat:
        raise RuntimeError(
            "ONEPULSE_ADO_PAT is not set. Copy .env.example to .env and fill in a real Azure DevOps "
            "Personal Access Token (Work Items: Read scope only)."
        )
    return base64.b64encode(f":{raw_pat}".encode()).decode()


ADO_PAT_KEY_VAULT_URL = os.environ.get("ONEPULSE_ADO_PAT_KEY_VAULT_URL", "https://onepulse-kv-dev.vault.azure.net/")
ADO_PAT_SECRET_NAME = "ado-pat"


async def fetch_ado_pat_from_keyvault(async_credential, vault_url: str | None = None) -> str:
    """Migration Plan Phase 6: the real, current source of the ADO PAT —
    replaces the plain `ONEPULSE_ADO_PAT` env var this project used
    through Phase 5. `scripts/run_pipeline.py` (the disclosed, kept-for-
    history CLI exception — see its own docstring) deliberately still
    reads the env var directly via `load_ado_pat()`'s original fallback;
    this function is the real service's own path, called once here and
    composed with `load_ado_pat(raw_pat)` for the actual base64 encoding,
    so that encoding logic stays a single, pure implementation either way.

    Access to this secret is granted, by real Key Vault RBAC role
    assignment, to the Investigation service's own Managed Identity
    ONLY — not core_api's, not bff's, not reporting's. See CLAUDE.md
    Task 45 for the direct verification that this boundary actually
    holds, not merely that it was configured.
    """
    vault_url = vault_url or ADO_PAT_KEY_VAULT_URL
    async with SecretClient(vault_url=vault_url, credential=async_credential) as client:
        secret = await client.get_secret(ADO_PAT_SECRET_NAME)
        return secret.value


def _ado_mcp_server_entry_path() -> Path:
    """The real, locally-installed Azure DevOps MCP server entry point —
    `investigation/node_modules/@azure-devops/mcp/dist/index.js`, the
    exact file this service's own `package.json`-pinned install's
    `bin.mcp-server-azuredevops` points at (confirmed live via `npm view
    @azure-devops/mcp@2.10.0 bin`). Extracted as its own function,
    separate from `_ado_mcp_server_params`, purely so a test can
    monkeypatch it to exercise the "install missing" error path without
    needing to actually delete the real local install.

    Real, deliberate relocation (Migration Plan Phase 4): `package.json`/
    `node_modules` moved from the repo root into `investigation/` itself
    — Node and this pinned package now exist only inside the
    Investigation service's own directory, not the repo root, matching
    this phase's own bar ("Node and the pinned @azure-devops/mcp present
    only in the Investigation service").
    """
    service_root = Path(__file__).resolve().parent
    return service_root / "node_modules" / "@azure-devops" / "mcp" / "dist" / "index.js"


def _ado_mcp_server_params(ado_org_name: str, ado_pat_b64: str, ado_project_name: str) -> StdioServerParameters:
    """Real bug found and fixed (Task 29): `@azure-devops/mcp`'s
    `wit_work_item` actions (get/get_batch/list_comments) call the real
    installed server's `elicitProject()` — which triggers an interactive
    `server.server.elicitInput()` form request — whenever the tool call
    itself omits `project` (confirmed by reading the real installed
    source, `dist/tools/work-items.js`). This project's `mcp.ClientSession`
    has no `elicitation_callback` registered (Task 10's own deliberate
    choice to bypass `agent_framework`'s native MCP client and reuse this
    project's own proven bridge, which never anticipated a
    server-initiated elicitation), so any such call hard-fails with
    "Client does not support form elicitation". Confirmed live: the
    investigation agent does not reliably include `project` on every one
    of its own `wit_work_item` calls — one real run included it and got
    real data; an identical, unmodified re-run omitted it and hit this
    failure on all 115 real calls, defaulting every item to "Needs Human
    Review" with a placeholder "could not retrieve" evidence string,
    which the pre-existing (Task 7) critical-item-referenced check then
    correctly refused to approve as `hard_stop_defect` — no short
    narrative can cite 115 items by name. The real, correct fix is not a
    client-side elicitation handler: `elicitProject`'s own real source
    checks `process.env.ado_mcp_project` FIRST and returns it directly,
    skipping elicitation entirely — the server's own documented escape
    hatch for a non-interactive client. Setting it here makes every
    `wit_work_item` call deterministic regardless of whether the agent
    remembers to pass `project` itself. Extracted as its own pure
    function so this specific real fix has a real regression test
    (`tests/test_pipeline_mcp_server_params.py`) without needing to spin
    up live Azure DevOps infrastructure just to prove an env var is set.

    Version pinned (2026-09-09): this was the actual mechanism behind
    the real Investigation outage `_extract_work_item_fields` fixes
    above. `npx -y @azure-devops/mcp` (no version) resolved to 2.9.0
    when Task 36 wrote that parser, then silently resolved to 2.10.0 by
    the time of this fix — a real upstream response-shape change (the
    guard-marker wrapping around `wit_work_item`'s `get_batch`/
    `list_comments` results) reached this project with zero code change
    on our side. Confirmed live (`npm view @azure-devops/mcp@2.10.0
    version`) that 2.10.0 — the version this project's parsers are now
    written and tested against — resolves cleanly. Pinning stops the
    next silent upstream shape change from becoming the same class of
    outage again; bumping this version is now a deliberate, reviewed
    action instead of something that happens automatically on the next
    `npx` cache miss.

    Spawns a real local install, not `npx` (2026-09-09): even pinned,
    `npx -y` still resolves and potentially fetches at every real spawn
    — real, live-demonstrated risk: an interrupted install (this
    project's own earlier diagnostic run, killed by a `timeout`) left a
    real corrupted npm cache entry (`@azure/msal-node-extensions/dist/`
    missing `index.mjs`) that broke the very next real pipeline run with
    a real `ERR_MODULE_NOT_FOUND`, recovered only by deleting the
    corrupted cache directory and letting a fresh install complete.
    Inside a container this class of failure has no equivalent
    recovery — a request-time `npx` fetch either needs outbound network
    access at runtime (often disallowed) or fails outright, and a
    corrupted cache persists across every subsequent request until the
    container is rebuilt. The real, correct fix: install
    `@azure-devops/mcp@2.10.0` as a normal declared dependency (this
    repo's own `package.json`, pinned to the identical version, with
    `package-lock.json` committed for a reproducible `npm ci`) and spawn
    its real installed entry point (`node_modules/@azure-devops/mcp/
    dist/index.js`, the file `bin.mcp-server-azuredevops` in the
    package's own `package.json` points at — confirmed live via `npm
    view @azure-devops/mcp@2.10.0 bin`) directly via `node`, never `npx`.
    A container build runs `npm ci` once, offline-safe after that, at
    build time — the exact same guarantee this project's Python
    dependencies already get from `uv`/`pip` installing into the image;
    Node dependencies were the one real gap. Confirmed live: the
    locally-installed binary starts identically to the npx-resolved one
    (same real `"version":"2.10.0"` startup banner, same behavior).
    Fails loudly with a clear, actionable error if the local install is
    missing, rather than silently falling back to `npx` — a silent
    fallback would just reintroduce the exact runtime-fetch risk this
    fix exists to remove.
    """
    server_entry = _ado_mcp_server_entry_path()
    if not server_entry.exists():
        raise RuntimeError(
            f"Local Azure DevOps MCP server install not found at {server_entry}. "
            "Run `npm install` inside investigation/ first (see investigation/package.json) — this service spawns "
            "the locally installed binary directly rather than resolving it via `npx` at request "
            "time (2026-09-09: an interrupted `npx` install once corrupted its own cache and broke "
            "a real pipeline run; a container has no recovery path for that at request time)."
        )
    return StdioServerParameters(
        command="node",
        args=[str(server_entry), ado_org_name, "--authentication", "pat", "-d", "core", "work-items"],
        env={"PERSONAL_ACCESS_TOKEN": ado_pat_b64, "ado_mcp_project": ado_project_name},
    )


async def investigate(
    chat_client: FoundryChatClient,
    ado_pat_b64: str,
    ado_org_name: str,
    ado_project_name: str,
    on_detail: Callable[[str], None] = noop_detail,
) -> tuple[list[dict], int, dict]:
    """Returns (findings, queried_item_count, tower_hierarchy).
    `queried_item_count` is the real, deterministic Committed-scope size
    (see `_query_committed_scope`) — required by `run_quality_gate`/
    `code_enforced_risk_floor_check` (Task 28/Part 1) to tell a genuine
    coverage shortfall apart from a legitimate zero-scope run.
    `tower_hierarchy` (Task 36) is the real, deterministic Epic/Feature
    structure from `_query_tower_hierarchy` — `{"epics": {}, ...}` (empty)
    when there is no real tower structure to report against.

    See `_ado_mcp_server_params`'s own docstring for a real, unrelated
    bug (Task 29) found and fixed in how this MCP server is spawned —
    a real elicitation-request failure mode, not a Part 1/2 logic issue.
    """
    server_params = _ado_mcp_server_params(ado_org_name, ado_pat_b64, ado_project_name)
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()

            feature_ids, child_ids = await _query_committed_scope(mcp_session, ado_project_name, on_detail)
            scope_ids = feature_ids + child_ids
            if not scope_ids:
                on_detail(f"No Features tagged 'Committed' found for '{ado_project_name}' — nothing to investigate.")
                return [], 0, {"features": {}, "children": {}, "epics": {}}

            tower_hierarchy = await _query_tower_hierarchy(mcp_session, feature_ids, child_ids, on_detail)

            tools, tool_call_progress = await build_mcp_function_tools(mcp_session, on_detail)

            async with Agent(
                client=chat_client,
                name="onepulse-investigation-agent",
                instructions=_investigation_instructions(ado_project_name, scope_ids),
                tools=tools,
                default_options={"response_format": INVESTIGATION_SCHEMA},
            ) as agent:
                async with heartbeat(on_detail, "Investigation agent"):
                    result = await agent.run(
                        f"Investigate exactly these {len(scope_ids)} real work item ID(s) — the already-confirmed "
                        f"Committed scope for '{ado_project_name}' — and report your findings for every one of "
                        f"them: {scope_ids}"
                    )
            on_detail(
                f"Investigation tool calls complete: {tool_call_progress['completed']} of "
                f"{tool_call_progress['dispatched']} real tool call(s) resolved."
            )

    return json.loads(result.text)["findings"], len(scope_ids), tower_hierarchy


