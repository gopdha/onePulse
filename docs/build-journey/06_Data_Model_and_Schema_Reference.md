# OnePulse — Data Model & Schema Reference

This describes the **real, applied** Postgres schema, including where it deliberately deviates from the original LLD design and why.

---

## Real Tables

| Table | Purpose |
|---|---|
| `tenants` | Top of the hierarchy |
| `portfolios` | Grouping of programs |
| `programs` | A tracked ADO project (e.g., `singleSlide`, `Agentic AI Observability Platform`) |
| `configurations` | Per-program settings |
| `reports` | One row per generated weekly report |
| `findings` | Individual investigated items within a report |
| `untracked_items` | Initiatives mentioned in status decks with no matching ADO item |
| `approval_records` | Append-only audit trail of approve/reject actions |
| `actors` | Reviewer identities (currently a placeholder mechanism — see Trade-offs Log) |
| `actor_scope` | Actor-to-program access mapping |

---

## Real Deviations from the Original LLD — Found via Live-Data Cross-Check

Before applying the schema, the actual real JSON shapes being produced by the live pipeline (Investigation's Finding structure, Self-critique's verdict output, Synthesis's narrative) were checked against the LLD's design. Six real mismatches were found and resolved:

| # | LLD Design | Real Mismatch | Resolution |
|---|---|---|---|
| 1 | `findings.evidence TEXT[]` (array) | Real Investigation produces one evidence string per finding, never an array | Changed to `TEXT` |
| 2 | `findings.status_label` — no CHECK constraint specified | Real FR-1 taxonomy needed explicit enforcement, matching what `INVESTIGATION_SCHEMA` already enforces in code | Added `CHECK` constraint with the real four-level taxonomy |
| 3 | `untracked_items.match_confidence` (implies a numeric score) | Real Status Analysis produces `reasoning` (free text), never a number | Replaced with `reasoning TEXT` |
| 4 | `reports.curated_features` / `curated_initiatives` (JSONB NOT NULL) | Nothing in the live pipeline produces a "curated/merged" JSON shape — Synthesis outputs narrative text; Rendering uses raw findings directly | **Dropped entirely** — will be re-added via a real migration if a genuine curation phase is ever scoped |
| 5 | No column for the real `route_to_human_review` vs. `approved` distinction | HLD Section 3 / FR-4's revision-cap decision produces a third real outcome (`hard_stop_defect`, which never persists) that the original schema had no place for | Added `quality_gate_outcome TEXT CHECK (IN ('approved', 'route_to_human_review'))` |
| 6 | `findings.title` — not present in the original LLD summary | Discovered missing while writing the actual DDL | Added |

---

## Real, Verified Constraints

- **`UNIQUE(program_id, week_of)`** — `week_of` is Monday-bucketed via a shared helper function used consistently across persistence and rendering (see Challenges & Real-World Findings #5 for the bug this constraint originally had)
- **`manifest_complete`** — a `GENERATED` column, completeness enforced by the database itself, not application code
- **RLS on `reports`** — enabled ahead of its originally Next-scope timeline, per explicit instruction (documented deviation, not silent scope creep)
- **`REVOKE UPDATE, DELETE` on `approval_records`** — the project's most rigorously stress-tested guarantee (see Governance & Security Reference)
- **`reviewed BOOLEAN` + `quality_gate_outcome`** — used together: FR-7/FR-13 requires human approval for *every* rendered report, not just ones flagged `route_to_human_review`. The real filter for "needs review" is `reviewed = FALSE`; `quality_gate_outcome` is informational context in the response, not the filter itself.

---

## Application Role Privileges — Design Intent, and Where the Real Numbers Actually Live

**Rewritten 2026-09-10 (pre-Phase-7 audit, CLAUDE.md Task 45 follow-up), replacing a hand-maintained
snapshot table with a pointer to the machine-checked source of truth.** This section previously
restated the exact live grant set per table, twice — dated 2026-09-09, then corrected 2026-09-10
after ADR-023's ownership fix. Both versions were wrong for the identical underlying reason: prose
cannot distinguish a real ACL entry from an ownership artifact, and nobody had checked which one an
observed privilege actually was before writing it down. A table like that is stale the instant the
database changes under it, with nothing forcing it back into sync — precisely the shape of problem
`scripts/verify_migration.py` exists to solve for the schema itself; the same fix now applies to
its privileges. **What follows is the design intent — why two roles per service, why
`approval_records` is revoked, what the schema boundary is and isn't — not a restated snapshot.**

**Why two roles per service, not one.** `app_role`/`investigation_role` are the real, deployed
workload identities (Managed Identity-mapped, Phase 6) — the roles a running container actually
authenticates as. `app_role_local_dev`/`investigation_role_local_dev` exist so a human developer can
authenticate interactively against the identical grant surface, since the production roles cannot
authenticate outside a real Managed Identity token (confirmed directly, ADR-023). The local-dev
role is only useful as *evidence* about the deployed identity's real behavior if its grants
genuinely match — `create_app_role_local_dev.sql`'s own stated design. That equality is not assumed
here; it's one of the things `verify_migration.py` asserts directly, for both schemas, every run.

**Ownership is not the same question as a grant, and conflating them is the specific, recurring bug
this schema has produced.** A table's real owner (`pg_class.relowner`) has full access regardless of
any `GRANT`/`REVOKE` layered on top, and — the less obvious half, found only by testing it directly —
granting a privilege to an object's *own current owner* is a genuine Postgres no-op that never
materializes as a real ACL entry. This produced the identical failure mode twice: once for all 12
`public` tables (ADR-023), once for `investigation.investigation_runs` at the very next real
opportunity (Migration Plan Phase 6). A verification check that only confirms a table *exists*, or
that a role *has* an intended privilege, cannot catch this — proving the boundary is real requires a
third, separate assertion: that the privileges ownership silently confers beyond what's
intended (`DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, `MAINTAIN`, and `UPDATE` where it isn't
meant to exist) are genuinely *absent*, not merely that the intended ones are present.

**Why `approval_records` has `UPDATE`/`DELETE` explicitly revoked, from every application role, in
both schemas' terms.** It is this project's append-only audit trail of every approve/reject
decision (FR-7/FR-13) — Governance & Security Reference §2 documents the guarantee having survived
three separate, real, adversarial attempts to route around it, not merely a REVOKE statement nobody
has tried to defeat.

**What the `public`/`investigation` schema split is, and isn't.** It is a real, structural boundary
between the Reporting service and the Investigation service (Migration Plan Phase 4/ADR-020) —
neither service's role has any `USAGE` on the other's schema, adversarially proven in
`tests/test_investigation_schema_isolation.py`, not merely undocumented. It is **not** an isolation
boundary *within* either service's own role pair: the human developer identity is a plain member of
both `app_role`/`app_role_local_dev` and `investigation_role`/`investigation_role_local_dev`
(`pg_auth_members` confirms no nesting *between* the pairs, but real membership of the same human in
all of them) — worth stating plainly rather than leaving for a reader to derive, per Governance &
Security Reference §6.

**Why a real per-column `UPDATE` grant exists on one column each of `tenants`, `portfolios`,
`programs`, `actors`, and `findings`, beyond what the flat SELECT/INSERT profile implies.**
Postgres's internal foreign-key check (`SELECT ... FOR KEY SHARE`, run automatically on every
`INSERT` into a table with a foreign key) requires `UPDATE` on the referenced table, not merely
`SELECT` — confirmed by direct, isolated empirical test (ADR-023), not assumed from documentation.
Scoped to each table's own real primary key column specifically, not a blanket table-level grant,
also confirmed sufficient by the same test.

**The real, current numbers — ownership of every table and sequence, the intended positive grant
profile per production role, and the confirmed absence of ownership-implied excess — live in
`scripts/verify_migration.py`, not here.** Run `python scripts/verify_migration.py --target dev`
for the live state; `PUBLIC_TABLE_PROFILES`/`INVESTIGATION_TABLE_PROFILES` in that same file are the
literal, single source the intended profile is defined from, read directly rather than transcribed.
`check_object_owner`/`check_schema_owner` assert ownership; `check_has_table_privileges` asserts the
intended profile is present; `check_no_excess_table_privileges` asserts nothing ownership silently
conferred beyond it is. Every one of those checks has its own forced-failure test in
`tests/test_verify_migration.py`, proving each can actually detect drift, not merely report success
unconditionally — the same standard this document's own now-corrected history should have been held
to from the start.

---

## Real Migration Tooling

- `migrate.py`/`migrate_investigation.py` — idempotent, apply the full schema for `public`/`investigation` respectively
- `verify_migration.py` — independently confirms, for **both** schemas: every table/column/sequence, the generated column, every CHECK constraint's real values, RLS + FORCE + policy, ownership of every table and sequence, the intended positive grant profile per production role, and the confirmed absence of the privileges ownership transfer silently confers — verified against live `information_schema`/`pg_catalog`, not just a clean exit code. This is the current source of truth for real application-role privileges; see the section above rather than a restated table.
- The verifier's own correctness is proven test-by-test in `tests/test_verify_migration.py` (119 checks as of the pre-Phase-7 audit), each with a forced-failure counterpart against the real database — a verifier that has never been shown to catch drift is just a script that returns "OK" and hopes
