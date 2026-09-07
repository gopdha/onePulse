**OnePulse — Build Plan & Sequence**

*Step 10 of 10 \| Now-Scope Build, Written Fresh from LLD \| Ref:
OnePulse LLD, HLD, MVP Prioritization*

This plan sequences the Now-scope build only, per the approved MVP
Prioritization. Every service is written fresh against the Low-Level and
High-Level Design specifications — singleSlide_demo is reference context
for the reasoning behind specific configuration values (Section 3,
Low-Level Design), not a codebase to port. All actual coding, and every
live verification, happens in your own environment via Claude Code —
this document is the sequence and the checkpoint criteria, not the code
itself.

# Scoping Notes — Read Before Starting

- Coordination uses simple, direct orchestration for this build — a
  plain sequential call chain, not Temporal. Temporal (NFR-5) is
  explicitly Next-scope; wiring it in later replaces this orchestration
  layer, it does not require rewriting the services it calls.

- The full Tenant → Portfolio → Program schema is created now, exactly
  as specified in Low-Level Design — cheap to build once, and every
  Now-scope table has a foreign key into it. Actively enforcing
  Row-Level Security and true multi-tenant isolation (NFR-1) remains
  Next-scope; for now, one real tenant, portfolio, and program row is
  sufficient.

- Microsoft Foundry and Managed Identity are required from the start,
  not deferred — NFR-2 is explicitly Now-scope, not an enhancement to
  add later.

- Prerequisites before Phase 1: three Azure Database for PostgreSQL
  Flexible Server instances, one per environment (Physical Architecture
  Section 4, DevOps Setup Section 4), a Foundry resource with Claude
  Sonnet 5 deployed, an Azure AI Content Safety resource, and a real
  Azure DevOps organization to investigate against — the same category
  of real infrastructure every prior component in this whole project has
  been held to.

  

# Build Sequence

|                                                       |                                                                                                             |                                                                                                                                                                                                                                                                            |
|-------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Phase**                                             | **Implements**                                                                                              | **Definition of Done**                                                                                                                                                                                                                                                     |
| 1\. Repo & Shared Foundation                          | Repo scaffold; shared config loading; Managed Identity-based Postgres and Foundry client setup (NFR-2)      | A shared library that authenticates to both Azure Database for PostgreSQL Flexible Server and Foundry using Managed Identity (Entra ID), with zero static credentials anywhere in the codebase — verified by grep, not assumed.                                                                                                |
| 2\. Schema & Migration Tooling                        | Full schema from Low-Level Design Section 1; migrate.py and verify_migration.py (NFR-9)                     | Every table exists in a real Azure Database for PostgreSQL Flexible Server instance, and verify_migration.py independently confirms it via information_schema — not just a clean migration exit code.                                                                                                               |
| 3\. Work Item Investigation & Status Update Analysis  | FR-1, FR-2; least-privilege tool scoping (NFR-3)                                                            | A real investigation against a real Azure DevOps org produces a grounded Finding with cited evidence, using only the exact tools each service is scoped to — verified by inspecting the real tool-call trace, not by reading the code.                                     |
| 4\. Narrative Synthesis & Deterministic Status Rollup | FR-3, FR-8                                                                                                  | A real draft report is produced from real Findings, and the overall status is reproducibly computed by a pure function — same inputs, same output, verified by a repeated call, not asserted.                                                                              |
| 5\. Quality Assurance, Revision & Content Safety      | FR-4; the revision cap decision logic (High-Level Design Section 3); mandatory content safety check (NFR-8) | A deliberately-broken draft is fed in and confirmed to trigger exactly one revision, and a forced code-enforced-check failure at the cap is confirmed to hard-stop rather than silently proceed — the single most important behavior in the whole design, tested directly. |
| 6\. Report Rendering                                  | FR-5                                                                                                        | A real rendered artifact is produced from real approved content and is retrievable by URI.                                                                                                                                                                                 |
| 7\. Human Governance API                              | FR-7, FR-13; reviewer attribution (NFR-11)                                                                  | A real approval and a real rejection are both recorded, the rejection is refused without notes, and the approval record correctly captures who decided, not just that a decision was made.                                                                                 |
| 8\. End-to-End Orchestration                          | Simple sequential coordination across Phases 3–7                                                            | One real, live, unattended run goes from a real Azure DevOps org through to a persisted, human-approved report — the same end-to-end proof every component in this project has ultimately been held to.                                                                    |

  

# Claude Code Kickoff Prompts, Per Phase

Each is a starting prompt, not the full instruction set — expect the
same iterative design-checkpoint-then-build rhythm used throughout this
whole project, not a single one-shot build.

**Phase 1: Repo & Shared Foundation**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Set
up a new repository for OnePulse (separate from singleSlide_demo,</p>
<p>which stays untouched as reference). Build a shared library
providing:</p>
<p>config loading, a Postgres client authenticated via Managed
Identity</p>
<p>(no connection string with an embedded password), and a
Foundry-backed</p>
<p>Claude client authenticated via Managed Identity (no static API
key).</p>
<p>Reference: Physical Architecture Section 5 (Network &amp;
Security),</p>
<p>Low-Level Design Section 3 (Service Configuration).</p>
<p>Show me the design before writing code: how credentials are
resolved,</p>
<p>and how you'll prove zero static secrets exist in the
repository.</p></td>
</tr>
</tbody>
</table>

**Phase 2: Schema & Migration Tooling**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Implement
the full schema from Low-Level Design Section 1 against a</p>
<p>real Azure Database for PostgreSQL Flexible Server instance, plus
migrate.py and verify_migration.py exactly as</p>
<p>specified in DevOps Setup Section 2.1. Prove verify_migration.py</p>
<p>actually queries information_schema directly and would fail if a</p>
<p>migration silently didn't apply — write a test that proves this
by</p>
<p>forcing that exact failure mode.</p></td>
</tr>
</tbody>
</table>

**Phase 3: Work Item Investigation & Status Update Analysis**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Build
these two services fresh against Low-Level Design Section 2's</p>
<p>API contracts and High-Level Design Section 2 (Core Cycle, steps
3).</p>
<p>Use the exact configuration values from Low-Level Design Section
3:</p>
<p>max_turns=6, and the full isolation flag set (setting_sources=[],</p>
<p>skills=[], strict_mcp_config=True) on every agentic call — these
are</p>
<p>not defaults to reconsider, they are proven fixes for real
incidents.</p>
<p>Design checkpoint first: show me the exact tool scope for each</p>
<p>service before implementation.</p></td>
</tr>
</tbody>
</table>

**Phase 4: Narrative Synthesis & Deterministic Status Rollup**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Build
Narrative Synthesis fresh against the FR-3 requirement and the</p>
<p>Report entity in Low-Level Design. Build the Status Rollup as a
pure,</p>
<p>dependency-free function — no network call, no database access —</p>
<p>exactly as justified in Physical Architecture Section 2. Provide
unit</p>
<p>tests proving the same input always produces the same
output.</p></td>
</tr>
</tbody>
</table>

**Phase 5: Quality Assurance, Revision & Content Safety**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>This
is the most important phase in the whole build. Implement</p>
<p>against High-Level Design Section 3 exactly: one bounded
revision,</p>
<p>then the branching decision — a code-enforced check failing twice</p>
<p>independently is a hard stop with nothing persisted, not a silent</p>
<p>pass. Add the mandatory Azure AI Content Safety call per NFR-8.</p>
<p>Before any other work: write the regression test that forces a</p>
<p>code-enforced check to fail twice and proves the hard stop
actually</p>
<p>fires and nothing is written to the Report store.</p></td>
</tr>
</tbody>
</table>

**Phase 6: Report Rendering**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Build
fresh against FR-5 and the Report entity's rendered_artifact_uri</p>
<p>field. Keep this deterministic — no model call — consistent with</p>
<p>Physical Architecture's reasoning for this component.</p></td>
</tr>
</tbody>
</table>

**Phase 7: Human Governance API**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Implement
the exact contracts from Low-Level Design Section 2.2:</p>
<p>approve and reject endpoints, reject requires non-empty notes</p>
<p>enforced server-side, and the approval_records write always
includes</p>
<p>actor_id. Prove the append-only guarantee: attempt an UPDATE
against</p>
<p>approval_records using the application role and confirm it is</p>
<p>rejected by the database itself, not just by application
code.</p></td>
</tr>
</tbody>
</table>

**Phase 8: End-to-End Orchestration**

<table width="640" data-cellpadding="9" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="620" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.1in 0.14in"><p>Write
simple sequential orchestration calling Phases 3 through 7 in</p>
<p>order, matching High-Level Design Section 2's numbered sequence.</p>
<p>No Temporal yet — that's Next-scope. Once wired, run one real,</p>
<p>live, end-to-end cycle against real Azure DevOps data and show me</p>
<p>the full output — same standard of proof as every live-verified</p>
<p>component throughout this entire project.</p></td>
</tr>
</tbody>
</table>

  

*Once Phase 8's live run succeeds, the Now scope is genuinely complete
and provable — not just written. Next-scope work (multi-tenant
enforcement, Temporal, on-demand triggers, cost gating) begins only
after that proof, per the Now/Next/Later sequencing already agreed.*
