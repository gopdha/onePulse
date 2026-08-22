  

**OnePulse**

Product Requirements Document

*AI-Powered Multi-Tenant Executive Reporting Platform*

|                       |                                                                                                                                                                                                                  |
|-----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Document Status**   | Draft — Pending Review                                                                                                                                                                                           |
| **Version**           | 1.0                                                                                                                                                                                                              |
| **Author**            | Claude (Anthropic)                                                                                                                                                                                               |
| **Reviewer**          | Gopinath Dhayanandamurthy                                                                                                                                                                                        |
| **Reference POC**     | singleSlide_demo (proof-of-concept repository)                                                                                                                                                                   |
| **Related Documents** | This PRD is Step 1 of a 10-step design process; subsequent steps (architecture fit review, solution/conceptual/logical/physical architecture, HLD, LLD, DevOps setup, build) depend on this document's approval. |

  

# Table of Contents

<div id="Table of Contents1" dir="ltr">



</div>

  

  

# 1. Executive Summary

OnePulse addresses a business problem validated through direct, lived
professional experience, independent of any technology choice: the
manual effort, inconsistency, and risk of important signals being missed
in recurring executive status reporting across programs and portfolios.
OnePulse is the production-grade evolution of singleSlide_demo, a
proof-of-concept multi-agent AI system built to test whether an
AI-driven approach could solve this already-confirmed problem — not to
discover whether the problem existed. The demo validated the core
agentic pipeline end-to-end against real infrastructure — an actual
Azure DevOps organization, real Anthropic API calls, and a real database
— and, in the process, surfaced concrete production risks that a
proof-of-concept is specifically supposed to surface before they reach
production.

This document defines the requirements to evolve that validated pipeline
into a secure, multi-tenant, observable, cost-governed platform capable
of serving multiple portfolios and programs concurrently, with
self-service access for two defined personas and no compromise to the
demo's core trust guarantees: every status is grounded in cited
evidence, the headline status indicator is computed deterministically
rather than by model judgment, and no report reaches an executive
without explicit human approval.

# 2. Problem Validation & Background

## 2.1 Problem Validation

This initiative did not begin with a technology and then search for a
problem to apply it to. It began with a real, personally-experienced
problem: the author has directly held Program Lead responsibility for
producing recurring executive status updates across enterprise programs,
and has firsthand experience with the time cost of manual compilation,
the inconsistency that results when report quality depends on whoever
compiles it that week, and the real risk of a genuine issue staying
buried in an unstructured status update until it is too late to act on
early. This is independently corroborated: Portfolio Leads separately
and consistently describe the same underlying need — faster, more
consistent visibility across multiple programs, without depending on
each program individually compiling and escalating its own status well.

This is treated as validated problem–market fit, established prior to
and independent of any architecture or technology decision. The proof of
concept that follows was built to test technical feasibility for an
already-confirmed real problem — not to determine whether the problem
was worth solving.

## 2.2 Key Learnings from the Proof of Concept

The proof of concept proved the core premise: a coordinated pipeline of
specialized AI agents — investigation, synthesis, self-critique with
bounded revision — can produce an executive-ready status report that is
demonstrably grounded in real data, not generic summarization. Equally
valuable, live testing against real infrastructure surfaced concrete
risks that directly shape this document's non-functional requirements,
rather than requirements being assumed abstractly:

- A real cost anomaly, in which per-run cost ran approximately 10x
  higher than the design-time estimate, was traced to agentic calls
  executing in an unintentionally broad session context rather than an
  isolated, narrow API call. This directly motivates the Cost Governance
  requirements (Section 7, NFR-6) and the Deployment Verification
  requirement (NFR-9).

- Two separate incidents occurred in which a correct database schema
  change was written but never applied to the live database, only
  discovered when a downstream feature failed. This directly motivates
  NFR-9, which requires deployment-time verification, not just a passing
  build.

- The proof of concept's self-service onboarding flow was found to cover
  only a subset of the configuration required for a project's full
  pipeline to run, discovered only when onboarding a second real
  project. This directly motivates FR-14.

- Real credential exposure incidents occurred during interactive
  development, each requiring credential rotation. This directly
  motivates NFR-2, which requires managed-identity-based authentication
  in production rather than static credentials of any kind.

These are treated as requirements inputs, not merely lessons: each
non-functional requirement in Section 7 traces to a concrete, observed
risk rather than a generic best practice.

# 3. Goals

- G1 — Support multiple concurrent tenants, portfolios, and programs
  with complete data isolation between them.

- G2 — Provide self-service, role-based access for two defined personas:
  Portfolio Lead and Program Lead.

- G3 — Preserve the proof of concept's core trust guarantees —
  evidence-grounded status determination, a deterministic headline
  status rollup, and mandatory human approval before finalization — at
  production scale.

- G4 — Provide real-time cost, quality, and safety observability with
  automated anomaly detection, closing the gap that allowed the original
  cost anomaly to go unnoticed until a manual trace review.

- G5 — Achieve an enterprise security and compliance posture: single
  sign-on, role-based access control, managed-identity-based secrets
  handling, and configurable data residency.

- G6 — Enable onboarding of a new portfolio or program without requiring
  engineering involvement for standard cases.

# 4. Non-Goals

- Replacing Azure DevOps or any team's status-reporting process.
  OnePulse is a synthesis and reporting layer that reads from these
  systems; it does not modify data within them.

- General-purpose business intelligence or reporting. Scope is
  specifically executive status reporting driven by Azure DevOps work
  item data and team status updates.

- Sub-second or continuously-refreshing real-time dashboards. The
  platform operates on a weekly cadence plus authorized on-demand
  generation, not continuous live refresh.

- Fine-tuning or training custom models. The platform uses pretrained
  frontier models via Microsoft Foundry.

# 5. Personas & Roles

## 5.1 Portfolio Lead

Oversees multiple programs or projects within a portfolio. Requires
visibility across every program's current and historical status, the
ability to request a fresh report outside the standard schedule, and
self-service natural-language access to report history.

## 5.2 Program Lead

Owns delivery of a single program or project. Requires the ability to
preview a fully rendered report and either approve it or reject it with
a recorded reason before it is considered final.

## 5.3 Platform Administrator

Implied by enterprise multi-tenant scope even though not explicitly
requested by name: onboards new tenants/portfolios, monitors
platform-wide cost and system health, and manages per-project
configuration. Included here for completeness; to be confirmed as
in-scope during review of this document.

# 6. Functional Requirements

## 6.1 Core Pipeline

|        |                                                                                                                                                                                                                                  |
|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                                                                                                                  |
| FR-1   | The system shall investigate Azure DevOps work items matching project-configured entry criteria and produce a status grounded in cited evidence, using a four-level taxonomy: On Track, At Risk, Blocked, or Needs Human Review. |
| FR-2   | The system shall parse team lead status reports to identify initiatives not tracked in Azure DevOps and flag possible connections to existing tracked work items.                                                                |
| FR-3   | The system shall merge, deduplicate, and curate investigated data into slide-ready content and an executive narrative, preserving continuity with the immediately prior reporting period.                                        |
| FR-4   | The system shall evaluate generated narratives against a defined quality rubric and revise the narrative up to a bounded number of times before finalizing it.                                                                   |
| FR-5   | The system shall render a finalized report's content into a locked, per-project visual template.                                                                                                                                 |
| FR-6   | The system shall persist every report, its complete supporting evidence, and its approval status durably and indefinitely.                                                                                                       |

## 6.2 Governance & Onboarding

|        |                                                                                                                                                                                        |
|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                                                                        |
| FR-7   | No report shall be considered final without explicit Program Lead approval; a rejection shall require a recorded reason before it is accepted.                                         |
| FR-8   | The platform-wide headline status indicator (Red, Amber, Green, or Unknown) shall be computed by a fixed, auditable rule and shall never be determined by model inference.             |
| FR-9   | A new portfolio or project shall be onboardable through a guided, data-grounded conversational flow without requiring direct engineering involvement for standard configurations.      |
| FR-14  | Onboarding shall generate every configuration artifact required for a project's full pipeline to execute, not a subset — directly addressing a gap discovered in the proof of concept. |

## 6.3 Portfolio Lead Capabilities

|        |                                                                                                                                          |
|--------|------------------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                          |
| FR-10  | A Portfolio Lead shall be able to view current and historical reports for every program within their portfolio.                          |
| FR-11  | A Portfolio Lead shall be able to trigger a new report generation cycle outside the standard schedule, subject to a defined usage limit. |

## 6.4 Shared Capabilities — Status Chat Assistant

The following capability is available to both personas, scoped to the
reports each is authorized to see: a Portfolio Lead may query across
every program in their portfolio; a Program Lead may query within their
own program's report history.

|        |                                                                                                                                                                                                                                                                                  |
|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                                                                                                                                                                  |
| FR-12  | A Portfolio Lead or Program Lead shall be able to ask natural-language questions about current and historical reports within their authorized scope and receive answers grounded exclusively in actual report history, with source citations identifying the originating report. |

## 6.5 Program Lead Capabilities

|        |                                                                                                                                   |
|--------|-----------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                   |
| FR-13  | A Program Lead shall be able to preview a fully rendered report and approve or reject it; rejection shall require recorded notes. |

## 6.6 Platform Administrator Capabilities

|        |                                                                                                                                                                                      |
|--------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                                                                      |
| FR-15  | A Platform Administrator shall be able to onboard new tenants and portfolios, monitor platform-wide cost and system health across all tenants, and manage per-project configuration. |

# 7. Non-Functional / Enterprise-Grade Requirements

Each requirement below traces to a specific, real risk observed during
the proof of concept (Section 2) or to a standard enterprise operating
requirement.

|        |                                                                                                                                                                                                                                                                        |
|--------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **ID** | **Requirement**                                                                                                                                                                                                                                                        |
| NFR-1  | Multi-Tenancy: all persisted data shall be logically isolated per tenant, enforced at the database layer, not application logic alone; every project identifier shall be scoped by tenant.                                                                             |
| NFR-2  | Identity & Secrets: all human access shall be authenticated via enterprise single sign-on; all service-to-service and service-to-model credentials shall use managed identities; no long-lived static credential shall be stored in application configuration or code. |
| NFR-3  | Least-Privilege Access: every AI agent and service shall be granted the minimum tool and data access required for its function; role-based access control shall govern human access according to persona.                                                              |
| NFR-4  | Scalability: agent execution shall scale independently per component to accommodate variable, concurrent multi-tenant load without cross-tenant performance interference.                                                                                              |
| NFR-5  | Reliability: the report generation workflow shall durably survive process or worker restarts and shall support long-running human-approval wait states without data loss.                                                                                              |
| NFR-6  | Cost Governance: the platform shall enforce per-tenant usage and cost limits proactively, before execution; actual spend shall be continuously monitored against the modeled estimate; deviations exceeding a defined threshold shall be automatically flagged.        |
| NFR-7  | Observability: every model and tool invocation shall be traced with cost, latency, and outcome data; every generated narrative shall be scored for groundedness and coherence; telemetry shall be queryable per tenant.                                                |
| NFR-8  | Content Safety: all model-generated content shall pass an explicit content-safety check before reaching a human reviewer, regardless of whether the underlying model provider applies this automatically.                                                              |
| NFR-9  | Deployment & Migration Integrity: no schema or configuration change shall be considered deployed until independently verified against the live environment as part of the deployment pipeline itself; a passing build alone shall not constitute sufficient evidence.  |
| NFR-10 | Data Residency: the platform shall support configurable data-processing residency to accommodate regional compliance requirements.                                                                                                                                     |
| NFR-11 | Auditability: every status determination shall retain its complete cited evidence indefinitely; every approval or rejection decision shall be permanently recorded with attribution and timestamp.                                                                     |
| NFR-12 | Availability: target 99.5% availability during business hours, reflecting a weekly-plus-on-demand usage pattern rather than continuous real-time use. To be confirmed during review.                                                                                   |

# 8. Assumptions & Constraints

- Frontier language model access is provided via Microsoft Foundry,
  subject to Foundry's current regional availability for the required
  model tier at time of deployment.

- Azure DevOps remains the system of record for tracked work; the
  platform reads from it and does not modify it.

- The proof of concept's core pipeline logic — agent prompts, status
  taxonomy, critique rubric — is assumed sound and will be carried
  forward rather than redesigned, unless a requirement in Section 6 or 7
  necessitates a change.

- Initial rollout targets a defined pilot set of tenants prior to
  general availability; exact pilot scope to be confirmed.

# 9. Success Metrics

- Time saved relative to manual report compilation (baseline to be
  measured during pilot).

- Percentage of reports approved without requiring revision beyond the
  automated critique-and-revision cycle.

- Actual cost per report versus the modeled estimate, tracked
  continuously — applying the same discipline that identified the proof
  of concept's original cost anomaly.

- Portfolio Lead adoption of the Status Chat Assistant, measured in
  queries per week.

- Zero cross-tenant data exposure incidents — a hard requirement, not a
  target to be approached.

# 10. Deferred to Future Iterations

The following were identified during the proof of concept as valuable
but are explicitly out of scope for this phase:

- A feedback loop through which a Program Lead's correction at approval
  time informs future agent behavior for that project.

- Automated drift detection on an agent's own judgment consistency over
  time.

- Full citation self-reporting for hallucination detection; the current
  approach checks that required content is present, not that every
  generated claim is independently verifiable.

- Agentic, query-planning retrieval for the Status Chat Assistant,
  pending general availability of the relevant Foundry capability;
  initial release uses direct vector and hybrid retrieval.

# 11. Open Questions for Architecture Fit Review (Step 2)

- Confirm Microsoft Foundry's current regional availability covers every
  required deployment region.

- Confirm target tenant and user scale for initial rollout, to size
  NFR-4 and NFR-6 concretely rather than qualitatively.

- Confirm the 99.5% availability target in NFR-12, or provide a revised
  target.

# 12. Appendix: singleSlide_demo Proof-of-Concept Reference

The proof of concept referenced throughout this document remains
available in its own repository as a reference implementation and is not
modified by this initiative. It implements eleven core components —
Feature Investigation Agent, Status Report Agent, RAG Rollup, Synthesis
Agent, Critique Agent, Slide Generation Agent, Discovery Agent,
Orchestrator, Archive, Review Gate, and an Observability layer — each
independently verified against real infrastructure prior to this
document being written.
