// View 1 (part): the project selector. Empty by default — a deliberate
// UX decision recorded in the Demo Narrative, not an oversight: nothing
// scoped to a project (report table, generate, chat) fetches or renders
// until one is picked (see useReports/useReportDetail's own `enabled`
// guards).

import { Select } from "@mantine/core";
import { usePrograms } from "../api/hooks";

interface Props {
  value: string | null;
  onChange: (programId: string | null) => void;
}

export function ProjectSelector({ value, onChange }: Props) {
  const programs = usePrograms();

  return (
    <Select
      label="Project"
      placeholder={programs.isLoading ? "Loading projects…" : "Select a project"}
      data={(programs.data ?? []).map((p) => ({ value: p.programId, label: p.name }))}
      value={value}
      onChange={onChange}
      disabled={programs.isLoading}
      searchable
      clearable
      w={320}
    />
  );
}
