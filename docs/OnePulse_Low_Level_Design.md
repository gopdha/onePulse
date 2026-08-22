**OnePulse — Low-Level Design**

*Step 8 of 10 \| Schemas, API Contracts & Configuration \| Ref: OnePulse
PRD v1.0*

This document makes every prior decision concrete and implementable:
real table definitions, real request and response contracts, and the
exact configuration values already proven correct in the
singleSlide_demo proof of concept — carried forward deliberately, not
rediscovered.

# 1. Database Schema

Every table below traces to an entity or gap-resolution defined in
Logical Architecture. Two design choices are enforced at the database
level, not just in application code, matching this project's standing
rule of guaranteeing correctness structurally:

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>--
Tenant hierarchy (resolves Step 2 Gap 1: no portfolio layer)</p>
<p>CREATE TABLE tenants (</p>
<p>tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),</p>
<p>name TEXT NOT NULL,</p>
<p>status TEXT NOT NULL DEFAULT 'active',</p>
<p>created_at TIMESTAMPTZ NOT NULL DEFAULT now()</p>
<p>);</p>
<p>CREATE TABLE portfolios (</p>
<p>portfolio_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),</p>
<p>tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),</p>
<p>name TEXT NOT NULL,</p>
<p>UNIQUE (tenant_id, name)</p>
<p>);</p>
<p>CREATE TABLE programs (</p>
<p>program_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),</p>
<p>portfolio_id UUID NOT NULL REFERENCES portfolios(portfolio_id),</p>
<p>name TEXT NOT NULL,</p>
<p>source_system_ref TEXT,</p>
<p>UNIQUE (portfolio_id, name)</p>
<p>);</p></td>
</tr>
</tbody>
</table>

  
  

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>--
Configuration completeness is a DATABASE GUARANTEE, not app logic</p>
<p>-- (closes the HLD Step 7 onboarding mechanism at the schema
level)</p>
<p>CREATE TABLE configurations (</p>
<p>program_id UUID PRIMARY KEY REFERENCES programs(program_id),</p>
<p>feature_agent_config JSONB,</p>
<p>status_report_agent_config JSONB,</p>
<p>synthesis_agent_config JSONB,</p>
<p>critique_agent_config JSONB,</p>
<p>slide_generation_agent_config JSONB,</p>
<p>manifest_complete BOOLEAN GENERATED ALWAYS AS (</p>
<p>feature_agent_config IS NOT NULL AND</p>
<p>status_report_agent_config IS NOT NULL AND</p>
<p>synthesis_agent_config IS NOT NULL AND</p>
<p>critique_agent_config IS NOT NULL AND</p>
<p>slide_generation_agent_config IS NOT NULL</p>
<p>) STORED</p>
<p>);</p></td>
</tr>
</tbody>
</table>

manifest_complete is a generated column, not an application check — the
database itself cannot represent a program as ready with any
configuration piece missing. A cycle's first query is a check against
this column; there is no code path that can accidentally skip it.

  

<table width="640" data-cellpadding="11" data-cellspacing="0"
style="page-break-before: always">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>CREATE
TABLE reports (</p>
<p>report_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,</p>
<p>program_id UUID NOT NULL REFERENCES programs(program_id),</p>
<p>week_of DATE NOT NULL,</p>
<p>rag_status TEXT NOT NULL CHECK (rag_status IN
('Red','Amber','Green','Unknown')),</p>
<p>executive_summary TEXT NOT NULL,</p>
<p>trend_line TEXT NOT NULL DEFAULT '',</p>
<p>curated_features JSONB NOT NULL,</p>
<p>curated_initiatives JSONB NOT NULL,</p>
<p>prior_report_id BIGINT REFERENCES reports(report_id),</p>
<p>rendered_artifact_uri TEXT,</p>
<p>attempts INT NOT NULL DEFAULT 1,</p>
<p>reviewed BOOLEAN NOT NULL DEFAULT FALSE,</p>
<p>UNIQUE (program_id, week_of)</p>
<p>);</p>
<p>-- Append-only by GRANT, not by convention (resolves Step 2 Gap 5:
reviewer attribution)</p>
<p>CREATE TABLE approval_records (</p>
<p>approval_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,</p>
<p>report_id BIGINT NOT NULL REFERENCES reports(report_id),</p>
<p>decision TEXT NOT NULL CHECK (decision IN
('approved','rejected')),</p>
<p>actor_id UUID NOT NULL REFERENCES actors(actor_id),</p>
<p>notes TEXT NOT NULL DEFAULT '',</p>
<p>decided_at TIMESTAMPTZ NOT NULL DEFAULT now()</p>
<p>);</p>
<p>REVOKE UPDATE, DELETE ON approval_records FROM app_role;</p></td>
</tr>
</tbody>
</table>

  
  

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>--
Cost-based governance (resolves Step 2 Gap 3: was request-count, not
cost)</p>
<p>CREATE TABLE usage_ledger (</p>
<p>usage_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,</p>
<p>tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),</p>
<p>program_id UUID REFERENCES programs(program_id),</p>
<p>estimated_cost_usd NUMERIC(10,4),</p>
<p>actual_cost_usd NUMERIC(10,4),</p>
<p>recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()</p>
<p>);</p>
<p>-- Tenant isolation (resolves Step 2 Gap 1: enforced at the database,
not app code)</p>
<p>ALTER TABLE reports ENABLE ROW LEVEL SECURITY;</p>
<p>CREATE POLICY tenant_isolation ON reports USING (</p>
<p>program_id IN (</p>
<p>SELECT p.program_id FROM programs p</p>
<p>JOIN portfolios pf ON p.portfolio_id = pf.portfolio_id</p>
<p>WHERE pf.tenant_id =
current_setting('app.current_tenant_id')::uuid</p>
<p>)</p>
<p>);</p></td>
</tr>
</tbody>
</table>

## 1.1 Supporting Tables

|                 |                                                                      |                                        |
|-----------------|----------------------------------------------------------------------|----------------------------------------|
| **Table**       | **Key Columns**                                                      | **Purpose**                            |
| findings        | report_id, source_item_ref, status_label, evidence text\[\]          | Per-item evidence trail (NFR-11).      |
| untracked_items | report_id, description, possible_linked_finding_id, match_confidence | Other Initiatives from status reports. |
| actors          | actor_id, tenant_id, role, entra_object_id                           | RBAC identity, tied to Entra ID.       |
| actor_scope     | actor_id, portfolio_id, program_id                                   | What each actor is authorized to see.  |

  

# 2. API Contracts

## 2.1 Trigger a Report Cycle

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>POST
/api/v1/programs/{programId}/reports</p>
<p>Request: { "requestedBy": "&lt;actorId&gt;" }</p>
<p>202 Accepted:</p>
<p>{ "cycleId": "&lt;temporal-workflow-id&gt;", "status": "queued" }</p>
<p>429 Too Many Requests (Usage Ledger check failed — Gap 3)</p>
<p>{ "error": "budget_exceeded",</p>
<p>"message": "Projected cost exceeds remaining budget for this cycle."
}</p></td>
</tr>
</tbody>
</table>

## 2.2 Review and Approve

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>GET
/api/v1/reviews/pending?programId={programId}</p>
<p>200 OK:</p>
<p>{ "reports": [</p>
<p>{ "reportId": 1042, "weekOf": "2026-08-21", "ragStatus": "Amber",</p>
<p>"renderedArtifactUri": "https://..." } ] }</p>
<p>POST /api/v1/reviews/{reportId}/approve</p>
<p>Request: { "actorId": "&lt;actorId&gt;", "notes": "" }</p>
<p>200 OK: { "reportId": 1042, "decision": "approved", "decidedAt":
"..." }</p>
<p>POST /api/v1/reviews/{reportId}/reject</p>
<p>Request: { "actorId": "&lt;actorId&gt;", "notes": "&lt;required,
non-empty&gt;" }</p>
<p>400 Bad Request (if notes is empty — enforced server-side, not just
in the UI)</p>
<p>{ "error": "notes_required" }</p></td>
</tr>
</tbody>
</table>

## 2.3 Conversational Access

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#f5f5f0"
style="background: #f5f5f0; border: 1px solid #000000; padding: 0.11in 0.14in"><p>POST
/api/v1/chat/query</p>
<p>Request: { "actorId": "&lt;actorId&gt;", "question": "&lt;text&gt;"
}</p>
<p>200 OK:</p>
<p>{ "answer": "&lt;grounded text&gt;",</p>
<p>"citations": [ { "reportId": 1038, "weekOf": "2026-08-14" } ] }</p>
<p>The actorId's authorized scope (Section 4.2, High-Level Design) is
resolved</p>
<p>server-side and applied as a mandatory filter on retrieval — never
passed</p>
<p>as a client-supplied, optional parameter.</p></td>
</tr>
</tbody>
</table>

  

# 3. Service Configuration

Every value below is carried forward from a real, live-verified finding
in the singleSlide_demo proof of concept — not a default guessed at
design time.

|                                   |                                                                                                                |                                                                                                                                                             |
|-----------------------------------|----------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Setting**                       | **Value**                                                                                                      | **Source**                                                                                                                                                  |
| Synthesis/Critique revision cap   | max_revisions = 1                                                                                              | Tied directly to the proof of concept's own real cost model; changing this number would silently invalidate that math.                                      |
| Feature Investigation turn budget | max_turns = 6                                                                                                  | 5 was the original estimate; 6 accounts for a mandatory tool-discovery step discovered only through live debugging in the proof of concept.                 |
| Model call isolation flags        | setting_sources=\[\], skills=\[\], strict_mcp_config=True on every agentic call                                | The exact fix for a real, confirmed 10x cost anomaly found in the proof of concept's own observability trace — mandatory on every AI service, not optional. |
| On-demand trigger rate limit      | 2 per Portfolio Lead per day, enforced at the API Gateway                                                      | Prevents a human from unintentionally repeating the exact cost-anomaly pattern already seen once in this project's real history.                            |
| Service replica count             | Minimum 3 per core service, spread across availability zones                                                   | Directly realizes the High-Level Design availability approach (Step 7, Section 6).                                                                          |
| Content safety check              | Mandatory call to Azure AI Content Safety after Quality Assurance, before any content reaches Human Governance | Closes the confirmed gap that Foundry does not apply automatic content filtering to Claude models.                                                          |

  

*This completes design. Every requirement in the PRD now traces through
Conceptual, Logical, and Physical Architecture and High-Level Design to
a concrete schema, contract, or configuration value here. DevOps Setup
(Step 9) and Build (Step 10) implement what is specified in this
document — they do not make further design decisions of their own.*
