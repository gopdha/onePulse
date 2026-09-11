// View 3: Status Report Assistant — chat scoped to the selected
// project, real citations from the real, mandatory server-side
// retrieval filter (ADR-027) — this component never sees a chunk the
// backend didn't already authorize for the signed-in identity.

import { useState } from "react";
import { Badge, Button, Group, Paper, ScrollArea, Stack, Text, Textarea, Title } from "@mantine/core";
import { useChatQuery } from "../api/hooks";
import type { Citation } from "../api/types";

interface Turn {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
}

export function ChatAssistant({ programId }: { programId: string }) {
  const chat = useChatQuery();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);

  async function send() {
    const q = question.trim();
    if (!q) return;
    setTurns((t) => [...t, { role: "user", text: q }]);
    setQuestion("");
    try {
      const result = await chat.mutateAsync({ question: q, programId });
      setTurns((t) => [...t, { role: "assistant", text: result.answer, citations: result.citations }]);
    } catch (err) {
      setTurns((t) => [...t, { role: "assistant", text: `Could not answer: ${String(err)}` }]);
    }
  }

  return (
    <Stack gap="sm">
      <Title order={5}>Status Report Assistant</Title>
      <ScrollArea h={280} type="auto">
        <Stack gap="sm">
          {turns.map((t, i) => (
            <Paper key={i} p="xs" withBorder={t.role === "assistant"} radius="md" bg={t.role === "user" ? "gray.1" : undefined}>
              <Text size="sm">{t.text}</Text>
              {t.citations && t.citations.length > 0 && (
                <Group gap={4} mt={4}>
                  {t.citations.map((c, ci) => (
                    <Badge key={ci} size="xs" variant="light">
                      {c.programName} · {c.weekOf.slice(0, 10)}
                      {c.sourceItemRef ? ` · #${c.sourceItemRef}` : ""}
                    </Badge>
                  ))}
                </Group>
              )}
            </Paper>
          ))}
        </Stack>
      </ScrollArea>
      <Group align="flex-end">
        <Textarea
          flex={1}
          placeholder="Ask about this project's report history…"
          value={question}
          onChange={(e) => setQuestion(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          autosize
          minRows={1}
          maxRows={3}
        />
        <Button loading={chat.isPending} onClick={send}>
          Ask
        </Button>
      </Group>
    </Stack>
  );
}
