"""Real Azure Storage Queue helpers (Migration Plan Phase 4, ADR-019) —
shared by the Reporting service (sends investigation-requests, receives
findings-ready) and the Investigation service (receives
investigation-requests, sends findings-ready). Generic queue mechanics
only; no domain logic and no Node/MCP/ADO-PAT-adjacent import, so this
module is safe for every service (including core_api/bff) to depend on
without pulling in anything Investigation-specific.

Real Storage account: onepulsequeuesdev (onepulse-gr), created for this
phase — `allowSharedKeyAccess=false`, Managed Identity / Entra ID only
(Storage Queue Data Contributor), no account key anywhere, per this
project's zero-static-secrets discipline.

Real queue names, two, not one with mixed message types — per the
Migration Plan's own explicit reasoning: a shared queue would force each
consumer to inspect and discard the other's messages, and blocks
scaling each queue's own backlog independently (KEDA, later phases):
  - investigation-requests: Reporting -> Investigation
  - findings-ready: Investigation -> Reporting (a real, deliberately
    thin notification only — cycle_id + trace_context. The actual
    findings payload is fetched by Reporting over a real HTTP call to
    Investigation's own service, never carried in the queue message
    itself and never read from Investigation's schema directly. Storage
    Queue messages also have a real 64KB size cap that 115 real findings
    plus evidence text could plausibly exceed — a second, independent
    reason HTTP is the right transport for the actual data.)
Each has a real dead-letter twin (`<name>-poison`) for messages that
exceed MAX_DEQUEUE_COUNT — Poison messages are a real failure mode
under at-least-once delivery, built deliberately, not discovered later.
"""

from __future__ import annotations

import json
from typing import Any

from azure.identity.aio import DefaultAzureCredential
from azure.storage.queue import QueueMessage
from azure.storage.queue.aio import QueueClient

QUEUE_ACCOUNT_URL = "https://onepulsequeuesdev.queue.core.windows.net"

INVESTIGATION_REQUESTS_QUEUE = "investigation-requests"
INVESTIGATION_REQUESTS_POISON_QUEUE = "investigation-requests-poison"
FINDINGS_READY_QUEUE = "findings-ready"
FINDINGS_READY_POISON_QUEUE = "findings-ready-poison"

# Real, deliberate dequeue-count limit (Migration Plan Phase 4's own
# explicit instruction: "build a dequeue-count limit and a dead-letter
# path deliberately"). A message that has been received this many times
# without ever being deleted (successfully processed) is treated as
# poison — moved to the matching `-poison` queue and removed from the
# real queue, rather than being redelivered forever.
MAX_DEQUEUE_COUNT = 5


def get_queue_client(queue_name: str, credential: DefaultAzureCredential) -> QueueClient:
    return QueueClient(account_url=QUEUE_ACCOUNT_URL, queue_name=queue_name, credential=credential)


async def send_json_message(queue_client: QueueClient, payload: dict[str, Any]) -> None:
    await queue_client.send_message(json.dumps(payload))


def parse_message(message: QueueMessage) -> dict[str, Any]:
    return json.loads(message.content)


async def is_poison(message: QueueMessage) -> bool:
    """True iff this message has already been received MAX_DEQUEUE_COUNT
    times without ever being deleted — a real, live signal Azure Storage
    Queues track natively per message (`dequeue_count`), not something
    this project has to compute or estimate itself.
    """
    return message.dequeue_count > MAX_DEQUEUE_COUNT


async def deadletter(
    main_queue_client: QueueClient, poison_queue_client: QueueClient, message: QueueMessage, reason: str
) -> None:
    """Moves a real poison message to its dead-letter twin — sends the
    original real payload plus the real reason (dequeue_count, when
    this was detected) to the poison queue, then removes it from the
    real main queue so it stops being redelivered forever.
    """
    envelope = {
        "original_message": message.content,
        "dequeue_count": message.dequeue_count,
        "reason": reason,
    }
    await poison_queue_client.send_message(json.dumps(envelope))
    await main_queue_client.delete_message(message)
