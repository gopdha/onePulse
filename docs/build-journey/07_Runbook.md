# OnePulse — Runbook

Practical, step-by-step operating instructions for this system, as actually used throughout development.

---

## 1. Environment Setup

```powershell
cd <repo root>
.venv\Scripts\Activate.ps1
```

The four backend services run as real containers via `docker compose` (Migration Plan Phase 5) —
see §2. This section covers the real Azure identity/credential state underneath them, current as of
Migration Plan Phase 6 (CLAUDE.md Task 45).

**Real per-service Managed Identities now exist and carry real RBAC/Postgres grants**
(`id-onepulse-app-dev` — shared by `core_api`/`reporting`, mapped to the Postgres `app_role`;
`id-onepulse-investigation-dev` — Investigation's own, mapped to `investigation_role`, plus Key
Vault `Secrets User`; `id-onepulse-bff-dev` — BFF's own, holding core_api's `Service.Access` app
role). **None of this is reachable from these LOCAL containers, confirmed by direct test, not
assumed:** a `curl` from inside a local container to Azure's Instance Metadata Service
(`169.254.169.254`, the endpoint `ManagedIdentityCredential` actually calls) fails to connect —
IMDS is only reachable from genuine Azure compute. Real Managed Identity auth becomes possible only
once these images run as real Container Apps (Phase 7).

Until then, `DefaultAzureCredential`'s `AzureCliCredential` fallback is what actually authenticates
every container — a real, once-per-environment interactive `az login --use-device-code`, its
resulting Linux-native token cache shared across all four containers via the `azure_cli_state` named
volume (see `docker-compose.yml`'s own header comment, and CLAUDE.md Task 44 for the real DPAPI
finding that led to this design). Confirm that volume holds a real, unexpired session before doing
anything real — Postgres, Foundry, Azure AI Search, Storage Queues, and Key Vault all rely on it.

**Azure DevOps is the one real exception to identity-based auth entirely, but is no longer a plain
env var.** ADO uses a scoped Personal Access Token (Work Items, read-only, 7-day expiry) — as of
Phase 6 it lives in Key Vault (`onepulse-kv-dev`, secret `ado-pat`), fetched at request time by the
Investigation service only, via its own `fetch_ado_pat_from_keyvault()`. This is still a deliberate,
time-boxed exception to the project's zero-static-secrets discipline (see Governance & Security
Reference §4 and Challenges & Real-World Findings #2 for why a PAT exists at all), but the PAT
itself no longer sits in any container's plain environment — confirmed live: `docker compose exec
investigation env` shows only `ONEPULSE_ADO_PAT_KEY_VAULT_URL`, never the PAT; `core_api`/`bff`/
`reporting` reference neither the PAT nor the vault URL at all. Because the underlying PAT still
expires every 7 days, a working `azure_cli_state` session alone is **not** sufficient to run the
pipeline — see §6 for the failure signature when it has lapsed.

---

## 2. Running the Pipeline

### Via the UI (recommended for demos)

**As of Migration Plan Phase 5, the four backend services run as containers, and `docker-compose.yml`
(repo root) is the real source of truth for the process shape — not this document.** It defines all
four service images, their dependency order, env var wiring, and port mapping directly; read it
rather than looking here for the literal startup sequence, which this Runbook no longer restates.
Streamlit stays a host process, deliberately not in the compose file — see its own header comment
for why (still local-first, and Phase 9 replaces it with a real frontend rather than ever
containerizing it).

**One-time setup, before the first `docker compose up`:** real Managed Identity is Phase 6 work: for
now, every container falls back to `DefaultAzureCredential`'s `AzureCliCredential`, same as every
local process before this phase — but a bind-mount of your own `~/.azure` does **not** work across a
Windows-host/Linux-container boundary (az CLI's token cache is DPAPI-encrypted on Windows, which a
Linux container cannot decrypt — confirmed live, not assumed; see §6). Populate the shared named
volume once instead, from inside a real container:

```powershell
docker compose run --rm --entrypoint az core_api login --use-device-code
```

Follow the printed URL/code once, in a browser, signing in with the same account you'd normally
`az login` with. Every container mounts the same `azure_cli_state` volume, so this is genuinely a
one-time step — not per-service, and not per-restart.

```powershell
docker compose up --build     # core_api, bff, investigation, reporting — in the order the file declares
streamlit run Home.py         # separate terminal, host process, unchanged
```

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

**Re-confirmed unchanged in containers (Migration Plan Phase 5, CLAUDE.md Task 44):** `docker kill
05onepulse-investigation-1` mid-run, then `docker compose up -d investigation` once the message
reappears (watch with the same real queue-peek technique), reproduces the identical real
before-and-after — the message goes invisible, reappears within the same real ~90s window, a fresh
container consumes it, and the run completes. `docker kill` sends `SIGKILL` directly (confirmed via
`docker compose ps -a` showing `Exited (137)`), an even more real "the process cannot clean up after
itself" test than a process-tree `taskkill` was.

**Real, expected asymmetry — don't try to shrink it:** `onepulse-investigation:phase5` is
substantially larger than the other three images (~1.83GB vs. ~1.33GB each, confirmed via `docker
images`) — the real cost of Node.js plus 219 npm packages living in exactly one container instead of
being a tax every service pays. This is Phase 4's own split made visible, not a regression to
optimize away this phase.

**As of Migration Plan Phase 5, the full-fidelity log moved to stdout** — container filesystems are
ephemeral, so the old `logs/<project>_<timestamp>.log` file would simply vanish on a container
restart, losing the only route to real per-tool-call detail (Trade-off #12). Same real content as
before (every tool call, the full draft/revision text, every PASS/FAIL check) for both Reporting and
Investigation; view it with `docker compose logs -f reporting` / `docker compose logs -f
investigation`. `ONEPULSE_DEBUG_SPAN_LOG` (see §4) still shows the real cross-service span chain when
needed for trace diagnosis.

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

- **A stale host-level process bound to `127.0.0.1` on the same port a container publishes to
  `0.0.0.0` can silently intercept traffic meant for the container — Windows allows both bindings to
  coexist without a "port already in use" error.** Confirmed live (Migration Plan Phase 5): leftover
  host processes from before this project's own local-process phase (never killed when switching to
  containers) kept `127.0.0.1:8000/8100/8200` bound while the containers correctly bound
  `0.0.0.0:8000/8100/8200` — `curl http://127.0.0.1:...` and every test against that address were
  silently hitting the stale host process, not the container, producing a confusing "the container
  never receives anything" symptom with no error anywhere. Before trusting any container-based test,
  confirm nothing non-Docker still holds the same ports: `netstat -ano | grep LISTENING | grep
  :8000` — if more than one PID appears, or a PID isn't the expected `com.docker.backend`-style
  proxy, kill the extras first. The exact same underlying lesson as the stale-process gotcha above,
  now recurring for a third time in this project's history — always confirm which process actually
  answered before trusting a result.
- **`@azure-devops/mcp` transitively depends on `keytar` (native credential-storage bindings), which
  needs `libsecret-1.so.0` at real runtime — absent from a minimal `python:3.12-slim` + Node.js image,
  and the resulting failure gives no hint of the real cause.** Confirmed live (Migration Plan Phase 5):
  the ADO MCP server crashed immediately on spawn inside the Investigation container, surfacing all
  the way up to Reporting as an opaque `mcp.shared.exceptions.MCPError: Connection closed` /
  `unhandled errors in a TaskGroup (1 sub-exception)`, with the real cause (`Error: libsecret-1.so.0:
  cannot open shared object file`) visible only by exec'ing into the running container and spawning
  the server binary directly (`docker compose exec investigation node
  investigation/node_modules/@azure-devops/mcp/dist/index.js ...`) — never in any log this project
  already had, since the MCP client bridge doesn't surface the spawned child's own stderr. Fixed by
  adding `libsecret-1-0` to the Investigation image's `apt-get install` list. If any future MCP-server
  dependency changes, re-verify by spawning it directly inside the container rather than trusting a
  clean `npm ci`.
- **A bind-mounted `~/.azure` does not work across a Windows-host/Linux-container boundary — az
  CLI's token cache is encrypted with the host OS's native secret storage (DPAPI on Windows) by
  default, and a Linux container has no way to decrypt it.** Confirmed live (Migration Plan Phase 5):
  `docker run -v "$USERPROFILE/.azure:/root/.azure" mcr.microsoft.com/azure-cli az account
  get-access-token` correctly reads the plaintext `azureProfile.json` (enough to know which user
  *should* have a cached token) but fails with `ERROR: User '...' does not exist in MSAL token
  cache. Run az login.` — a real decode/lookup failure, not a missing-file or permissions problem.
  The working fix is a real, one-time `az login --use-device-code` run inside a container using a
  shared **named volume** (not a bind-mount of the host path) — see §2 — which produces a genuinely
  Linux-native token cache every container sharing that volume can then use exactly like a normal
  `az login` session, going forward.
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
- **A new Entra RBAC/app-role assignment does not retroactively affect an already-issued, not-yet-
  expired access token.** Found live during Migration Plan Phase 6 (Task 45): adding core_api's
  `Service.Access` app role and assigning it did not fix BFF's real service-to-service call, which
  kept 403ing with `missing_app_role` — BFF's container had a real, still-valid cached access token
  (up to ~32 minutes of remaining life) acquired *before* the role assignment, and Azure AD does not
  invalidate a bearer token when the backing role assignment changes; the token remains valid with
  its original claims until natural expiry. `docker compose restart` does not help — the cache lives
  in the shared `azure_cli_state` volume, not the container's process memory. The real fix: clear
  only the `AccessToken` entries from `/root/.azure/msal_token_cache.json` inside the affected
  container (preserving `RefreshToken`/`Account` so no new interactive login is needed) — the next
  `get-access-token` call silently reacquires, picking up the new role. If a freshly-changed role
  assignment doesn't seem to be taking effect, check the cached token's real `expiresOn` before
  assuming the assignment itself is wrong.
