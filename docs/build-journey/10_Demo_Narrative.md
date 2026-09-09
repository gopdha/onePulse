# OnePulse — Demo Narrative

A suggested flow and the real substance behind each beat — every claim below is backed by something genuinely proven, not aspirational.

---

## The One-Sentence Framing
"OnePulse turns real Azure DevOps data and real team-lead updates into an executive-ready status report — investigated by AI, quality-gated by code, and never published without a human's approval."

---

## Suggested Live Flow

### 1. Open on the empty state (10 seconds)
Show the clean, intentional blank screen — no eager loading, just a project selector. This is a real, deliberate UX decision (previously the app auto-loaded and stalled for seconds on open) — worth a one-line mention if it fits naturally.

### 2. Select "Agentic AI Observability Platform" and trigger a real run
This is the actual demo-worthy project: **465 real work items**, of which OnePulse deterministically investigates the **115 that sit under 7 real "Committed" Features** — a genuine, non-trivial scale, not a toy example.

**What to narrate while it runs**: the minimal 7-step view shows real, computed numbers — item counts, feature counts, live-ticking timers — not a generic spinner. If asked "what's happening under the hood," the honest answer is: real Azure DevOps MCP tool calls, a real LLM investigating real work items, all fully logged.

### 3. Point out the quality gate, live
If a revision fires (a real, live possibility — this has happened naturally, unprompted, in testing), narrate it plainly: "The system just caught its own draft failing a tone check and rewrote it — this isn't scripted, it's a real, code-enforced gate."

If it reaches `route_to_human_review` instead of a clean approval — that's *also* a good story: "This means the report itself is factually sound, but the system decided a human should look at it before it goes out — that's the actual point of a governance gate."

### 4. Show the Tower View report
This is the strongest visual asset in the system. **Business language, not ADO jargon**: three real Towers (Observability, Eval as a Service, AI Ops Center), real completion percentages, a plain-English "Needs Your Decision" list. Worth stating explicitly: *"An executive doesn't see work-item IDs — they see percentages, owners needed, and initiatives happening outside the tracked backlog."*

### 5. Approve or Reject a report live
Show the real database-enforced behavior: reject with empty notes and let it get blocked — a genuine server-side rule, not a UI nicety. Then reject with real notes, or approve — either way, this is backed by a database guarantee that has been adversarially tested three separate ways (see Governance & Security Reference) — worth a confident one-liner if it comes up: *"Once approved or rejected, that record can never be altered or deleted — even by an administrator. That's enforced at the database level, not just assumed."*

### 6. Ask the Status Report Assistant a real question
Something the current data can genuinely answer — e.g., a question about a flagged item or the untracked vendor-contract-style initiative. Show the real citation in the answer. If time allows, ask something the system genuinely doesn't know, and show the honest "not found" response — **this might be the single most credibility-building moment available**: a system that admits what it doesn't know is more trustworthy than one that always sounds confident.

---

## If Asked "What Was Hard About Building This?"
Pick one or two real stories, not a laundry list:
- **The Azure DevOps identity investigation** — four distinct real failures, fully diagnosed, honestly documented as still partially open, worked around with an explicit, time-boxed exception rather than swept under the rug.
- **The scale stress test** — deliberately threw 465 real items at the system, found it broke in two different honest ways (an empty report that got wrongly approved; a real model producing wildly inconsistent results at scale), and fixed the actual root cause rather than papering over the symptom.

## If Asked "What's Not Done Yet?"
Answer plainly, from the Project Plan: Content Safety integration hasn't started; the ADO identity issue has a working exception but not a real fix; the reviewer-identity mechanism is an honest placeholder, not real authentication yet. Volunteering this, rather than waiting to be caught, is itself part of the credibility story.

## If Asked About Cost/Model Choice
Be direct: originally intended for Claude Sonnet/Haiku tiering, currently running on GPT-5-mini due to a real regional quota constraint — and that this decision remains explicitly open, not quietly settled.

---

## What NOT to Over-Claim
- Don't imply Content Safety is handled — it isn't
- Don't imply the reviewer-approval flow has real authentication behind it — it doesn't yet
- Don't claim the Arize/Application Insights observability stack is gap-free — there are small, documented, non-fatal limitations, and admitting them if asked is stronger than pretending otherwise
