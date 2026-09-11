-- Real, individually-identified follow-up to 0009: migration 0009's own
-- backfill matched only the exact test_human_governance.py marker text
-- (440 rows). A direct check for any remaining report with an
-- implausible week_of (before 2025 or after 2035) not already marked
-- found exactly two more, both self-describing as test artifacts in
-- their own executive_summary text:
--   report_id=21  ('CLI end-to-end test report', week_of=4197-06-14)
--   report_id=95  ('Fixture row for testing the new single-page Reject
--                   popover flow (Task 19).', week_of=3273-02-17)
-- A third, report_id=999, is this same session's own deliberate Phase 8
-- SAS-download positive-control test report (CLAUDE.md Task 49) — real
-- data, not pipeline output, and the same category of "not something a
-- visitor should see as if it were a real report."
--
-- Deliberately by explicit report_id, not a date-range heuristic: a
-- genuinely real future-dated report is plausible (Task 47's own
-- report_id=532 uses a real future Monday, 2026-09-14, and correctly
-- stays visible) — marking by name avoids ever silently hiding real
-- data that merely has an unusual date.
--
-- Idempotent: re-running touches zero rows the second time.

-- Same real gotcha as 0009: any UPDATE re-validates every CHECK
-- constraint regardless of which column changed, and these three rows'
-- own week_of values aren't guaranteed to satisfy reports_week_of_is_
-- monday (0002, NOT VALID) even though it's irrelevant to this update.
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_week_of_is_monday;

UPDATE reports SET is_test_fixture = TRUE
WHERE report_id IN (21, 95, 999) AND NOT is_test_fixture;

ALTER TABLE reports ADD CONSTRAINT reports_week_of_is_monday
    CHECK (extract(dow FROM week_of) = 1) NOT VALID;
