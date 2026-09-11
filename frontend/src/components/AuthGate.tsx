// Migration Plan Phase 9: the app's real entry gate. Two real, distinct
// states this component exists to tell apart honestly — "not signed
// in" (a real Sign-in link, a top-level navigation to Easy Auth, never
// a fetch) and "signed in, but the backend is cold" (real measured
// cold-start Phase 7 recorded: ~55.7s for bff+core_api chained from
// zero). The second one is a UX problem, not just an ops one — someone
// opening the URL cold should see an honest "waking up" message with a
// real elapsed-seconds counter, never a fabricated percentage bar
// implying a known duration this app has no way to actually know.

import { useEffect, useState } from "react";
import { Alert, Anchor, Center, Loader, Stack, Text, Title } from "@mantine/core";
import { ApiError, UnauthenticatedError } from "../api/client";
import { buildSignInUrl } from "../api/client";
import { useMe } from "../api/hooks";

function useElapsedSeconds(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [active]);
  return elapsed;
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const elapsed = useElapsedSeconds(me.isLoading);

  if (me.isLoading) {
    return (
      <Center h="100vh">
        <Stack align="center" gap="sm" maw={420}>
          <Loader size="md" />
          <Title order={4}>Waking up OnePulse</Title>
          <Text size="sm" c="dimmed" ta="center">
            The backend scales to zero between uses and the first request after a quiet period is
            genuinely slow — real, measured cold starts run up to about a minute. This is not stuck;
            it will resolve.
          </Text>
          <Text size="xs" c="dimmed" ff="monospace">
            {elapsed}s elapsed
          </Text>
        </Stack>
      </Center>
    );
  }

  if (me.isError) {
    if (me.error instanceof UnauthenticatedError) {
      return (
        <Center h="100vh">
          <Stack align="center" gap="md" maw={420}>
            <Title order={3}>OnePulse</Title>
            <Text size="sm" c="dimmed" ta="center">
              Sign in with your organization account to continue.
            </Text>
            <Anchor href={buildSignInUrl()} fw={600}>
              Sign in
            </Anchor>
          </Stack>
        </Center>
      );
    }
    // A real 403 no_access (authenticated, not provisioned) reaches
    // here as a plain ApiError, not UnauthenticatedError — a genuinely
    // different real case (Migration Plan Phase 8's own no-actors-row
    // path), shown as its own honest message rather than folded into
    // the sign-in prompt. Anything that is NOT a real HTTP response at
    // all (a network/CORS failure — fetch() throws a plain TypeError
    // for those, never reaching ApiError's own status-code branch) gets
    // its own distinct, honest message too — conflating "the backend
    // said no" with "the backend was never actually reached" is exactly
    // the kind of misleading error this app must not produce.
    if (me.error instanceof ApiError) {
      return (
        <Center h="100vh">
          <Alert color="red" title="Access not provisioned" maw={480}>
            You're signed in, but this identity has no OnePulse access yet. Ask a platform admin to
            provision it.
          </Alert>
        </Center>
      );
    }
    return (
      <Center h="100vh">
        <Alert color="orange" title="Could not reach the backend" maw={480}>
          {String(me.error)}
        </Alert>
      </Center>
    );
  }

  return <>{children}</>;
}
