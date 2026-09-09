# OnePulse — Project Plan (Updated)

This formalizes the live tracker (maintained day-to-day in Google Sheets and `CLAUDE.md`) into a structured document. Status reflects the real, verified state — not aspirational completion.

---

## Phase 0 — Demo Prep
| Task | Status |
|---|---|
| Provision Foundry, deploy models | Done (changed scope — GPT-5-mini, not Claude, due to quota) |
| RBAC setup | Done |
| Bare Foundry Agent Service call | Done |
| Attach real ADO MCP server | Done, with an open item (PAT exception, Entra-ID fix still open) |
| Cost/model-tiering comparison | Cancelled — replaced with generated-report demo |
| Package for real conversation | Done |

## Phase 1 — Repo & Shared Foundation
| Task | Status |
|---|---|
| Postgres client (Managed Identity) | Done — proven live |
| Foundry Agent Service / Agent Framework client | Done |
| Secret-scan CI gate | **Pending** — long-standing small gap |
| Verify original 10x-cost bug cannot recur under new architecture | Open hypothesis — consistent with observations, not formally re-proven |

## Phase 2 — Schema & Migration Tooling
| Task | Status |
|---|---|
| Apply full schema | Done — 6 real mismatches found and fixed via live-data cross-check |
| migrate.py / verify_migration.py | Done — verifier proven via 8 forced-failure tests |
| RLS enforcement | Done (flagged as authorized deviation ahead of original Next-scope timeline) |

## Phase 3 — Investigation & Status Analysis
| Task | Status |
|---|---|
| Investigation Worker | Done — proven at both small (3 items) and large (115-item, deterministically-scoped) real scale |
| Status Analysis Worker + custom PPTX MCP server | Done — real MCP server built from scratch |
| Least-privilege tool scoping | Partially done — not yet formalized against full FR-1/FR-2 spec |
| Deterministic Committed-Feature scoping | Done — real, measured ~5.9x token / ~59% latency reduction at scale |

## Phase 4 — Synthesis & Deterministic Rollup
| Task | Status |
|---|---|
| Synthesis Worker | Done |
| Deterministic Status Rollup | Done |

## Phase 5 — Quality, Revision & Content Safety
| Task | Status |
|---|---|
| Self-Critique Worker | Done |
| Hard-stop regression test | Done — built first, per Build Plan sequencing |
| Revision-cap decision logic | Done — **all three branches proven live** (approved, route_to_human_review, hard_stop_defect) |
| Vacuous-truth bug fix | Done — real regression tests reproducing the exact failure scenarios |
| Citation-format bug fix | Done — verified via two clean first-attempt approvals |
| **Content Safety integration** | **Not started** — the one remaining real gap in this phase |

## Phase 6 — Report Rendering
| Task | Status |
|---|---|
| Deterministic .pptx builder (flat findings format) | Done |
| Tower View executive format | Done — data-driven, automatic fallback for non-hierarchical projects |
| Rendered-artifact persistence | Done |
| Real download from UI | Done |

## Phase 7 — Human Governance API
| Task | Status |
|---|---|
| Approve / Reject endpoints | Done |
| Reviewer attribution | Done, with an honest, explicitly-flagged placeholder identity mechanism |
| Append-only enforcement | Done — the most rigorously stress-tested guarantee in the project (3 real attack vectors) |

## Chat Assistant (RAG) — Pulled Forward from Later-Scope
| Task | Status |
|---|---|
| Azure AI Search infrastructure | Done — stood up from scratch |
| Two-level chunking + real citations | Done |
| Proven both directions (answer + honest "not found") | Done |
| Scoped to selected project only | Done |

## Phase 8 — End-to-End Orchestration
| Task | Status |
|---|---|
| Single-command pipeline with real persistence | Done |
| Connected Agents NOT used for core pipeline | Design decision, confirmed correct |
| One real, live, unattended run | Done, with the caveat that review and chat remain separate manual steps |

## Observability
| Task | Status |
|---|---|
| Application Insights integration | Done |
| Arize integration (OpenInference) | Done — required a real SDK migration (Agent Framework) |
| Root-span grouping | Done, re-verified under threaded architecture |
| Flush-on-exit bug | Found and fixed |
| Cosmetic root-span display quirk | Investigated in depth; accepted, non-fatal limitation |

## UI (Streamlit)
| Task | Status |
|---|---|
| Full Ops Console redesign | Done, multiple real bugs found and fixed via live screenshot review |
| Multi-project support | Done |
| Minimal 7-step progress view + full log file split | Done |
| Threading + cancellation guarantee re-verification | Done — honest, corrected framing documented |

---

## Real, Open Follow-Up Items

| Item | Status |
|---|---|
| Entra-ID identity duality for `gopdha` ADO org | **Open, real blocker** — PAT remains the working exception |
| Revoke the diagnostic PAT | **Open** — check real expiry status |
| Claude quota/model decision | **Open** — currently on GPT-5-mini by necessity |
| Content Safety integration | **Not started** |
| Secret-scan CI gate | **Pending** |
| Azure Static Web Apps deployment | **Open** — deliberate Next-scope, UI proven locally first |
| Full least-privilege formalization against FR-1/FR-2 | **Partially done** |
| Multi-deck ingestion for Status Analysis | **Open** — deliberately deferred, two real decks prepared but only one used |
| Real auth for reviewer identity | **Open** — explicitly flagged placeholder today |
