# OnePulse Documentation Index & Supersession Notes

## Purpose
This index maps the **original design documents** (created early in the project — PRD, HLD, LLD, Architecture set) against the **real, built, and verified system** as it exists today. It exists because the original documents describe *intended* design, and a substantial amount of real engineering — including several deliberate pivots — happened after they were written. Rather than silently letting the original documents go stale, this note says explicitly what's still true, what's superseded, and where to look for the current answer.

> **Honest limitation**: this session does not have direct file access to the original `.docx` documents (PRD, HLD, LLD, Architecture set) to edit them in place — they were created in an earlier session. This index substitutes for that edit by telling you exactly what in them is now stale.

---

## Original Documents — Status

| Document | Still Valid | Now Stale / Superseded By |
|---|---|---|
| **PRD + PRD Addendum** | Core FRs/NFRs, MVP scope philosophy, human-governance requirement (FR-7/FR-13) | Nothing structurally overturned — see Trade-offs Log for scope additions (Chat Assistant pulled forward, Tower View added) |
| **MVP Prioritization** | Now/Next/Later framing | Chat Assistant (originally "Later") was pulled forward and fully built — see Build Timeline |
| **Solution Architecture (Simple)** | High-level pipeline shape (Investigation → Synthesis → QA → Render → Approve) | Agent runtime specifics — see Current-State Architecture |
| **Conceptual Architecture** | Largely still valid at the conceptual level | — |
| **Logical Architecture** | Layer structure (Sources/Ingestion/Agent Runtime/Data/Presentation) | "Agent Runtime" layer — see Current-State Architecture for what's actually there now |
| **Physical Architecture** | VNet/boundary/private-endpoint intent, single-egress security posture | **Three real corrections**: (1) Neon Postgres → Azure DB for PostgreSQL Flexible Server (Managed Identity requirement); (2) the Anthropic API egress path was removed entirely once Azure-hosted Claude was confirmed to keep inference inside Azure — see ADR-013; (3) the specified AKS compute target is itself now superseded — the real deployment target is Azure Container Apps, and the original single-service shape is being split into a BFF, core API, and two workers — see ADR-016/017/019/020 and the Migration Plan |
| **High-Level Design (HLD)** | Section 3's revision-cap decision logic (approved / route_to_human_review / hard_stop_defect) — this logic is unchanged and has been proven live in all three branches | The *framework* executing this logic changed twice — see ADR-001, ADR-002 |
| **Low-Level Design (LLD)** | Most schema intent; §10.2's server-side scope-resolution requirement for the Chat Assistant | Real schema deviates in specific, tested ways — see Data Model & Schema Reference for the exact diff. §10.2's endpoint contract is not yet implemented but is not new design work either — ADR-015/022 point back to it as the real spec for the endpoints the migration builds |
| **DevOps Setup** | CI/CD gate philosophy | Actual bootstrap sequence differed in real, documented ways (see Challenges doc — the ADO identity saga, the Postgres role bootstrap) |
| **Build Plan** | 8-phase structure, Now/Next scoping discipline | See Project Plan (Updated) for current per-phase status. A **second**, later-scope phase sequence was layered on top of it — the Migration Plan (React/FastAPI/Container Apps/microservices), governed by ADR-015 through ADR-031 — and, as of 2026-09-13, has itself run to completion (Phases M0–M11); Project Plan (Updated) carries both sequences side by side |
| **Product Discovery & Adoption Plan** | Not materially affected | — |
| **Technical Assessment (pptx)** | Original POC framing | Superseded in spirit by the actual built system — see Demo Narrative for the current story |

---

## Where to find the current answer to common questions

| Question | Document |
|---|---|
| "What agent framework does this actually run on?" | Current-State Architecture |
| "Why did you move off Claude Agent SDK?" | Architecture Decision Record (ADR-001, ADR-002) |
| "What went wrong during the build, and how was it fixed?" | Challenges & Real-World Findings |
| "What's the real database schema, and how does it differ from the LLD?" | Data Model & Schema Reference — also the source for the real `app_role`/`app_role_local_dev` privilege matrix, corrected 2026-09-09 (the two roles are not equivalent) |
| "What trade-offs did you knowingly accept?" | Trade-offs Log — entries 5, 6, and 12 are now superseded/resolved by the migration architecture (ADR-015/016, the Migration Plan, and ADR-021 respectively); see the log for the replacement trade-offs (15-21) each one bought |
| "How do I actually run this system?" | Runbook |
| "What security/governance guarantees are actually proven, not just designed?" | Governance & Security Reference |
| "What's done, and what's still open — a full status ledger, task by task?" | Project Plan (Updated) — every task across both the original Build Plan and the Migration Plan, each marked Done/Open/Partial as verified |
| "For anything that's still open, what do I actually need to do about it?" | Deferred Items and Open Follow-Ups — not a second status list; it names a concrete next step for each open item the Project Plan marks as anything other than Done |
| "What does this system actually look like right now — services, data flow, deployment?" | Current-State Architecture |
| "I want to actually learn this codebase — what's in each module, and how does a request/a trigger flow through it?" | Code Map — module-by-module, with the two real request paths traced file by file, and what's vestigial/overlapping/hard to understand flagged plainly |
| "What design patterns does this codebase actually use, and where?" | Pattern Inventory — real file/function citations only, including where a pattern is used inconsistently or was deliberately not used |
| "What should I show in a live demo?" | Demo Narrative |
| "What was the target architecture, and is this actually it now?" | Current-State Architecture — the target (React SPA → FastAPI BFF → core API → Investigation/Reporting workers over a Storage Queue, on Azure Container Apps) was reached as of Migration Phase M11 (2026-09-13); Architecture Decision Record (ADR-014 through ADR-031) for the individual decisions, Migration Plan for how they were sequenced to get there |
| "Why is the Streamlit UI being replaced?" | ADR-015 — the reasoning (multi-user auth, a durable execution boundary, escaping the rerun model) and its direct amendment of ADR-010, which had deferred Azure Static Web Apps as Next-scope work that (per ADR-015) was never actually viable for Streamlit in the first place |
| "What was the real migration sequence, and what had to be true before public ingress opened?" | Migration Plan — phased, each phase with a real Definition of Done; public ingress opened only once reviewer identity was real (Phase M8, 2026-09-11) |

---

*This index will itself go stale the moment something else changes. Treat it as a snapshot, not a live document. Last brought current 2026-09-13 (Migration Plan Phase 11 — Streamlit retired, the React frontend and four-service backend are current; the Project Plan brought current across both the original Build Plan and the Migration Plan; the Code Map and Pattern Inventory added as learning references, verified directly against the code the same day), against ADR-001 through ADR-031, Trade-offs Log entries 1-21, and the Migration Plan.*
