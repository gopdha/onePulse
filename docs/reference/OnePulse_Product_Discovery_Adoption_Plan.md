**OnePulse — Product Discovery & Adoption Plan**

*Companion to OnePulse PRD v1.0 and Addendum \| Author: Claude
(Anthropic) \| Reviewer: Gopinath Dhayanandamurthy*

This closes the three remaining PM discipline gaps identified alongside
the PRD: competitive and alternative analysis, product usage analytics
distinct from AI-behavior observability, and a real adoption plan. It
also includes an interview guide — not a formality, but the actual
instrument the Kill & Pivot Criteria addendum already commits to using
for its “time savings” signal.

# 1. Competitive & Alternative Analysis

*Honest scope note: this is a first-pass, category-level analysis.
Naming specific commercial competitors with confidence would require
real market research beyond what this document does — the interview
guide in Section 4 is the intended mechanism for validating or
correcting this analysis with real Portfolio and Program Lead input, not
a substitute for it.*

|                                                                |                                                                                      |                                                                                                                                                                   |
|----------------------------------------------------------------|--------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Alternative**                                                | **What It Does**                                                                     | **What's Missing**                                                                                                                                                |
| Manual compilation (the current baseline, per PRD Section 2.1) | A person reads Azure DevOps and team updates directly and writes the report by hand. | Time cost, inconsistency between compilers, and no structural guarantee that a real risk isn't missed.                                                            |
| BI/dashboard tools (e.g. Power BI, Tableau)                    | Visualizes Azure DevOps data — burndown charts, status counts, filters.              | No narrative synthesis, no investigation of why an item is at risk, no evidence citation, no human-approval workflow. Shows data; does not produce a judgment.    |
| Ad hoc use of a general-purpose AI assistant                   | A Program Lead pastes raw data into a chat tool and asks for a summary.              | No grounding guarantee, no deterministic status rule, no persistent memory for week-over-week continuity, no multi-tenant governance, no mandatory approval gate. |
| Purpose-built AI status-reporting point solutions              | An emerging category; specific products and capabilities change quickly.             | Not evaluated here with confidence — flagged explicitly as needing real, current research before being compared against by name.                                  |

OnePulse's differentiation, if this category-level view holds up under
real interviews: it is the only option combining automated investigation
with cited evidence, a deterministic (not AI-judged) headline status,
and a mandatory human approval step — not simply visualizing existing
data or generating ungrounded prose.

  

# 2. Product Usage Analytics

Deliberately distinct from the Arize-based observability already
designed: Arize answers whether the AI is behaving well (cost,
groundedness, safety). This answers whether people are actually getting
value — a different question, for a different audience (product
decisions, not AI governance).

|                            |                                                                                                                                  |                                                                                                                          |
|----------------------------|----------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| **Metric**                 | **What It Reveals**                                                                                                              | **Data Source**                                                                                                          |
| Onboarding completion rate | % of programs that reach manifest_complete versus abandon partway through setup.                                                 | Direct query against the configurations table's own completeness flag — already captured, no new instrumentation needed. |
| Time-to-first-value        | Days from a program's onboarding completing to its first approved report.                                                        | Timestamp difference between configurations and the first approved reports row.                                          |
| Chat Assistant adoption    | Queries per week per Portfolio Lead — the exact metric the Kill Criteria addendum's threshold depends on.                        | Request logging on the Conversational Access API.                                                                        |
| On-demand trigger usage    | How often Portfolio Leads request a report outside the schedule — signals whether the on-demand capability is valued or ignored. | Request logging on the Trigger API.                                                                                      |
| Report engagement          | How often an approved report is actually opened/viewed after publication, not just generated.                                    | Request logging on the Report API's read endpoint.                                                                       |

Every source above is a request log on an API that already exists in the
Low-Level Design — this is additive logging, not a new system, and
deliberately lightweight for a first version.

# 3. Adoption & Rollout Plan

## 3.1 Rollout Sequencing

Matches the Now/Next/Later prioritization already established, rather
than a separate rollout philosophy invented here.

**1.** Pilot: 1–2 real portfolios, minimum 6 weeks — long enough for the
Kill Criteria addendum's own 4-week and “first month” thresholds to
produce a real signal, not a premature one.

**2.** Expansion: additional portfolios onboarded only after the pilot's
kill criteria are checked and pass.

**3.** General availability: broader rollout, informed by whatever the
pilot's product usage analytics (Section 2) actually showed — not
assumed in advance.

## 3.2 Training & Enablement

Deliberately lightweight, because the product's own guided onboarding
conversation (Discovery Agent) already serves as setup training — a
separate, traditional training program would duplicate it. What is still
needed is short, role-specific enablement for ongoing use, not setup:

|                        |                                                                                                                                |
|------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| **Audience**           | **Format**                                                                                                                     |
| Program Lead           | A 15-minute walkthrough of the review-and-approve screen, plus a one-page quick reference for what to do on rejection.         |
| Portfolio Lead         | A 15-minute walkthrough of the dashboard, on-demand trigger, and Chat Assistant.                                               |
| Platform Administrator | A working session on the onboarding flow and the cost/health monitoring view, run once per new administrator, not per program. |

## 3.3 Support Model

First-line support routes to the Platform Administrator role already
defined in the PRD Addendum's stakeholder map — not a new support
organization. A defined escalation path separates two genuinely
different problem types: a content-quality concern (the Chat Assistant
answered oddly, a report reads wrong) goes back to product/engineering
as feedback; a hard failure (onboarding won't complete, a report never
generates) is treated as an operational incident.

  

# 4. Stakeholder Interview Guide

This is not a formality — the Kill & Pivot Criteria addendum explicitly
commits to checking the “time savings” signal through direct follow-up
conversation with Portfolio Leads. This is that instrument, with a
second use before launch: validating or correcting Section 1's
competitive analysis with real answers instead of assumption.

## 4.1 Pre-Launch (informs Section 1)

**1.** Walk me through how you currently get status from your programs
today — step by step.

**2.** What tools, if any, do you already use to help with this
(dashboards, AI assistants, templates)?

**3.** What's the most time-consuming part of that process for you?

**4.** Has a real risk ever surfaced later than it should have because
it was buried in someone's update? What happened?

**5.** If a tool did the compilation and initial quality check for you,
what would make you trust its output enough to actually rely on it?

## 4.2 Post-Pilot (operationalizes the Kill Criteria time-savings check)

**1.** Compared to before, has the real time you spend on reporting
changed? Roughly by how much?

**2.** Has anything this system flagged changed a decision you made, or
caught something you would have otherwise missed?

**3.** Was there a moment you didn't trust the output? What was it, and
what would have fixed that?

**4.** Would you keep using this if it were entirely your choice? Why or
why not?

**5.** What's the single most valuable thing about it, and the single
most annoying thing?

Question 1 in the post-pilot set is the direct, literal check for the
Kill Criteria addendum's time-savings threshold — the answer here is the
actual data point that decision depends on, not a proxy for it.

  

*This completes the identified PM discipline gaps that could be
addressed as design artifacts. Two items remain genuinely dependent on
real-world execution rather than documentation: actually running the
interviews above, and actually staffing the support model in Section 3.3
— both are yours to execute, not something a design document can
complete on your behalf.*
