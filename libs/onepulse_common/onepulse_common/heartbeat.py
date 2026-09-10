"""Real fix (Task 39, generalized Task 49/Phase 4): a background
elapsed-time ticker wrapping any real, possibly-slow `await` — used by
BOTH the Investigation service (`investigation/investigate.py`) and the
Reporting service's own agent-invoking functions
(`onepulse_common.pipeline`). Relocated here (Migration Plan Phase 4)
from `onepulse_common.pipeline`, which used to be the one place both
investigation and reporting code lived; now that Investigation is its
own service with its own process (and, deliberately, no shared-library
coupling back into the rest of `onepulse_common.pipeline`, which stays
free of any Node/MCP/ADO-PAT-adjacent import so the Reporting/core_api/
BFF services' own import graphs never touch it), this tiny, fully
generic utility is the one piece of the old heartbeat machinery real
enough to share, and small enough that sharing it costs nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Callable


def noop_stage(n: int, total: int, message: str) -> None:
    pass


def noop_detail(message: str) -> None:
    pass


@contextlib.asynccontextmanager
async def heartbeat(on_detail: Callable[[str], None], label: str, interval_seconds: float = 10.0):
    """Wraps any real, possibly-slow `await` with a background task that
    logs real elapsed time every `interval_seconds` regardless of what's
    actually happening inside — cancelled the instant the wrapped call
    returns (success or failure), so it never logs after the real work
    is done, and it never claims fake progress — only real elapsed
    seconds, honestly labeled as "still running." See Task 39's own
    CLAUDE.md entry for the real gap this originally closed (Application
    Insights showed real gaps of 30-71s around slow individual tool
    calls) and Task 42's for the real, live-found gap this same
    mechanism closed a second time (an uncovered WIQL call hitting a
    genuine ~37s ADO API slowdown).
    """
    start = time.monotonic()

    async def _tick() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            on_detail(f"· {label}: still running ({time.monotonic() - start:.0f}s elapsed, no result yet)")

    task = asyncio.create_task(_tick())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
