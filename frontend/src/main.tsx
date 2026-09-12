import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import App from "./App";

const theme = createTheme({
  primaryColor: "indigo",
  colors: {
    // Real navy from onepulse_common/report_rendering.py's own _NAVY
    // constant, reused here rather than picked freshly — the same
    // visual identity every prior UI pass in this project matched.
    indigo: [
      "#eef1f6", "#dde3ee", "#b9c6dd", "#94a8cc", "#708bbb", "#4c6daa",
      "#385792", "#2b4373", "#1F3864", "#152645",
    ],
  },
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false }, // A 401/403/404 should never be silently
    // retried — each is a real, distinct outcome the UI needs to show,
    // not a transient failure to paper over.
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <Notifications />
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>
);
