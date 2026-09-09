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

**As of Migration Plan Phase 1, two processes must be running together** — `streamlit run Home.py`
alone now produces failed requests. Reviews (pending/approve/reject), the report list and detail
view, and chat all call the real FastAPI service; Streamlit no longer talks to Postgres/Search
directly for those:

```powershell
uvicorn api.main:app --port 8000    # in one terminal, from the repo root
streamlit run Home.py               # in a second terminal
```

Select a project from the dropdown (nothing loads until you do), then click Generate Status Report.

**Generation itself is the one real exception, deliberately not behind the API.** Clicking
"Generate Status Report" still calls `run_pipeline_cycle` directly, in-process inside Streamlit —
it does **not** go through `uvicorn api.main:app`. This is intentional, not a gap someone forgot to
wire up: the real LLD-specified trigger endpoint (`POST /api/v1/programs/{programId}/reports`,
returning `202` with a cycle handle) only becomes real in Migration Plan Phase 3, once execution
moves to a worker with a real status table behind it — building an in-memory cycle registry now
would be pure throwaway work. Don't read the API service as the whole story for how a report gets
generated, and don't go looking for a trigger endpoint that isn't there yet on purpose.

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
  freshly-inserted row — there is no "try it and delete it after" with this guarantee. Two real,
  safe alternatives instead: verify against a row that's already been reviewed (nothing new gets
  written), or use the same transactional-rollback pattern `tests/test_human_governance.py` uses
  (open a transaction, run the real check, roll back — every real constraint and error still fires,
  nothing is ever actually committed).
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
