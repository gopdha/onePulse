# OnePulse — Current-State Architecture

This document describes what is **actually running today**, superseding the agent-runtime and observability portions of the original Physical/Logical Architecture documents (see Documentation Index for the precise diff), and superseding its own earlier description of a single-user, local-only Streamlit application, now fully retired (Migration Plan Phase 11). See `12_Migration_Plan.md` for the phase-by-phase history of how the system got from there to here, and `11_Deferred_Items_and_Open_Follow_Ups.md` for what remains genuinely open.

---

## 1. Agent Runtime

| Layer | Current Reality |
|---|---|
| **Framework** | Microsoft Agent Framework (migrated from classic `azure.ai.agents.AgentsClient` — see ADR-002) |
| **Model hosting** | Azure-hosted Claude via Foundry (originally intended) and `onePulse-gpt-5-mini` (currently in active use — see ADR-005) |
| **Orchestration** | Deterministic Python, not Connected Agents, for the core pipeline (see ADR-003) |
| **Tool integration** | Manual `mcp.ClientSession` bridge wrapped as `agent_framework.FunctionTool`s, not the native `MCPStdioTool` (see ADR-006) |
| **Process boundary** | Investigation runs as its own real service (`investigation`), not in-process with the rest of the pipeline — see §2 below and ADR-019/020 |

### The Four Core Agents
1. **Investigation** — queries real, deterministically-scoped Committed Features + children via the Azure DevOps MCP server, running inside the `investigation` service
2. **Status Analysis** — parses a real team-lead status deck (`.pptx`), identifies untracked initiatives and possible connections, running inside the `reporting` service
3. **Synthesis** — drafts the executive narrative from Investigation + Status Analysis output, also in `reporting`
4. **Self-Critique** — evaluates the draft against a code-enforced risk floor and a subjective tone/conciseness check, producing one of three outcomes: `approved`, `route_to_human_review`, or `hard_stop_defect`

### Deterministic (Non-LLM) Components
- **Status Rollup** — pure function computing overall RAG status from findings
- **Revision-cap decision logic** — HLD Section 3's three-way branch, entirely code-enforced
- **Rendering** — `.pptx` generation via `python-pptx`, no model call
- **Tower rollup computation** — per-tower completion %, flagged counts, feature health dots

---

## 2. Service Topology — Four Backend Services, One Frontend

The single monolithic pipeline (Phases 0–9's own build history) was split into four real, independently-deployed services over Migration Plan Phases 2–4. What's running today, and what each one is (and is not) allowed to touch:

| Service | Real role | Data access |
|---|---|---|
| **`core_api`** | Owns the domain: every route, every Postgres connection, Foundry, Azure AI Search, Blob Storage, rate limiting, role/tenant resolution | Full — the only service with broad data access |
| **`bff`** | Owns session and identity: Easy Auth cookie sits in front of it, resolves the caller's identity, forwards a real service-to-service Entra token to `core_api`, serves the built React bundle same-origin | **None** — no database, search, Foundry, or blob client of any kind, enforced structurally (`tests/test_bff_no_data_access.py`, static import-graph + adversarial subprocess check), not by convention |
| **`investigation`** | Owns the Azure DevOps MCP server, Node runtime, and the ADO PAT (fetched from Key Vault at request time) | Its own `investigation` Postgres schema only — no access to `public` |
| **`reporting`** | Owns synthesis, self-critique, rendering, and persistence; consumes cycles from a real Azure Storage Queue rather than polling | `public` schema (via `app_role`) — no access to `investigation` |

Coordination is queue-based, not synchronous (ADR-019): `core_api` publishes a cycle onto `report-cycles`; `reporting` claims it, dispatches to `investigation` via `investigation-requests`, and receives the result via `findings-ready`. A killed `investigation` process is recoverable via the queue's own visibility-timeout redelivery (proven live, Migration Plan Phase 4); a killed `reporting` process is, since Migration Plan Phase 3, also queue-driven and redeliverable, and its own resume logic asks `investigation` directly whether the investigation half already completed rather than re-dispatching it (Migration Plan Phase 7 follow-up, ADR-026) — see Runbook §2 for the real, current mechanics.

The real reviewer-facing UI is a React single-page application (Vite + TypeScript + Mantine + TanStack Query, Migration Plan Phase 9), served same-origin by `bff` — see §6.

---

## 3. Persistence — Azure DB for PostgreSQL Flexible Server

- Entra-ID-only authentication (no password auth exists on the server)
- Real per-service Managed Identities as of Migration Plan Phase 6: `app_role` (via `id-onepulse-app-dev`, shared by `core_api`/`reporting`), `investigation_role` (via `id-onepulse-investigation-dev`, `investigation` schema only), plus `app_role_local_dev`/`investigation_role_local_dev` for local development — all now genuinely identical in grant profile to their production counterparts (ADR-023's own finding corrected this; see Data Model & Schema Reference)
- Real, tested guarantees:
  - `UNIQUE(program_id, week_of)` with `week_of` correctly Monday-bucketed, scoped by a partial index (`WHERE NOT is_test_fixture`) so a deliberately forced test run never collides with the real weekly report (Migration Plan Phase 10/CLAUDE.md Task 55)
  - `manifest_complete` as a `GENERATED` column
  - `REVOKE UPDATE, DELETE` on `approval_records` — proven to survive direct attempts, a genuine privilege-escalation workaround attempt, and (ADR-028) a real, structural exemption of the Postgres Entra Administrator via `pg_write_all_data` membership, closed with an ACL-independent `BEFORE UPDATE OR DELETE` trigger
- **`reports`' RLS policy — now genuinely enforcing, not merely installed.** `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + a `tenant_isolation` policy sit on `reports`; as of Migration Plan Phase 8, `core_api` and `reporting` — the only two of the four services that ever touch `reports` — both call `SELECT set_config('app.current_tenant_id', $1, true)` inside every real transaction that reads or writes it, resolved from the caller's real `actor_scope` row via `get_current_actor()`. Proven against a real second tenant (Meridian Health), not the one convenient row this document previously warned against relying on: a visitor scoped to one tenant cannot see the other's reports through the list endpoint, the chat retrieval filter, or a SAS download request. See Trade-off #9 and Governance & Security Reference §3/§6 for the full history of how this guarantee went from "designed, never exercised" to real.

See Data Model & Schema Reference for the full table structure.

---

## 4. Observability — Dual Stack

| System | Role |
|---|---|
| **Azure Application Insights** | Infra-level tracing — token counts, latency, tool-call spans, operation grouping |
| **Arize AX** | Quality-eval-ready tracing via OpenInference span kinds (`AGENT`, `LLM`, `TOOL`) |

Both share one `TracerProvider` per process, built by the one shared `onepulse_common.observability.enable_observability()` function. Each of the four backend services calls it once, at real ASGI `lifespan` startup — not per-request, and not the Streamlit-era `@st.cache_resource` mechanism this document previously described, which no longer exists. A single explicit root span wraps each real unit of work (an HTTP request in `core_api`/`bff`, a queue-consumed cycle in `reporting`, a queue-consumed investigation in `investigation`), and a real W3C `traceparent` is deliberately carried across every process boundary this migration introduced — the HTTP hop between `bff` and `core_api`, and the two queue hops between `reporting` and `investigation` — so Arize shows one connected trace per real user action, not several unrelated siblings. `ONEPULSE_DEBUG_SPAN_LOG` (a shared, bind-mounted JSONL file locally; a per-service log locally and in Container Apps) exists specifically because this project has no Arize Developer Access API key provisioned, so cross-process trace linkage has to be provable from captured span IDs directly rather than read off the Arize UI.

**Known, accepted limitations** (see Challenges & Real-World Findings for full detail):
- A small number of setup-time HTTP spans are skipped by Arize's router (pre-existing, non-fatal, does not affect real agent/tool/LLM span delivery)
- Application Insights drops bare root spans exceeding its custom-dimensions size limit at large scale (data still lands in Arize; this is an Application Insights-specific display gap)
- A cosmetic root-span naming/status quirk can appear in Arize's trace list view even when underlying data is complete and correct

---

## 5. Multi-Project Support

OnePulse supports multiple, independently-configured ADO projects concurrently. As of Migration Plan Phase 1 (CLAUDE.md Task 40), **Agentic AI Observability Platform is the only active test target** — `singleSlide` and `Leave Tracker` are retired as ongoing test targets (they never had proper committed-feature test data) but remain registered, real programs with real historical report rows, still reachable through the product like any other program:
- `singleSlide` — small scope (3 items), flat findings report format
- `Leave Tracker` — small-to-medium scope, seeded with deliberate status variety (Green/Amber/Red/Closed)
- `Agentic AI Observability Platform` — large real scope (465 total items, 115 within Committed-Feature scope, real 3-Epic hierarchy), Tower View report format
- `Meridian Health` (Meridian Patient Portal) — a real, fictional second tenant seeded specifically to prove cross-tenant RLS isolation (Migration Plan Phase 8), not an active demo target

The report format (flat findings vs. Tower View) is selected automatically per project based on whether a real Epic hierarchy exists above the Committed Features — no manual configuration required.

---

## 6. UI — React Frontend

A single-page React application (Vite + TypeScript + Mantine v9 + TanStack Query, Migration Plan Phase 9), served same-origin by `bff` — not a separate deployment, and not the retired Streamlit "Ops Console" this document previously described. No authentication library and no token of any kind reaches browser JavaScript (ADR-018): sign-in happens at the Container Apps ingress via Azure Easy Auth, and the session is an HttpOnly cookie the browser presents automatically.

Two views, matching what an owner and a visitor are each authorized to do (role read from the API via `GET /api/v1/me`, never inferred client-side — hiding a control is usability, `core_api`'s own authorization checks are the actual security boundary):
- **Report table** — project selector (empty by default, nothing loads until a project is picked), recent report history, Approve/Reject for owners, download via the real SAS flow for anyone in scope
- **Generate Status Report** (owner only) — a 7-step progress view driven by polling the real `cycles` status table, all five real terminal outcomes (`persisted`, `persisted_route_to_human_review`, `not_persisted_already_exists`, `hard_stop_defect`, `failed`) rendering distinctly, an owner-only `force` flag for re-running against a week that already has a real report (excluded from all normal views via `is_test_fixture`), and a "Download this report" control reading the just-completed cycle's own `reportId` directly, independent of the report table's fixture filtering
- **Chat** — a RAG-based interface scoped to the currently-selected project, further constrained server-side to the caller's real `authorized_program_ids`

The cold start on first request after scale-to-zero (chained `bff`→`core_api`, ~55.7s measured, Migration Plan Phase 7) is treated as a UX concern, not just an ops one: an honest "waking up" screen with a real per-second elapsed counter, never a fabricated progress bar.

---

## 7. Chat Assistant (RAG)

- Real Azure AI Search index (two-level chunking: report-level summaries, finding-level detail), rebuildable and reconcilable via `scripts/ingest_reports_to_search.py` — the real `reindex` command ADR-022 called for, including a prune step that deletes anything the index holds that Postgres no longer accounts for (ADR-029)
- Agent Framework + `FunctionTool` wrapping real hybrid search queries, with a `recency_boost` scoring profile so a current-status question about an item mentioned across several weekly reports prefers the most recent one rather than treating every week as equally relevant
- Every answer cites real `report_id` and, where applicable, `source_item_ref` — no uncited claims
- The retrieval filter is mandatory and server-side: `core_api` passes the caller's real `authorized_program_ids` (resolved from `actor_scope`, never a client-supplied parameter) unconditionally into every query, so a chunk outside the caller's tenant/program scope is never retrieved, let alone shown to the model — the model cannot leak what it never saw
- Explicitly does not perform live ADO queries — answers only from the persisted report archive (see ADR-008)

---

## 8. Deployment

The four backend services run as real Azure Container Apps (Migration Plan Phase 7), each with its own user-assigned Managed Identity, behind a Container Apps environment with `minReplicas: 0` (scale-to-zero) except where a real, disclosed reason says otherwise. `bff` is the only one with public ingress, gated by Azure Easy Auth; `core_api`, `investigation`, and `reporting` are internal-only, with no public FQDN at all — proven by a real failed external request, not a config screenshot. Images build via `az acr build` into a Basic-tier Azure Container Registry; there is no Infrastructure-as-Code yet (a real, disclosed scope gap, not an oversight) — deployment is a documented sequence of `az` commands (Runbook §7).

Locally, the same four services run via `docker-compose.yml`, authenticating through `DefaultAzureCredential`'s `AzureCliCredential` fallback (real Managed Identity via IMDS is only reachable from genuine Azure compute, confirmed by direct test) — see Runbook §1–2 for the real, current setup and run instructions.

---

## 9. What Remains From the Original Design, Genuinely Unchanged

- The HLD Section 3 revision-cap decision logic (three branches, code-enforced) — the framework executing it, and the process boundary it runs inside, both changed more than once, but the logic itself has not
- The core pipeline sequence: Investigation → Status Analysis → Deterministic Rollup → Synthesis → Self-Critique → Rendering → Persistence
- The zero-static-secrets discipline (Managed Identity throughout; the Azure DevOps PAT remains the one explicitly time-boxed, documented exception — see Governance & Security Reference §1/§4)
- The human-governance requirement (FR-7/FR-13) — every rendered report requires human approval before being considered final
