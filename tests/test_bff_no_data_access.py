"""Real, automated enforcement of ADR-017's boundary: "the BFF owns no
data stores... A single 'just this one query' connection from the BFF
to Postgres collapses the boundary and forfeits the entire reason for
the split." Migration Plan Phase 2 asks for this to be enforced
structurally, not by discipline — this is that enforcement, not a
description of it.

Two distinct, real checks:

1. Static — parses `bff/main.py` and `bff/observability.py`'s own
   source directly (via `ast`, not a substring/grep heuristic that a
   comment could fool) and asserts none of the forbidden data-layer
   modules are imported anywhere in either file.

2. Adversarial, at the process level, not just source text — imports
   `bff.main` for real, in a fresh subprocess (so this process's own
   already-imported modules from other test files can't produce a false
   negative), and confirms the real Postgres driver (`asyncpg`), the
   real Azure AI Search SDK, and the real Foundry project SDK were never
   loaded into `sys.modules` as a transitive result of that import —
   the strongest local proof available that the BFF's actual live
   import graph, not merely its own top-level file, never touches a
   data store. Real network-level isolation (the BFF genuinely being
   unable to *reach* Postgres over the wire) is Phase 7 work (Container
   Apps internal-only ingress) — not claimed here.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_FORBIDDEN_MODULE_PREFIXES = (
    "onepulse_common.db",
    "onepulse_common.search_index",
    "onepulse_common.embeddings",
    "onepulse_common.chat_assistant",
    "onepulse_common.pipeline",
    "onepulse_common.human_governance",
    "asyncpg",
)


def _imported_module_names(file_path: Path) -> set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_bff_main_does_not_statically_import_any_data_store_module() -> None:
    imported = _imported_module_names(REPO_ROOT / "bff" / "main.py")
    for forbidden in _FORBIDDEN_MODULE_PREFIXES:
        matches = {m for m in imported if m == forbidden or m.startswith(forbidden + ".")}
        assert not matches, f"bff/main.py imports forbidden module(s): {matches}"


def test_bff_observability_does_not_statically_import_any_data_store_module() -> None:
    imported = _imported_module_names(REPO_ROOT / "bff" / "observability.py")
    for forbidden in _FORBIDDEN_MODULE_PREFIXES:
        matches = {m for m in imported if m == forbidden or m.startswith(forbidden + ".")}
        assert not matches, f"bff/observability.py imports forbidden module(s): {matches}"


def test_bff_live_import_graph_never_loads_asyncpg_search_or_foundry_sdks() -> None:
    """The real, adversarial check: import bff.main for real, in a
    fresh subprocess, and confirm asyncpg / azure.search.documents /
    azure.ai.projects never entered sys.modules as a result.
    """
    probe = (
        "import sys; "
        "sys.path.insert(0, r'" + str(REPO_ROOT / 'libs' / 'onepulse_common') + "'); "
        "sys.path.insert(0, r'" + str(REPO_ROOT) + "'); "
        "import bff.main; "
        "forbidden = ['asyncpg', 'azure.search.documents', 'azure.ai.projects']; "
        "loaded = [m for m in forbidden if m in sys.modules]; "
        "print('LOADED_FORBIDDEN:' + ','.join(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"probe subprocess failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    loaded_line = next(
        (line for line in result.stdout.splitlines() if line.startswith("LOADED_FORBIDDEN:")), None
    )
    assert loaded_line is not None, f"probe produced no marker line; stdout={result.stdout!r}"
    loaded = loaded_line.removeprefix("LOADED_FORBIDDEN:")
    assert loaded == "", f"Forbidden module(s) loaded via bff.main's real import graph: {loaded}"
