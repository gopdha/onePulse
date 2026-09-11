-- Real cleanup of test-fixture noise in `reports` (CLAUDE.md Task 39/40's
-- own already-disclosed accumulation, ~440 rows from
-- test_human_governance.py before it was made transactional). A real
-- schema column, not a text match against the fixture marker string —
-- self-documenting, and doesn't depend on a real report never
-- coincidentally containing that exact executive_summary text forever.
--
-- Backfilled once, here, for the exact historical marker text
-- ('test_human_governance.py fixture row') — no ongoing mechanism needs
-- to set this going forward, since Task 40 already made the test suite
-- transactional (nothing it does is ever committed).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, backfill is a plain UPDATE
-- matched by content, safe to re-run (a second run touches zero rows).

ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_test_fixture BOOLEAN NOT NULL DEFAULT FALSE;

-- Real, live-discovered necessity: reports_week_of_is_monday (0002) is
-- NOT VALID (non-retroactive for existing rows), but Postgres
-- re-validates ALL check constraints on ANY UPDATE regardless of which
-- column changed — the exact gotcha already on record (Runbook §6,
-- Task 41). The fixture rows being backfilled here have real,
-- deliberately non-Monday week_of values, so the plain UPDATE below
-- fails immediately without this. Dropping and re-adding NOT VALID is
-- safe and changes nothing about the constraint's own semantics.
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_week_of_is_monday;

UPDATE reports SET is_test_fixture = TRUE
WHERE executive_summary = 'test_human_governance.py fixture row' AND is_test_fixture = FALSE;

ALTER TABLE reports ADD CONSTRAINT reports_week_of_is_monday
    CHECK (extract(dow FROM week_of) = 1) NOT VALID;
