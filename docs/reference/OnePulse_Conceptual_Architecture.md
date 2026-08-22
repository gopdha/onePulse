**OnePulse — Conceptual Architecture**

*Step 4 of 10 \| Major Building Blocks & Data Flow, Technology-Agnostic
\| Ref: OnePulse PRD v1.0*

This view identifies the major functional building blocks required to
satisfy every requirement in the PRD and how information flows between
them. No technology, product, or vendor is named at this level — that
decision is deferred to Physical Architecture (Step 6). Each block is
defined purely by the responsibility it owns.

***ACTORS***

|                    |                  |                            |
|--------------------|------------------|----------------------------|
| **Portfolio Lead** | **Program Lead** | **Platform Administrator** |

↓

***EXTERNAL SOURCES — data OnePulse reads but never modifies***

|                                              |                         |
|----------------------------------------------|-------------------------|
| **Work Tracking System (e.g. Azure DevOps)** | **Team Status Updates** |

↓

***UNDERSTANDING — investigates raw source data, produces cited
findings***

|                             |                            |
|-----------------------------|----------------------------|
| **Work Item Investigation** | **Status Update Analysis** |

↓

***SYNTHESIS & ASSURANCE — combines findings, checks its own quality***

|                         |                                  |                                 |
|-------------------------|----------------------------------|---------------------------------|
| **Narrative Synthesis** | **Quality Assurance & Revision** | **Deterministic Status Rollup** |

↓

***DELIVERY & INTERACTION — where humans see and engage with output***

|                      |                                 |                                 |
|----------------------|---------------------------------|---------------------------------|
| **Report Rendering** | **Human Governance (Approval)** | **Conversational Access (Q&A)** |

↓

***KNOWLEDGE — the durable memory everything above reads from and writes
to***

|                                                                                 |
|---------------------------------------------------------------------------------|
| **Knowledge Store — reports, evidence, approvals & attribution, configuration** |

  

***CROSS-CUTTING FOUNDATIONS — apply to every band above, not a separate
stage***

|                                  |                                |                               |                                         |
|----------------------------------|--------------------------------|-------------------------------|-----------------------------------------|
| **Identity, Access & Isolation** | **Configuration & Onboarding** | **Coordination (Sequencing)** | **Platform Governance & Observability** |

  

# Block Responsibilities

|                                     |                                                                                                                                   |                                                                              |
|-------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| **Block**                           | **Responsibility**                                                                                                                | **Key Data In / Out**                                                        |
| Work Item Investigation             | Determines a grounded status for each tracked work item, citing specific evidence.                                                | In: raw work item data. Out: status + evidence per item.                     |
| Status Update Analysis              | Identifies work mentioned in team updates that isn't tracked elsewhere; flags possible links to tracked items.                    | In: raw team updates. Out: untracked items + possible links.                 |
| Narrative Synthesis                 | Merges all findings into one coherent, executive-readable narrative, preserving continuity with the prior period.                 | In: findings + prior period. Out: draft narrative.                           |
| Quality Assurance & Revision        | Checks the draft against defined quality criteria; triggers a bounded revision if it falls short.                                 | In: draft narrative. Out: approved-for-rendering narrative + quality record. |
| Deterministic Status Rollup         | Computes the single overall status indicator by a fixed rule — never by judgment.                                                 | In: individual item statuses. Out: one overall status.                       |
| Report Rendering                    | Produces the final, human-readable report artifact from approved content.                                                         | In: approved narrative + status. Out: rendered report.                       |
| Human Governance                    | Presents the rendered report to the accountable leader and records an approval or rejection with reasoning.                       | In: rendered report. Out: decision + attribution + notes.                    |
| Conversational Access               | Answers natural-language questions using only real report history in scope for the asker.                                         | In: question + asker's scope. Out: grounded answer + citation.               |
| Knowledge Store                     | Durably retains every report, its evidence, every decision and who made it, and all configuration.                                | In: all of the above. Out: history for synthesis, governance, and Q&A.       |
| Identity, Access & Isolation        | Establishes who someone is, what they may see, and keeps every tenant's and portfolio's data separate from every other's.         | Applies to every interaction, human or automated.                            |
| Configuration & Onboarding          | Guides setup of a new portfolio or program, capturing everything the pipeline needs to run for it — completely, not partially.    | Out: complete configuration for all downstream blocks.                       |
| Coordination                        | Sequences the end-to-end flow, runs independent work in parallel where possible, and manages bounded retries.                     | Owns no content decisions of its own.                                        |
| Platform Governance & Observability | Tracks cost and usage before and during execution, monitors output quality and safety, and verifies changes actually took effect. | Out: alerts, spend limits enforced, quality/safety scores.                   |

# How This Resolves the Step 2 Architecture Gaps

|                                                   |                                                                                                                                                                                                |
|---------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Gap (from Step 2)**                             | **Resolved By**                                                                                                                                                                                |
| No portfolio hierarchy in the data model          | Identity, Access & Isolation now explicitly scopes by portfolio as well as tenant and program — conceptually required for Conversational Access and Portfolio Lead visibility to work at all.  |
| FR-14's fix never designed, only required         | Configuration & Onboarding is scoped, at this level, to guarantee complete coverage — its responsibility statement says so explicitly, not left implicit.                                      |
| Cost governance was request-count, not cost-based | Platform Governance & Observability's responsibility explicitly includes tracking cost “before and during execution,” not just counting requests.                                              |
| tenant_id missing from trace schema               | Platform Governance & Observability inherits tenant/portfolio scope from Identity, Access & Isolation by design — carried forward as a concrete data element in Logical Architecture (Step 5). |
| No reviewer attribution on approval               | Human Governance's responsibility explicitly includes recording attribution, not just a decision.                                                                                              |

  

Note: this document intentionally names no database, cloud provider, AI
model, or messaging technology. Those choices, and the concrete data
structures that implement each block above, are addressed in Logical
Architecture (Step 5) and Physical Architecture (Step 6).
