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

**Correction (2026-09-09):** this section previously claimed `app_role_local_dev` has "the same
effective privileges as `app_role`... for testing purposes," and that both roles are limited to
`SELECT`+`INSERT` on `findings`/`untracked_items` with no `UPDATE`/`DELETE` "at all." Both claims
are false for `app_role_local_dev` — confirmed via a direct query of
`information_schema.table_privileges` against every real table in the schema (11 tables, not one).
`app_role_local_dev` holds strictly more privileges than `app_role` on every table except
`approval_records`:

| Table | `app_role` | `app_role_local_dev` |
|---|---|---|
| `actor_scope` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `actors` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `approval_records` | INSERT, SELECT | INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE |
| `configurations` | INSERT, SELECT, UPDATE | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `findings` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `portfolios` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `programs` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `reports` | INSERT, SELECT, UPDATE | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `tenants` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `untracked_items` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |
| `usage_ledger` | INSERT, SELECT | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE |

`app_role` — the production/workload identity — matches the original description: `UPDATE` allowed
on `reports`/`configurations`, `DELETE` not granted anywhere (a real, deliberate gap, not an
explicit `REVOKE`). `approval_records` is the **one** table where the original "same privileges"
claim holds: both roles genuinely lack `UPDATE`/`DELETE` there — the one table with an *explicit*
`REVOKE UPDATE, DELETE`, as opposed to every other table, where `app_role`'s narrower grants simply
were never widened. This narrower fact is Task 15's actual, original finding
("[`app_role_local_dev`] received the identical `REVOKE UPDATE, DELETE` in Task 14's migration" —
true, but scoped to that one table). It was later over-generalized into a schema-wide equivalence
claim that direct testing does not support.

The two roles share no role-membership relationship in either direction (`pg_auth_members` confirms
no nesting either way); the only real overlap is that the human developer identity is a plain member
of both, which is how a local session can authenticate as either — not evidence they carry equal
grants. Since this system is currently local-first, `app_role_local_dev` — the **more** permissive
role — is also the one that runs everything today, including the full test suite, not `app_role`.

---

## Real Migration Tooling

- `migrate.py` — idempotent, applies the full schema
- `verify_migration.py` — independently confirms every table, the generated column, every CHECK constraint's real values, RLS + policy, and the REVOKE actually holding — verified against live `information_schema`/`pg_catalog`, not just a clean exit code
- The verifier's own correctness was proven via 8 tests, each forcing a genuine failure mode against the real database — a verifier that has never been shown to catch drift is just a script that returns "OK" and hopes
