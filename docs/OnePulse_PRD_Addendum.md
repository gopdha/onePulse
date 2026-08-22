**OnePulse PRD Addendum**

*Personas, Success Criteria & Governance \| Amends OnePulse PRD v1.0 \|
Author: Claude (Anthropic) \| Reviewer: Gopinath Dhayanandamurthy*

This addendum amends OnePulse PRD v1.0 without reopening it. It replaces
Section 5's capability-based personas with motivation-based ones, adds
explicit kill and pivot criteria alongside Section 9's existing success
metrics, and adds a stakeholder and approval map that Section 5 did not
cover. Sections 1–4 and 6–8 of the base PRD are unchanged.

# 1. Job-to-Be-Done Personas (replaces PRD Section 5)

The base PRD defined each persona by what they can click. This defines
them by what they are actually trying to accomplish and what stands in
their way today — directly grounded in the real problem validation
established in Section 2.1 of the base PRD, not a generic template.

**Portfolio Lead**

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#ddebf7"
style="background: #ddebf7; border: 1px solid #000000; padding: 0.11in 0.14in"><p><strong>Job
to be done:</strong> <em>When I need to report portfolio health to
leadership, I want a fast, reliable, and consistent view across every
program I own, so I can speak with confidence about risk without
personally chasing each Program Lead for an update.</em></p>
<p><strong>Real pain today:</strong></p>
<p>• Chasing individual Program Leads for status ahead of every
leadership review.</p>
<p>• Depth and quality of what comes back varies by whoever compiled it
that week.</p>
<p>• A real risk can stay buried in one program's update long enough to
become a surprise at the portfolio level.</p>
<p><strong>Desired outcome:</strong> Confidence walking into a
leadership review, real time reclaimed, and nothing important missed
because it was buried in someone else's report.</p></td>
</tr>
</tbody>
</table>

**Program Lead**

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#fff2cc"
style="background: #fff2cc; border: 1px solid #000000; padding: 0.11in 0.14in"><p><strong>Job
to be done:</strong> <em>When it's time for my recurring status update,
I want the compilation and quality-checking done for me, so my time goes
to judgment — reviewing and approving — not manual authorship.</em></p>
<p><strong>Real pain today:</strong></p>
<p>• Manually cross-referencing tracked work items and team updates
every reporting cycle.</p>
<p>• Format and depth drift week to week depending on time pressure.</p>
<p>• Genuine worry that something worth escalating gets missed in the
rush to finish before a deadline.</p>
<p><strong>Desired outcome:</strong> A grounded, quality-checked draft
ready for review — the job becomes confirming it's right, not writing it
from scratch.</p></td>
</tr>
</tbody>
</table>

**Platform Administrator**

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd">
<td width="616" data-valign="top" data-bgcolor="#e8f3e8"
style="background: #e8f3e8; border: 1px solid #000000; padding: 0.11in 0.14in"><p><strong>Job
to be done:</strong> <em>When onboarding a new program or portfolio, I
want a setup process I can trust to be complete on the first try, and I
want to see cost or health anomalies before a user does, not
after.</em></p>
<p><strong>Real pain today:</strong></p>
<p>• An incomplete setup only becomes visible when a real report cycle
fails, not during onboarding itself.</p>
<p>• A cost or quality anomaly is only discovered after someone happens
to look, not surfaced proactively.</p>
<p><strong>Desired outcome:</strong> Confidence that a new program is
genuinely ready the moment onboarding finishes, and early warning of
anything abnormal before it becomes an incident.</p></td>
</tr>
</tbody>
</table>

  

# 2. Kill & Pivot Criteria (adds to PRD Section 9)

Section 9 of the base PRD defines what success looks like. This defines
the other half of that judgment — the specific, measurable signals that
should trigger a pause and a real rethink, not a decision made
informally after the fact.

|                         |                                                                                                                                                   |                                                                                                                                                                                                                                                   |
|-------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Signal**              | **Threshold**                                                                                                                                     | **Response**                                                                                                                                                                                                                                      |
| Chat Assistant adoption | Fewer than 1 query per week, averaged across pilot portfolios, after 4 weeks of availability                                                      | Pause further investment in retrieval/RAG infrastructure. This was already flagged as the most infrastructure-heavy, least-proven item in the design — this is the concrete test of that judgment call, not a reason to have skipped building it. |
| Report rejection rate   | More than 30% of reports rejected (not merely revised) by Program Leads in the first month of a pilot                                             | Pause onboarding of additional programs. Investigate whether the core narrative-quality trust story is actually working before scaling it to more users.                                                                                          |
| Cost governance failure | A real per-report cost anomaly of 5x or greater slips past the Cost Regression Gate a second time, post-launch                                    | Halt onboarding of new tenants until the gate itself is root-caused and fixed — the gate failing once already happened in the proof of concept; a repeat means the fix was incomplete, not that anomalies are simply expected.                    |
| Time savings            | Portfolio Leads report, in direct follow-up conversation, that real time spent on reporting has not measurably decreased after a full pilot cycle | Revisit the core problem-validation hypothesis (PRD Section 2.1) directly — this would mean the assumed source of time savings was wrong, not just that execution needs tuning.                                                                   |

# 3. Stakeholder & Approval Map (new — not covered in base PRD Section 5)

Section 5 of the base PRD names three operational personas. It does not
name who else must approve real decisions this platform makes — handling
organizational data, incurring real cost, and generating AI content at
scale. This table closes that gap.

|                                                        |                            |                                 |                                                          |                       |
|--------------------------------------------------------|----------------------------|---------------------------------|----------------------------------------------------------|-----------------------|
| **Decision**                                           | **Responsible**            | **Accountable**                 | **Consulted**                                            | **Informed**          |
| New tenant onboarding                                  | Platform Admin             | Finance (budget approval)       | Legal (data handling terms), Security (isolation review) | Portfolio Lead        |
| Production deployment                                  | Engineering/Platform Admin | Platform Admin                  | Security (for any change touching data access)           | —                     |
| AI model or vendor change (e.g. Foundry configuration) | Engineering                | Platform Admin                  | Legal (vendor terms), Security                           | Finance (cost impact) |
| Ongoing spend threshold changes                        | Platform Admin             | Finance                         | —                                                        | Portfolio Lead        |
| Individual report content                              | AI pipeline (drafts)       | Program Lead (approves/rejects) | —                                                        | Portfolio Lead        |

Legal, Security, and Finance are not operational users of the platform
and are deliberately not added as personas in Section 1 above — their
role is governance and approval at specific decision points, not
day-to-day interaction with the product.

  

*This addendum, together with PRD v1.0, forms the complete requirements
baseline. The remaining identified gaps — competitive and alternative
analysis, product usage analytics, and the adoption and change
management plan — are addressed in the companion Product Discovery &
Adoption Plan.*
