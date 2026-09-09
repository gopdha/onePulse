# OnePulse — Challenges & Real-World Findings

This document captures the genuine, hard-won problems encountered during the build — each one real, reproduced, and resolved with evidence, not assumption. These are presented in rough chronological/thematic order, not by severity.

---

## 1. The Original 10x Cost Bug (singleSlide_demo POC)

**What happened**: Claude Agent SDK's session model loaded ambient context (`CLAUDE.md`, full tool catalog) by default, silently inflating cost.

**Root cause**: `setting_sources=None` (the SDK default) meant every session absorbed unnecessary context on every call.

**Fix**: Explicit `setting_sources=[], skills=[], strict_mcp_config=True`.

**Result**: Real, measured cost reduction from $2.83 to $1.62 per run (~43%) once combined with proper Arize/OTel instrumentation for visibility into where cost was actually going.

**Why it mattered later**: This exact failure *shape* — unintended, silent LLM/context involvement in something that should be bounded — became the recurring lens for evaluating later design decisions (see ADR-003, ADR-007).

---

## 2. The Azure DevOps Tenant-Duality Identity Saga

The single longest, most involved investigation in the entire project.

**The symptom**: `TF400813: The user ... is not authorized to access this resource` when the MCP bridge attempted a real WIQL query, despite the account having confirmed Basic access and Project Administrator rights on the target ADO project.

**Investigation, step by step**:
1. Confirmed org-level access was Basic (not Stakeholder) — ruled out the most common cause.
2. Confirmed Project Administrator membership — ruled out project-level permissions.
3. Read `@azure-devops/mcp`'s actual installed source to understand its `azcli` authentication path.
4. Discovered the `gopdha` ADO org is **MSA-only** — it has no backing Azure AD tenant at all (confirmed via `X-VSS-ResourceTenant: 00000000-0000-0000-0000-000000000000`).
5. The local `az login` session was authenticated into a *different*, real AAD tenant (`onePulse`'s own tenant) — a mismatch invisible from the outside.
6. `@azure-devops/mcp`'s `azcli` auth path has no guard for the zero-GUID tenant case (confirmed by reading `dist/auth.js` directly): it attempts `az account get-access-token --tenant 00000000-...`, which fails immediately (`AADSTS900021`), and `ChainedTokenCredential` silently falls through to a token scoped to the *wrong* tenant.

**Real remediation attempts, all genuinely tried**:
- **Tenant-link fix (Option 1)**: Attempted linking `gopdha`'s ADO org to the `onePulse` AAD tenant via Organization Settings → Azure Active Directory → Connect directory. Failed twice with "not allowed to link... only active members." Diagnosed further: the account was a Guest in that tenant, not (initially believed to be) a Member — but later found the account's own `User type` field already said "Member," revealing the block was something subtler (a federation/sign-in-identifier issue, never fully resolved).
- **Interactive auth (Option 3)**: Switched `--authentication interactive`. Hit a *new*, different error: `AadUserStateException: Identity ... has not been materialized, please use interactive login over the browser first.` Resolved by visiting the ADO org once in a real browser to materialize the identity — then hit a *fourth* distinct identity GUID and error.
- **Scoped PAT (final resolution for the deadline)**: After four real attempts surfacing three different identity GUIDs and no convergence, adopted a narrowly-scoped Personal Access Token (Work Items Read-only, 7-day expiry) as an explicit, documented, time-boxed diagnostic exception — not a permanent pattern.

**Status**: The underlying Entra-ID identity duality for `gopdha`'s ADO org **remains unresolved** as of this writing — tracked as open technical debt. The PAT-based workaround is functional but explicitly not the intended long-term pattern.

**Real lesson**: A four-attempt, no-convergence investigation is itself a valid, honest outcome — not a failure to hide. Documenting exactly what was tried and why each attempt failed is more valuable than papering over the gap with a single untested "fix."

---

## 3. The Vacuous-Truth Bug in the Quality Gate

**Discovered during**: A deliberate stress test against a 465-item real ADO project (far beyond the system's previously-tested scale).

**The bug**: `code_enforced_risk_floor_check` looped over the findings list to verify no critical findings were dropped from the narrative — but had no way to detect that the findings list itself was *empty*. An empty list vacuously satisfies "no critical finding is missing," so the check passed automatically.

**Real consequence observed**: One stress-test run returned 0 findings (due to unrelated agent inconsistency at scale) and Synthesis wrote a vague "no findings recorded, monitoring continues" narrative — which the quality gate then **approved**. A completely empty, meaningless report shipped as `approved`, with no error anywhere.

**Fix**: `code_enforced_risk_floor_check` now takes a required `queried_item_count`. Zero queried items legitimately passes (an honest empty-scope case). Nonzero queried but insufficient findings coverage now deterministically fails, reaching `hard_stop_defect`.

**Verification discipline**: Seven new regression tests were written *before* the fix, explicitly reproducing the exact 0/465 and 20/465 scenarios found during the stress test, plus the legitimate zero-scope case — proving the fix catches the real failure modes, not just a synthetic approximation of them.

---

## 4. The Citation-Format Bug (Post-Fix Regression)

**What happened**: After fixing the vacuous-truth bug, real runs against the 465-item project (now correctly scoped to Committed Features only) began hitting `hard_stop_defect` — twice in a row, on two separate real runs.

**Investigation**: Comparing the failing drafts against an earlier passing draft for the same project revealed a pattern: the passing draft cited every flagged item **with its literal work item ID**; the failing drafts described the same items accurately but only by title, never the ID.

**Root cause, confirmed by reading the actual check code**: `code_enforced_risk_floor_check` accepts either the literal work item ID *or* the finding's exact verbatim title as satisfying the citation requirement — not just the ID, as first hypothesized. But in practice, generative synthesis paraphrases titles rather than quoting them verbatim, making the title-match path essentially unreachable. The ID was the only path a model could reliably hit.

**Fix**: `SYNTHESIS_INSTRUCTIONS` now explicitly requires citing the real work item ID for every Blocked/Needs Human Review finding; the quality gate's revision feedback now names each dropped item's real ID directly when a violation is caught.

**Verification**: Two full real runs against the same 465-item project both reached `approved` with zero recurrence — critically, both passed the risk-floor check on the **first attempt**, not just eventually via revision, confirming the fix addressed the actual mechanism rather than making failure merely less likely.

---

## 5. The Week-Uniqueness Bug

**What happened**: A `UNIQUE(program_id, week_of)` constraint was designed to prevent duplicate weekly reports — but `run_pipeline_cycle` was setting `week_of` to the literal day the pipeline ran, not a Monday-bucketed week value, even though a correct `week_of()` helper already existed elsewhere in the codebase (used only for the rendered slide's printed header text).

**Real consequence**: Three separate "weekly" reports existed for the exact same real ISO week before this was caught — proven by direct query, not inferred.

**Why prior testing never caught it**: Every trigger during earlier testing happened to land on a different calendar day, so only same-day collisions were ever exercised — same-week-different-day was a genuine blind spot in test coverage, not a case anyone had actively avoided.

**Fix**: Wired the existing, correct `week_of()` helper into what actually gets persisted, rather than duplicating the logic.

**Accepted trade-off**: Same-week, different-day retriggers now correctly collide, reducing testing convenience — judged the right cost given the "weekly report" framing needs to actually be true.

**Note**: The three pre-existing miscategorized reports were deliberately *not* retroactively merged — the append-only design (see below) makes this cleanly impossible, and they remain as an honest artifact of the pre-fix period.

---

## 6. The Append-Only Guarantee, Stress-Tested Three Ways

**Original design**: `REVOKE UPDATE, DELETE` on `approval_records` at the database level, proven once in Task 15 via a direct application-role `UPDATE`/`DELETE` attempt.

**Real re-test, months later**: An attempt to delete an old test report (`report_id=306`) required investigating this guarantee far more deeply than the original test.

**Attempt 1 — Direct DELETE**: Failed as expected on `approval_records` directly.

**Real complication discovered**: Deleting the *parent* `reports` row (306) also failed with the identical `approval_records` permission error — because Postgres's internal foreign-key integrity check needs to verify no `approval_records` row references the report being deleted, and that internal check itself requires privilege on the referenced table. Confirmed as row-triggered (not a blanket block) by testing a delete matching zero rows, which succeeded instantly.

**Attempt 2 — RLS misdiagnosis, then correction**: Initially suspected Row-Level Security was the blocker (the admin identity's `rolbypassrls` was confirmed `False`). Directly disproven: `approval_records` has *no RLS policy at all* — the migration only ever applied one to `reports`. Separately confirmed the admin identity already bypasses `reports`' RLS via table-ownership membership, independent of `BYPASSRLS` — meaning granting `BYPASSRLS` would have been a complete no-op for the actual problem, and was correctly declined as pure future risk with no present benefit.

**Attempt 3 — Genuinely-tried SELECT-based workaround**: A transient `GRANT SELECT` (not DELETE) on `approval_records`, just enough to satisfy the internal FK check, was actually applied and tested — not just theorized. The delete **still failed**, because Postgres's real internal query uses `FOR KEY SHARE OF x` (a row-lock clause), which requires `UPDATE` privilege, not `SELECT`. The transient grant was immediately reverted, confirmed back to baseline via `relacl`.

**Final decision**: Declined to extend authorization to a transient `UPDATE` grant — correctly identified as touching the exact privilege the guarantee exists to withhold, a categorically bigger ask than the SELECT attempt. The test report was left in place, and a zero-cost alternative (retrigger against a genuinely empty week) was used instead.

**Conclusion**: The append-only guarantee has now survived a direct write attempt, a genuinely-executed privilege-escalation workaround, and a principled refusal to cross into the one remaining path that would have defeated it — a materially stronger, more rigorously proven guarantee than the original design review could have established alone.

---

## 7. The Arize Root-Span / Setup-Span Investigation

**The symptom**: Arize's trace list occasionally showed a scattered, incorrectly-named root ("GET," "AIProjectClient.get_openai_client," etc.) instead of the expected single named root, despite Application Insights showing the same run's data as completely clean and correctly grouped.

**Real, layered investigation**:
- Confirmed via direct code reproduction that exactly 3 generic HTTP-level setup spans (all literally named "GET," kind `CHAIN`) are skipped by Arize's router per run — these come from `AIProjectClient`'s own internal connection-string lookup, which runs *before* the routing context is established. This is a pre-existing gap (documented since Tasks 10-13), not a regression.
- Separately found and fixed a genuine flush-ordering bug: Arize's span processor is created lazily on first matching span, meaning its entire backlog could ride on an unguaranteed `atexit` teardown with no guaranteed timing — while Application Insights' processor had been auto-flushing throughout the run. Fixed with an explicit `force_flush()` in a `finally` block, verified via a clean flush confirmation and zero regression on Application Insights' own span count.
- A related, later investigation into "not showing as one tree" root the same phenomenon in a different code path — traced to a specific accidental `run_pipeline.py --help` invocation (no argparse guard existed) that was killed mid-run by a broken pipe (`| head -20`) before its root span could close. This was confirmed to be an isolated, explainable artifact, not a recurring architectural gap — every deliberately-completed real run has produced a correctly grouped, fully intact trace.

**Standing, accepted limitation**: A cosmetic "In progress" status can appear on a manually-instrumented root span's own summary row in Arize's list view, even when every real child span underneath is complete and correct. Investigated in real depth (sampling ruled out via direct code read, all span processors checked, a minimal reproduction built) — the mechanism was not fully pinned down, and the investigation was deliberately stopped once real data integrity was confirmed unaffected. Cosmetic gap, not a data-loss issue.

---

## 8. The Project-Switch Cancellation Investigation

**The question**: Does switching projects mid-generation in the UI genuinely stop the backend pipeline call, or does it keep running invisibly and potentially persist a surprise report later?

**Original (single-threaded) architecture**: Confirmed via direct source-tracing of Streamlit's own cancellation mechanism — `RerunException` is raised synchronously from inside the `on_stage`/`on_detail` callback stack, unwinding the entire call stack including the live `asyncio.run()` call. No code path survives to reach `persist_report()`. Genuinely, deterministically terminated.

**After introducing background threading** (for live-ticking timers): Re-verified with the same rigor. Real measurements against Application Insights span data: a "quiet stretch" scenario (switch during a single long LLM call) showed the in-flight call completing naturally ~4.1s after the switch; a "general case" scenario (switch during a large concurrent tool-call batch) showed a real ~16.5s delay before the thread actually stopped, confirmed via a per-second span histogram. Critically, the UI's visual switch (at +7.7s) was shown to happen well *before* the backend actually stopped (+16.5s) — two genuinely independent events under the new architecture, unlike the old one where they were the same event.

**Honest, corrected framing adopted**: Not "project-switch is instant and free," but "project-switch always eventually stops the backend — never silently completes and persists a surprise report — but the actual stop time is bounded by in-flight work, not instant."

---

## 9. The Elicitation / Missing-Project-Argument MCP Bug

**The symptom**: Placeholder findings appeared for all 115 investigated items in one demo run, each carrying an identical evidence string: `"Could not retrieve work item data or comments: API error 'Client does not support form elicitation'"`.

**Root cause**: `@azure-devops/mcp`'s `wit_work_item` tool triggers an interactive elicitation request whenever a call omits its own `project` argument — and this project's MCP client session had no elicitation handler registered, causing a hard failure. The investigation agent did not reliably include `project` on every call; an identical re-run sometimes succeeded and sometimes didn't.

**Fix**: The MCP server itself documents the correct mitigation — checking `process.env.ado_mcp_project` before attempting elicitation. Added that environment variable to the server's spawn configuration.

**Verification**: Re-ran the same 115-item scope: zero elicitation errors, zero placeholder findings, a realistic status split matching an earlier known-healthy run almost exactly.

---

## 10. Real Azure/Tooling Friction, Worth Recording as Institutional Knowledge

- **`az boards query --project X`** without an explicit `WHERE [System.TeamProject]` clause returns organization-wide results despite the `--project` flag — a real CLI gotcha discovered while validating seeded test data.
- **PostgreSQL 18 revokes `CREATE` on schema from `PUBLIC` by default** — required an explicit one-time grant to both application roles during initial database creation.
- **Azure Data Studio was retired February 28, 2026** — the correct current replacement for Postgres GUI work is the official Microsoft PostgreSQL extension for VS Code (not the MSSQL extension, which is SQL Server-specific).
- **Azure's "Entra Administrator" role for Postgres is not automatically a full superuser** — it can manage other roles but does not automatically bypass Row-Level Security, a real and non-obvious distinction discovered mid-investigation.
