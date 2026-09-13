// Task 57: the real SAS download flow, extracted once it needed a
// second real caller (GenerateView, alongside ReportTable) — the error
// handling (artifact_predates_blob_storage vs artifact_not_available vs
// anything else, CLAUDE.md Task 55) is real, load-bearing logic, not
// boilerplate worth duplicating a second time.

import { notifications } from "@mantine/notifications";
import { ApiError } from "./client";
import type { DownloadResponse } from "./types";

export async function downloadReportOrNotify(
  reportId: number,
  mutateAsync: (reportId: number) => Promise<DownloadResponse>,
): Promise<void> {
  try {
    const { downloadUrl } = await mutateAsync(reportId);
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
