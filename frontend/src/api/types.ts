// Real response shapes, mirroring core_api/main.py's own Pydantic
// models exactly (camelCase, matching the frontend contract Phase 1
// established) — not re-derived, kept in sync by hand since there is no
// shared schema generator in this project.

export type RagStatus = "Red" | "Amber" | "Green" | "Unknown";
export type QualityGateOutcome = "approved" | "route_to_human_review";
export type StatusLabel = "On Track" | "At Risk" | "Blocked" | "Needs Human Review";
export type Decision = "approved" | "rejected";

export interface MeResponse {
  role: string;
  isOwner: boolean;
  authorizedProgramIds: string[];
}

export interface ProgramItem {
  programId: string;
  name: string;
}

export interface ReportSummary {
  reportId: number;
  programName: string;
  weekOf: string;
  ragStatus: RagStatus;
  qualityGateOutcome: QualityGateOutcome;
  reviewed: boolean;
  renderedArtifactUri: string | null;
  createdAt: string;
  decision: Decision | null;
  findingCount: number;
}

export interface FindingItem {
  findingId: number;
  sourceItemRef: string | null;
  title: string;
  statusLabel: StatusLabel;
  evidence: string;
}

export interface UntrackedItem {
  untrackedItemId: number;
  description: string;
  evidence: string | null;
  possibleLinkedFindingId: number | null;
  reasoning: string | null;
}

export interface ReportDetail {
  reportId: number;
  programName: string;
  weekOf: string;
  ragStatus: RagStatus;
  qualityGateOutcome: QualityGateOutcome;
  executiveSummary: string;
  renderedArtifactUri: string | null;
  reviewed: boolean;
}

export interface ReportDetailResponse {
  report: ReportDetail;
  findings: FindingItem[];
  untrackedItems: UntrackedItem[];
}

export interface TriggerResponse {
  cycleId: string;
  status: string;
}

export interface DownloadResponse {
  downloadUrl: string;
  expiresInMinutes: number;
}

// The real cycles.status CHECK taxonomy (core_api/main.py's own
// CycleStatus Literal) — "queued"/"running" are in-flight; the other
// five are terminal, four of them the real ADR-021 outcomes named
// explicitly in this phase's own bar, "failed" a fifth, distinct,
// unexpected-worker-exception state (onepulse_common/cycle_progress.py).
export type CycleStatus =
  | "queued"
  | "running"
  | "persisted"
  | "persisted_route_to_human_review"
  | "not_persisted_already_exists"
  | "hard_stop_defect"
  | "failed";

export type StageRunStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface StageState {
  status: StageRunStatus;
  start_ts: number | null;
  end_ts: number | null;
  detail: string | null;
  live_note: string | null;
}

// Real keys are ints (1-7) but JSON object keys are always strings once
// this crosses the wire — read with Number(key) at render time.
export type Stages = Record<string, StageState>;

export interface CycleStatusResponse {
  cycleId: string;
  status: CycleStatus;
  stages: Stages;
  reportId: number | null;
  errorDetail: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface Citation {
  reportId: number;
  programName: string;
  weekOf: string;
  sourceItemRef: string | null;
  findingTitle: string | null;
}

export interface ChatQueryResponse {
  answer: string;
  citations: Citation[];
}

export interface ApiErrorBody {
  error?: string;
  message?: string;
  detail?: unknown;
}
