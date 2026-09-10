# OnePulse — Migration Plan v3: React, BFF, Core API, and two workers on Azure Container Apps

Supersedes plan v2. Changes in this revision: the Investigation/Reporting split and queue
coordination added as Phase 4 (ADR-019/020); the status table and Blob Storage folded into Phases 3
and 7 (ADR-021); RAG indexing placement recorded (ADR-022).

Same shape as the original Build Plan (§12.2) — every phase has a Definition of Done provable with
real evidence, not assertion. Governed by ADR-015 through ADR-022.

**Sequencing principles**
1. FastAPI first, with Streamlit kept locally as a temporary client. The deployed container never
   contains Streamlit, so nothing throwaway gets built and every cloud problem is debugged against a
   UI already known to work.
2. Build one thing, prove it, then split it. Splitting something that works reveals what the boundary
   costs; starting split does not.
3. No public ingress until reviewer identity is real (Phase 8).

---

## Phase 0 — Prerequisites

| Item | Why |
|---|---|
| Close out the in-flight Claude Code work: `week_of` uniqueness check, tag-stripping hardening, MCP version pin, completion logging, spotlighting audit | Do not migrate on top of a possible data-integrity regression or an unpinned dependency that already caused one outage. |
| Confirm a clean end-to-end run on AOP at the reduced scope | The regression baseline everything after is measured against. **`singleSlide` and `Leave Tracker` are retired as test targets** — they never had proper test data. AOP is now tagged down to 1 Committed Feature with 11 children for a fast cycle; the 6-feature / 115-item scope is restored by re-tagging in ADO. |
| Add unit coverage for ADR-012's report-format selection | Retiring `singleSlide` removes the only exercise of the flat-findings fallback path — and of the `WorkItemType == "Epic"` check added after a stray legacy parent link triggered the wrong format. Unit tests over the selection logic replace that regression guard more cheaply than keeping a project alive. |
| Seed a second `programs` row before Phase 8 | With one program, a scope filter that silently does nothing is indistinguishable from one that works. A second program with a couple of seeded reports is enough to make a leak visible, and is what makes Phase 8's Definition of Done meaningful. No second ADO project is needed. |
| Resolve the test-fixture pollution in `reports` | 425 of 445 rows are fixtures from `test_human_governance.py`, still accumulating. `list_recent_reports` returns fixtures ahead of real output, and `ingest_reports_to_search.py` has no filter, so a reindex would push fixtures into the RAG corpus. Phase 1 builds the query layer that carries this forward; Phase 4 would pollute the core schema specifically. |
| Append ADR-015 through ADR-022; amend ADR-010; update Trade-offs Log entries 5, 6, 12 | Record the decisions before building against them. |
| Commit `docs/build-journey/` to the repository, or add a Task-number mapping table | The 13-document set is not in version control, and `CLAUDE.md` carries a parallel record under different numbering. ADR references currently do not resolve on the machine doing the work. |
| Decide what data external visitors will see | The generated narrative names real assignees and towers. If any maps to real client work, that is a confidentiality question, not a technical one. |

**Definition of Done**: a clean run producing a persisted, approvable report, with the ADR set
updated and committed.

---

## Phase 1 — FastAPI, single service, behind existing Streamlit

Implement the endpoint contract specified in LLD §10.2 and never built: report trigger returning
`202` with a cycle handle, pending reviews, approve, reject (`400 notes_required` on empty notes),
and chat query.

Do not modify `onepulse_common` — FastAPI wraps the proven functions. Pydantic models mirror
constraints the database already enforces. Rewire Streamlit to call the endpoints instead of
importing directly.

**Definition of Done**: a full real run, an approval, a rejection blocked for empty notes, and a
cited chat answer — all over HTTP, with Streamlit behaving identically to its baseline. Prove the
empty-notes rejection is still refused at the database level too, not only by Pydantic.

---

## Phase 2 — Split into BFF and core API (ADR-017)

Still local. One variable changes: the service boundary.

- **BFF**: session, identity resolution, response shaping. **No data stores of any kind.**
- **Core API**: the domain, every data connection, dispatch to workers.
- BFF authenticates to the core API with an Entra token for the core API's own app registration —
  not a shared secret, not a trusted header.
- Decide and record ADR-017's open question: does the BFF pass the actor down, or does the core API
  resolve identity independently?

**Definition of Done**: a real request traversing both services under Managed Identity
authentication, and **one connected trace in Arize spanning both** — W3C `traceparent` propagated
across the HTTP boundary. Third re-verification of the single-root-span guarantee; hold it to the
same standard as the previous two.

---

## Phase 3 — Separate pipeline execution, and add the status table

- Pipeline runs in a worker, not inside a request or a UI process
- **Status table** in Postgres with the four terminal outcomes (ADR-021), written *during* long
  stages and not only at stage boundaries
- Retire ADR-009's `threading.Event` plumbing and `contextvars` propagation
- Observability moves to application lifespan rather than `@st.cache_resource`

**Definition of Done**: start a run, close the client entirely, confirm it completes and persists.
Confirm the trace is still one correctly grouped tree. Confirm no silent gap longer than ~30 seconds
appears in the status table during the `list_comments` window.

---

## Phase 4 — Split Investigation from Reporting, coordinated by a queue (ADR-019, ADR-020)

Still local — use Azurite or a real Storage account, but not yet deployed.

- **Investigation service**: ADO MCP, Python + Node. Owns the investigation schema and its own role.
- **Reporting service**: synthesis, self-critique, rendering, persistence. Owns the core schema.
- Two queues: `investigation-requests` and `findings-ready`
- Investigation results keyed on cycle ID, so at-least-once redelivery overwrites rather than
  accumulates
- Dequeue-count limit and dead-letter path built deliberately
- Reporting obtains findings from Investigation **over HTTP**, never from its schema

**Definition of Done**: a real run completing across both services via the queues. A **real query
from the Reporting service's database role against the investigation schema, shown failing with a
permission error** — tested adversarially, in the same spirit as the append-only guarantee. Kill the
Investigation service mid-run and confirm the message redelivers and the run completes.

---

## Phase 5 — Containerize, locally

- Investigation image carries **both Python and Node.js**; every other image is Python only
- `az login` credentials still mounted in — identity is deliberately not changed yet
- Logs to stdout / Application Insights rather than `logs/<project>_<timestamp>.log`

**Definition of Done**: a real run completes across the containerized services. Verify `node` and
the pinned `@azure-devops/mcp` are present in the running Investigation container and absent from
the others — installed at image build time via `npm ci`, never resolved at spawn time. Run once at
the reduced scope for the loop, then re-tag AOP to the full 6-feature scope and run once more:
concurrency behaviour under 115 items is not exercised by 11.

> **The reduced-scope leg may not be available when this phase starts — confirm before relying on
> it, don't rediscover it here.** Phase 4 (CLAUDE.md Task 43) tried to re-tag AOP down and found no
> safe, working way to remove a `Committed` tag in this environment: `az boards work-item update
> --fields "System.Tags=X"` only ever ADDS to existing tags, never replaces or removes; `az rest`/
> `az devops invoke` against `dev.azure.com` both fail for this org via the same real MSA/AAD
> tenant-duality issue on record since Task 4 (a sign-in-page redirect instead of an API response);
> and the project's own `ONEPULSE_ADO_PAT` is deliberately read-only. Phase 4's own verification ran
> the full 115-item scope four times instead and treated that as the harder, load-bearing case. If
> this phase needs the small-then-full pattern specifically (not just "a real run," but a genuine
> low-concurrency-then-high-concurrency comparison), resolve a real tag-mutation path first — or pick
> a different, genuinely small real project to register instead of trying to shrink AOP in place.

---

## Phase 6 — Managed Identity, replacing `az login`

- User-assigned Managed Identity per service
- `Cognitive Services OpenAI User` on Foundry; data-plane role on `onepulse-search-dev`
- Postgres Entra principals mapped to the per-service roles — `app_role` was created in the original
  Phase 2 for exactly this purpose and has never actually been used
- ADO PAT to Key Vault, granted **only** to the Investigation service's identity
- Blob Storage and Queue data-plane roles

> **Amended 2026-09-10 (CLAUDE.md Task 45, ADR-024) — the original Definition of Done below was
> written before a real, structural fact was known: genuine Managed Identity auth (the IMDS-based
> mechanism) is unreachable from a local container, confirmed by direct test (a `curl` to
> `169.254.169.254` from inside a container fails to connect, not a permissions error). "A full run
> with zero interactive credentials available" cannot be proven from these local containers — not a
> shortfall in this phase's execution, a structural property of where these containers run. See
> ADR-024 for the full decision and why a Service Principal secret was rejected as a substitute.**
>
> **What this phase actually proved, real and complete:** every identity, RBAC grant, Postgres role
> mapping, and Key Vault secret this phase's own bullet list calls for — created and live-verified
> by direct query, not configured and assumed. The ADO PAT reachable only by Investigation's
> identity, demonstrated via direct RBAC query and a live container environment dump. A real,
> full-scope end-to-end AOP run through the complete chain (BFF's own new service-to-service app-role
> check, core_api, Postgres, Foundry, Key Vault) with the shared local credential standing in for
> the identity call this environment cannot make. `verify_migration.py` and the full suite green.
>
> **What remains genuinely unproven, deferred to Phase 7 explicitly, not silently:** that any of
> these real identities can actually authenticate a container via true Managed Identity end to end,
> with the shared `azure_cli_state` volume absent or demonstrably unused. This is Phase 7's own
> Definition of Done now, stated there directly — not something to rediscover when Phase 7 starts.

**Definition of Done, revised**: every identity/RBAC/Postgres-role/Key-Vault item above created and
live-verified (not merely configured); the ADO PAT's access boundary demonstrated by direct query,
not asserted; a real, full-scope AOP run completing through the whole chain with these grants
engaged; a grep for static credentials (the check used in the original Phase 1); each role's live
grants confirmed against the Schema Reference — the first time these roles carry real load.
**Not** part of this phase's Definition of Done, by explicit decision: a literal zero-interactive-
credential run — deferred to Phase 7 (see above and ADR-024).

---

## Phase 7 — Deploy to Azure Container Apps, ingress restricted

**Not public.** Internal or IP-restricted until Phase 8 lands.

- Azure Container Registry (Basic); Container Apps environment + Log Analytics
- BFF: external ingress. Core API, Reporting, Investigation: internal only.
- One Storage account for both the queues and the rendered-report blob container
- `rendered_artifact_uri` begins holding a blob path; download by short-lived user-delegation SAS
  issued after an authorisation check
- KEDA queue-depth scaling on the Investigation service; `minReplicas: 0` elsewhere, raised to 1
  temporarily before demos
- Built-in Entra authentication enabled from the first deployment
- Postgres network access from the Container Apps environment

> **Carries forward a real, stated dependency from Phase 6 (ADR-024) — not something to rediscover
> here.** Phase 6 provisioned every real identity, RBAC grant, and Postgres role mapping this
> phase's containers now need, and proved all of it live except the one thing no local container
> could prove: that Managed Identity auth actually works, end to end, when a container is real
> Azure compute. This phase is where that becomes checkable for the first time — make it a real,
> explicit part of this phase's own Definition of Done, not an assumption carried in from Phase 6.

**Definition of Done**: local Streamlit, pointed at the deployed BFF, completes a real run, a real
approval, and a real report download via SAS. Measure the real cold-start time on the Python + Node
image rather than assuming published figures. Confirm the core API and both workers are genuinely
unreachable from outside the environment. **A real run completing with the `azure_cli_state` volume
absent or demonstrably unused by these containers — proving Managed Identity auth actually works
end to end, not merely that it was configured in Phase 6** (Postgres via `app_role`/
`investigation_role`, Foundry, Search, Key Vault, Queues — the same real grants Phase 6 already put
in place, now exercised for the first time by the identity they were actually granted to, not a
shared human credential standing in for it).

---

## Phase 8 — Real reviewer identity and the role model

Gating for any public URL. Closes Governance & Security Reference §5 — acceptable on `localhost`, a
live hole once strangers can reach the app, and made worse by `approval_records` being permanently
unerasable.

- `get_current_actor()` resolving the platform-verified Entra identity against
  `actors.entra_object_id`; applied to every route; `actor_id` never accepted from the client
- Owner versus visitor roles. `actors`, `actor_scope`, and RLS on `reports` all exist from the
  original Phase 2 and have never been enforced.
- Read-only visitor mode: generate disabled, browsing and chat enabled. Recommended shape for
  external sharing — a real run takes ~6 minutes with a long quiet stretch, while the Tower View,
  approval flow, and cited chat answers are all instant.
- If triggering is ever opened to visitors, FR-11's rate limit (2/day) and NFR-6's usage-ledger check
  must exist first. Neither is built.

> **RLS enforcement is a stated dependency of this phase, not something to rediscover here** (see
> ADR-023, Trade-off #9, Governance & Security Reference §3). The policy exists, is syntactically
> correct, and — as of the pre-Phase-6 ownership fix — can no longer be bypassed by table ownership
> (`FORCE ROW LEVEL SECURITY`). It enforces nothing today, because nothing sets
> `app.current_tenant_id` on any real request. This phase is where that input first exists (a real,
> verified identity), so this phase is where the setter belongs:
> - `get_current_actor()`'s own resolution should also resolve the caller's real tenant —
>   `actor_scope` → (`portfolio_id`/`program_id`) → `portfolios.tenant_id`, the identical join
>   `tenant_isolation`'s own policy subquery already performs.
> - `SET LOCAL app.current_tenant_id = <resolved tenant>` inside the transaction, in both `core_api`
>   and `reporting` — the only two of the four services that ever touch `reports` (`bff` has no data
>   store access by design; `investigation` has no access to the `public` schema by design).
> - Scoped, not open-ended: three call sites already wrap in an explicit transaction and just need
>   the `SET LOCAL` added (`approve_report`, `reject_report`, `persist_report`); three more are
>   currently bare reads and need an explicit transaction wrap added first (`get_report_detail`,
>   `list_pending_reviews`, `list_recent_reports`).
> - **Enforcement must be proven against a second real tenant row, not the one that exists today.**
>   A pass with a single tenant proves nothing — it cannot distinguish "isolation works" from "there
>   was never anything to isolate from." This is exactly the class of finding this whole correction
>   is about; do not let Phase 8 repeat it by testing a guarantee that still only has one case to run
>   against.

**Definition of Done**: an attempt to approve while supplying a different `actor_id` than the
authenticated identity is rejected — shown as a real request and a real error. A visitor-role account
cannot trigger a run, and cannot retrieve a SAS for a report outside its scope. `reports`' RLS policy
is proven to actually filter — a second real tenant's reports genuinely invisible to a caller scoped
to the first, shown by a real query under each context, not inferred from the policy text. **Opening
ingress to the public is part of this phase's DoD, not an earlier one.**

---

## Phase 9 — React frontend

Vite + React + TypeScript. TanStack Query for server state. A real component library rather than
hand-rolled CSS — the original Phase 11 lost time to a CSS contrast bug inside a Streamlit wrapper
div and a column-width overflow regression. No authentication library and no token handling
(ADR-018).

Three views matching the Ops Console: project selector plus report table with approve/reject; the
7-step progress view driven by polling the status table; and the chat assistant scoped to the
selected project.

**Definition of Done**: feature parity with the Ops Console, including the empty-by-default project
selector and correct icon behaviour on `hard_stop_defect` outcomes.

---

## Phase 10 — Serve the frontend

FastAPI serves the built bundle from a single origin (ADR-015 amendment). Azure Static Web Apps
considered and not chosen.

**Definition of Done**: a real end-to-end run triggered from a browser on a device that is not the
development machine, including a successful report download.

---

## Phase 11 — Retire Streamlit and update the record

- Remove the Streamlit client
- Runbook: ADO PAT correction, deployment steps, pre-demo warm-up step
- Current-State Architecture §1 and §6
- Trade-offs Log: entries 5, 6, 12 resolved or superseded; 15–21 added
- Build a `reindex` command alongside `migrate.py` and `verify_migration.py` (ADR-022)

**Definition of Done**: no section of the documentation set still describes the local-only
architecture as current.

---

## Cross-cutting

| Concern | Requirement |
|---|---|
| Observability | The single explicit root span must survive every architecture change. Already re-verified once under threading; this migration changes the execution model four more times (Phases 2, 3, 4, 7). Queue hops lose `traceparent` unless it is deliberately carried in the message envelope — the most likely thing to be discovered late. |
| Cost | Scale-to-zero keeps compute inside the free grant. Added spend is Container Registry (~US$5/mo) and Log Analytics. A cloud UI largely cancels the Postgres stop/start saving. |
| Content Safety | ADR-014 remains draft, pending verification of the deployment's filter configuration. A public URL is a reasonable trigger to settle it. |
| Regression discipline | Test before fix, evidence before "done". |
