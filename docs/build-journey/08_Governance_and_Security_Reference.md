# OnePulse — Governance & Security Reference

This document describes guarantees that have been **proven through real, adversarial testing** — not just designed. Where a guarantee has a known limitation, it's stated plainly.

---

## 1. Zero Static Secrets

Every credential in this system is obtained dynamically via Managed Identity / Entra ID — there is no API key, password, or connection string stored anywhere in code or configuration, with two explicitly-tracked exceptions, both named and bounded rather than silently accepted (see §4): one time-boxed (the ADO PAT), one permanent by the nature of the mechanism it serves (the Easy Auth client secret, added Migration Plan Phase 7 — see ADR-025). The two are not interchangeable instances of "one kind of thing"; §4 treats them as the different categories they actually are.

- **Postgres**: Entra-ID-only authentication (password auth is not even possible on the server)
- **Foundry**: `DefaultAzureCredential`, falling back to `az login` locally
- **Azure AI Search**: API-key auth disabled service-wide; RBAC-only, Entra ID token provider

---

## 2. The Append-Only Guarantee on `approval_records`

**This is the most rigorously tested guarantee in the entire system.** It has survived:

1. **A direct application-role `DELETE`/`UPDATE` attempt** — blocked by an explicit `REVOKE UPDATE, DELETE`, verified via a real `InsufficientPrivilegeError`.
2. **A parent-row deletion attempt** — deleting a `reports` row that has a real `approval_records` reference also fails, because Postgres's internal foreign-key integrity check itself requires privilege on the referenced table. This is *stronger* protection than the original design anticipated.
3. **A genuinely-executed privilege-escalation workaround** — a transient `GRANT SELECT` (not DELETE) was actually applied to see if it would satisfy the internal FK check. It did not — Postgres's real internal check uses `FOR KEY SHARE OF x`, which requires `UPDATE` privilege, not `SELECT`. The grant was immediately reverted and confirmed back to baseline.
4. **A principled stop before the one path that would have worked** — extending the grant to `UPDATE` was recognized as touching the exact privilege the guarantee exists to withhold, and was declined rather than executed, even though it was technically available.

**Conclusion**: this guarantee is not just designed correctly — it has been adversarially tested against real, escalating attempts to defeat it, and held.

---

## 3. Row-Level Security (RLS)

- Enabled on `reports` (built ahead of its originally Next-scope timeline, per explicit instruction — a documented deviation, not silent scope creep)
- **Not** enabled on `approval_records`, `findings`, or `untracked_items` — the append-only guarantee on `approval_records` comes from the `REVOKE`, not RLS
- The project's Entra Administrator role does **not** automatically have `BYPASSRLS` — confirmed via direct query (`rolbypassrls = False`).
- **Explicit decision**: `BYPASSRLS` was *not* granted to the admin role, even though doing so would have resolved a real, encountered friction point. Reasoning: it was confirmed via direct testing to be a complete no-op for the actual problem encountered, and represents standing future risk (a blanket bypass that could silently defeat RLS's guarantee once real multi-tenant enforcement matters) with zero present benefit.

**Corrected 2026-09-10 (Task 44 follow-up, ADR-023): this section previously described RLS as a real, tested guarantee, and separately described the admin's access to `reports` as an unconditional bypass. Neither was accurate.** `FORCE ROW LEVEL SECURITY` was never set on `reports` until this same follow-up, so ownership exemption applied unconditionally to whichever role owned the table: first `app_role_local_dev` (the direct owner), and the admin identity too, via its real membership in that owning role — **every role that has ever queried `reports` in this project's history was exempt from the policy for the entire time it existed.** The policy was genuinely enabled, genuinely installed, syntactically correct in every way that could be checked without running it — and structurally inert the whole time, because nothing that ever touched the table was subject to it.

It ran for the first time only as an incidental side effect of retroactively transferring table ownership to `app_role` (ADR-023) — and the first real evaluation failed outright: `current_setting('app.current_tenant_id')` is called with no `missing_ok` flag, in two places (one inside a subquery that SQL's `OR` does not guarantee short-circuits around), against a GUC that nothing anywhere in this codebase has ever set. A genuinely non-owner role touching `reports` for the first time hit `unrecognized configuration parameter`, not row filtering. Fixed to be permissive when the tenant context is unset (`0005_fix_tenant_isolation_policy_unset_guc.sql`), matching this project's real Now-scope single-tenant state.

**A second, direct consequence of the ownership transfer, closed in the same follow-up: `app_role` — now `reports`' real owner — would itself have been exempt from the policy meant to constrain it, the identical bug one level up.** Fixed by enabling `FORCE ROW LEVEL SECURITY` (`0006_force_row_level_security_on_reports.sql`). **State this precisely: FORCE makes the policy un-bypassable by ownership once it enforces something. It does not make it enforce anything today.** Confirmed by direct, adversarial test, not assumed from the `ALTER TABLE` succeeding: connected as the admin identity (a real member of `app_role`, the table's owner) and queried `reports` three ways — with no tenant context set, all 461 real rows returned (the permissive-when-unset fallback, genuinely active); with `app.current_tenant_id` set to a deliberately wrong UUID, zero rows returned. **This is a real, positive result, not just the removal of a bug: FORCE closed the admin's own ownership-membership exemption too, not merely the literal table-owner identity** — the admin's earlier-documented "bypasses via table-ownership membership" is no longer true when a tenant context is actually set; it remains true only in the sense that the permissive-when-unset fallback (not ownership) is what lets every real query through today, since nothing in this codebase sets that context on any real request yet. Real per-request tenant resolution is deliberately deferred to Phase 8's `get_current_actor()` work (see `12_Migration_Plan.md`'s Phase 8 Definition of Done, which now names this as a stated dependency) — validating a tenant-setter against this project's one real tenant row today would itself be unverifiable code, the same pattern this whole finding is about, just a smaller instance of it.

**This is the fourth real instance of the same class of finding in this project: a guarantee designed correctly, documented confidently, and never actually exercised** — joining `app_role_local_dev`'s undocumented excess privileges (§6, Task 39), `investigation.investigation_runs`'s wrong table owner (§6, Task 43), and the entire `public` schema's ownership (§6, Task 44/ADR-023). **The append-only `REVOKE` on `approval_records` is the deliberate counter-example, not another instance of the pattern**: it has been adversarially tested three separate, independent ways (a direct `DELETE`, a `SELECT`-based workaround attempt, a stop at the authorization boundary rather than escalating further — see §2) and held every time. The difference between these outcomes is not the design quality of either guarantee — both were built correctly the first time. It is entirely whether anyone ever actually ran the thing the guarantee claims to do. A guarantee that has only ever been reasoned about, never exercised against a real adversarial or even merely-different case, is a claim, not a fact — regardless of how confident the documentation describing it sounds.

---

## 4. The Two Known Exceptions to Zero Static Secrets

Two, not one — deliberately given equal visibility rather than letting the second one read as a
smaller footnote to the first. They are different in kind, not degree: the ADO PAT is time-boxed and
its underlying cause is tracked as open technical debt to eventually close; the Easy Auth client
secret is permanent, because the mechanism it serves has no secretless alternative today, not because
anyone chose not to look for one.

### 4a. The ADO Personal Access Token

**What it is**: A Personal Access Token scoped to Work Items (Read-only), 7-day expiration, used to work around an unresolved Azure DevOps tenant-identity issue (see Challenges & Real-World Findings #2).

**Why it exists**: Four real, distinct Managed-Identity-based authentication attempts against the `gopdha` ADO org failed with four different errors, tracing back to a genuine MSA/AAD tenant-duality issue in how that specific org is configured. Rather than block all further work indefinitely, a narrowly-scoped, explicitly-labeled exception was adopted.

**What makes this acceptable, not a silent violation of the zero-secrets principle**:
- Scoped to the minimum real permission needed (read-only, one resource type)
- Time-boxed (7-day expiry, not indefinite)
- Explicitly documented, in code comments and in the project's own tracking, as a diagnostic exception — not presented as the intended production pattern
- The underlying issue remains tracked as open technical debt, not abandoned

**Current status**: Still in use. The proper fix (resolving the Entra-ID identity duality) remains open.

### 4b. The `bff` Easy Auth Client Secret

**What it is**: A real client secret on the `onepulse-bff-signin` Entra app registration, generated once (`az ad app credential reset`, 1-year expiry) and stored only in the `bff` container app's own managed secret store — configured as the credential Azure Container Apps' built-in authentication (Easy Auth) presents to Entra for its own server-side AAD provider exchange (Migration Plan Phase 7, ADR-025).

**Why it is unavoidable**: This is not the same shape of problem Managed Identity solves anywhere else in this project. Every credential Managed Identity eliminated here — Postgres, Foundry, Search, Storage Queues — was an *outbound* call: this project's own code proving its own identity to another Azure resource. Easy Auth's own AAD provider is the opposite shape: the *platform*, on behalf of a signing-in browser, performs a server-side OAuth confidential-client authorization-code exchange with Entra — proving to Entra that whoever redeems the code is who it claims to be, before any identity belonging to this project's own code exists in that exchange at all. Confirmed directly by reading `az containerapp auth microsoft update`'s real parameter surface, not assumed: it accepts a client secret or a certificate, and nothing else — no Managed-Identity-federated option exists for this specific platform mechanism today.

**What bounds it**: scoped to exactly one purpose (this one AAD provider registration's own confidential-client exchange, nothing else); held in exactly one place (Container Apps' own managed secret store for `bff`, never in this project's own code, `.env`, or version control, never presented by any of this project's own code — only the platform's Easy Auth sidecar ever reads it); a real, bounded 1-year expiry rather than indefinite, even though the underlying *need* for some secret here does not expire the way the ADO PAT's diagnostic need eventually should.

**What would change if it ever became avoidable**: if Container Apps' own AAD provider ever adds a genuinely secretless mode for its own inbound exchange (not to be confused with Managed Identity federating this project's own outbound calls, which is already true and unrelated), or if this project moves off Container Apps' built-in authentication toward validating tokens itself (reopening ADR-018's own choice, a materially larger change than this one detail), this exception is removed then — not left in place out of inertia once an alternative genuinely exists. See ADR-025 for the full reasoning, including why this does not reopen or weaken ADR-024's separate, still-standing rejection of a Service Principal secret as a stand-in for Managed Identity itself — a different problem, correctly given a different answer.

**Current status**: In use, real, live-verified (Migration Plan Phase 7). No known path to removing it exists today; not being chased, since the platform provides none.

---

## 5. Reviewer Identity — An Honest, Stated Placeholder

The Human Governance API (`approve_report`, `reject_report`) requires an `actor_id`, correctly enforcing reviewer attribution at the database level. However, **there is currently no real authentication verifying that the caller genuinely is the actor they claim to be** — it's a trusted CLI argument / UI selection, not a verified identity.

This is stated plainly, both in code comments and in this document, rather than allowed to look more complete than it is. A real fix would resolve identity from a verified Entra ID token and match it against `actors.entra_object_id` — never trust a caller-supplied value.

---

## 6. Least-Privilege Investigation Scoping

Investigation's real ADO access is scoped via the MCP server's own tool catalog (`wit_query`, `wit_work_item`, etc.) — it cannot write to ADO. Combined with the deterministic Committed-Feature pre-scoping (see ADR-007), the system's real blast radius against a source ADO project is: read-only, limited to a specific, tag-defined subset of work items.

**Not yet formalized**: a complete, explicit mapping of least-privilege tool scoping against the full FR-1/FR-2 specification remains a real, open item (see Project Plan).

**Table ownership silently bypasses the entire grant model, and negative-only verification cannot detect it.** A least-privilege design built entirely from `GRANT`/`REVOKE` statements is only as good as the assumption that no role involved also happens to *own* the object — Postgres gives an object's owner every privilege on it unconditionally, regardless of any `GRANT`/`REVOKE` layered on top, and ownership is not visible to a check that only asks "does this role have privilege X" in the negative (a role can correctly show zero *explicit* grants while still having full *implicit* access via ownership). This project has hit this exact class of bug **three times**, independently, at three different layers:

1. **A documented privilege claim that was simply false** (CLAUDE.md Task 39): "`app_role_local_dev` has the same effective privileges as `app_role`" was asserted in an earlier task's own summary and never re-checked until a full privilege matrix was built across all 11 real tables — `app_role_local_dev` in fact holds strictly more privileges than `app_role` on every single one (DELETE, REFERENCES, TRIGGER, TRUNCATE, none of which `app_role` has). This was a documentation/assumption failure, not an ownership bug specifically, but the same root cause: nobody had verified the *positive* grant set directly against the database, only reasoned about it from what the migration *intended* to grant.
2. **A real object silently owned by the wrong role** (Migration Plan Phase 4 merge review, CLAUDE.md Task 43): `investigation.investigation_runs` was owned by `app_role_local_dev` — the Reporting service's own role — for the entire duration of Phase 4's development and live verification, giving Reporting full implicit access to the exact table the phase's whole design exists to wall off from it. Every schema-isolation check already in place (both negative-privilege checks, both existence checks) passed the entire time, because none of them asked the positive question — "can this role actually use this object, and if so, why." The gap was found only when a positive-grant check was added for an unrelated reason (auditing the new schema's shape) and immediately failed.
3. **The entire `public` schema, all 35 real objects** (ADR-023, CLAUDE.md Task 44 follow-up, pre-Phase-6 ownership audit): every one of the 12 real tables and their 6 sequences was owned by `app_role_local_dev`, not `app_role` — the role Phase 2 created specifically for the deployed workload identity, which had simply never been used for anything. Root cause: `migrate.py` had always connected as `app_role_local_dev` by default, so it became the owner of everything it ever created, on every one of this project's real migration runs. Fixing it retroactively surfaced three further, previously-invisible consequences purely because a genuinely non-owner role finally tried to use these tables for real — see ADR-023's own Consequences section for the full account: a GRANT-to-owner is a silent no-op that never persists a real ACL entry; a new owner automatically inherits privileges (`TRUNCATE`/`REFERENCES`/`TRIGGER`/`MAINTAIN`) nobody intended it to have; and Postgres's internal FK-check row lock requires `UPDATE`, not `SELECT`, on the referenced table — closing the exact open question Task 31 hit and left unresolved for `approval_records`/`reports`.

**The generalizable lesson, stated plainly so it isn't rediscovered a fourth time**: negative verification ("role X has no grant on object Y") proves discipline was followed; it does not prove the underlying assumption (which role owns Y) was ever true. Any schema-isolation or least-privilege claim in this system should be verified with both a negative check (the excluded role has no access) *and* a positive check (the intended role's access is real and matches what ownership would also grant) — a positive-only or negative-only check each miss half of what "the boundary holds" actually means. `verify_migration.py` now includes a positive-ownership check (`check_object_owner`) for exactly this reason.

**A fourth instance, found Migration Plan Phase 7, a different real mechanism but the same underlying class: a permission that looked correct and wasn't, never checked against what the code actually calls.** `id-onepulse-app-dev`/`id-onepulse-investigation-dev` were granted `Cognitive Services OpenAI User` in Phase 6 — a real, correctly-scoped role for the real-time inference calls this project's agents make, verified against the Schema Reference at the time. It does not cover a second, separate real Foundry operation every one of `core_api`/`reporting`/`investigation`'s own `enable_observability()` calls at startup: listing the project's own connections, to fetch the Application Insights connection string. This is not an ownership bug — nothing here is owned wrong — it is the identical *shape* of failure one layer up: a privilege that was reasoned about (inference calls need this role) rather than checked against the complete, real set of operations the code actually performs (startup also calls a control-plane read this role's data-plane grant doesn't reach). Every one of `core_api`/`reporting`/`investigation` crashed on first real deployment with a genuine `ClientAuthenticationError: (PermissionDenied) Principal does not have access to API/Operation` and then crash-loop-backed-off, invisible to every prior verification in this project's history because Phase 6's own checks ran under the broadly-privileged shared human credential, which was never subject to this narrower boundary at all — only a genuinely deployed Managed Identity, running the code for real for the first time, could have found it. **What specifically made this non-obvious, worth stating plainly rather than left implicit:** the failure came from `enable_observability()` — this project's own dual-telemetry setup, called once at process startup, ahead of any real request — not from anything in the actual investigation/reporting workload the RBAC grant was designed around. A permission gap in observability plumbing crash-loops the whole service before the workload it's meant to observe ever runs a single line, which reads exactly like "the deployment is broken" rather than "one specific, narrow, named operation lacks a grant" — the real diagnosis required reading the container's own startup traceback down to the exact SDK call (`get_application_insights_connection_string()`), not inferring it from the symptom. Fixed with the real, resource-type-correct role (`Foundry User` — this Foundry project resource's own documented recommendation, a superset covering both the control-plane read this gap needed and the data-plane access already granted, so the original `Cognitive Services OpenAI User` grant was left in place as redundant rather than removed).

**`app_role` and `app_role_local_dev` are not an isolation boundary between a deployed workload and a developer's own machine, and should not be described or relied on as one.** They provide different, deliberately narrower grant sets for `app_role` — a real, meaningful distinction — but they do not provide separation of *access*: the real Postgres Entra Administrator identity is a plain member of both roles (confirmed directly via `pg_auth_members`), so anyone who can authenticate as `app_role_local_dev` today can already `SET ROLE app_role` and act with its identity. This is worth stating explicitly rather than leaving it as something a reader has to derive by querying `pg_auth_members` themselves — a design that assumed these two roles kept humans and the deployed workload structurally apart would be relying on something that has never actually been true.

---

## 7. Secret Handling Discipline — Real Incidents, Real Response

Two real credentials were exposed directly in conversation during development (an ADO PAT, an Arize API key). Both were treated as compromised the moment exposure occurred — rotated immediately, not just "avoided going forward." This project's `.gitignore` includes an explicit, unusually broad set of secret-pattern exclusions (`.env*`, `*credentials*`, `*secrets*`, `*.pem`, `*.key`, etc.) with a comment directly acknowledging this real history, rather than a generic template.

Before any `git push`, this project's discipline is to explicitly verify `.env` was never committed at any point in history (`git log --all --full-history -- .env`), not just that it's currently ignored.
