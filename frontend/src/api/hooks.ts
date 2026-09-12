// TanStack Query hooks — one per real endpoint. Server state lives here
// exclusively; no duplicate copies in component-local state.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";
import type {
  ChatQueryResponse,
  CycleStatusResponse,
  DownloadResponse,
  MeResponse,
  ProgramItem,
  ReportDetailResponse,
  ReportSummary,
  TriggerResponse,
} from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<MeResponse>("/api/v1/me"),
    staleTime: 5 * 60 * 1000, // Real role/scope changes are rare; a 403
    // from any later mutating call is still the actual enforcement —
    // this staleness only affects which buttons render, never what's
    // allowed (see core_api/main.py's own get_me docstring).
  });
}

export function usePrograms() {
  return useQuery({
    queryKey: ["programs"],
    queryFn: () => apiGet<ProgramItem[]>("/api/v1/programs"),
  });
}

export function useReports(programId: string | null) {
  return useQuery({
    queryKey: ["reports", programId],
    queryFn: () => apiGet<ReportSummary[]>(`/api/v1/reports?programId=${programId}`),
    enabled: programId !== null, // Real, deliberate: nothing fetches
    // before a project is picked (Demo Narrative's own empty-by-default
    // decision, Ops Console precedent) — this is the mechanism, not a
    // loading spinner shown for no reason.
  });
}

export function useReportDetail(reportId: number | null) {
  return useQuery({
    queryKey: ["report", reportId],
    queryFn: () => apiGet<ReportDetailResponse>(`/api/v1/reports/${reportId}`),
    enabled: reportId !== null,
  });
}

export function useTriggerReport(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<TriggerResponse>(`/api/v1/programs/${programId}/reports`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports", programId] });
      // A real trigger just consumed one of FR-11's own counted slots —
      // refetch "me" so the remaining-count display doesn't sit stale
      // against `useMe`'s own 5-minute staleTime until the next
      // unrelated remount. A refused (429) attempt never reaches
      // onSuccess, correctly: nothing was actually consumed.
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useCycleStatus(cycleId: string | null) {
  return useQuery({
    queryKey: ["cycle", cycleId],
    queryFn: () => apiGet<CycleStatusResponse>(`/api/v1/cycles/${cycleId}`),
    enabled: cycleId !== null,
    // ADR-021's own stated cadence — the same real polling interval the
    // Ops Console already uses against this exact table.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const terminal =
        status === "persisted" ||
        status === "persisted_route_to_human_review" ||
        status === "not_persisted_already_exists" ||
        status === "hard_stop_defect" ||
        status === "failed";
      return terminal ? false : 3000;
    },
  });
}

export function useApprove(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reportId: number) => apiPost(`/api/v1/reviews/${reportId}/approve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports", programId] });
    },
  });
}

export function useReject(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reportId, notes }: { reportId: number; notes: string }) =>
      apiPost(`/api/v1/reviews/${reportId}/reject`, { notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports", programId] });
    },
  });
}

export function useDownloadReport() {
  return useMutation({
    mutationFn: (reportId: number) => apiGet<DownloadResponse>(`/api/v1/reports/${reportId}/download`),
  });
}

export function useChatQuery() {
  return useMutation({
    mutationFn: ({ question, programId }: { question: string; programId: string | null }) =>
      apiPost<ChatQueryResponse>("/api/v1/chat/query", { question, programId }),
  });
}
