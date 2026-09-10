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

**As of Migration Plan Phase 4, FIVE processes must be running together** — Investigation is now
its own service, coordinated with Reporting through two real Azure Storage Queues rather than an
in-process function call. `worker/` was renamed `reporting/` (it's still the same claim-a-cycle,
run-stages-2-7 process Phase 3 built); a new `investigation/main.py` service owns stage 1 entirely.
Reviews, the report list/detail, and chat still go through the BFF → core API, unchanged from Phase
2/3; the BFF/core API themselves never talk to Investigation directly — only Reporting does.

```powershell
uvicorn core_api.main:app --port 8000        # terminal 1, from the repo root — start this first
uvicorn bff.main:app --port 8100             # terminal 2 — depends on core_api already running
uvicorn investigation.main:app --port 8200   # terminal 3 — the Investigation service; start before reporting
python -m reporting.main                     # terminal 4 — polls cycles AND dispatches to Investigation over the queue
streamlit run Home.py                        # terminal 5
```

Order matters more than in Phase 3: Reporting's first real action on claiming a cycle is sending an
`investigation-requests` message, so Investigation should already be listening before Reporting
claims real work (a message sent to a not-yet-running consumer just waits in the queue — nothing
breaks, but it's a needless delay while you're paying attention to it live).

Select a project from the dropdown (nothing loads until you do), then click Generate Status Report.

**What actually happens now, Phase 4 (ADR-019/020):** Reporting claims a queued cycle exactly as in
Phase 3 (`FOR UPDATE SKIP LOCKED`, unchanged), but instead of calling `investigate()` in-process, it
sends a real `investigation-requests` message (`cycle_id`, `program_name`, `requested_by_actor_id`,
a fresh injected W3C `traceparent`) and polls `findings-ready` for the matching `cycle_id`. The
Investigation service — the only process with a Node runtime and ADO PAT access — picks the message
up, runs the real investigation, upserts its results into its own `investigation.investigation_runs`
row (keyed on `cycle_id`, so a redelivery overwrites rather than accumulates), and sends a thin
`findings-ready` notification back. Reporting then fetches the real findings over a plain HTTP
`GET /internal/investigations/{cycleId}` call to the Investigation service — **never** by querying
the `investigation` schema directly; there is no grant that would even let it (see §6). Progress
writes to `cycles.stages` continue exactly as in Phase 3, including a heartbeat while Reporting
waits on the queue round trip, so the UI never sits silent for more than ~10s even though the
granular per-tool-call detail that used to stream live now lives only in Investigation's own log
(`INVESTIGATION_BASE_URL`, `ONEPULSE_INVESTIGATION_PG_ROLE` — see `.env.example`).

**The headline property Phase 4 adds, proven live (CLAUDE.md Task 43): a hard-killed Investigation
process is now recoverable, not just a hard-killed worker.** Phase 3's own baseline (Task 42): a
worker killed mid-run leaves its cycle stuck at `running` forever, invisible even to a freshly
started worker, since nothing was watching for it. Real, repeated Phase 4 test: kill the
Investigation process tree mid-run (its `investigation-requests` message is already invisible,
leased for `VISIBILITY_TIMEOUT_SECONDS=90`) — the message stays invisible for the remainder of that
lease (confirmed via a direct queue peek showing zero visible messages, though
`approximate_message_count` still counts it), then becomes visible again once the lease expires
with no renewal (a dead consumer, by definition, can't renew), gets picked up by a **freshly
started** Investigation process, and the run completes end to end. Closing the browser tab (Phase 3's
own guarantee) and killing Investigation (Phase 4's new one) are now both survivable; only killing
Reporting itself still loses the in-flight run (Reporting's own claim has no queue redelivery behind
it — same as Phase 3, deliberately unchanged, since Reporting's own dispatch-to-Investigation step is
idempotent and safe to just re-trigger).

The full-fidelity log file (`logs/<project>_<timestamp>.log`) is still written by Reporting, same
real content as before for stages 2-7; Investigation's own per-tool-call detail is not in that file
— it's in Investigation's own process output (or, when actually needed for live incident diagnosis,
`ONEPULSE_DEBUG_SPAN_LOG` on both services shows the real span chain, see §4).

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

### The `investigation` schema (Migration Plan Phase 4, ADR-020)
`investigation.investigation_runs` is a **separate schema with a separate role**
(`investigation_role_local_dev` locally) — the same Entra login above connects to it fine as the
admin, but `app_role`/`app_role_local_dev` (what Reporting/core API/BFF connect as) genuinely cannot
query it at all: `SELECT * FROM investigation.investigation_runs` from that role fails with
`InsufficientPrivilegeError: permission denied for schema investigation`, by real Postgres GRANT, not
by convention. Reporting never queries this schema; it fetches Investigation's results over HTTP
instead (see §2). To apply a migration against this schema, use `scripts/migrate_investigation.py`,
not `scripts/migrate.py` — connecting as the Investigation role itself so it owns its own schema from
first `CREATE SCHEMA`, avoiding the ownership-transfer trap `0001_initial_schema.sql`'s own header
comment documents in detail.

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

### Proving a trace crossed a process boundary directly, without an Arize Developer Access key
Set `ONEPULSE_DEBUG_SPAN_LOG=<path to a .jsonl file>` before starting any service (`core_api`,
`bff`, `reporting`, `investigation` all wire it in their own `main()`/lifespan) — it adds a real,
additional `SimpleSpanProcessor` to the process's already-configured `TracerProvider`, appending one
JSON line per span at real `on_end()` time (`{service, name, trace_id, span_id, parent_span_id,
start_time, end_time}`) — the exact same span objects every other configured exporter (Application
Insights, Arize) also receives. Point two or more services at the **same** file to interleave their
real spans and directly confirm a parent-child chain across an HTTP or queue hop by eye: grep for
each service's named root span (e.g. `"reporting run_cycle"`, `"investigation POST
investigation-requests"`) and check that one's `span_id` equals the other's `parent_span_id`, under
an identical `trace_id`. No-op with zero overhead when the env var isn't set. This is how the
Reporting→Investigation queue-hop trace was proven for real in Migration Plan Phase 4 (CLAUDE.md
Task 43) — a named span only appears in the file once it *ends*, so a long-running root span (the
whole cycle) won't show up until the whole run finishes.

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

- **A Postgres Flexible Server client-IP allowlist rule drifts silently — a real network reconnect
  mid-session (a new public IP) causes every NEW connection to hang and time out
  (`OSError: [WinError 121] The semaphore timeout period has expired`) while already-open pool
  connections keep working fine, and every OTHER Azure endpoint (Foundry, Entra login, Storage
  Queues) stays reachable.** This reads exactly like a code bug in whichever service is starting
  fresh, not a firewall problem, because the symptom is service-specific and asymmetric. Isolate it
  by testing raw TCP connectivity directly (`socket.create_connection((host, 5432), timeout=10)`) —
  if that alone times out while HTTPS to other Azure hosts is instant, check
  `az postgres flexible-server firewall-rule list --resource-group onepulse-gr --server-name
  onepulse-pg-dev -o table` against your current IP (`curl https://api.ipify.org`) before chasing
  anything in the code. Fix: `az postgres flexible-server firewall-rule create --resource-group
  onepulse-gr --server-name onepulse-pg-dev --name <rule-name> --start-ip-address <ip>
  --end-ip-address <ip>` (note: `--name` is the *rule* name; `--server-name` is separate — an easy
  swap to get backwards, since the CLI's own error for the wrong combination is unhelpful). Hit live
  during Migration Plan Phase 4 verification.
- **Stale processes from an earlier session (or an earlier terminal in the same one) silently race
  freshly-started ones for the exact same real work — `FOR UPDATE SKIP LOCKED` and queue consumption
  both correctness-guarantee against duplicate PROCESSING, not against a confusing race for WHICH
  process wins.** A pre-rename `worker.main` process left running from before `worker/` became
  `reporting/` claimed a real cycle before the newly-started `reporting.main` could, using its own
  stale in-process code (which itself resolved a `node_modules` path that no longer existed after
  the Investigation-service move) — producing an error that looked like a real code bug in the new
  service, not what it actually was. Before trusting any test result, confirm which processes are
  really running and on which ports/PIDs: `Get-CimInstance Win32_Process -Filter "Name='python.exe'"
  | Select-Object ProcessId, CommandLine`. Note this also legitimately shows TWO processes per
  `uvicorn`/`python -m` launch on Windows — a thin `.venv\Scripts\python.exe` redirector plus the
  real interpreter underneath it (not a bug, not a duplicate service; only the latter binds ports or
  does real work) — don't mistake that pairing itself for the stale-process problem.
- **`az boards work-item update --fields "System.Tags=X"` only ever ADDS to the existing tags — it
  cannot remove one, regardless of what value you pass** (confirmed live: setting `Tags=` to empty,
  or to the desired final value alone, left the old tags untouched; only a genuinely new tag value
  gets unioned in). There is no working mechanism in this environment to fully replace/remove a tag
  via script: `az rest`/`az devops invoke` against `dev.azure.com` both fail for this org specifically
  — the same real MSA/AAD tenant-duality issue already documented in §1/Governance & Security
  Reference §4 (a generic AAD token gets a sign-in-page redirect, not an API response, the identical
  failure shape the PAT gotcha above describes for an expired token) — and the project's own
  `ONEPULSE_ADO_PAT` is deliberately read-only (`401` on any write). Don't attempt to mutate real ADO
  tags via script for a one-off test without first confirming a working write path exists; a
  temporary, unremovable extra tag is real, permanent debris on shared data, not a clean rollback.
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
