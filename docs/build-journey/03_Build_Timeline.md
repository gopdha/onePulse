# OnePulse — Build Timeline

A chronological narrative of the real build, from initial design through the current state. Task numbers reference the detailed log maintained in `CLAUDE.md`.

---

## Phase 0 — Foundation & POC (singleSlide_demo)
- Built `singleSlide_demo`: 11 components, all live-verified, using Claude Agent SDK calling Anthropic's API directly.
- Found and fixed the original 10x cost bug (see Challenges #1) — real cost reduced from $2.83 to $1.62/run.
- Established Arize/OpenTelemetry observability as a first-class concern from the start.

## Phase 1 — Full Enterprise Design (10-step design process)
- Produced the complete original design document set: PRD + Addendum, MVP Prioritization, Solution/Conceptual/Logical/Physical Architecture, HLD, LLD, DevOps Setup, Build Plan, Product Discovery & Adoption Plan, Technical Assessment.
- Key early decisions: Neon Postgres (later revised — ADR-011), Claude Agent SDK as the agent runtime (later revised — ADR-001/002), AKS/Container Apps as the compute target.

## Phase 2 — Infrastructure Provisioning
- Azure resource group, Postgres Flexible Server (Entra-ID-only), Managed Identity, local-dev Entra security group.
- Real bootstrap: `app_role` and `app_role_local_dev` created, live Postgres connection proven for the first time via `az login`-based Managed Identity.

## Phase 3 — Career/Learning Pivot Discussion
- AI-103 certification identified as the relevant, current Microsoft credential (successor to the retired AI-102), specifically covering Foundry, agentic solutions, and RAG — directly aligned with this project's real work.
- Deliberate decision: migrate toward Foundry Agent Service, reasoned as *more* aligned with the learning goal than staying on Claude Agent SDK, not a compromise.

## Phase 4 — Foundry Agent Service Adoption & First Real Blocker
- Real quota exhaustion hit on Claude Sonnet 5 and Haiku 4.5 in the default region — diagnosed via Azure's quota dashboard, revealing Claude isn't even on the standard Azure OpenAI quota page.
- Pivoted through `gpt-5.4-mini` (found to have a real Agent Service support gap) to `gpt-5-mini` (confirmed supported) under real time pressure ahead of an AT&T stakeholder conversation.
- **Task 3 — Go/no-go checkpoint**: First real Foundry Agent Service call succeeded. Found and fixed a real API-generation mismatch (`AIProjectClient.agents` vs. classic `azure.ai.agents.AgentsClient`).

## Phase 5 — Real ADO Integration & the Identity Saga
- **Task 4**: Built the FunctionTool-to-MCP bridge (Option 1 — client-side, not hosted toolboxes). Proved the mechanism, then hit the full Azure DevOps tenant-duality identity crisis (see Challenges #2) — four real attempts, no full convergence, resolved via a scoped, time-boxed PAT.
- First genuinely grounded, non-hallucinated agent output achieved: a real `TF400813` authorization error correctly surfaced as an honest diagnostic rather than fabricated findings.

## Phase 6 — AT&T Demo Prep (Real Deadline Pressure)
- Explicit scope change: dropped the originally-planned cost/model-tiering comparison in favor of a real, generated status report demo.
- Built, under real time pressure: Synthesis worker, Deterministic Status Rollup, `.pptx` Rendering — all working end to end.
- Deliberately, honestly **not** built for the deadline: Self-critique/revision loop, Human Governance approval gate — stated plainly rather than faked.

## Phase 7 — Full Pipeline: Self-Critique, Observability, and the Complete Chain
- Self-critique agent and the hard-stop regression test built (test written *before* the agent, per Build Plan's own sequencing discipline).
- Real, live proof of all three revision-cap branches: `approved`, `route_to_human_review`, and (later, at scale) `hard_stop_defect`.
- Full dual observability stood up: Application Insights (infra-level tracing) and, after a real SDK migration (ADR-002), Arize (OpenInference quality-eval-ready spans).
- **First full real end-to-end proof**: live investigation → persistence → appears in `review_cli.py pending` → indexed → correctly answered by `chat_cli.py`, citing that exact run.

## Phase 8 — Database Schema, Governance, and Real Data Cross-Checks
- Postgres schema applied for the first time — but only after a real cross-check against actual live agent output revealed six real mismatches against the original LLD design (dropped speculative `curated_features`/`curated_initiatives`; added `quality_gate_outcome` to capture the already-proven three-way revision-cap decision).
- Real `REVOKE UPDATE, DELETE` on `approval_records` proven live via a genuine `InsufficientPrivilegeError`.
- Human Governance API built as plain async functions (`approve_report`, `reject_report`, `list_pending_reviews`) with a real, deliberately-flagged placeholder for reviewer identity (no full auth system, stated honestly).

## Phase 9 — Chat Assistant (Pulled Forward from "Later")
- Real Azure AI Search infrastructure stood up from scratch (Free tier, RBAC-only, no static keys).
- Two real SDK bugs found and fixed via direct research (an `EmbeddingsClient` endpoint mismatch; a `SearchFieldDataType` enum-to-string bug in a new major SDK version).
- Proven in both directions: a correct, cited answer to an answerable question, and an honest "not found" to an unanswerable one.

## Phase 10 — Full Pipeline Persistence & the Week-Uniqueness Bug
- `run_pipeline.py` wired to persist real output to Postgres for the first time as its final stage.
- Real bug found and fixed: `week_of` was never actually bucketed to a Monday, despite a correct helper already existing elsewhere in the codebase (see Challenges #5).

## Phase 11 — UI Build (Streamlit)
- Initial three-page UI (Home/Review/Chat), then a full single-page redesign (per a Claude Design reference, the "Ops Console" layout).
- Multiple real, live-discovered bugs fixed along the way: a Streamlit duplicate-element-key crash silently killing multi-stage console captures; a checkmark/status-icon contradiction on hard-stop outcomes; a real CSS contrast bug traced to a Streamlit internal wrapper div; a column-width regression causing text overflow.
- Real multi-project support added (`singleSlide`, `Leave Tracker`, `Agentic AI Observability Platform`), including a deliberate architecture decision to scope the whole page (including chat) to one selected project at a time.

## Phase 12 — Scale Stress Test & the Deterministic Scoping Fix
- Real 465-item ADO project used as an honest stress test (not a curated demo) — revealed the flat "investigate everything" approach was both non-deterministic and impractical at scale (see Challenges #6/#7 in the ADR, and Challenges #3/#4 in this document).
- Fixed via deterministic Committed-Feature scoping (ADR-007) plus the vacuous-truth and citation-format fixes (Challenges #3/#4) — real, measured ~5.9x token and ~59% latency reduction, with correctness genuinely solved, not just cost.

## Phase 13 — Threading, Live-Ticking UI, and the Cancellation Guarantee Re-Verification
- Redesigned the Generate Status Report console: full technical detail relocated to a real log file, UI reduced to a clean, minimal 7-step view with real computed numbers and live-ticking timers.
- A real architectural conflict was surfaced and resolved (ADR-009): background threading for smooth ticking, with new explicit cancellation plumbing, re-verified with the same rigor as the original single-threaded guarantee.

## Phase 14 — Executive Reporting: Tower View
- Designed and built a second, business-language report format for projects with real Epic/Feature hierarchy — computed entirely deterministically (per-tower completion %, flagged-item counts), with a graceful, automatic fallback to the original flat-findings format for projects without real hierarchy.
- Real bug found during verification: a stray legacy parent link was incorrectly triggering the new format for `singleSlide` — fixed by requiring the real `WorkItemType == "Epic"` check.

## Phase 15 — Real Data Preparation, First Real Push to GitHub, Governance Stress Test
- Prepared real, curated team-lead status decks against the actual Agentic AI Observability Platform ADO data (2 team leads, natural Tower-based split), each deliberately including real tracked references, one genuinely untracked initiative, and one deliberately ambiguous "possible connection."
- First real push of the entire implementation to GitHub — discovered a pre-existing repo with only the original docs ever committed; verified `.gitignore` and `.env` history before pushing the full real build.
- The append-only guarantee stress-tested three separate ways during an attempted test-data cleanup (see Challenges #6) — the single most rigorous validation of any guarantee in the project.

---

## Where This Leaves Things
As of this document, the system has a real, live-verified, end-to-end pipeline (Investigation → Status Analysis → Deterministic Rollup → Synthesis → Self-Critique/Revision → Rendering → Persistence), a working multi-project UI, a RAG-based Chat Assistant, dual observability, and a business-facing executive report format — running against genuinely real ADO data at both small and large scale. See the Project Plan (Updated) for the precise current status of every phase, and the Trade-offs Log for what remains deliberately open.
