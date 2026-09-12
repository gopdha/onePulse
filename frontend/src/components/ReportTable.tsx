// View 1: the report table — latest run, recent history, approve/
// reject for owners, download via the real SAS flow. Feature parity
// target: the Ops Console's own "Previous Status Reports" section.

import { useState } from "react";
import { Badge, Button, Group, Loader, Modal, Stack, Table, Text, Textarea, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { ApiError } from "../api/client";
import { useApprove, useDownloadReport, useReject, useReports } from "../api/hooks";
import type { QualityGateOutcome, RagStatus, ReportSummary } from "../api/types";
import { ReportDetailModal } from "./ReportDetailModal";

const RAG_COLOR: Record<RagStatus, string> = {
  Red: "red",
  Amber: "yellow",
  Green: "green",
  Unknown: "gray",
};

const QUALITY_LABEL: Record<QualityGateOutcome, string> = {
  approved: "Approved by QA",
  route_to_human_review: "Needs human review",
};

function reviewLabel(r: ReportSummary): string | null {
  if (!r.reviewed) return null;
  if (r.decision === "approved") return "Approved";
  if (r.decision === "rejected") return "Rejected";
  return "Reviewed";
}

export function ReportTable({
  programId,
  programName,
  isOwner,
}: {
  programId: string;
  programName: string;
  isOwner: boolean;
}) {
  const reports = useReports(programId);
  const approve = useApprove(programId);
  const reject = useReject(programId);
  const download = useDownloadReport();
  const [detailReportId, setDetailReportId] = useState<number | null>(null);
  const [rejectTarget, setRejectTarget] = useState<number | null>(null);
  const [rejectNotes, setRejectNotes] = useState("");

  async function handleDownload(reportId: number) {
    try {
      const { downloadUrl } = await download.mutateAsync(reportId);
      window.location.href = downloadUrl;
    } catch (err) {
      if (err instanceof ApiError && err.code === "artifact_predates_blob_storage") {
        // Real, distinct situation from "never had one" (CLAUDE.md Task
        // 55): this report was rendered before the pipeline uploaded to
        // Blob Storage for real — its file lived only inside a
        // `reporting` container that has since recycled. Genuinely,
        // permanently gone, not a bug to retry.
        notifications.show({
          color: "yellow",
          title: "File no longer exists",
          message: "This report was generated before downloads were wired up for real — its original file no longer exists.",
        });
      } else if (err instanceof ApiError && err.code === "artifact_not_available") {
        notifications.show({
          color: "yellow",
          title: "No downloadable artifact",
          message: "This report has no real file available for download.",
        });
      } else {
        notifications.show({ color: "red", title: "Download failed", message: String(err) });
      }
    }
  }

  async function handleReject() {
    if (rejectTarget === null) return;
    try {
      await reject.mutateAsync({ reportId: rejectTarget, notes: rejectNotes });
      setRejectTarget(null);
      setRejectNotes("");
      notifications.show({ color: "green", title: "Rejected", message: "Report rejected." });
    } catch (err) {
      if (err instanceof ApiError && err.code === "notes_required") {
        notifications.show({ color: "red", title: "Notes required", message: "Rejection notes cannot be empty." });
      } else {
        notifications.show({ color: "red", title: "Reject failed", message: String(err) });
      }
    }
  }

  if (reports.isLoading) {
    return <Loader size="sm" />;
  }

  const rows = reports.data ?? [];

  return (
    <Stack gap="sm">
      <Title order={5}>{programName} — Status Reports</Title>
      {rows.length === 0 ? (
        <Text size="sm" c="dimmed">
          No reports yet for this project.
        </Text>
      ) : (
        // Real fix, found live via screenshot (the same discipline this
        // project has applied to every prior CSS bug): a plain <Table>
        // redistributes column width to fit its container, so a row
        // needing all 4 owner actions (View/Download/Approve/Reject)
        // squeezed every other row's badges into ellipsis truncation,
        // even rows with only 2 actions. Mantine's own real, documented
        // fix for exactly this — many-column tables with action cells —
        // is a horizontal scroll container over a table with a real
        // minimum width, not fighting the browser's own column-fit
        // algorithm.
        <Table.ScrollContainer minWidth={1000}>
          <Table striped highlightOnHover withTableBorder>
            <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ minWidth: 100 }}>Week of</Table.Th>
              <Table.Th style={{ minWidth: 90 }}>RAG</Table.Th>
              <Table.Th style={{ minWidth: 130 }}>Quality gate</Table.Th>
              <Table.Th style={{ minWidth: 110 }}>Review</Table.Th>
              <Table.Th style={{ minWidth: 80 }}>Findings</Table.Th>
              <Table.Th style={{ minWidth: 260 }} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => {
              const review = reviewLabel(r);
              return (
                <Table.Tr key={r.reportId}>
                  <Table.Td>{r.weekOf}</Table.Td>
                  <Table.Td>
                    <Badge color={RAG_COLOR[r.ragStatus]}>{r.ragStatus}</Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{QUALITY_LABEL[r.qualityGateOutcome]}</Text>
                  </Table.Td>
                  <Table.Td>
                    {review ? (
                      <Badge color={review === "Rejected" ? "red" : "green"} variant="light">
                        {review}
                      </Badge>
                    ) : (
                      <Text size="sm" c="dimmed">
                        Pending review
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{r.findingCount}</Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Button size="xs" variant="subtle" onClick={() => setDetailReportId(r.reportId)}>
                        View
                      </Button>
                      <Button size="xs" variant="subtle" loading={download.isPending} onClick={() => handleDownload(r.reportId)}>
                        Download
                      </Button>
                      {/* Real security note: hiding these two buttons for a
                          visitor is a usability decision only — core_api's
                          own `_require_owner` already refuses the request
                          server-side (real 403s, proven live in Phase 8).
                          This `isOwner` check is not what stands between a
                          visitor and an approve/reject call. */}
                      {isOwner && !r.reviewed && (
                        <>
                          <Button
                            size="xs"
                            color="green"
                            loading={approve.isPending}
                            onClick={() => approve.mutate(r.reportId)}
                          >
                            Approve
                          </Button>
                          <Button size="xs" color="red" variant="outline" onClick={() => setRejectTarget(r.reportId)}>
                            Reject
                          </Button>
                        </>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <ReportDetailModal reportId={detailReportId} onClose={() => setDetailReportId(null)} />

      <Modal opened={rejectTarget !== null} onClose={() => setRejectTarget(null)} title="Reject report">
        <Stack>
          <Textarea
            label="Rejection notes"
            description="Required — the database itself refuses an empty-notes rejection."
            value={rejectNotes}
            onChange={(e) => setRejectNotes(e.currentTarget.value)}
            minRows={3}
            autosize
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRejectTarget(null)}>
              Cancel
            </Button>
            <Button color="red" loading={reject.isPending} onClick={handleReject}>
              Reject
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
