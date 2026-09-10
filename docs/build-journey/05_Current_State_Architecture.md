# OnePulse — Current-State Architecture

This document describes what is **actually running today**, superseding the agent-runtime and observability portions of the original Physical/Logical Architecture documents (see Documentation Index for the precise diff).

---

## 1. Agent Runtime

| Layer | Current Reality |
|---|---|
| **Framework** | Microsoft Agent Framework (migrated from classic `azure.ai.agents.AgentsClient` — see ADR-002) |
| **Model hosting** | Azure-hosted Claude via Foundry (originally intended) and `onePulse-gpt-5-mini` (currently in active use — see ADR-005) |
| **Orchestration** | Deterministic Python, not Connected Agents, for the core pipeline (see ADR-003) |
| **Tool integration** | Manual `mcp.ClientSession` bridge wrapped as `agent_framework.FunctionTool`s, not the native `MCPStdioTool` (see ADR-006) |

### The Four Core Agents
1. **Investigation** — queries real, deterministically-scoped Committed Features + children via the Azure DevOps MCP server
2. **Status Analysis** — parses a real team-lead status deck (`.pptx`), identifies untracked initiatives and possible connections
3. **Synthesis** — drafts the executive narrative from Investigation + Status Analysis output
4. **Self-Critique** — evaluates the draft against a code-enforced risk floor and a subjective tone/conciseness check, producing one of three outcomes: `approved`, `route_to_human_review`, or `hard_stop_defect`

### Deterministic (Non-LLM) Components
- **Status Rollup** — pure function computing overall RAG status from findings
- **Revision-cap decision logic** — HLD Section 3's three-way branch, entirely code-enforced
- **Rendering** — `.pptx` generation via `python-pptx`, no model call
- **Tower rollup computation** — per-tower completion %, flagged counts, feature health dots

---

## 2. Data Investigation Scope

Investigation's real scope is deterministically computed **before any agent runs**:
1. Query ADO for Features tagged `Committed` in the target project
2. Query each Committed Feature's real children via `System.Parent`
3. Investigate only this filtered set

If a project has zero Committed Features, the system produces an honest "no committed features found" result — there is no fallback to full-project investigation.

---

## 3. Persistence — Azure DB for PostgreSQL Flexible Server

- Entra-ID-only authentication (no password auth exists on the server)
- Two application roles: `app_role` (production/workload identity) and `app_role_local_dev` (local development, group-mapped)
- Real, tested guarantees:
  - `UNIQUE(program_id, week_of)` with `week_of` correctly Monday-bucketed
  - `manifest_complete` as a `GENERATED` column
  - `REVOKE UPDATE, DELETE` on `approval_records` — proven to survive direct attempts and a genuine privilege-escalation workaround attempt (see Governance & Security Reference)
- **`reports`' RLS policy — corrected 2026-09-10, was never a tested guarantee, contrary to how this document previously described it.** `ENABLE ROW LEVEL SECURITY` + a `tenant_isolation` policy are genuinely present on `reports`, built ahead of the originally Next-scope timeline as stated — but every role that has ever queried this table (`app_role_local_dev`, until Task 44) also owned it, and Postgres exempts an owner from its own RLS policy by default. The policy had never actually been evaluated. It ran for the first time as an incidental side effect of a retroactive ownership fix (ADR-023) and was found broken (`current_setting('app.current_tenant_id')` called with no `missing_ok` flag against a GUC nothing in this codebase has ever set) — fixed to be permissive when unset, matching Now-scope's real single-tenant state. `FORCE ROW LEVEL SECURITY` is now also enabled, closing a second, direct consequence of the same ownership fix (`app_role`, the real production role, had just become the table's new owner and would otherwise have been exempt from the very policy meant to constrain it). **Read this precisely: FORCE makes the policy un-bypassable by ownership once it enforces something — it does not make it enforce anything today.** Nothing in this codebase yet sets `app.current_tenant_id` on any real request, so the permissive-when-unset branch is what is actually active. **Current, honest state: the policy exists, is syntactically correct, and can no longer be bypassed by ownership — tenant isolation itself does not yet do anything.** Real enforcement is deliberately deferred to Phase 8's `get_current_actor()` work, not something this system currently has. See Trade-off #9 and Governance & Security Reference §3/§6 for the full account.

See Data Model & Schema Reference for the full table structure.

---

## 4. Observability — Dual Stack

| System | Role |
|---|---|
| **Azure Application Insights** | Infra-level tracing — token counts, latency, tool-call spans, operation grouping |
| **Arize AX** | Quality-eval-ready tracing via OpenInference span kinds (`AGENT`, `LLM`, `TOOL`) |

Both share one `TracerProvider`, wrapped in `@st.cache_resource` in the UI to avoid re-initialization on every Streamlit rerun. A single explicit root span (`onepulse_pipeline_run` / `onepulse_ui_pipeline_run`) wraps each full execution, propagated correctly across the UI's background-thread execution via `contextvars.copy_context()`.

**Known, accepted limitations** (see Challenges & Real-World Findings for full detail):
- A small number of setup-time HTTP spans are skipped by Arize's router (pre-existing, non-fatal, does not affect real agent/tool/LLM span delivery)
- Application Insights drops bare root spans exceeding its custom-dimensions size limit at large scale (data still lands in Arize; this is an Application Insights-specific display gap)
- A cosmetic root-span naming/status quirk can appear in Arize's trace list view even when underlying data is complete and correct

---

## 5. Multi-Project Support

OnePulse supports multiple, independently-configured ADO projects concurrently:
- `singleSlide` — small scope (3 items), flat findings report format
- `Leave Tracker` — small-to-medium scope, seeded with deliberate status variety (Green/Amber/Red/Closed)
- `Agentic AI Observability Platform` — large real scope (465 total items, 115 within Committed-Feature scope, real 3-Epic hierarchy), Tower View report format

The report format (flat findings vs. Tower View) is selected automatically per project based on whether a real Epic hierarchy exists above the Committed Features — no manual configuration required.

---

## 6. UI — Streamlit "Ops Console"

A single-page application, not a multi-page app:
- Project selector (empty by default — no eager loading)
- Report table: latest run pinned, 3 most recent history rows, Approve/Reject actions with a database-enforced empty-notes-blocked rejection flow
- Generate Status Report: a minimal, curated 7-step progress view with live-ticking timers and real computed per-step summaries; full technical detail relocated to a real log file
- Status Report Assistant: a RAG-based chat interface scoped to the currently-selected project's persisted reports only

Real observability is wired into both the pipeline-trigger and chat-query code paths.

---

## 7. Chat Assistant (RAG)

- Real Azure AI Search index (two-level chunking: report-level summaries, finding-level detail)
- Agent Framework + `FunctionTool` wrapping real hybrid search queries
- Every answer cites real `report_id` and, where applicable, `source_item_ref` — no uncited claims
- Explicitly does not perform live ADO queries — answers only from the persisted report archive (see ADR-008)

---

## 8. What Remains From the Original Design, Genuinely Unchanged

- The HLD Section 3 revision-cap decision logic (three branches, code-enforced) — the framework executing it changed twice, but the logic itself has not
- The core pipeline sequence: Investigation → Status Analysis → Deterministic Rollup → Synthesis → Self-Critique → Rendering → Persistence
- The zero-static-secrets discipline (Managed Identity throughout, no API keys, no passwords)
- The human-governance requirement (FR-7/FR-13) — every rendered report requires human approval before being considered final
