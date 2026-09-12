-- Real, individually-identified follow-up to 0009/0010/0012: two more
-- non-real rows found live during Migration Plan Phase 9's own visitor-
-- identity audit (CLAUDE.md, 2026-09-12), left unmarked deliberately at
-- the time only because they needed to stay visible in
-- list_recent_reports for a pending real visitor-role UI verification.
--
--   report_id=997 ('Meridian Patient Portal is on track this week...',
--   week_of=2030-01-07) and report_id=998 ('...patient records
--   migration is blocked...', week_of=2030-01-14) — Migration Plan
--   Phase 8's own fictional Meridian Health seed data
--   (scripts/seed_phase8_test_data.py), real findings text but
--   fictional content, never corresponding to any real ADO project.
--   Both were `reviewed = FALSE`, meaning both sat live in Meridian
--   Health's own "Pending review" list with a real, clickable
--   Approve/Reject control — precisely the shape that produced reports
--   532, 454, and 1113 (see Runbook §6). The visitor-role UI check that
--   needed them visible has been deferred (ADR-031); that reason no
--   longer applies, so they are marked now rather than left waiting for
--   a fourth instance of the same recurring cause.
--
-- Deliberately by explicit report_id, not a date-range heuristic, same
-- reasoning as 0010/0012: report_id=532's own real future Monday
-- (2026-09-14) must stay visible, and these two rows' far-future
-- week_of values (2030) are themselves part of what makes them
-- fictional test data, not the marking criterion on their own.
--
-- Idempotent: re-running touches zero rows the second time.

ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_week_of_is_monday;

UPDATE reports SET is_test_fixture = TRUE
WHERE report_id IN (997, 998) AND NOT is_test_fixture;

ALTER TABLE reports ADD CONSTRAINT reports_week_of_is_monday
    CHECK (extract(dow FROM week_of) = 1) NOT VALID;
