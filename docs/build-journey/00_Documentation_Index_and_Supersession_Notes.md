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
| **Physical Architecture** | VNet/boundary/private-endpoint intent, single-egress security posture | **Two real corrections**: (1) Neon Postgres → Azure DB for PostgreSQL Flexible Server (Managed Identity requirement); (2) the Anthropic API egress path was removed entirely once Azure-hosted Claude was confirmed to keep inference inside Azure — see ADR-013 |
| **High-Level Design (HLD)** | Section 3's revision-cap decision logic (approved / route_to_human_review / hard_stop_defect) — this logic is unchanged and has been proven live in all three branches | The *framework* executing this logic changed twice — see ADR-001, ADR-002 |
| **Low-Level Design (LLD)** | Most schema intent | Real schema deviates in specific, tested ways — see Data Model & Schema Reference for the exact diff |
| **DevOps Setup** | CI/CD gate philosophy | Actual bootstrap sequence differed in real, documented ways (see Challenges doc — the ADO identity saga, the Postgres role bootstrap) |
| **Build Plan** | 8-phase structure, Now/Next scoping discipline | Real completion state is far along — see Project Plan (Updated) for current status per phase |
| **Product Discovery & Adoption Plan** | Not materially affected | — |
| **Technical Assessment (pptx)** | Original POC framing | Superseded in spirit by the actual built system — see Demo Narrative for the current story |

---

## Where to find the current answer to common questions

| Question | Document |
|---|---|
| "What agent framework does this actually run on?" | Current-State Architecture |
| "Why did you move off Claude Agent SDK?" | Architecture Decision Record (ADR-001, ADR-002) |
| "What went wrong during the build, and how was it fixed?" | Challenges & Real-World Findings |
| "What's the real database schema, and how does it differ from the LLD?" | Data Model & Schema Reference |
| "What trade-offs did you knowingly accept?" | Trade-offs Log |
| "How do I actually run this system?" | Runbook |
| "What security/governance guarantees are actually proven, not just designed?" | Governance & Security Reference |
| "What's actually done vs. still open?" | Project Plan (Updated) |
| "What should I show in a live demo?" | Demo Narrative |

---

*This index will itself go stale the moment something else changes. Treat it as a snapshot, not a live document.*
