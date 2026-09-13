# OnePulse — Code Map

A module-by-module map of what's actually in this repository, for learning it, not for planning
work against it. Accuracy over tidiness: where something is messy, duplicated, or a leftover, this
document says so rather than smoothing it over. Streamlit was retired in Migration Plan Phase 11 —
the frontend below is React only; nothing deleted is mapped.

Line counts are from a real `wc -l` on 2026-09-13 and will drift as the code changes — read them as
"roughly this size," not as a maintained metric.

---

## Orientation: two real paths through the system

### The read path — browser to database, for a GET request

1. **Browser** — the React SPA (built by Vite, served as static files) makes a `fetch()` call with
   `credentials: "include"` (`frontend/src/api/client.ts`). No token is attached client-side; the
   HttpOnly session cookie Azure Easy Auth set at sign-in rides automatically.
2. **`bff/main.py`** — the request hits the BFF first (same origin as the SPA — `bff` serves both).
   Easy Auth has already gated it before this code even runs; a route handler here calls
   `_core_headers()`, which extracts the real signed-in identity from the `X-MS-CLIENT-PRINCIPAL`
   header (`_resolve_entra_object_id`), acquires a real Entra service-to-service bearer token for
   `core_api`'s own audience, and injects the current span's W3C `traceparent`.
3. **`core_api/main.py`** — receives the proxied request. `Depends(verify_service_token)`
   (`core_api/security.py`) validates the bearer token's signature/audience/issuer/app-role.
   `Depends(get_current_actor)` resolves the Entra object ID against `actors`, then resolves the
   real tenant (`actor_scope` → `portfolios.tenant_id`) and the real set of authorized `program_id`s
   — fresh, on every request, no cache.
4. **A domain function in `onepulse_common`** (e.g. `pipeline.list_recent_reports`,
   `human_governance.get_report_detail`) — takes the real `conn`/`tenant_id`, does
   `SELECT set_config('app.current_tenant_id', ...)` inside a transaction, and queries Postgres. The
   real `reports` RLS policy (`FORCE`d) is what actually filters by tenant at this point — the SQL
   itself does not need a `WHERE tenant_id = ...` clause because the database enforces it.
5. **Postgres** (`onepulse-pg-dev`) answers, RLS having already narrowed what's visible.

The response retraces the same path back: `core_api` returns a Pydantic model as camelCase JSON;
`bff` proxies the bytes unchanged (`_proxy_response`); the frontend's `apiGet`/`apiPost` parses it or
throws a typed `ApiError`/`UnauthenticatedError`.

### The trigger path — a click to a persisted report

1. **`GenerateView.tsx`** calls `useTriggerReport`, which `POST`s to
   `/api/v1/programs/{programId}/reports`.
2. **`bff` → `core_api`**, same identity/token machinery as above. `core_api.trigger_report()`
   checks `_require_owner`, `_require_program_in_scope`, and FR-11's rate limit
   (`_check_rate_limit`), then calls `cycles.create_cycle()` — a plain `INSERT` into `cycles` with
   `status='queued'` — and publishes a thin `{cycle_id}` message onto the real `report-cycles` Azure
   Storage Queue. Returns `202` immediately; nothing has executed yet.
3. **`reporting/main.py`**'s `_consume_loop` picks up the message, calls
   `cycles.get_cycle_for_execution()` (marks the row `running`), and starts `_execute_cycle()`.
4. **The Investigation round trip.** `_resolve_investigation_result()` first asks Investigation
   directly (`GET /internal/investigations/{cycle_id}`) whether this cycle already has a real
   result — the ADR-026 resume check, so a redelivered message doesn't re-pay Investigation's cost.
   If not, `reporting` sends a real message onto `investigation-requests` and polls `findings-ready`.
5. **`investigation/main.py`**'s own consume loop picks up the `investigation-requests` message,
   calls `investigation/investigate.py`'s `investigate()` — which spawns the real, locally-installed
   `@azure-devops/mcp` Node server, deterministically queries Committed-tagged Features and their
   children, and runs a real `agent_framework.Agent` against them — then upserts the real result into
   `investigation.investigation_runs` (keyed on `cycle_id`) and sends a thin notification onto
   `findings-ready`.
6. **Back in `reporting`**: `_await_findings()` sees the notification, `_fetch_investigation_result()`
   fetches the real findings over HTTP (never by querying Investigation's schema — there is no grant
   that would allow it), and `onepulse_common.pipeline.run_reporting_stages()` runs Status Update
   Analysis → Deterministic Rollup → Synthesis → Self-critique/quality gate → Rendering → the real
   `persist_report()` (uploads the rendered `.pptx` to Blob Storage, then `INSERT`s into
   `reports`/`findings`/`untracked_items`).
7. **`cycles.mark_cycle_terminal()`** writes the real terminal status; the frontend, which has been
   polling `GET /api/v1/cycles/{cycleId}` every 3 seconds, renders it.

Closing the browser at any point after step 2 does not stop the run — it is a queue-driven worker
chain from that point on, entirely decoupled from the request that started it.

---

## `core_api/` — the domain service

| File | ~Lines | What it does | Depends on | Called by |
|---|---|---|---|---|
| `main.py` | 975 | Every real route: programs, reports, reviews, cycles, chat, download, `/me`. Owns the Postgres pool, Foundry client, Search/embedding clients, and the `report-cycles` queue publisher, all built once in `lifespan()`. Every response model is a Pydantic `BaseModel`; a custom `HTTPException` handler flattens every error to one consistent `{"error", "message"}` shape. | `core_api.security`, almost every `onepulse_common` module, `trace_debug` | `bff` (the only real caller) |
| `security.py` | 282 | `verify_service_token` (validates the BFF's bearer JWT against live JWKS), `resolve_actor`/`resolve_tenant_id`/`resolve_authorized_program_ids`, and the `get_current_actor` FastAPI dependency every route depends on. | `onepulse_common.roles`, `jwt`, `asyncpg` | `main.py` (via `Depends`) |

Entry point: `uvicorn core_api.main:app --port 8000`. Nothing else imports this package — it is a
leaf, not a library other services build on.

---

## `bff/` — session, identity, and the frontend host

| File | ~Lines | What it does | Depends on | Called by |
|---|---|---|---|---|
| `main.py` | 353 | Proxies every real route to `core_api`, one-to-one, adding the service token and identity header on the way; extracts the real signed-in identity from Easy Auth's own header; serves the built React bundle same-origin (`StaticFiles` mount, must stay the last-registered route). | `bff.observability`, `httpx`, `trace_debug` | The browser, directly |
| `observability.py` | 66 | A deliberate near-duplicate of `onepulse_common.observability.enable_observability` — same dual Application-Insights/Arize export, but reads the connection string from a plain env var instead of calling Foundry, because this file's whole job is proving the BFF *never* calls Foundry, Postgres, or Search. | `arize.otel`, `azure.monitor.opentelemetry` | `main.py` |

Structurally enforced, not just documented: `tests/test_bff_no_data_access.py` parses this package's
own imports and, separately, checks in a fresh subprocess that `asyncpg`/`azure.search.documents`/
`azure.ai.projects` never enter `sys.modules` as a result of importing `bff.main`.

Entry point: `uvicorn bff.main:app --port 8100`. Requires `core_api` running first.

---

## `investigation/` — the ADO/Node/Foundry service

| File | ~Lines | What it does | Depends on | Called by |
|---|---|---|---|---|
| `investigate.py` | 569 | The real Work Item Investigation logic (FR-1): deterministic WIQL scoping (`_query_committed_scope`, `_query_tower_hierarchy`), the guard-marker-wrapped MCP response parsers (`_extract_work_item_ids`/`_extract_work_item_fields`), spawning the pinned local `@azure-devops/mcp` server, and `investigate()` itself — the real agent call. Also owns the Key Vault PAT fetch. | `onepulse_common.heartbeat`, `onepulse_common.mcp_bridge`, `mcp`, `agent_framework` | `investigation/main.py`; also `scripts/run_pipeline.py` (the one disclosed exception) |
| `main.py` | 324 | A real FastAPI service whose `lifespan` runs a background queue-consumer loop against `investigation-requests` (lease renewal, poison dead-lettering) alongside one real route, `GET /internal/investigations/{cycle_id}` — the only way `reporting` ever learns a result. | `investigation.investigate`, `investigation.store`, `onepulse_common.queues`/`observability`/`db` | The queue; `reporting` (via HTTP) |
| `store.py` | 92 | The one and only module with real Postgres grants on the `investigation` schema — `upsert_investigation_run` (keyed on `cycle_id`, `ON CONFLICT DO UPDATE`) and `get_investigation_run`. Deliberately kept out of `onepulse_common` so the schema-access boundary holds at the Python import-graph level, mirroring the BFF precedent. | `asyncpg` only | `investigation/main.py` only |

This is the one service with a Node runtime (`node_modules/@azure-devops/mcp`, pinned at 2.10.0,
installed at image build time) and the only real consumer of the Azure DevOps PAT.

Entry point: `python -m investigation.main`.

---

## `reporting/` — synthesis, rendering, persistence

| File | ~Lines | What it does | Depends on | Called by |
|---|---|---|---|---|
| `main.py` | 648 | A real Azure Storage Queue consumer on `report-cycles` (not a DB poller — retired in a Phase 7 follow-up). Per cycle: the ADR-026 resume check, the Investigation round trip over two more queues, a real sha256 status-deck integrity check (`_verify_status_deck_integrity`) before doing any real work, and calling `onepulse_common.pipeline.run_reporting_stages()`. Writes real, incremental progress to `cycles.stages` via a background `_progress_writer` task. | `onepulse_common.pipeline`/`cycles`/`cycle_progress`/`queues`/`heartbeat`/`observability`, `httpx` | The `report-cycles` queue |

This is the one service touching both the `investigation-requests`/`findings-ready` queues (as the
Investigation caller) and the `report-cycles` queue (as its own outer trigger) — the busiest queue
consumer in the system.

Entry point: `python -m reporting.main`.

---

## `libs/onepulse_common/onepulse_common/` — the shared library

Imported by `core_api`, `bff`, `reporting`, and (selectively) `investigation`/`scripts`. The one hard
rule that holds throughout: nothing here imports Node/MCP/ADO-PAT-adjacent code, so importing this
package never pulls the Investigation service's own concerns into `core_api`/`bff`/`reporting`.

| File | ~Lines | What it does | Real callers |
|---|---|---|---|
| `pipeline.py` | 851 | The Reporting half of the pipeline: `analyze_status_deck`, `synthesize`, `self_critique`, `run_quality_gate`, `persist_report` (real blob upload + Postgres INSERT), `list_recent_reports`, `build_output_path`, and the top-level `run_reporting_stages()` orchestrator. The single largest module in the shared library. | `core_api`, `reporting`, `scripts/run_pipeline.py` |
| `human_governance.py` | 287 | Approve/reject, pending-review listing, report detail — real, tenant-scoped `asyncpg` functions, no HTTP framework of its own. | `core_api`, `scripts/review_cli.py` |
| `report_rendering.py` | 406 | The two real `.pptx` builders (`render_status_report`, the flat fallback; `render_tower_report`, the Tower View) plus the shared `week_of()` Monday-bucketing helper used by both persistence and the trigger-collision check. Pure — no model call. | `pipeline.py`, `core_api.main` (imports `week_of`) |
| `cycles.py` | 189 | The `cycles` status table's real DB I/O: `create_cycle`, `get_cycle_for_execution`, `write_cycle_stages`, `mark_cycle_terminal`/`mark_cycle_failed`, `get_cycle`, `terminal_status_from_result`. | `core_api`, `reporting` |
| `cycle_progress.py` | 161 | Pure curation: turns raw `on_stage`/`on_detail` text into the structured `stages` dict the frontend renders. Parses the *exact wording* of specific log lines with regex (`re.search(r"real children of (\d+) Committed Feature", message)` and similar) — see "Hardest to understand cold," below. | `reporting/main.py` |
| `tower_rollup.py` | 196 | Deterministic Epic/Feature rollup for the Tower View: per-tower percent-complete, flagged counts, the 3-tier health color, templated "Needs Your Decision" lines. No model call. | `pipeline.py` |
| `quality_gate.py` | 108 | `code_enforced_risk_floor_check` (the coverage + critical-item-citation check) and `decide_revision_outcome` (the pure 3-input HLD Section 3 decision). | `pipeline.py` |
| `status_rollup.py` | 47 | `compute_overall_status` — the fixed FR-8 Red/Amber/Green/Unknown rule. | `pipeline.py` |
| `search_index.py` | 240 | Azure AI Search index definition (including the real `recency_boost` scoring profile) and `hybrid_search()`, with the mandatory `authorized_program_ids` OData filter. | `chat_assistant.py`, `scripts/ingest_reports_to_search.py` |
| `chat_assistant.py` | 148 | The RAG chat agent — one `agent_framework.Agent`, one `FunctionTool` wrapping `hybrid_search`. | `core_api.main` (chat route), `scripts/chat_cli.py` |
| `embeddings.py` | 71 | The real embedding client (`text-embedding-3-small` via the classic Azure OpenAI REST shape, not the unified inference route, which 404s for this deployment). | `search_index.py` callers, `scripts/ingest_reports_to_search.py` |
| `blob_storage.py` | 110 | `upload_report_blob`/`issue_download_sas` — real user-delegation SAS, no account key. | `pipeline.py` (upload), `core_api.main` (SAS issuance) |
| `queues.py` | 102 | Generic Azure Storage Queue helpers shared by `investigation` and `reporting`: `send_json_message`, `parse_message`, `is_poison`/`deadletter`, the three real queue-name pairs. No domain logic. | `investigation/main.py`, `reporting/main.py`, `core_api.main` (publishes to `report-cycles`) |
| `heartbeat.py` | 59 | `heartbeat()` — a background ticker logging real elapsed time around a slow `await`, so no gap in the status table or log exceeds ~20s. | `investigation/investigate.py`, `pipeline.py`, `reporting/main.py` |
| `mcp_bridge.py` | 79 | `build_mcp_function_tools` — wraps a real, dynamically-discovered MCP tool as a plain `agent_framework.FunctionTool`, logging both dispatch and completion. Shared because both Investigation's ADO session and Reporting's own PPTX-parsing session need the identical bridge. | `investigation/investigate.py`, `pipeline.py` (`analyze_status_deck`) |
| `roles.py` | 32 | `is_owner_role` — the entire Owner/Visitor model in one function. | `core_api.security` |
| `db.py` | 100 | `PostgresClient` — Entra-ID-token-as-password connection pooling. | Every service that touches Postgres |
| `config.py` | 66 | `PostgresSettings`/`FoundrySettings` dataclasses and a `Settings.load()` classmethod. **Largely vestigial for the real system — see "Vestigial," below.** | `db.py` (the `PostgresSettings` dataclass only); `Settings.load()` itself has no real caller |
| `constants.py` | 41 | LLD §3's configuration values, transcribed. **Mostly read only by its own test — see "Vestigial," below.** | `core_api.main` (one constant, `ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY`) |
| `observability.py` | 102 | The real dual Application-Insights/Arize export, built once per process. | `core_api`, `investigation`, `reporting`, `scripts/run_pipeline.py` |
| `foundry.py` | 59 | A Messages-API Claude-on-Foundry client. **Fully superseded — see "Vestigial," below.** | `scripts/foundry_agent_spike.py` only |
| `agent_cleanup.py` | 39 | `maybe_delete_agent` — deletes or keeps a classic `AgentsClient` agent based on `ONEPULSE_KEEP_AGENTS`. **Superseded — see "Vestigial," below.** | Four spike scripts only |

---

## `frontend/src/` — the React SPA

| File | ~Lines | What it does |
|---|---|---|
| `main.tsx` | 40 | App bootstrap: Mantine theme (the real navy reused from `report_rendering.py`'s own `_NAVY`), a `QueryClient` with `retry: false` (a 401/403/404 is a real outcome, never transient), renders `<App />`. |
| `App.tsx` | 76 | The whole layout: header (title, "Signed in as {role}", the project selector), and — once a project is picked — a 7:5 split between (report table + generate view) and the chat assistant. Wraps everything in `<AuthGate>`. |
| `components/AuthGate.tsx` | 100 | The real sign-in gate: a loading state with an honest elapsed-seconds counter (never a fake progress bar) while `useMe()` resolves, then one of three real outcomes — unauthenticated (a Sign-in link), authenticated-but-unprovisioned (`403 no_access`), or a genuine network/CORS failure — each with its own distinct message. |
| `components/ProjectSelector.tsx` | 31 | The project dropdown. Empty by default; nothing scoped to a project fetches until one is picked. |
| `components/ReportTable.tsx` | 193 | The report table: history, Approve/Reject (owner-only, hidden not enforced client-side), download via the shared `downloadReportOrNotify` helper. |
| `components/GenerateView.tsx` | 302 | The 7-step progress view (polls `useCycleStatus`), the pre-click weekly-collision banner and `force` control, and the "Download this report" button reading the just-completed cycle's own `reportId`. The largest, most stateful component in the frontend. |
| `components/ReportDetailModal.tsx` | 54 | A read-only modal: executive summary, findings, untracked items. |
| `components/ChatAssistant.tsx` | 79 | The chat UI — local turn history (not persisted across a reload), citations rendered as badges. |
| `api/client.ts` | 100 | The one real `fetch` wrapper (`credentials: "include"` only), `ApiError`/`UnauthenticatedError`, `buildSignInUrl()`. |
| `api/hooks.ts` | 137 | One TanStack Query hook per endpoint. |
| `api/download.ts` | 40 | `downloadReportOrNotify` — the shared SAS-download-with-error-handling logic, used by both `ReportTable` and `GenerateView`. |
| `api/types.ts` | 148 | Hand-maintained TypeScript mirrors of `core_api`'s Pydantic response models — **no shared schema generator; see "Hardest to understand cold," below.** |

Entry points: the browser loads `index.html` from wherever `bff` serves `frontend/dist`; `npm run
dev` (Vite, port 5173) works for GET-driven local iteration only — every real POST hits the same
Easy Auth cross-origin preflight block described in `bff/main.py`'s own docstring.

---

## `scripts/` — CLI tools, migrations, and historical spikes

Not all scripts here are equally "real system" — this directory holds three genuinely different
kinds of file, worth telling apart rather than treating as one undifferentiated pile:

**Still actively used:**
- `run_pipeline.py` (232 lines) — the one disclosed exception to "Investigation and Reporting are
  separate processes": a standalone, un-queued, in-process composition of `investigation.investigate`
  and `onepulse_common.pipeline`, for scripted/headless local runs.
- `migrate.py` (92)/`migrate_investigation.py` (91) — apply the real, numbered SQL migrations in
  `scripts/migrations/`/`scripts/investigation_migrations/`.
- `verify_migration.py` (898 — the largest file in the whole repository) — independently confirms
  the real schema against live `information_schema`/`pg_catalog`, including positive-ownership and
  positive-grant checks added after ADR-023's own finding that negative checks alone don't prove an
  isolation claim.
- `apply_admin_migration.py` (108) — the real, reusable way a human holding the Postgres Entra
  Administrator role applies a schema-owning migration (workload identities can't authenticate
  interactively to do this themselves).
- `ingest_reports_to_search.py` (376) — the real `reindex` command: fetches report/finding chunks,
  embeds them, uploads, and prunes anything the index holds that Postgres no longer accounts for.
- `review_cli.py` (132)/`chat_cli.py` (136) — real, directly-runnable front ends to
  `human_governance`/`chat_assistant`, predating any HTTP API.
- `check_no_secrets.py` (151) — the repo-wide static-credential-pattern scanner.
- `pptx_mcp_server.py` (62) — the custom PPTX-parsing MCP server Status Update Analysis reads
  through.

**Real, still-relevant seed/fixture scripts** (four, with real but distinct scopes — see "Overlapping
modules," below): `seed_dev_data.py` (135), `seed_phase8_test_data.py` (316),
`seed_rag_test_data.py` (188), `seed_leave_tracker_project.py` (258).

**Historical spikes, superseded, kept for the reasoning trail, not touched by any real service today:**
`foundry_agent_spike.py` (83), `ado_investigation_spike.py` (203), `observability_spike.py` (116),
`observability_export_run.py` (71), `create_sample_status_deck.py` (52),
`create_aiobs_status_deck.py` (45). These are real, runnable scripts, not dead files — they just
aren't part of any path a real request or queue message takes.

`scripts/bootstrap/` holds the one-time SQL that creates the Postgres application roles themselves
(`create_app_role.sql`, `create_app_role_local_dev.sql`, `create_investigation_role.sql`,
`create_investigation_role_local_dev.sql`, `create_database.sql`) — run once per environment, by an
administrator, never by `migrate.py`.

---

## `tests/` — what's actually covered

15 files, 2,455 lines. Two real testing disciplines coexist deliberately, not by accident:

- **Pure logic** (`test_status_rollup.py`, `test_quality_gate.py`, `test_cycle_progress.py`,
  `test_constants.py`, `test_config.py`, `test_check_no_secrets.py`,
  `test_pipeline_mcp_server_params.py`, `test_extract_work_item_fields.py`,
  `test_tower_view_selection.py`) — no database, no network, fast.
- **Real infrastructure** (`test_human_governance.py`, `test_cycles.py`,
  `test_phase8_identity_and_roles.py`, `test_verify_migration.py`,
  `test_investigation_schema_isolation.py`, `test_bff_no_data_access.py`) — every one of these hits
  the real `onepulse-pg-dev` instance (transactional-rollback style since Task 40, so they don't
  leave rows behind) or does a real subprocess/import-graph check. This project's tests were never
  meant to mean "logic is correct in isolation" — several exist specifically to adversarially prove a
  real privilege or isolation boundary holds (`test_investigation_schema_isolation.py`,
  `test_bff_no_data_access.py`, and the append-only-guarantee tests inside
  `test_human_governance.py`).

`test_pipeline_mcp_server_params.py`'s own filename is a small, harmless leftover: the function it
tests (`_ado_mcp_server_params`) moved out of `onepulse_common.pipeline` into
`investigation/investigate.py` during the Phase 4 split; the imports are correct, only the filename
still says "pipeline."

---

## Vestigial or superseded code, not yet removed

- **`onepulse_common/foundry.py`** (the Messages-API `AnthropicFoundry` client) and
  **`onepulse_common/agent_cleanup.py`** (classic-`AgentsClient` cleanup) are both fully superseded —
  the real pipeline uses `agent_framework.foundry.FoundryChatClient` against Azure-hosted GPT-5-mini,
  not this path, and creates no portal-visible agent resource for `agent_cleanup.py` to manage.
  Confirmed by grep: their only real callers are `scripts/foundry_agent_spike.py` and three other
  spike scripts, none of which any real service or queue message ever invokes. Kept deliberately, per
  this project's own stated convention, as a record of a real decision point — not an oversight.
- **`onepulse_common/config.py`'s `Settings`/`FoundrySettings`/`Settings.load()`** have no real
  caller anywhere except their own test (`tests/test_config.py`). Every real service constructs
  `PostgresSettings` inline, directly, with its own hardcoded host/database and an env-var-sourced
  role name — never through `Settings.load()`, which itself requires env vars
  (`ONEPULSE_ENVIRONMENT`, `ONEPULSE_PG_HOST`, `ONEPULSE_FOUNDRY_BASE_URL`) that no `.env.example` or
  Dockerfile in this repository actually sets. This class was written early and never wired to
  anything real.
- **`onepulse_common/constants.py`'s `MAX_REVISIONS`, `MAX_TURNS`, `AGENT_CALL_ISOLATION`,
  `CONTENT_SAFETY_CHECK_MANDATORY`, `MIN_SERVICE_REPLICAS`** are read by nothing except
  `tests/test_constants.py`. This is worth being precise about, not just noting: the real "exactly
  one revision" behavior is not parameterized by `MAX_REVISIONS` at all — it's implicit in
  `pipeline.run_quality_gate()`'s own control flow (check once, revise once if needed, check again,
  decide). If someone changed `MAX_REVISIONS` to `2` today, nothing in the running system would
  change. `CONTENT_SAFETY_CHECK_MANDATORY = True` is the sharpest instance of this: the constant
  asserts a real requirement (NFR-8) that is genuinely enforced nowhere — Content Safety integration
  is 0% built (see `11_Deferred_Items_and_Open_Follow_Ups.md`). `ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY`
  is the one constant in this file that *is* real — `core_api/main.py` imports and uses it directly.
- **`onepulse_common/observability.py`'s own module docstring** still describes "Home.py does so via
  `st.cache_resource`" as a live fact about how a caller ensures single-init. `Home.py` no longer
  exists (Migration Plan Phase 11) — the real callers that ensure single-init today are each
  service's own `lifespan()` function, which runs exactly once per process, the same guarantee the
  docstring already correctly attributes to `scripts/run_pipeline.py`.

---

## Anywhere two modules do overlapping things

- **The Red/Amber/Green(/Unknown) 3-tier health rule is implemented three separate times, not
  shared.** `status_rollup.compute_overall_status()` (the real FR-8 rule, operating on FR-1's four
  item statuses), `tower_rollup._health()` (its own docstring literally says "Same 3-tier rule as
  `status_rollup.compute_overall_status`"), and a third inline check
  (`s in ("At Risk", "Needs Human Review")`, duplicated as `_FLAGGED_STATUSES` in `tower_rollup.py`
  and `_CRITICAL_STATUSES` in `quality_gate.py`) all express the identical "Blocked beats At-
  Risk/Needs-Human-Review beats On-Track" ordering independently. None of the three would notice if
  the other two drifted — there is no shared constant or function backing the rule itself, only
  three authors independently agreeing on the same real business rule at three different times.
- **Four seed scripts with real, distinct, but easily-confused purposes**: `seed_dev_data.py` (the
  general tenant/portfolio/program bootstrap), `seed_phase8_test_data.py` (the second-tenant/RLS-
  proof data), `seed_rag_test_data.py` (one representative report for early Chat Assistant testing),
  `seed_leave_tracker_project.py` (an entire second ADO project's worth of work items). Picking the
  wrong one for a given real need is an easy mistake — none of their names alone makes clear which of
  the other three it does *not* also do.

---

## The hardest parts to understand cold, and why

1. **The `on_stage`/`on_detail` text-parsing curation
   (`onepulse_common/cycle_progress.py`).** The real, structured `stages` JSON the frontend renders
   is built by regex-parsing the *exact wording* of free-text progress lines
   (`re.search(r"real children of (\d+) Committed Feature", message)`,
   `message.startswith("Persisted as report_id=")`, and several more like it). The "API" between
   "what the pipeline logs" and "what the UI shows" is an implicit string format, not a real data
   structure — changing a log message's wording anywhere in `pipeline.py`/`investigation.py` without
   updating the matching regex here silently breaks the UI's own summary text, with no type system or
   test catching the mismatch until someone notices a blank or wrong-looking stage detail.
2. **The queue choreography across `reporting`/`investigation`.** Three real queues
   (`report-cycles`, `investigation-requests`, `findings-ready`), each with lease renewal, poison
   dead-lettering, and a resume-check (`_resolve_investigation_result`) that has to correctly
   distinguish "never dispatched," "dispatched, still running," and "already completed" from a single
   HTTP call's 404-vs-200 response. Understanding why a redelivered message is *safe* (Investigation's
   `ON CONFLICT DO UPDATE` upsert) and separately why it's *cheap* (the resume check skipping
   re-dispatch) requires reading `investigation/store.py`, `reporting/main.py`, and ADR-026 together
   — no single file tells the whole story.
3. **The guard-marker JSON parsing in `investigation/investigate.py`
   (`_extract_work_item_fields`).** A bespoke, hand-written parser for an undocumented third-party
   wrapper format (`<<hash>> [UNTRUSTED ...] <<hash>> ... <</hash>>`) that a specific version of
   `@azure-devops/mcp` wraps certain tool results in — and doesn't wrap others in. The function's own
   docstring records two real bugs already found in this exact parsing logic; a third would not be
   surprising, since nothing about the wrapper's shape is documented upstream.
4. **`frontend/src/api/types.ts` is a hand-maintained mirror, not generated.** Every response shape
   is retyped by hand to match `core_api/main.py`'s Pydantic models — there is no shared schema, no
   OpenAPI-to-TypeScript generation step. A field renamed on one side and not the other would only
   surface at runtime (a `undefined` value rendering blank), not at compile time.
