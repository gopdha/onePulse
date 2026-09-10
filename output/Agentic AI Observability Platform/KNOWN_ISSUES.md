# Known issue — two files in this folder contain wrong-deck content

Recorded 2026-09-10, Task 44 follow-up (see `CLAUDE.md`). Not deleted or
regenerated — the append-only discipline this project applies to its
database records applies to this rendered-artifact record too.

**Affected, do not present as real AOP status content:**

- `Agentic AI Observability Platform_2026-09-07.pptx`
- `Agentic AI Observability Platform_2026-09-08.pptx`

Both used the Tower View template, and both render a real "This Week's
Initiatives" section sourced from a status deck that was not actually
AOP's own deck at the time — `STATUS_DECK_PATH_BY_PROJECT` had no entry
for Agentic AI Observability Platform until Migration Phase 5
(2026-09-10), so every run before that fell through to
`DEFAULT_STATUS_DECK_PATH`, which itself held drifted, unrelated
content for part of that window (see CLAUDE.md, Task 44). The rest of
each file — Key Findings / tower percentages / program health — is real
and unaffected; only the "This Week's Initiatives" section is wrong.

**Not affected:**

- `Agentic AI Observability Platform_2026-09-06.pptx` and
  `..._2026-09-09.pptx` — both rendered via the flat fallback template,
  which has no "This Week's Initiatives" section at all.

The mapping is fixed and now integrity-checked (`reporting/main.py`,
`_verify_status_deck_integrity`) as of this same follow-up. A fresh run
against the current, verified `aiobs_status_deck.pptx` will not
reproduce this.
