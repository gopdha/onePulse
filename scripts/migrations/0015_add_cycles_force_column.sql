-- Task 55: the real force flag itself. An owner-only, default-off
-- request to bypass the real weekly collision for one cycle, recorded
-- on the cycles row (the same one core_api's trigger endpoint already
-- writes and reporting already reads in full via
-- get_cycle_for_execution) rather than threaded separately through the
-- report-cycles queue envelope -- one real source, not two.
--
-- Owner-level DDL (cycles is owned by app_role, ADR-023) -- same SET
-- ROLE dance as 0014.
SET ROLE app_role;

ALTER TABLE cycles ADD COLUMN IF NOT EXISTS force BOOLEAN NOT NULL DEFAULT FALSE;

RESET ROLE;
