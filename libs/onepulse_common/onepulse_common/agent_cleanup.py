"""Optional agent-retention toggle for local development/spike scripts.

Normal iteration deletes each agent immediately after use, keeping the
Foundry portal's Agents list clean run after run. Set
ONEPULSE_KEEP_AGENTS=true to skip deletion for a single run when a
persistent, clickable agent and thread in the Foundry portal is actually
needed — for verification or a demo. Default (unset) is `default_keep`,
which every script leaves at False except scripts/run_pipeline.py, which
passes True: every run of that specific entry point is a deliberate,
real demo run, not quiet iteration, so its agents should persist by
default. An explicit ONEPULSE_KEEP_AGENTS value always wins over
whatever a caller passes as `default_keep`.
"""

from __future__ import annotations

import os

from azure.ai.agents import AgentsClient


def keep_agents_enabled(default_keep: bool = False) -> bool:
    raw = os.environ.get("ONEPULSE_KEEP_AGENTS")
    if raw is None:
        return default_keep
    return raw.strip().lower() == "true"


def maybe_delete_agent(
    agents_client: AgentsClient, agent_id: str, label: str = "agent", default_keep: bool = False
) -> None:
    """Deletes the agent unless keep-agents is enabled (explicitly via
    ONEPULSE_KEEP_AGENTS, or via this call's own default_keep), in which
    case it is left in place in the Foundry portal instead.
    """
    if keep_agents_enabled(default_keep=default_keep):
        print(f"--- keeping {label} ({agent_id}) in the Foundry portal, not deleting ---")
        return
    agents_client.delete_agent(agent_id)
