-- Real, individually-identified follow-up to 0009/0010: a fourth
-- diagnostic row, missed by both prior passes because it was created
-- (2026-09-11) and only approved (2026-09-12) after 0010 was written and
-- applied.
--
--   report_id=1113 ('Phase 9 diagnostic: confirms the real
--   set_config(tenant_id) UUID-vs-str fix works; not a real generated
--   report.', week_of=2026-09-21, program='Agentic AI Observability
--   Platform') — a real diagnostic artifact from verifying Task 42's
--   RLS tenant-context fix, not pipeline output.
--
-- Found already `reviewed = TRUE` with a real approval_records row
-- (approval_id=646, decided_at 2026-09-12 19:09:37 UTC, actor_id
-- e6e1593f-... resolving to the real owner identity,
-- entra_object_id 20f87799-...) — approved during the real Migration
-- Plan Phase 9 interactive sign-in verification, most likely a real
-- click against a diagnostic row that should never have been visible
-- as a candidate in the first place. This is NOT a hypothetical risk:
-- the approval already happened, and per the append-only guarantee
-- (ADR-023 REVOKE, ADR-028 trigger) it cannot be deleted or reversed by
-- any identity, including azure_pg_admin. Marking it as a test fixture
-- is the only available remedy — it stops it from appearing in
-- "Previous reports," the RAG index, or (had it not already been
-- reviewed) "Pending review," matching the exact treatment 0009/0010
-- already established for this class of row.
--
-- Deliberately by explicit report_id, not a date-range heuristic, same
-- reasoning as 0010: report_id=532's own real future Monday
-- (2026-09-14) must stay visible.
--
-- Idempotent: re-running touches zero rows the second time.

ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_week_of_is_monday;

UPDATE reports SET is_test_fixture = TRUE
WHERE report_id = 1113 AND NOT is_test_fixture;

ALTER TABLE reports ADD CONSTRAINT reports_week_of_is_monday
    CHECK (extract(dow FROM week_of) = 1) NOT VALID;
