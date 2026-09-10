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

import json
from pathlib import Path

import pytest

import investigation.investigate as investigate_module
from investigation.investigate import _ado_mcp_server_entry_path, _ado_mcp_server_params


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


def test_ado_mcp_server_version_is_pinned_in_package_json() -> None:
    # Real regression case (2026-09-09): the server was originally spawned
    # via unpinned `npx -y @azure-devops/mcp`, and it silently resolving
    # to a newer version (2.9.0 -> 2.10.0) between Task 36 and the first
    # fix is the actual mechanism behind a real Investigation outage
    # (_extract_work_item_fields's guard-marker parsing fix). The pin now
    # lives in package.json (2026-09-09, second fix): this project spawns
    # a real local `npm install`, not `npx`, so package.json's declared
    # version — not a CLI arg string — is the real, load-bearing pin.
    # Asserting it directly here means a future accidental un-pin (e.g.
    # someone bumping the dependency without reviewing it) fails a fast,
    # offline test instead of surfacing as another silent outage.
    # Migration Plan Phase 4: package.json lives in investigation/ now,
    # not the repo root — Node and this pinned package exist only inside
    # the Investigation service's own directory.
    investigation_dir = Path(__file__).resolve().parents[1] / "investigation"
    package_json = json.loads((investigation_dir / "package.json").read_text(encoding="utf-8"))
    assert package_json["dependencies"]["@azure-devops/mcp"] == "2.10.0"


def test_ado_mcp_server_spawns_the_real_local_install_via_node_not_npx() -> None:
    # Real regression case (2026-09-09): `npx -y`, even version-pinned,
    # still resolves (and can fetch) at every real spawn — a real,
    # live-demonstrated failure mode (an interrupted install once
    # corrupted its own npm cache and broke the next real pipeline run).
    # Fixed by spawning the real, already-installed entry point directly
    # via `node`. Asserting the exact command/args shape here means a
    # future accidental reintroduction of `npx` fails a fast, offline
    # test rather than only surfacing inside a container with no network
    # access to fall back on.
    params = _ado_mcp_server_params("gopdha", "encoded-pat", "singleSlide")
    assert params.command == "node"
    assert params.args[0] == str(_ado_mcp_server_entry_path())
    assert params.args[0].endswith(str(Path("@azure-devops") / "mcp" / "dist" / "index.js"))
    assert "npx" not in (params.command, *params.args)


def test_ado_mcp_server_params_raises_a_clear_error_when_local_install_is_missing(monkeypatch) -> None:
    # Real design requirement: a missing local install must fail loudly
    # with an actionable message (run `npm install`), not silently fall
    # back to `npx` — a silent fallback would just reintroduce the exact
    # runtime-fetch risk this fix exists to remove. Monkeypatches the
    # entry-point resolver rather than deleting the real local install,
    # so this test doesn't disturb the actual installed dependency other
    # real tests/runs in this session rely on.
    monkeypatch.setattr(investigate_module, "_ado_mcp_server_entry_path", lambda: Path("/nonexistent/dist/index.js"))
    with pytest.raises(RuntimeError, match="npm install"):
        _ado_mcp_server_params("gopdha", "encoded-pat", "singleSlide")
