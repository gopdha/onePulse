# OnePulse — Project Plan (Updated)

The authoritative status ledger for every task across both the original Build Plan (Phases 0–8) and
the Migration Plan (Phases M0–M11, prefixed `M` so the two numbering schemes never collide). Status
reflects the real, verified state as of when each row was last brought current — not aspirational
completion.

**What this document is not**: it does not say what to do about anything that isn't `Done` — that's
`11_Deferred_Items_and_Open_Follow_Ups.md`, cross-referenced per row below rather than restated here.
It does not describe the system's current architecture either — that's `05_Current_State_
Architecture.md`. This document answers exactly one question: what state is each real piece of work
actually in.

Last brought current 2026-09-13 (Migration Plan Phase 11).

---

## Original Build Plan (Phases 0–8)

### Phase 0 — Demo Prep
| Task | Status |
|---|---|
| Provision Foundry, deploy models | Done (changed scope — GPT-5-mini, not Claude, due to quota; see Trade-off #1, still open) |
| RBAC setup | Done |
| Bare Foundry Agent Service call | Done |
| Attach real ADO MCP server | Done. **The PAT exception's own handling changed materially during the migration**: as of Migration Phase M6, the PAT is stored in Key Vault and fetched at request time by the Investigation service's identity only — no longer a plain env var anywhere. The underlying Entra-ID tenant-duality issue that made the PAT necessary in the first place is unchanged and still open (Trade-off #2) |
| Cost/model-tiering comparison | Cancelled — replaced with generated-report demo |
| Package for real conversation | Done |

### Phase 1 — Repo & Shared Foundation
| Task | Status |
|---|---|
| Postgres client (Managed Identity) | Done — proven live |
| Foundry Agent Service / Agent Framework client | Done |
| Secret-scan CI gate | Not started — no CI pipeline exists yet to wire it into |
| Verify original 10x-cost bug cannot recur under new architecture | Open hypothesis — consistent with observations, not formally re-proven |

### Phase 2 — Schema & Migration Tooling
| Task | Status |
|---|---|
| Apply full schema | Done — 6 real mismatches found and fixed via live-data cross-check |
| migrate.py / verify_migration.py | Done — verifier proven via forced-failure tests, now 124/124 real checks |
| RLS enforcement | **Two distinct milestones, not one — this row originally described only the first.** Installed ahead of the original Next-scope timeline (a real, authorized deviation): the policy existed, syntactically correct, but was never actually evaluated (every role that queried `reports` also owned it) — a real, later-discovered gap (ADR-023), not something this row knew about when first written. **Actually enforcing as of Migration Phase M8**: `get_current_actor()` resolves the caller's real tenant and `SET LOCAL app.current_tenant_id` runs inside every transaction that touches `reports`, proven against a real second tenant (Meridian Health), not one convenient row. See Trade-off #9 for the full corrected history |

### Phase 3 — Investigation & Status Analysis
| Task | Status |
|---|---|
| Investigation Worker | Done — proven at both small (3 items) and large (115-item, deterministically-scoped) real scale; extracted into its own real service as of Migration Phase M4 |
| Status Analysis Worker + custom PPTX MCP server | Done — real MCP server built from scratch |
| Least-privilege tool scoping | Partially done — not yet formalized against full FR-1/FR-2 spec (see Deferred Items) |
| Deterministic Committed-Feature scoping | Done — real, measured ~5.9x token / ~59% latency reduction at scale |
| Multi-deck ingestion for Status Analysis | Open, deliberately deferred (Trade-off #14) — two real decks prepared, only one used as live pipeline input |

### Phase 4 — Synthesis & Deterministic Rollup
| Task | Status |
|---|---|
| Synthesis Worker | Done |
| Deterministic Status Rollup | Done |

### Phase 5 — Quality, Revision & Content Safety
| Task | Status |
|---|---|
| Self-Critique Worker | Done |
| Hard-stop regression test | Done — built first, per Build Plan sequencing |
| Revision-cap decision logic | Done — all three branches proven live (approved, route_to_human_review, hard_stop_defect) |
| Vacuous-truth bug fix | Done — real regression tests reproducing the exact failure scenarios |
| Citation-format bug fix | Done — verified via two clean first-attempt approvals |
| Content Safety integration | Not started — the one remaining real gap in this phase (see Deferred Items) |

### Phase 6 — Report Rendering
| Task | Status |
|---|---|
| Deterministic .pptx builder (flat findings format) | Done |
| Tower View executive format | Done — data-driven, automatic fallback for non-hierarchical projects |
| Rendered-artifact persistence | Done — a real `blob://` URI as of Migration Phase M10 (previously `file://`, a real gap closed live) |
| Real download from UI | Done — via a short-lived SAS URL as of the migration (Phases M7/M9), not the original Streamlit `file://` read |

### Phase 7 — Human Governance API
| Task | Status |
|---|---|
| Approve / Reject endpoints | Done |
| Reviewer attribution | **Done, but not the way this row originally described.** Originally an honest, explicitly-flagged placeholder identity (a fixed stand-in actor, no real session). **Replaced with real Entra-based identity resolution as of Migration Phase M8** — `get_current_actor()` resolves the platform-verified caller against `actors.entra_object_id`; no client-supplied `actor_id` is ever trusted |
| Append-only enforcement | Done — the most rigorously stress-tested guarantee in the project, now proven against four real attack vectors including a structural admin-privilege exemption (ADR-028) |

### Phase 8 — End-to-End Orchestration
| Task | Status |
|---|---|
| Single-command pipeline with real persistence | Done |
| Connected Agents NOT used for core pipeline | Design decision, confirmed correct |
| One real, live, unattended run | Done — superseded in shape by Migration Phase M3/M4, which moved this off any single command entirely into a queue-driven worker chain |

### Chat Assistant (RAG) — Pulled Forward from Later-Scope
| Task | Status |
|---|---|
| Azure AI Search infrastructure | Done — stood up from scratch |
| Two-level chunking + real citations | Done |
| Proven both directions (answer + honest "not found") | Done |
| Scoped to selected project only | Superseded — as of Migration Phase M8, scoping is mandatory and server-side (`authorized_program_ids`, resolved from the caller's real tenant/role), not merely a UI-selected project filter |

### Observability
| Task | Status |
|---|---|
| Application Insights integration | Done |
| Arize integration (OpenInference) | Done — required a real SDK migration (Agent Framework) |
| Root-span grouping | Done, re-verified under threaded architecture, then again across every process boundary the migration introduced (Migration Phases M2–M4) |
| Flush-on-exit bug | Found and fixed |
| Cosmetic root-span display quirk | Investigated in depth; accepted, non-fatal limitation |

### UI — Streamlit (retired, see Migration Phase M11 below)
| Task | Status |
|---|---|
| Full Ops Console redesign | Done, multiple real bugs found and fixed via live screenshot review |
| Multi-project support | Done |
| Minimal 7-step progress view + full log file split | Done |
| Threading + cancellation guarantee re-verification | Done — honest, corrected framing documented |

This entire client no longer exists in the repository — removed outright, not left dormant, per
Migration Phase M11. See Current-State Architecture §6 for its real replacement.

---

## Migration Plan (Phases M0–M11)

Governed by ADR-015 through ADR-031; the full per-phase Definition of Done and evidence trail lives
in `12_Migration_Plan.md` — this table is the concise status ledger, not a restatement of it.

### M0 — Prerequisites
| Task | Status |
|---|---|
| Close out in-flight pre-migration hardening (`week_of` check, tag-stripping, MCP version pin, completion logging, spotlighting audit) | Done |
| Confirm a clean end-to-end run on AOP at reduced scope | **Not achieved** — no safe way was ever found to reduce AOP's real Committed-Feature tag scope in this ADO org (see M4/M5 below); every real verification through the rest of the migration used the full 115-item scope instead |
| Unit coverage for ADR-012's report-format selection | Done — `tests/test_tower_view_selection.py` |
| Seed a genuine second tenant before Phase M8 | Done — Meridian Health, a real portfolio/program/actors/actor_scope |
| Resolve the test-fixture pollution in `reports` | Done — transactional rollback in the test suite plus a real `is_test_fixture` column excluding historical debris from every real view |
| Append ADR-015–022; amend ADR-010; update Trade-offs Log entries 5/6/12 | Done |
| Commit `docs/build-journey/` to the repository | Done |
| Decide what data external visitors will see | Not recorded as an explicit decision — in practice, no real client names appear in any indexed or demoed content |

### M1 — FastAPI, single service, behind existing Streamlit
| Task | Status |
|---|---|
| LLD §10.2 endpoint contract (trigger, pending reviews, approve, reject, chat) | Done |
| Streamlit rewired to call endpoints instead of importing `onepulse_common` directly | Done (superseded by M11 — Streamlit no longer exists) |
| Empty-notes rejection refused at the database level, not only Pydantic | Done — a real CHECK constraint |

### M2 — Split into BFF and core API
| Task | Status |
|---|---|
| BFF: session/identity/response-shaping only, zero data-store access | Done — enforced structurally (`tests/test_bff_no_data_access.py`), not by convention |
| Core API: domain, every data connection, dispatch | Done |
| Service-to-service auth via a real Entra token, not a shared secret | Done |
| ADR-017's open question (who resolves the actor) | Decided and built — the core API resolves identity from the header the BFF forwards |
| One connected Arize trace across the HTTP hop, real span IDs | Done |

### M3 — Separate pipeline execution, add the status table
| Task | Status |
|---|---|
| Pipeline moved into a worker, not a request or UI process | Done |
| `cycles` status table, real terminal outcomes, written during long stages | Done |
| ADR-009's `threading.Event`/`contextvars` plumbing retired | Done |
| Observability moved to application lifespan | Done |

### M4 — Split Investigation from Reporting, coordinated by a queue
| Task | Status |
|---|---|
| Investigation service: ADO MCP, Python+Node, its own schema/role | Done |
| Reporting service: synthesis/self-critique/rendering/persistence | Done — itself made queue-driven, not just a poller, in a Phase M7 follow-up |
| Two named queues, results keyed on `cycle_id`, dequeue-limit/dead-letter | Done |
| Reporting fetches findings over HTTP only — proven adversarially | Done |
| Kill-mid-run recovery via queue redelivery | Done, proven live, twice |
| Verify at reduced scope, then full scope | Reduced-scope leg not performed (see M0) — full-scope runs used as the load-bearing case throughout |

### M5 — Containerize, locally
| Task | Status |
|---|---|
| Four real Dockerfiles — Investigation carries Python+Node, others Python-only | Done |
| `docker-compose.yml` as the real process-shape source of truth | Done |
| Logs moved to stdout (container filesystems are ephemeral) | Done |
| Reduced-then-full-scope verification | Same reduced-scope gap as M4 — full scope only |

### M6 — Managed Identity, replacing `az login`
| Task | Status |
|---|---|
| Per-service Managed Identity; real RBAC on Foundry/Search/Storage/Key Vault | Done, live-verified by direct query, not merely configured |
| ADO PAT moved to Key Vault, reachable only by Investigation's identity | Done |
| A literal zero-interactive-credential run | **Deferred to M7 by explicit decision** (ADR-024) — structurally unreachable from local containers, since IMDS is only reachable from genuine Azure compute |

### M7 — Deploy to Azure Container Apps, ingress restricted
| Task | Status |
|---|---|
| ACR, Container Apps environment, four real container apps | Done |
| BFF external; core API/Reporting/Investigation internal-only | Done, proven by a real failed external request, not a config screenshot |
| Real Managed Identity auth proven end to end (no shared credential) | Done |
| Real cold-start measured | Done — ~55.7s chained `bff`→`core_api`; ~50s for Investigation |
| Real cost reported | Done — see M11 follow-up for the revised, lower figure once `reporting` became queue-driven |

### M8 — Real reviewer identity and the role model
| Task | Status |
|---|---|
| `get_current_actor()` resolving a real Entra identity, never client-supplied | Done |
| Owner/visitor roles enforced in `core_api` | Done |
| RLS on `reports` actually enforcing | Done — proven against a real second tenant, not one convenient row |
| No-`actors`-row case returns a clean 403 | Done |
| Provisioning path written down and exercised for real | Done |
| FR-11 rate limit (2/day) enforced | Done — currently overridden to 10 on the deployed environment for testing (see Deferred Items) |
| Public ingress opened | Done, 2026-09-11, as its own distinct final action after every guarantee above passed |

### M9 — React frontend
| Task | Status |
|---|---|
| Vite+React+TypeScript+Mantine+TanStack Query; no auth library, no token in JS | Done |
| Feature parity with the Ops Console for an owner | Done, verified against the deployed backend |
| Real interactive sign-in completed | Done — two real Entra misconfigurations found and fixed along the way (ADR-025/030) |
| All real terminal outcomes rendering distinctly | Done |
| Real SAS download from the browser; real chat answer with citations | Done |
| A real signed-in visitor session exercised through the actual UI | **Not done — deferred until every other phase is complete** (ADR-031); every server-side boundary a visitor session depends on is proven independently, by direct request, regardless of what the UI renders (see Deferred Items) |

### M10 — Serve the frontend
| Task | Status |
|---|---|
| Same-origin serving via `bff` (`StaticFiles` mount) | Done — pulled forward into M9 once Easy Auth's CORS interception forced the question early |
| A real end-to-end run and download via a browser, on a device that is not the development machine | Done, 2026-09-13 — real evidence: `report_id=1226` |

### M11 — Retire Streamlit and update the record
| Task | Status |
|---|---|
| Streamlit removed outright (`Home.py`, `api_client.py`, `streamlit_app_common.py`, `.streamlit/`, the dependency) | Done |
| Runbook and Current-State Architecture brought current | Done |
| Trade-offs Log entries 5/6/12 marked resolved/superseded | Done — already true from earlier migration-phase work by the time this phase checked |
| Real `reindex` command (ADR-022) | Done — found already built (Task 50); two real live bugs found and fixed while confirming it (a listing-cap overflow, a Free-tier storage-quota wall) |
| Every open item consolidated into one document | Done — `11_Deferred_Items_and_Open_Follow_Ups.md` |

---

For what to do about anything above that isn't `Done`, see `11_Deferred_Items_and_Open_Follow_Ups.md`
— it intentionally does not restate status, only current state (where needed for context) and a
concrete next step. For what the system actually looks like today, see `05_Current_State_
Architecture.md`.
