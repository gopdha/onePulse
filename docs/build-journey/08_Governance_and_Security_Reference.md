# OnePulse — Governance & Security Reference

This document describes guarantees that have been **proven through real, adversarial testing** — not just designed. Where a guarantee has a known limitation, it's stated plainly.

---

## 1. Zero Static Secrets

Every credential in this system is obtained dynamically via Managed Identity / Entra ID — there is no API key, password, or connection string stored anywhere in code or configuration, with one explicitly-tracked, time-boxed exception (see §4).

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
- The project's Entra Administrator role does **not** automatically have `BYPASSRLS` — confirmed via direct query (`rolbypassrls = False`). It already bypasses `reports`' RLS via table-ownership membership instead, a different and narrower mechanism.
- **Explicit decision**: `BYPASSRLS` was *not* granted to the admin role, even though doing so would have resolved a real, encountered friction point. Reasoning: it was confirmed via direct testing to be a complete no-op for the actual problem encountered, and represents standing future risk (a blanket bypass that could silently defeat RLS's guarantee once real multi-tenant enforcement matters) with zero present benefit.

---

## 4. The One Known, Time-Boxed Exception: The ADO Personal Access Token

**What it is**: A Personal Access Token scoped to Work Items (Read-only), 7-day expiration, used to work around an unresolved Azure DevOps tenant-identity issue (see Challenges & Real-World Findings #2).

**Why it exists**: Four real, distinct Managed-Identity-based authentication attempts against the `gopdha` ADO org failed with four different errors, tracing back to a genuine MSA/AAD tenant-duality issue in how that specific org is configured. Rather than block all further work indefinitely, a narrowly-scoped, explicitly-labeled exception was adopted.

**What makes this acceptable, not a silent violation of the zero-secrets principle**:
- Scoped to the minimum real permission needed (read-only, one resource type)
- Time-boxed (7-day expiry, not indefinite)
- Explicitly documented, in code comments and in the project's own tracking, as a diagnostic exception — not presented as the intended production pattern
- The underlying issue remains tracked as open technical debt, not abandoned

**Current status**: Still in use. The proper fix (resolving the Entra-ID identity duality) remains open.

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

**`app_role` and `app_role_local_dev` are not an isolation boundary between a deployed workload and a developer's own machine, and should not be described or relied on as one.** They provide different, deliberately narrower grant sets for `app_role` — a real, meaningful distinction — but they do not provide separation of *access*: the real Postgres Entra Administrator identity is a plain member of both roles (confirmed directly via `pg_auth_members`), so anyone who can authenticate as `app_role_local_dev` today can already `SET ROLE app_role` and act with its identity. This is worth stating explicitly rather than leaving it as something a reader has to derive by querying `pg_auth_members` themselves — a design that assumed these two roles kept humans and the deployed workload structurally apart would be relying on something that has never actually been true.

---

## 7. Secret Handling Discipline — Real Incidents, Real Response

Two real credentials were exposed directly in conversation during development (an ADO PAT, an Arize API key). Both were treated as compromised the moment exposure occurred — rotated immediately, not just "avoided going forward." This project's `.gitignore` includes an explicit, unusually broad set of secret-pattern exclusions (`.env*`, `*credentials*`, `*secrets*`, `*.pem`, `*.key`, etc.) with a comment directly acknowledging this real history, rather than a generic template.

Before any `git push`, this project's discipline is to explicitly verify `.env` was never committed at any point in history (`git log --all --full-history -- .env`), not just that it's currently ignored.
