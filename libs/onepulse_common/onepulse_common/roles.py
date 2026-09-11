"""Owner/Visitor authorization model (Migration Plan Phase 8, ADR-027).

Deliberate design choice, recorded here rather than only in the
migration comment: `actors.role` keeps its original organizational-title
values (`portfolio_lead`, `program_lead`, `platform_admin`) rather than
gaining a second, separate access-level column. Every one of those
legacy values is treated as Owner-tier — every actor seeded before this
phase existed was, in practice, a full-capability reviewer/admin, so
this reads their real historical intent correctly with no backfill. The
two new literal values, `owner` and `visitor`, are for actors seeded
*after* this phase specifically to exercise or need the distinction.

Owner: may generate a report, may approve/reject, sees everything within
their resolved scope. Visitor: may view and use the chat assistant
within scope, may never generate or approve — enforced entirely in
`core_api`, never in the UI (a hidden button is usability, not security).
"""

from __future__ import annotations

VISITOR_ROLE = "visitor"


def is_owner_role(role: str) -> bool:
    """True for every role that may generate/approve — every legacy
    organizational-title role plus the new explicit 'owner' value.
    False only for the literal 'visitor' role. Deliberately an exclusion
    check, not an allow-list of legacy values, so a future new role
    value defaults to Owner-tier (matching every historical actor's real
    capability) unless it is explicitly 'visitor'.
    """
    return role != VISITOR_ROLE
