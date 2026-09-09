# OnePulse — Runbook

Practical, step-by-step operating instructions for this system, as actually used throughout development.

---

## 1. Environment Setup

```powershell
cd <repo root>
.venv\Scripts\Activate.ps1
```

Confirm you're `az login`'d under the correct account and tenant before doing anything real —
Postgres and Foundry authentication both rely on `DefaultAzureCredential` falling back to this
session.

**Azure DevOps is the exception.** ADO does *not* authenticate via `DefaultAzureCredential`. It
uses a scoped Personal Access Token (Work Items, read-only, 7-day expiry), read from
`ONEPULSE_ADO_PAT` in `.env`. This is a deliberate, time-boxed exception to the project's
zero-static-secrets discipline, adopted after four real Managed-Identity authentication attempts
against the `gopdha` ADO org failed with four different errors, tracing to a genuine MSA/AAD
tenant-duality issue in how that org is configured. See Governance & Security Reference §4 and
Challenges & Real-World Findings #2. The underlying Entra-ID fix remains open technical debt; the
PAT is not the intended long-term pattern.

Because the token expires every 7 days, an `az login` session alone is **not** sufficient to run
the pipeline. See §6 for the failure signature when it has lapsed.

---

## 2. Running the Pipeline

### Via the UI (recommended for demos)

**As of Migration Plan Phase 3, four processes must be running together** — `streamlit run
Home.py` alone now produces failed requests, and clicking "Generate Status Report" with the worker
not running will queue a real cycle that simply never progresses past `queued` (no error — nothing
is watching the table yet). Reviews (pending/approve/reject), the report list/detail, chat, and now
generation itself all go through the BFF, which forwards each request to the core API; Streamlit no
longer talks to the core API (or Postgres/Search) directly for any of it, and no longer calls
`run_pipeline_cycle` at all:

```powershell
uvicorn core_api.main:app --port 8000   # terminal 1, from the repo root — start this first
uvicorn bff.main:app --port 8100        # terminal 2 — depends on core_api already running
python -m worker.main                   # terminal 3 — polls the real cycles table; order vs. bff doesn't matter
streamlit run Home.py                   # terminal 4
```

Select a project from the dropdown (nothing loads until you do), then click Generate Status Report.

**Generation is real now (Migration Plan Phase 3, ADR-021), and the two-path split Phase 1
deliberately left open is closed.** Clicking "Generate Status Report" calls the real LLD-specified
trigger endpoint (`POST /api/v1/programs/{programId}/reports`, a real `202` with a cycle handle) —
execution happens in `worker/main.py`, a separate local process that polls the real `cycles` status
table for queued work (`FOR UPDATE SKIP LOCKED`), executes the pipeline, and writes progress into
that same table *during* execution, not only at stage boundaries — reusing the exact
on_stage/on_detail heartbeat hook Task 39 already proved keeps every real gap under ~10s. The UI
polls `GET /api/v1/cycles/{cycleId}` roughly every three seconds (ADR-021) and renders whatever the
worker has already written. **The headline property this buys**: closing the browser tab entirely,
mid-run, does not touch the worker — the run completes and persists (or reaches whichever of the
four real terminal outcomes applies) regardless, because nothing in the browser or in Streamlit's
own process ever owned the work. No queue exists yet (that's Phase 4/ADR-019) — if the worker
process itself is killed mid-run, the run is lost; there is no redelivery yet. See CLAUDE.md Task 42
for the real, live-measured proof of both of these, in both directions.

The full-fidelity log file (`logs/<project>_<timestamp>.log`) is written by the worker now, not
Streamlit — same real content as before (every tool call, the full draft/revision text, every
PASS/FAIL check), just relocated a second time.

**Why two services instead of one, as of Phase 2 (ADR-017/ADR-018):** the BFF owns session,
identity resolution, and response shaping for the frontend — it holds no database connection, no
Azure AI Search client, and no Foundry client of any kind, enforced structurally, not just by
convention (`tests/test_bff_no_data_access.py` proves it via static import-graph analysis plus a
live, adversarial subprocess check of `sys.modules`). The core API owns the domain and every real
data connection. The BFF authenticates to the core API with a real Entra service-to-service token
(not a shared secret), and forwards the caller's Entra object ID via the
`X-Onepulse-Entra-Object-Id` header — the core API is the only place that ever resolves an object
ID into an internal `actor_id`; nothing external is ever trusted to supply one directly. There is
still no real reviewer authentication (that's Phase 8) — the BFF currently forwards a fixed stub
object ID (`ONEPULSE_STUB_ENTRA_OBJECT_ID`), but the real shape (a header carrying an identity the
core API resolves itself) is already in place for Phase 8 to slot a real token into.

### Via CLI (for scripted/headless runs)
```powershell
python scripts/run_pipeline.py --project "Agentic AI Observability Platform"
```
A real `argparse` guard is in place: `-h`/`--help` prints usage text and exits before any pipeline
logic runs, and an unrecognized flag exits with an error — neither triggers a real run against any
project. `--project` names the real Azure DevOps project to investigate; it defaults to
`singleSlide` (or `$ONEPULSE_ADO_PROJECT`, if set), but **singleSlide is retired as a test target**
— pass `--project` explicitly for any real invocation rather than relying on the default.

### What "Done" Actually Means
The pipeline can genuinely end in one of several states — don't assume "done" means "a new report was created":
- **Persisted, approved** — a new report exists, ready for review
- **Persisted, `route_to_human_review`** — a new report exists, flagged for extra scrutiny
- **Not persisted — already exists** — a report for this program/week already exists (the week-uniqueness constraint correctly prevented a duplicate); nothing new was created, and this is often the *correct* outcome, not a bug
- **`hard_stop_defect`** — the quality gate rejected the draft twice; nothing was rendered or persisted

Check the real log file (`logs/<project>_<timestamp>.log`) for full technical detail behind any of these outcomes.

---

## 3. Verifying Data Directly in Postgres

### Via VS Code (GUI, recommended)
1. Install the **official Microsoft PostgreSQL extension** for VS Code (not Azure Data Studio — retired; not the MSSQL extension — that's SQL Server-specific)
2. New Connection → Parameters tab:
   - Server: `onepulse-pg-dev.postgres.database.azure.com`
   - Database: `onepulse`
   - Authentication Type: `Entra Auth`
   - Entra Username: your real tenant-native UPN (**not** your MSA/gmail address — these are genuinely different identities for authentication purposes; see Challenges & Real-World Findings)

### Via Cloud Shell / psql (fallback, always works)
```bash
TOKEN=$(az account get-access-token --resource https://ossrdbms-aad.database.windows.net --query accessToken -o tsv)
PGPASSWORD=$TOKEN psql "host=onepulse-pg-dev.postgres.database.azure.com port=5432 dbname=onepulse user=<your-real-UPN> sslmode=require"
```
**Must be Bash**, not PowerShell — the `TOKEN=$(...)` syntax is Bash-specific. If Cloud Shell opens in PowerShell, switch the shell-type dropdown first.

### A Useful Real Query
```sql
SELECT r.report_id, p.name, r.week_of, r.rag_status, r.quality_gate_outcome, r.reviewed, r.created_at
FROM reports r JOIN programs p ON p.program_id = r.program_id
ORDER BY r.created_at DESC LIMIT 15;
```

---

## 4. Verifying Observability

### Application Insights
Portal → Application Insights resource → Transaction Search (GUI, no query needed) or Logs (Kusto):
```kql
dependencies
| where timestamp > ago(2h)
| summarize SpanCount = count() by operation_Id
| order by SpanCount desc
```
One `operation_Id` grouping all spans from a single run confirms correct trace propagation.

### Arize
Traces tab → click into a specific trace → confirm real `AGENT`/`LLM`/`TOOL` span kinds and real nested hierarchy. Note: the outer Traces list can occasionally show a misleading name/status on the root row even when the detail view underneath is fully correct — always click in before concluding something is wrong.

---

## 5. Git Workflow

```powershell
git status      # ALWAYS check first — confirm .env doesn't appear anywhere
git add .
git status      # check the staged list too, before committing
git commit -m "..."
git push
```

**Before ever running `git init` on this or a similar project**: create and verify `.gitignore` *first*. Once a secret is committed, removing it later doesn't remove it from history — a real incident happened in this project with an exposed PAT and API key, both requiring rotation.

To check whether a specific file was ever committed, at any point:
```powershell
git log --all --full-history -- .env
```
Empty output means it's genuinely never been committed.

---

## 6. Common Real Gotchas

- **If you hit any ADO failure, check whether the PAT has expired before assuming something new
  broke.** The token has a 7-day expiry and is not auto-renewed. An expired ADO PAT usually does
  *not* return a clean `401` — Azure DevOps commonly returns `203 Non-Authoritative Information`
  with an HTML sign-in page in the body, which a client expecting JSON then fails to parse. Through
  the MCP bridge this is likely to surface as a JSON parse error or unexpected-content-type
  failure, which reads like a new integration bug and will send you chasing the wrong thing.
  Check the token first: Azure DevOps → User settings → Personal access tokens on the `gopdha` org.
- **`az boards query --project X`** without an explicit `WHERE [System.TeamProject]` clause returns organization-wide results despite the `--project` flag
- **Cloud Shell may default to PowerShell**, not Bash — Bash-specific commands will fail with a generic PowerShell parse error if this happens
- **A newly-created Postgres server on PostgreSQL 18** revokes `CREATE` on schema from `PUBLIC` by default — a one-time admin grant is needed before the first migration
- **The Entra Administrator role for Postgres is not a full superuser** — it can manage roles but does not automatically bypass RLS
- **A `reports` row that gets a real `approve_report`/`reject_report` decision becomes permanently
  undeletable on that first write, and the `REVOKE` blocks recovering from it in either direction.**
  Both real delete paths fail with the identical `InsufficientPrivilegeError`:
  `DELETE FROM reports WHERE report_id=X` (Postgres checks the referencing `approval_records`
  table's own privileges as part of the delete) and `DELETE FROM approval_records WHERE
  report_id=X` (the `REVOKE UPDATE, DELETE` itself). This is the append-only guarantee working
  exactly as designed, not a bug to route around — and it has now bitten three separate times
  during ordinary work (report 306, report 320, report 532), correctly, every time. It will bite
  again the moment any one-off verification exercises `approve_report`/`reject_report` against a
  freshly-inserted row — there is no "try it and delete it after" with this guarantee. **Correction,
  found the hard way during Migration Plan Phase 2 (report 454):** "verify against a row that's
  already been reviewed" is *not* actually safe — `approve_report`/`reject_report` never check the
  row's current `reviewed` state before writing. Re-approving an already-reviewed report succeeds
  and inserts a second, real `approval_records` row for the same report, just as undeletable as the
  first. The only real safe alternative is the transactional-rollback pattern
  `tests/test_human_governance.py` uses (open a transaction, run the real check, roll back — every
  real constraint and error still fires, nothing is ever actually committed), or picking a row that
  has genuinely never been decided on and accepting the resulting permanent row as the real cost of
  testing against real infrastructure.
- **Old pre-Task-40 test-fixture `reports` rows can have a `week_of` far outside any sane calendar
  range** (some from years like 4396 or 9853 — leftovers from the old `_random_week_of()` test
  helper, before `tests/test_human_governance.py` was rewritten around transactional rollback).
  Migration `0002`'s `reports_week_of_is_monday` CHECK is `NOT VALID`, so these old rows were never
  retroactively validated and sat there quietly — but any real `UPDATE` against one (which is
  exactly what `approve_report`/`reject_report` do) re-checks the constraint on the new row image
  and fails with a genuine `CheckViolationError`, not a bug in the code doing the updating. Confirmed
  live during Phase 2 BFF verification (report 489). If a review action 500s with this error, check
  the row's actual `week_of` before assuming the service layer broke.
- **The RAG index is stale and contains no data for the project this system now tests against.**
  Confirmed live by direct query against the real Azure AI Search index: 57 total documents, 100%
  `program_name = 'singleSlide'`, zero for Agentic AI Observability Platform or Leave Tracker —
  51 report-level + 6 finding-level chunks, report_ids 1 through 51, matching Task 17's own last
  real `ingest_reports_to_search.py` run exactly and never re-run since (predates AOP being
  registered as a program at all). Asking the Chat Assistant anything about AOP today will get an
  honest "not found in any generated report" — correctly, since the index genuinely has nothing to
  retrieve, not because retrieval is broken. Don't read that as a chat quality problem. The fix is
  re-running `ingest_reports_to_search.py`, but not yet, and not naively: that script currently has
  no filter at all and would also pull in the accumulated `test_human_governance.py` fixture rows
  wholesale — the reindex is planned for a later migration phase (Migration Plan Phase 11 /
  ADR-022), alongside adding that filter, not as a standalone fix today.
