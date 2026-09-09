-- Migration Plan Phase 3 (ADR-021): the real status table. Pipeline
-- execution moves out of the request path into a worker; a run's
-- progress and terminal outcome now live here instead of in whichever
-- process happened to be running it — the property that lets a run
-- survive the client closing and be read by anything that can reach
-- the database, not only the process that started it.
--
-- Four real terminal outcomes (ADR-021's own list), plus two real
-- in-flight states and one genuine failure state for an unexpected
-- worker-side exception (distinct from `hard_stop_defect`, which is a
-- real, expected quality-gate outcome, not a crash):
--   queued                          -- inserted by the core API, not yet claimed
--   running                         -- claimed by the worker, executing
--   persisted                       -- quality_gate_outcome='approved', persisted
--   persisted_route_to_human_review -- persisted, flagged for review
--   not_persisted_already_exists    -- correct, not a failure — see ADR-021
--   hard_stop_defect                -- nothing rendered or persisted
--   failed                          -- a real, unexpected worker exception
--
-- `stages` is a real, structured curation of on_stage/on_detail events
-- (onepulse_common.cycle_progress — the same logic the UI used to build
-- in-process, relocated here since a non-UI process, the worker, is now
-- the one building it), written by the worker DURING execution — not
-- only at stage boundaries — via the exact on_stage/on_detail hook the
-- already-proven heartbeat mechanism (Task 39) already relies on.
--
-- `trace_context` carries the real W3C traceparent the core API's
-- trigger endpoint captured at enqueue time, so the worker can extract
-- it and nest its own root span under the SAME trace the request that
-- created this cycle started — the API-to-worker half of Phase 3's
-- tracing bar, the same real mechanism Phase 2 already proved across
-- the BFF-to-core-API hop.
--
-- No REVOKE here, unlike approval_records: this is a live, worker-
-- mutated status row, not an audit log — UPDATE is the whole point.
--
-- Idempotent: every statement can be re-run safely. Run via
-- scripts/migrate.py, never applied by hand.

CREATE TABLE IF NOT EXISTS cycles (
    cycle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id UUID NOT NULL REFERENCES programs(program_id),
    requested_by_actor_id UUID NOT NULL REFERENCES actors(actor_id),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running',
        'persisted', 'persisted_route_to_human_review',
        'not_persisted_already_exists', 'hard_stop_defect',
        'failed'
    )),
    stages JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_id BIGINT REFERENCES reports(report_id),
    error_detail TEXT,
    trace_context TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cycles_status_created_at_idx ON cycles (status, created_at);

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['app_role', 'app_role_local_dev']
    LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE ON cycles TO %I', r);
    END LOOP;
END $$;
