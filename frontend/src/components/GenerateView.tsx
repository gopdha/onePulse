// View 2: Generate Status Report — the 7-step progress view, driven by
// polling the real `cycles` status table (ADR-021), not by anything
// computed client-side. Mirrors Home.py's own `_render_stage_ui` icon
// rules exactly, including the real hard_stop_defect/route_to_human_
// review checkmark-vs-warning distinction (Task 32's own fix — an
// icon and its text must never contradict each other).

import { useEffect, useState } from "react";
import { Alert, Box, Button, Group, Progress, Stack, Text, Title } from "@mantine/core";
import { ApiError } from "../api/client";
import { useCycleStatus, useTriggerReport } from "../api/hooks";
import type { CycleStatus, StageState } from "../api/types";

// A 403 (not permitted, ever, for this role) and a 429 (permitted, but
// this actor's own quota is used up for now) are different situations
// with different correct next actions — collapsing both into a generic
// "Request failed with {status}" (what `String(err)` on a bare ApiError
// produces) told the user nothing they could act on. Real bug found
// live during Phase 10 device testing (CLAUDE.md Task 53): the
// underlying cause was in core_api's own error responses, not just this
// rendering — see core_api/main.py's new `http_exception_handler`.
function describeTriggerError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      return "You've used your report generations for today. Try again tomorrow.";
    }
    if (err.status === 403) {
      return "You don't have permission to generate reports for this project.";
    }
    if (err.status === 404) {
      return "This project isn't available to you.";
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

const STAGE_NAMES: Record<number, string> = {
  1: "ADO Investigation",
  2: "Status Reports Investigation",
  3: "Deterministic Rollup",
  4: "Synthesis",
  5: "Self-critique",
  6: "Rendering",
  7: "Persisting",
};

const TOTAL_STAGES = 7;

function fmtMMSS(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function StageRow({ n, stage, nowMs }: { n: number; stage: StageState | undefined; nowMs: number }) {
  const name = STAGE_NAMES[n];
  const s = stage ?? { status: "pending" as const, start_ts: null, end_ts: null, detail: null, live_note: null };

  if (s.status === "pending") {
    return (
      <Text size="sm" c="dimmed">
        ○ {name}
      </Text>
    );
  }
  if (s.status === "running") {
    const elapsed = s.start_ts ? nowMs / 1000 - s.start_ts : 0;
    return (
      <Text size="sm" fw={600} c="#1F3864">
        ● {name}
        {s.live_note ? ` — ${s.live_note}` : ""} · {fmtMMSS(elapsed)}
      </Text>
    );
  }
  if (s.status === "done") {
    const duration = (s.end_ts ?? nowMs / 1000) - (s.start_ts ?? nowMs / 1000);
    const raw = s.detail ?? "";
    // Same real distinction Task 32 fixed: a genuine hard_stop_defect
    // or route_to_human_review outcome must not render the same green
    // checkmark as a clean pass.
    let icon = "✓";
    let color = "#2f6b4f";
    if (raw.includes("hard_stop_defect")) {
      icon = "!";
      color = "#8A2F2F";
    } else if (raw.includes("route_to_human_review")) {
      icon = "!";
      color = "#9a6b1f";
    }
    return (
      <Text size="sm" c={color}>
        {icon} {name}
        {raw ? ` — ${raw}` : ""} · {fmtMMSS(duration)}
      </Text>
    );
  }
  if (s.status === "skipped") {
    return (
      <Text size="sm" c="dimmed">
        – {name}
        {s.detail ? ` — ${s.detail}` : ""}
      </Text>
    );
  }
  // failed
  return (
    <Text size="sm" c="#8A2F2F">
      ✗ {name} — failed: {s.detail ?? ""}
    </Text>
  );
}

const TERMINAL_SUMMARY: Record<string, { color: string; text: (reportId: number | null) => string }> = {
  persisted: { color: "green", text: () => "Report generated and saved." },
  persisted_route_to_human_review: {
    color: "yellow",
    text: () => "Report generated — flagged for human review.",
  },
  not_persisted_already_exists: {
    color: "blue",
    text: () => "No new report — one already exists for this program this week. This is frequently the correct result, not a failure.",
  },
  hard_stop_defect: { color: "red", text: () => "Generation stopped — the quality gate found a real defect. Nothing was rendered or saved." },
  failed: { color: "red", text: () => "Generation failed unexpectedly." },
};

export function GenerateView({ programId, isOwner }: { programId: string; isOwner: boolean }) {
  const trigger = useTriggerReport(programId);
  const [cycleId, setCycleId] = useState<string | null>(null);
  const cycle = useCycleStatus(cycleId);
  const [nowMs, setNowMs] = useState(Date.now());

  // Real per-second visual tick for the running-stage elapsed timers —
  // independent of the 3s poll interval, same as the Ops Console's own
  // live-ticking behavior.
  useEffect(() => {
    const running = cycle.data?.status === "queued" || cycle.data?.status === "running";
    if (!running) return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [cycle.data?.status]);

  if (!isOwner) {
    return (
      <Stack gap="xs">
        <Title order={5}>Generate Status Report</Title>
        <Text size="sm" c="dimmed">
          Visitors can view and download reports but cannot generate new ones.
        </Text>
      </Stack>
    );
  }

  const status: CycleStatus | undefined = cycle.data?.status;
  const isRunning = status === "queued" || status === "running";
  const summary = status ? TERMINAL_SUMMARY[status] : undefined;

  const doneCount = cycle.data
    ? Object.values(cycle.data.stages).filter((s) => s.status === "done" || s.status === "skipped" || s.status === "failed").length
    : 0;

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={5}>Generate Status Report</Title>
        <Button
          size="sm"
          loading={trigger.isPending}
          disabled={isRunning}
          onClick={async () => {
            const result = await trigger.mutateAsync();
            setCycleId(result.cycleId);
          }}
        >
          {isRunning ? "Running…" : "Generate report"}
        </Button>
      </Group>

      {trigger.isError && (
        <Alert color="red" title="Could not start">
          {describeTriggerError(trigger.error)}
        </Alert>
      )}

      {cycle.data && (
        <>
          <Progress value={(doneCount / TOTAL_STAGES) * 100} striped={isRunning} animated={isRunning} />
          <Box
            style={{
              background: "#fafbfc",
              border: "1px solid #e6e9ee",
              borderRadius: 9,
              padding: "14px 18px",
              maxHeight: 260,
              overflowY: "auto",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            <Stack gap={4}>
              {Array.from({ length: TOTAL_STAGES }, (_, i) => i + 1).map((n) => (
                <StageRow key={n} n={n} stage={cycle.data!.stages[String(n)]} nowMs={nowMs} />
              ))}
            </Stack>
          </Box>
          {summary && (
            <Alert color={summary.color} title={status}>
              {summary.text(cycle.data.reportId)}
            </Alert>
          )}
          {status === "failed" && cycle.data.errorDetail && (
            <Text size="xs" c="dimmed" ff="monospace">
              {cycle.data.errorDetail}
            </Text>
          )}
        </>
      )}
    </Stack>
  );
}
