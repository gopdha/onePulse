"""Task 29 regression test: a real bug found via a live stress test, not
a hypothetical — `@azure-devops/mcp`'s wit_work_item actions elicit the
real project interactively whenever a tool call omits `project`, and
this project's mcp.ClientSession has no elicitation_callback registered
to answer that request, so the call hard-fails with "Client does not
support form elicitation". The real fix is the server's own documented
env-var escape hatch (`ado_mcp_project`), which skips elicitation
entirely. This is a pure, deterministic check that the fix is actually
wired into the real spawned server's environment — not a live
Azure DevOps call, which is what `investigate()` itself needs and is
verified separately, live, per this project's own convention.
"""

from __future__ import annotations

from onepulse_common.pipeline import _ado_mcp_server_params


def test_ado_mcp_server_env_sets_project_to_skip_elicitation() -> None:
    params = _ado_mcp_server_params("gopdha", "encoded-pat", "Agentic AI Observability Platform")
    assert params.env["ado_mcp_project"] == "Agentic AI Observability Platform"


def test_ado_mcp_server_env_still_carries_the_pat() -> None:
    params = _ado_mcp_server_params("gopdha", "encoded-pat", "singleSlide")
    assert params.env["PERSONAL_ACCESS_TOKEN"] == "encoded-pat"


def test_ado_mcp_server_project_env_matches_the_real_target_project() -> None:
    # Real regression case: the elicitation bug fires per-project (Task 29
    # was found against "Agentic AI Observability Platform" specifically),
    # so a mismatched project here would silently resolve elicitation to
    # the WRONG project rather than actually failing loudly — worth
    # asserting the env value is never left stale from another caller.
    params = _ado_mcp_server_params("gopdha", "encoded-pat", "Leave Tracker")
    assert params.env["ado_mcp_project"] == "Leave Tracker"
    assert params.env["ado_mcp_project"] != "singleSlide"
