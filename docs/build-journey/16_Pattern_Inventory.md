# OnePulse — Pattern Inventory

Every design pattern actually present in this codebase, each with a real file/function to go read —
not an aspirational list of patterns that could have been used. Where an ADR or module docstring
already records the reasoning, this points at it rather than re-deriving it. Streamlit is retired
(Migration Plan Phase 11); one entry below is explicitly historical and says so.

---

## Patterns in active use

### 1. Backend for Frontend (BFF)
**Where**: `bff/main.py`, the whole module. **Problem it solves**: the frontend needs one thing
(session/identity/response shaping); the domain needs another (every data connection). ADR-017
splits them into two real services rather than one FastAPI app doing both, so the boundary is
structural — `bff` cannot reach a data store even if a future change tried to add one, because
nothing in its own import graph can (`tests/test_bff_no_data_access.py` proves this adversarially,
not just by convention). **The alternative**: one service doing both, the shape every earlier phase
of this project actually used (Migration Plan Phase 1's single `core_api`-only service) — rejected
specifically for the identity-resolution boundary ADR-017 wanted, not for a performance reason.

### 2. Dependency Injection (framework-native)
**Where**: `core_api/security.py`'s `get_current_actor`/`verify_service_token`, consumed via
FastAPI's own `Depends(...)` on every route in `core_api/main.py`. **Problem it solves**: every
route needs the same real identity/role/scope resolution before doing anything else; `Depends`
makes that a declared part of each route's own signature (visible at the call site) rather than a
line every handler body would otherwise have to remember to call. **The alternative**: a global
middleware doing the resolution and stashing it on `request.state` — rejected implicitly by using
`Depends` instead, which keeps each route's real auth requirement legible from its own signature
(`core_api/main.py`'s own comment states this directly: "applied per-route via `Depends` rather than
buried in middleware, so each route's real auth requirement is visible in its own signature").

### 3. Guard Clause / Two-Phase Deterministic Gate
**Where**: `onepulse_common/quality_gate.py` — `code_enforced_risk_floor_check` (the guard: a pure
boolean invariant with no model call) and `decide_revision_outcome` (the gate: a pure 3-input
decision table). **Problem it solves**: HLD Section 3 requires a code-enforced check to run
*independently, twice* (before and after the one permitted revision) so that a real defect — not a
content judgment — produces a hard stop with nothing persisted. Keeping the guard pure and outside
any model call is what makes the regression tests in `tests/test_quality_gate.py` possible at all:
they can force a real hard stop without needing a real, flaky model response to cooperate.
**The alternative**: letting the Self-critique agent itself decide pass/fail on both factual
completeness and tone — rejected explicitly (`quality_gate.py`'s own docstring: "a subjective,
skill-defined check... is a legitimate content outcome, not a defect," kept structurally separate
from the code-enforced one).

### 4. Idempotent Consumer with a Durable Resume Check (at-least-once delivery)
**Where**: `investigation/store.py`'s `upsert_investigation_run` (`ON CONFLICT (cycle_id) DO
UPDATE`) is the write-side half; `reporting/main.py`'s `_resolve_investigation_result` (a real `GET
/internal/investigations/{cycle_id}` call *before* ever dispatching) is the read-side half. **Problem
it solves**: Azure Storage Queues guarantee at-least-once delivery, so any consumer must tolerate
redelivery. Keying the Investigation result on `cycle_id` makes redelivery *safe* (overwrite, not
duplicate); checking for an existing result before dispatching makes redelivery *cheap* too — a
process killed mid-cycle and redelivered skips re-paying Investigation's real ~80%-of-runtime cost
(ADR-026's own stated distinction: "redelivery is safe" vs. "redelivery is cheap"). **The
alternative**: a second, separate "was this already dispatched" flag on the `cycles` row — considered
and rejected (ADR-026) specifically because it would be a second source of truth that could drift
from Investigation's own real record.

### 5. Dead Letter Queue
**Where**: `onepulse_common/queues.py` — `is_poison`/`deadletter`, `MAX_DEQUEUE_COUNT = 5`, and the
three real `-poison` queue twins. **Problem it solves**: a message that can never be successfully
processed (a permanently malformed envelope, a bug that always throws) would otherwise redeliver
forever under at-least-once semantics. **The alternative**: no limit at all, letting a genuinely
poison message cycle indefinitely — explicitly rejected; the Migration Plan's own Phase 4 kickoff
asked for this "built deliberately, not discovered later."

### 6. Choreographed Saga
**Where**: the real three-queue round trip — `core_api` publishes to `report-cycles`; `reporting`
publishes to `investigation-requests` and consumes `findings-ready`; `investigation` consumes
`investigation-requests` and publishes `findings-ready`. **Problem it solves**: a multi-step,
multi-service real-world process (trigger → investigate → synthesize → persist) that must survive a
process crash at any point, without a single request holding it all open. **The alternative**: a
central orchestrator service directing each step — not built; ADR-019/020 chose a database-per-service
plus point-to-point queues instead, accepting `findings` duplication across schemas as "the accepted
trade of database-per-service" rather than introducing a coordinator with its own state.

### 7. Adapter
**Where, live**: `onepulse_common/mcp_bridge.py`'s `build_mcp_function_tools` — adapts the real MCP
tool-calling protocol (`mcp.ClientSession.call_tool`) to `agent_framework`'s own `FunctionTool`
interface, so an MCP server's tools can be handed to an `Agent` unmodified. **Where, historical
(deleted, Migration Plan Phase 11)**: `api_client.py`'s functions used to adapt `core_api`'s
camelCase JSON/ISO-string response shapes into the snake_case dicts and real Python `date`/`datetime`
objects `Home.py`'s Streamlit rendering code expected — the same adapter role `frontend/src/api/
client.ts` now plays for React instead (a straight pass-through of the same JSON shapes, needing no
translation since TypeScript consumes camelCase JSON natively). Recorded here because it's an
instructive example of the same pattern name solving the same real problem (translate one interface's
shape into another's) twice, for two different client technologies, one of which no longer exists.

### 8. Functional Core, Imperative Shell
**Where**: named explicitly in this codebase's own comments, not just observable from structure —
`onepulse_common/cycles.py`'s docstring: "Pure curation logic lives in `onepulse_common.cycle_
progress`; this module is the actual Postgres I/O, same split as `onepulse_common.human_governance`
(I/O) vs. `onepulse_common.quality_gate` (pure) elsewhere in this project." Also:
`status_rollup.py`/`tower_rollup.py` (pure) vs. `pipeline.py` (the impure shell calling them).
**Problem it solves**: the pure halves (`quality_gate.py`, `cycle_progress.py`, `status_rollup.py`,
`tower_rollup.py`) are testable with plain unit tests and no database; the impure halves
(`human_governance.py`, `cycles.py`, `pipeline.py`) are exactly where the real `asyncpg` calls live,
tested instead against real infrastructure. **The alternative**: mixing decision logic and I/O in one
function per feature — the shape this project explicitly moved away from as each new feature area was
added (see the Code Map's inconsistency note below for the one real exception).

### 9. Composition Root
**Where**: `scripts/run_pipeline.py` is, by its own module docstring and `onepulse_common.pipeline`'s,
"the ONE place allowed to import both `investigation.investigate` (Node/ADO-PAT-adjacent) and
`onepulse_common.pipeline` (Reporting-stage logic) together." **Problem it solves**: Migration Plan
Phase 4 requires `onepulse_common.pipeline` to never import anything Investigation-adjacent (so
`core_api`/`bff`/`reporting`'s own import graphs stay clean of Node/MCP/PAT concerns) — but a
real, headless CLI run still needs both halves composed into one process. `run_pipeline.py` is where
that composition is allowed to happen, and the only place. **The alternative**: letting
`onepulse_common.pipeline` import `investigation.investigate` directly for convenience — rejected,
since it would silently reopen the exact import-graph boundary Phase 4 exists to hold.

### 10. Structural Boundary via Import-Graph Isolation
**Where**: `bff/observability.py` (deliberately duplicates ~60 lines from `onepulse_common.
observability` rather than import it, specifically because that function calls Foundry) and
`investigation/store.py` (deliberately kept out of `onepulse_common` so only `investigation/main.py`
can ever import a module with real grants on the `investigation` schema). **Problem it solves**: "no
data-store access" and "no cross-schema access" are real security/architecture claims this project
doesn't want to rest on discipline alone — keeping the sensitive capability physically unreachable
from a forbidden module's own import graph makes the claim checkable by a static tool
(`tests/test_bff_no_data_access.py`'s AST-based import check; `tests/test_investigation_schema_
isolation.py`'s adversarial query). **The alternative**: one shared `enable_observability()`/one
shared Postgres access module for everything, with a code-review rule "don't call the Foundry/
investigation-schema bits from here" — rejected in both cases, since a rule that lives only in a
comment is exactly the kind of guarantee this project's own Governance & Security Reference has
repeatedly found "designed correctly, documented confidently, never exercised."

### 11. Defense in Depth (application-layer authorization + data-layer enforcement)
**Where**: `core_api/main.py`'s own explicit checks (`_require_owner`, `_require_program_in_scope`)
running *in addition to*, not instead of, Postgres's own `FORCE ROW LEVEL SECURITY` policy on
`reports` (`tenant_isolation`, set via `SELECT set_config('app.current_tenant_id', ...)` throughout
`human_governance.py`/`pipeline.py`/`cycles.py`). **Problem it solves**: RLS alone only enforces
*tenant*-level isolation; it structurally cannot express "this actor may see program A but not
program B within the same tenant" (see the "looks like a pattern but isn't quite" section below) —
so the application layer's own `authorized_program_ids` check is not redundant with RLS, it covers a
real gap RLS's own policy shape cannot close. **The alternative**: relying on RLS alone and assuming
tenant-level isolation is "enough" — this is close to what actually happened for most of this
project's history (RLS installed since Phase 2, not actually evaluated until Phase 8; see Trade-off
#9) before the program-level gap was identified and closed explicitly in Phase 8.

### 12. Deterministic Rendering, Strictly Separated from Generation
**Where**: `onepulse_common/report_rendering.py` (`render_status_report`/`render_tower_report`) and
`onepulse_common/tower_rollup.py` — neither makes a model call; both take already-generated content
(from `synthesize()`, from Investigation's own findings) and lay it out into a fixed, hard-coded
`.pptx` template. Which of the two renderers runs is itself a deterministic branch
(`build_tower_rollups(...)` empty or not — ADR-012), not a model decision. **Problem it solves**:
FR-5 requires "a locked, per-project visual template" — keeping layout entirely in code makes every
rendered report byte-for-byte reproducible from the same inputs, and keeps a model's own
unreliability (formatting drift, hallucinated structure) out of the one part of the system a
reviewer visually inspects. **The alternative**: asking the Synthesis agent to also produce
formatted slide content, or asking a model to choose the flat-vs-Tower layout — neither was built.

### 13. Constrained (Schema-First) Structured Generation
**Where**: every single real agent call in this codebase passes `default_options={"response_format":
<a real JSON Schema dict>}` — `INVESTIGATION_SCHEMA`, `STATUS_ANALYSIS_SCHEMA`, `SYNTHESIS_SCHEMA`,
`SELF_CRITIQUE_SCHEMA` (all in `pipeline.py`), `CHAT_SCHEMA` (`chat_assistant.py`). **Problem it
solves**: every real caller parses the result with a plain `json.loads(result.text)[...]` and trusts
the shape — structured output makes that trust well-founded instead of hopeful, with no free-text
parsing of a model's own prose anywhere in this codebase. **The alternative**: a raw prompt asking
for "JSON" in natural language and hoping — never used; this is applied with zero exceptions across
five real agents.

### 14. Content-Hash Pinning / Fail-Fast Input Verification
**Where**: `reporting/main.py`'s `_verify_status_deck_integrity` — a real sha256 pin
(`STATUS_DECK_SHA256_BY_PROJECT`) checked before dispatching to Investigation at all. **Problem it
solves**: a real, live incident (Migration Plan Phase 5 follow-up) where a status deck's on-disk
content had silently drifted from what a project-name-to-path mapping assumed, producing a
plausible-looking but wrong report with no error anywhere. A hash pin answers "is this exactly the
file this mapping was reviewed for," which neither a path check nor a text-content heuristic
("does the deck mention its own project name") can — the module's own docstring explains why the
text-heuristic alternative was tried and rejected (the real, correct deck for singleSlide never
contains the string "singleSlide" at all). **The alternative considered and rejected**: a
substring/keyword heuristic on the deck's own text content.

---

## Where the same problem is solved inconsistently

- **Connection ownership for Postgres writes.** Almost every real write path in this codebase
  accepts an already-open `conn: asyncpg.Connection` as a parameter — `human_governance.py`'s
  `approve_report`/`reject_report`, `cycles.py`'s every function — which is what makes the
  transactional-rollback test discipline (`tests/test_human_governance.py`, `tests/test_cycles.py`)
  possible: a test opens one real transaction, calls the function inside it, and rolls back, leaving
  no trace. **`onepulse_common/pipeline.py`'s `persist_report()` is the one real exception**: it
  opens its own brand-new `PostgresClient` internally (`client = await PostgresClient.connect(PG_
  SETTINGS, ...)`) rather than accepting a caller-supplied connection. This is not an oversight
  without a real consequence — it is the direct, structural reason `persist_report()` cannot be
  tested with the same rollback discipline as everything else, and it is why this project's own
  history (CLAUDE.md Tasks 55/56/57) is full of disclosed, permanent, un-rollback-able test rows
  (`report_id` 1199, 1200, 1226, and others) accumulating in the real `reports` table every time this
  specific function gets exercised for real verification — a cost every other real write path in this
  codebase does not pay.
- **The same background-task shape, used for two unrelated purposes, never unified.**
  `onepulse_common/heartbeat.py`'s `heartbeat()` (ticks `on_detail` every ~10s so no gap in the
  status table/log exceeds the project's own "no silent gap" bar) and `investigation/main.py`'s
  `_renew_lease`/`reporting/main.py`'s `_renew_cycle_lease` (tick `queue_client.update_message()`
  every 45s to extend a real Azure Storage Queue visibility lease) are, structurally, the identical
  piece of code: an `asyncio.create_task` running a `while True: await asyncio.sleep(interval); ...`
  loop, cancelled the instant the wrapped work finishes. They exist for genuinely different reasons
  (user-visible progress vs. queue-concurrency control) and arguably should stay conceptually
  separate — but the actual Python (create a background task, sleep-loop, cancel-on-exit,
  `contextlib.suppress(asyncio.CancelledError)`) is written out three separate times
  (`heartbeat.py`, `investigation/main.py`, `reporting/main.py`) rather than built once as a generic
  "cancellable periodic background task" helper the other two compose.
- **The 3-tier Red/Amber/Green health rule, reimplemented three times.** See the Code Map's
  "Anywhere two modules do overlapping things" section for the full detail
  (`status_rollup.compute_overall_status`, `tower_rollup._health`, and the `_CRITICAL_STATUSES`/
  `_FLAGGED_STATUSES` frozensets in `quality_gate.py`/`tower_rollup.py`) — worth a second mention here
  specifically because it's the same *design rule* (a fixed, auditable, no-model-call severity
  ordering — a real, deliberate pattern in its own right, see FR-8) applied three independent times
  rather than expressed once and shared.

---

## Where something looks like a known pattern but isn't quite, or was deliberately not used

- **Row-Level Security looks like it should be "the" authorization mechanism — it structurally isn't
  the whole story, and treating it as such was this project's own real, corrected mistake (Trade-off
  #9).** RLS's `tenant_isolation` policy on `reports` enforces tenant-level isolation only — it has no
  concept of "this actor may see program A within the tenant but not program B." Every real route in
  `core_api/main.py` that scopes by `programId` (`_require_program_in_scope`, and the unfiltered-list
  case in `pipeline.list_recent_reports`) does a second, entirely separate, application-layer check
  against `authorized_program_ids` — not because RLS is broken, but because RLS's own policy shape
  cannot express program granularity at all. A reader who assumes "RLS is on, so authorization is
  handled" would be missing half of the real enforcement, which lives in plain Python conditionals
  a few files away, not in the database.
- **`agent_framework`'s native `MCPStdioTool` was deliberately not used** for either the
  Investigation service's ADO session or Reporting's PPTX session, in favor of the hand-rolled
  `onepulse_common/mcp_bridge.py` adapter (Pattern 7, above). The reasoning is on record in both
  `pipeline.py`'s and `investigate.py`'s own module docstrings: three separate, confirmed
  camelCase-vs-snake_case compatibility bugs were found live in the native client against a real
  `mcp>=2.0` installation, crossing this project's own "stop and report a pattern" threshold rather
  than continuing to patch an unknown remainder.
- **`arize.otel`'s own `register()` convenience function was deliberately not used.** It creates and
  claims its own global `TracerProvider`, which would fight `azure-monitor-opentelemetry`'s
  `configure_azure_monitor()` for ownership of the same global OpenTelemetry state. Every real
  observability setup in this codebase (`onepulse_common/observability.py`, `bff/observability.py`)
  instead adds Arize's own span processors onto the *existing* provider by hand — the reasoning is
  recorded directly in `observability.py`'s own comments.
- **Deterministic orchestration over Connected Agents (ADR-003)** — the example the user already
  named, restated for completeness: Foundry's own dynamic multi-agent routing capability was
  considered for the core pipeline and explicitly rejected in favor of plain, deterministic Python
  calling each real agent in a fixed sequence (`onepulse_common.pipeline.run_reporting_stages`) — and
  the same reasoning was applied a second time, independently, for the Chat Assistant
  (`chat_assistant.py`'s own docstring: "Connected Agents... considered and deliberately not used: a
  single agent with one retrieval tool is the more honest fit for one well-scoped capability").
- **Indexing only the most recent report per program — a real, plausible alternative design,
  considered and explicitly rejected (ADR-029).** `onepulse_common/search_index.py`'s own docstring
  records this directly: LLD Section 2.3 frames the Chat Assistant as an archive, and "how has this
  item's status changed over time" is a real, intended question — so near-duplicate weekly chunks
  are a ranking problem to fix (the real `recency_boost` `FreshnessScoringFunction`), not a reason to
  throw away history at index time.
