import { useState } from "react";
import { AppShell, Box, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { AuthGate } from "./components/AuthGate";
import { ProjectSelector } from "./components/ProjectSelector";
import { ReportTable } from "./components/ReportTable";
import { GenerateView } from "./components/GenerateView";
import { ChatAssistant } from "./components/ChatAssistant";
import { useMe, usePrograms } from "./api/hooks";

function Dashboard() {
  const me = useMe();
  const programs = usePrograms();
  const [programId, setProgramId] = useState<string | null>(null);

  const programName = programs.data?.find((p) => p.programId === programId)?.name ?? "";
  const isOwner = me.data?.isOwner ?? false;

  return (
    <AppShell header={{ height: 64 }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="lg" justify="space-between">
          <Title order={3} c="#1F3864">
            OnePulse
          </Title>
          <Group gap="md">
            {me.data && (
              <Text size="sm" c="dimmed">
                Signed in as {me.data.role}
              </Text>
            )}
            <ProjectSelector value={programId} onChange={setProgramId} />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        {programId === null ? (
          <Stack align="center" justify="center" h="60vh">
            <Text c="dimmed" ta="center">
              Your executive status report is one click away.
            </Text>
            <Text size="sm" c="dimmed" fw={700}>
              SELECT YOUR PROJECT
            </Text>
          </Stack>
        ) : (
          <Group align="flex-start" gap="lg" wrap="nowrap">
            <Box flex={7}>
              <Stack gap="xl">
                <Paper p="md" withBorder>
                  <ReportTable programId={programId} programName={programName} isOwner={isOwner} />
                </Paper>
                <Paper p="md" withBorder>
                  <GenerateView programId={programId} isOwner={isOwner} />
                </Paper>
              </Stack>
            </Box>
            <Box flex={5}>
              <Paper p="md" withBorder>
                <ChatAssistant programId={programId} />
              </Paper>
            </Box>
          </Group>
        )}
      </AppShell.Main>
    </AppShell>
  );
}

export default function App() {
  return (
    <AuthGate>
      <Dashboard />
    </AuthGate>
  );
}
