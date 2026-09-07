"""Phase 0 / Task 4 go/no-go checkpoint: real Azure DevOps MCP server
attached to an Investigation-style AgentsClient agent.

Not a build phase deliverable — a spike proving the mechanism end to end
before Phase 3 (Work Item Investigation, Status Update Analysis) is
designed against it: can an azure.ai.agents.AgentsClient agent discover
and call real Azure DevOps MCP tools, against a real Azure DevOps
organization?

*** PAT-BASED AUTH — DIAGNOSTIC USE ONLY, NEVER THE PATTERN FOR REAL
PHASE 3 CODE, REMOVE BEFORE THAT WORK BEGINS. ***
This violates CLAUDE.md convention #4 (no static credentials, ever) as a
deliberate, scoped, time-boxed exception: neither `--authentication
azcli` nor `--authentication interactive` could resolve to the org's
actual member identity (`fd8ef742-fefb-6ef8-8e68-bbbadd3abda8`, origin
`msa`) after four real attempts surfacing three different identity GUIDs
— see CLAUDE.md's Phase 0 tracker for the full trail. The PAT used here
must be scoped to Work Items (Read) only, short-expiry (7 days), read
from the `PERSONAL_ACCESS_TOKEN` environment variable (never hardcoded,
never committed), and explicitly revoked once this spike's purpose is
served — not left to expire on its own. The real ADO identity problem
this works around is still open and still needs a real fix (most likely
linking `gopdha`'s Azure Active Directory to the onePulse tenant) before
Phase 3 can build on this org for real.

Architecture decision (see CLAUDE.md path resolution and this repo's
Physical Architecture, which places the MCP server co-located in the
Container Apps Environment rather than as a separately-hosted network
service): azure-ai-agents 1.1.0 (latest on PyPI) has no McpTool class and
no native server-side "mcp" tool type. So this is an agent-side tool
loop, not Foundry's built-in remote-mcp tool:

  1. Spawn the official `@azure-devops/mcp` server as a local stdio
     subprocess. Uses `--authentication interactive` (one-time browser
     sign-in via MSAL), NOT `--authentication azcli` as originally
     planned: the `gopdha` org is MSA-only, backed by tenant
     00000000-0000-0000-0000-000000000000 (confirmed via the org's own
     `X-VSS-ResourceTenant` header), while `az login` here authenticates
     into the real AAD tenant behind the onePulse subscription. The
     tool's `azcli` path has no zero-tenant guard (unlike its
     `interactive` path, which correctly falls back to the `/common`
     authority for exactly this case) — it silently mints a token in the
     wrong tenant, which Azure DevOps rejects as unauthorized (TF400813)
     even with correct org access and project permissions on paper. Real
     fix for headless, no-popup use going forward is either linking
     `gopdha` to the onePulse AAD tenant (Organization Settings ->
     Azure Active Directory), or a one-time
     `az login --tenant 9188040d-6c67-4c5b-b112-36a304b66dad` to cache a
     consumer-tenant credential — not yet done; `interactive` is this
     run's proof-of-mechanism choice, not the long-term answer.
  2. Use the official `mcp` Python SDK as a stdio client to that
     subprocess: list_tools() for the real tool catalog, call_tool() to
     actually invoke one.
  3. Register those tools' real JSON schemas as FunctionToolDefinitions
     on an AgentsClient agent — the same primary path verified in
     scripts/foundry_agent_spike.py.
  4. Drive the run loop manually (create -> poll -> requires_action ->
     submit_tool_outputs -> poll) rather than using AgentsClient's
     built-in ToolSet auto-calling, because that convenience wrapper
     expects synchronous local callables and our real tool execution is
     the async MCP client call.

Domains restricted to `core work-items` via the server's own `-d` flag —
least-privilege tool scoping (NFR-3), not just a smaller demo surface.

Run: python scripts/ado_investigation_spike.py
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    FunctionDefinition,
    FunctionToolDefinition,
    ListSortOrder,
    ToolOutput,
)
from azure.identity import DefaultAzureCredential
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from onepulse_common.agent_cleanup import maybe_delete_agent

PROJECT_ENDPOINT = "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
DEPLOYMENT_NAME = "onePulse-gpt-5-mini"

ADO_ORG_NAME = "gopdha"

USER_QUESTION = (
    "List the work items in the 'singleSlide' Azure DevOps project. "
    "For each one, give its ID, title, and state."
)


async def discover_tools(session: ClientSession) -> list[FunctionToolDefinition]:
    result = await session.list_tools()
    print(f"\n--- Real tools discovered from @azure-devops/mcp ({len(result.tools)}) ---")
    tool_defs = []
    for tool in result.tools:
        print(f"  - {tool.name}: {tool.description}")
        tool_defs.append(
            FunctionToolDefinition(
                function=FunctionDefinition(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool.input_schema,
                )
            )
        )
    return tool_defs


async def run_agent_loop(
    agents_client: AgentsClient,
    mcp_session: ClientSession,
    tool_defs: list[FunctionToolDefinition],
) -> None:
    agent = agents_client.create_agent(
        model=DEPLOYMENT_NAME,
        name="onepulse-investigation-spike-agent",
        instructions=(
            "You are a Work Item Investigation agent for OnePulse. "
            "You have tools to query a real Azure DevOps organization. "
            "Always call a tool to get real data before answering; "
            "never fabricate project or work item details."
        ),
        tools=tool_defs,
    )
    print(f"\nCreated agent: {agent.id}")

    thread = agents_client.threads.create()
    print(f"Created thread: {thread.id}")

    agents_client.messages.create(thread_id=thread.id, role="user", content=USER_QUESTION)
    print(f"Posted question: {USER_QUESTION!r}")

    run = agents_client.runs.create(thread_id=thread.id, agent_id=agent.id)

    while run.status in ("queued", "in_progress", "requires_action"):
        if run.status == "requires_action":
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            tool_outputs = []
            for call in tool_calls:
                args = json.loads(call.function.arguments) if call.function.arguments else {}
                print(f"\n>>> Agent called real MCP tool: {call.function.name}({args})")
                result = await mcp_session.call_tool(call.function.name, args)
                output_text = "\n".join(
                    block.text for block in result.content if hasattr(block, "text")
                )
                print(f"<<< Real result from Azure DevOps:\n{output_text}")
                tool_outputs.append(ToolOutput(tool_call_id=call.id, output=output_text))
            run = agents_client.runs.submit_tool_outputs(
                thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs
            )
        else:
            await asyncio.sleep(1)
            run = agents_client.runs.get(thread_id=thread.id, run_id=run.id)

    print(f"\nFinal run status: {run.status}")
    if run.status == "failed":
        print(f"Run failed: {run.last_error}")

    messages = agents_client.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
    print("\n--- Thread messages ---")
    for msg in messages:
        if msg.text_messages:
            print(f"[{msg.role}] {msg.text_messages[-1].text.value}")

    maybe_delete_agent(agents_client, agent.id, label=agent.name)


async def main() -> None:
    credential = DefaultAzureCredential()
    agents_client = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    import os

    pat_env = os.environ.get("PERSONAL_ACCESS_TOKEN")
    if not pat_env:
        raise RuntimeError("PERSONAL_ACCESS_TOKEN is not set in this process's environment")

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@azure-devops/mcp", ADO_ORG_NAME, "--authentication", "pat", "-d", "core", "work-items"],
        env={"PERSONAL_ACCESS_TOKEN": pat_env},
    )

    with agents_client:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                tool_defs = await discover_tools(mcp_session)
                await run_agent_loop(agents_client, mcp_session, tool_defs)


if __name__ == "__main__":
    asyncio.run(main())
