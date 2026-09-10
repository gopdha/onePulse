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

## Real Application Role Privileges (as Actually Verified, Not Assumed)

**Superseded 2026-09-10 (Migration Plan Phase 6, CLAUDE.md Task 45).** The table this section
previously carried (dated 2026-09-09) documented a real asymmetry that existed at the time —
`app_role_local_dev` holding strictly more privileges than `app_role` on every table except
`approval_records` — but that asymmetry was itself an artifact of table **ownership**, not a
deliberate grant design: `app_role_local_dev` owned all 12 `public` tables (every migration had
always connected as it), and Postgres gives an owner every privilege unconditionally regardless of
any `GRANT`/`REVOKE` layered on top. ADR-023 (2026-09-10) retroactively transferred ownership to
`app_role` — the real, already-provisioned workload identity — and in doing so found the true grant
picture underneath was never what either the old table above or the original "same privileges"
claim described. Both were wrong, in opposite directions, for the same underlying reason: nobody
had checked whether an observed privilege was a real ACL entry or an ownership artifact. See
ADR-023 and Governance & Security Reference §6 for the full account of both directions of this bug.

**Current, live-verified state, both application schemas, confirmed by direct query of
`information_schema`/`pg_catalog` — not the migration files' stated intent:**

`app_role` and `app_role_local_dev` now hold **genuinely identical** real grants on every one of the
12 `public` tables — the original design intent (`create_app_role_local_dev.sql`: "must grant this
role the identical table-level privileges it grants `app_role`... divergence here would mean local
dev stops being genuine evidence about what the deployed workload can actually do") is true for the
first time, not merely stated:

| Table | Real grants (both roles, identical) |
|---|---|
| `tenants`, `portfolios`, `programs`, `findings`, `untracked_items`, `actors`, `actor_scope`, `usage_ledger`, `approval_records` | SELECT, INSERT |
| `configurations`, `reports`, `cycles` | SELECT, INSERT, UPDATE |

`approval_records` additionally has `UPDATE`/`DELETE` explicitly `REVOKE`d from both roles (the
append-only guarantee — Governance & Security Reference §2), and `DELETE` is granted nowhere at all,
same as always. **`app_role` genuinely owns all 12 tables and their 6 sequences** (confirmed by
direct `pg_class.relowner` query) — `FORCE ROW LEVEL SECURITY` is set on `reports` specifically so
this ownership cannot bypass `tenant_isolation` (see Trade-off #9).

**One real, additional, narrowly-scoped grant beyond the flat table above, found and needed only
because of a genuine Postgres mechanic, not a design choice:** both roles also hold column-level
`UPDATE` on exactly one column each of `tenants`, `portfolios`, `programs`, `actors`, and `findings`
— their own real primary key, the column every real foreign key in this schema references.
Postgres's internal FK-check row lock (`SELECT ... FOR KEY SHARE`, run automatically on every
`INSERT` into a table with a foreign key) requires `UPDATE` on the referenced table, not merely
`SELECT` — confirmed by direct, isolated empirical test (ADR-023), not assumed from documentation.
Scoped to the single referenced column specifically (not a blanket table-level `UPDATE`), confirmed
sufficient by the same test.

`investigation.investigation_runs` — `investigation_role` and `investigation_role_local_dev` are
likewise identical: `SELECT, INSERT, UPDATE`, no `DELETE`/`TRUNCATE`/`REFERENCES`/`TRIGGER`. Real,
if smaller, repeat of the exact ADR-023 finding: `investigation_role` picked up the same
owner-implicit widening the moment it became the schema's real owner (Migration Plan Phase 6,
Task 45), fixed by the identical `REVOKE ALL` + re-`GRANT` pattern
(`investigation_migrations/0002_reassert_investigation_grants.sql`). This table has no foreign keys
in or out, so the FK-check column-level grant does not apply here.

**Cross-schema isolation, both directions, reconfirmed live as part of this same audit:**
`app_role`/`app_role_local_dev` have zero `USAGE` on `investigation`; `investigation_role`/
`investigation_role_local_dev` have zero `USAGE` on `public`. Structural, not disciplinary — the
same real adversarial standard `tests/test_investigation_schema_isolation.py` already proves.

The two role PAIRS (`app_role`/`app_role_local_dev`, `investigation_role`/`investigation_role_local_dev`)
share no role-membership relationship with each other (`pg_auth_members` confirms no nesting). The
human developer identity is a plain member of `app_role`, `app_role_local_dev`, and
`investigation_role_local_dev` — which is how a local session can authenticate as any of them, not
evidence any two of them carry equal grants by construction; each pair's equality above was verified
independently, not inferred from membership.

---

## Real Migration Tooling

- `migrate.py` — idempotent, applies the full schema
- `verify_migration.py` — independently confirms every table, the generated column, every CHECK constraint's real values, RLS + policy, and the REVOKE actually holding — verified against live `information_schema`/`pg_catalog`, not just a clean exit code
- The verifier's own correctness was proven via 8 tests, each forcing a genuine failure mode against the real database — a verifier that has never been shown to catch drift is just a script that returns "OK" and hopes
