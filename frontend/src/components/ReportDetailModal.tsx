import { Badge, Divider, Loader, Modal, Stack, Text, Title } from "@mantine/core";
import { useReportDetail } from "../api/hooks";

export function ReportDetailModal({ reportId, onClose }: { reportId: number | null; onClose: () => void }) {
  const detail = useReportDetail(reportId);

  return (
    <Modal opened={reportId !== null} onClose={onClose} title="Report detail" size="lg">
      {detail.isLoading && <Loader size="sm" />}
      {detail.data && (
        <Stack gap="md">
          <div>
            <Title order={5}>
              {detail.data.report.programName} — {detail.data.report.weekOf}
            </Title>
            <Text size="sm" c="dimmed">
              {detail.data.report.executiveSummary}
            </Text>
          </div>
          <Divider label="Findings" />
          <Stack gap="xs">
            {detail.data.findings.map((f) => (
              <div key={f.findingId}>
                <Text size="sm" fw={600}>
                  {f.title} <Badge size="xs">{f.statusLabel}</Badge>
                </Text>
                <Text size="xs" c="dimmed">
                  {f.evidence}
                </Text>
              </div>
            ))}
          </Stack>
          {detail.data.untrackedItems.length > 0 && (
            <>
              <Divider label="Untracked initiatives" />
              <Stack gap="xs">
                {detail.data.untrackedItems.map((u) => (
                  <div key={u.untrackedItemId}>
                    <Text size="sm">{u.description}</Text>
                    {u.evidence && (
                      <Text size="xs" c="dimmed">
                        {u.evidence}
                      </Text>
                    )}
                  </div>
                ))}
              </Stack>
            </>
          )}
        </Stack>
      )}
    </Modal>
  );
}
