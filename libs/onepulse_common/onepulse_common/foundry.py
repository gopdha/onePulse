"""Foundry-backed Claude client authenticated via Microsoft Entra ID —
no static API key, ever, anywhere.

Verified directly against Microsoft Learn
(foundry-models/how-to/use-foundry-models-claude) rather than assumed:
the `anthropic` SDK's `AnthropicFoundry` client accepts an
`azure_ad_token_provider`, built from `DefaultAzureCredential` scoped to
`https://ai.azure.com/.default`. The calling identity needs the
**Cognitive Services User** role assigned on the Foundry resource, or
calls fail with 403 — this is an infrastructure/RBAC step, not something
this module can do for itself.

Scope note: this client is the plain Messages API path — correct as-is
for a zero-tool-call service like Narrative Synthesis (Physical
Architecture Section 2). It remains a documented fallback only for
agentic, tool-using services — see CLAUDE.md's "Foundry Agent Integration
— Path Resolution" for the full picture.

SUPERSEDED (kept for history, not deleted — see CLAUDE.md path
resolution): Work Item Investigation and Status Update Analysis
(Phase 3) were originally expected to go through the Claude Agent SDK
instead, via Microsoft Foundry's apparent Agent SDK / Claude Code
backend support (`CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_BASE_URL`),
with the LLD Section 3 isolation flags
(`onepulse_common.constants.AGENT_CALL_ISOLATION`) applied on every call.
That path's Entra ID token wiring was never independently verified per
convention #6. The Phase 0/Task 3 go/no-go checkpoint (2026-09-05)
verified `azure.ai.agents.AgentsClient` instead, and it held up — Phase 3
now builds on AgentsClient, not this SDK path. Do not resurrect this
path without re-verifying it against real infrastructure first.
"""

from __future__ import annotations

from anthropic import AnthropicFoundry
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from onepulse_common.config import FoundrySettings

# Confirmed against Microsoft Learn
# (foundry-models/how-to/use-foundry-models-claude): the fixed scope
# Entra ID issues Foundry-inference-scoped tokens for.
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"


def create_foundry_client(settings: FoundrySettings) -> AnthropicFoundry:
    """Create a Messages-API client for a Foundry-hosted Claude
    deployment, authenticated via Entra ID. Safe to call once per
    process and reuse — `get_bearer_token_provider` handles token
    refresh internally, callers do not need to manage token lifetime.
    """
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        FOUNDRY_TOKEN_SCOPE,
    )
    return AnthropicFoundry(
        azure_ad_token_provider=token_provider,
        base_url=settings.base_url,
    )
