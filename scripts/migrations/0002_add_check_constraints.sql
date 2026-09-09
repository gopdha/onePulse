-- Migration 0002: two defensive CHECK constraints found necessary by
-- direct investigation (2026-09-09/09-10), neither part of the original
-- schema.
--
-- 1. reports.week_of must be a real Monday. Confirmed directly:
--    persist_report() (onepulse_common/pipeline.py) takes week_of as a
--    plain parameter and does no bucketing itself -- it trusts the
--    caller (run_pipeline_cycle, which calls report_rendering.week_of())
--    to have already Monday-bucketed it. The database itself never
--    enforced this. Confirmed live: 400+ non-Monday rows already exist
--    (the large majority are test-suite fixtures from
--    tests/test_human_governance.py's own deliberately-random week_of,
--    now fixed separately; a handful are real historical rows from a
--    since-discarded diagnostic script that called persist_report()
--    directly with a manually varied date). Added NOT VALID -- Postgres's
--    standard non-retroactive form: enforced on every future INSERT/
--    UPDATE, existing rows are never scanned or rejected and are left
--    exactly as they are.
--
-- 2. approval_records: a 'rejected' decision must carry real, non-empty
--    notes. Previously enforced only in application code
--    (onepulse_common.human_governance.reject_report's own
--    NotesRequiredError check, which runs before any database write) --
--    nothing stopped a direct INSERT from bypassing it. Confirmed live
--    that zero existing rows violate this, so added as a normal
--    (validated) constraint, not NOT VALID.
--
-- Idempotent, matching this project's existing migration convention:
-- DROP CONSTRAINT IF EXISTS before ADD CONSTRAINT, since ADD CONSTRAINT
-- itself is not naturally re-runnable.

ALTER TABLE reports
    DROP CONSTRAINT IF EXISTS reports_week_of_is_monday;
ALTER TABLE reports
    ADD CONSTRAINT reports_week_of_is_monday
    CHECK (extract(dow FROM week_of) = 1) NOT VALID;

ALTER TABLE approval_records
    DROP CONSTRAINT IF EXISTS approval_records_rejected_notes_required;
ALTER TABLE approval_records
    ADD CONSTRAINT approval_records_rejected_notes_required
    CHECK (decision != 'rejected' OR length(trim(notes)) > 0);
