"""This project's own proven `mcp.ClientSession`-to-`agent_framework`
bridge — generic, real, and used by more than one MCP server: the
Investigation service's real Azure DevOps MCP session
(`investigation/investigate.py`) and the Reporting service's own real
PPTX-parsing MCP session (`onepulse_common.pipeline.analyze_status_deck`,
a Python-based server via `sys.executable`, unrelated to Node/ADO).
Relocated here (Migration Plan Phase 4) specifically because it is
shared by both — it was previously colocated with the Investigation-only
code it happened to be adjacent to, but has no ADO/Node/PAT-specific
logic of its own and belongs in the shared library, not either service.

See `onepulse_common.pipeline`'s own module docstring for why
`agent_framework.MCPStdioTool` (the native MCP client) is deliberately
NOT used instead — three real, confirmed camelCase/snake_case
compatibility bugs were found live in it.
"""

from __future__ import annotations

from typing import Callable

from agent_framework import FunctionTool
from mcp import ClientSession

from onepulse_common.heartbeat import noop_detail


async def build_mcp_function_tools(
    mcp_session: ClientSession, on_detail: Callable[[str], None] = noop_detail
) -> tuple[list[FunctionTool], dict[str, int]]:
    """Wraps each real, dynamically discovered MCP tool as a plain
    `agent_framework.FunctionTool`.

    Real bug found and fixed (2026-09-09): a real run against a
    115-item scope has the Investigation agent dispatch all 115
    `wit_work_item(list_comments, ...)` calls concurrently within ~70ms
    of each other, then wait up to several minutes for the real ADO API
    responses to trickle back — but this function only ever logged on
    DISPATCH, never on completion, so the entire multi-minute real wait
    produced zero log output. That silence is what convinced an earlier
    session the run had hung (it hadn't — confirmed by a later run that
    completed normally after the same ~4m17s silent window). Fixed by
    logging a real, exact completion counter (`N/M tool call(s)
    resolved`) as each call actually returns, not just when it's issued
    — this is on `on_detail`, the same single source of truth the
    curated UI view and the full-fidelity log file both already read
    from (no second tracking system), so both outputs get it for free.

    Returns `(function_tools, progress)` — `progress` is the same
    mutable `{"dispatched": int, "completed": int}` dict every returned
    tool's own closure updates, so a caller can read its real final
    counts after the agent's tool-use loop finishes and log one real
    summary line, without a second, separate tracking mechanism.
    """
    result = await mcp_session.list_tools()
    function_tools = []
    progress = {"dispatched": 0, "completed": 0}
    for tool in result.tools:

        async def call_tool(_tool_name=tool.name, **kwargs) -> str:
            progress["dispatched"] += 1
            on_detail(f"· real tool call: {_tool_name}({kwargs})")
            call_result = await mcp_session.call_tool(_tool_name, kwargs)
            progress["completed"] += 1
            on_detail(
                f"· real tool call completed: {_tool_name} "
                f"({progress['completed']}/{progress['dispatched']} tool call(s) resolved so far)"
            )
            return "\n".join(block.text for block in call_result.content if hasattr(block, "text"))

        function_tools.append(
            FunctionTool(
                name=tool.name,
                description=tool.description or "",
                input_model=tool.input_schema,
                func=call_tool,
            )
        )
    return function_tools, progress
