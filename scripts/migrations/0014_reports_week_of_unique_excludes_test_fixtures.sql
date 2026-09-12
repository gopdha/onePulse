-- Task 55: replace the plain UNIQUE(program_id, week_of) with a partial
-- unique index scoped to real (non-fixture) rows only.
--
-- Real motivation, not hypothetical: this real constraint is what
-- pushed the user to manually backdate week_of on real recent rows
-- (reports 1172/1173, and retroactively the six original non-Monday
-- AOP rows Task 39 could only infer the shape of) every time a real
-- fix needed testing twice against the same real program in the same
-- real week. That practice produced rows indistinguishable from real
-- data until someone went looking -- exactly the shape of mistake this
-- migration exists to make unnecessary.
--
-- The fix: keep the real weekly-dedup guarantee fully intact for every
-- real report (WHERE NOT is_test_fixture), and let is_test_fixture rows
-- bypass it entirely -- they are never enforced unique against each
-- other or against the real row for that week, matching the fact that
-- they are already invisible to every real-facing view
-- (list_recent_reports/list_pending_reviews/RAG ingestion, Task 49/55).
-- A forced re-run is now a disclosed, schema-enforced, automatically-
-- hidden row -- not one that looks like real data until inspected.

-- Both operations are owner-level (DROP CONSTRAINT, CREATE INDEX) --
-- reports is owned by app_role (ADR-023), and this migration is applied
-- as the real Postgres Entra Administrator, a plain member of app_role,
-- not app_role itself -- SET ROLE is required, same pattern as
-- migration 0011's own trigger-creation dance.
SET ROLE app_role;

ALTER TABLE reports DROP CONSTRAINT reports_program_id_week_of_key;

CREATE UNIQUE INDEX reports_program_id_week_of_real_key
    ON reports (program_id, week_of)
    WHERE NOT is_test_fixture;

RESET ROLE;
