**OnePulse — MVP Prioritization**

*Now / Next / Later — Product Roadmap Sequencing \| Ref: OnePulse PRD
v1.0 \| Author: Claude (Anthropic) \| Reviewer: Gopinath
Dhayanandamurthy*

<table width="980" data-cellpadding="13" data-cellspacing="0">
<tbody>
<tr class="odd" data-valign="top">
<td width="300" data-bgcolor="#e8f3e8"
style="background: #e8f3e8; border: 1px solid #000000; padding: 0.14in 0.15in"><p><strong>NOW
— MVP</strong></p>
<p><em>Prove the core trust hypothesis, single pilot portfolio</em></p>
<p><strong>FR-1–6 — Core Pipeline</strong></p>
<p>Investigation, Synthesis, Rendering, Persistence — without this
there's no product.</p>
<p><strong>FR-7,8,13 — Approval Gate + Deterministic Rollup</strong></p>
<p>The actual differentiator: AI-generated, always human-approved, never
silently wrong.</p>
<p><strong>NFR-2 — Managed Identity</strong></p>
<p>Can't handle real org data without it — a pilot blocker, not a
nice-to-have.</p>
<p><strong>NFR-3 — Least-Privilege Agent Access</strong></p>
<p>Cheap now, expensive to retrofit later.</p>
<p><strong>NFR-8 — Content Safety Check</strong></p>
<p>A legal/safety floor for even one real pilot user.</p>
<p><strong>NFR-9 — Migration Verification</strong></p>
<p>Directly caused two real incidents in the demo — cheap insurance.</p>
<p><strong>NFR-11 — Evidence + Approval Attribution</strong></p>
<p>Core to the trust story — an unattributed approval isn't really
auditable.</p></td>
<td width="301" data-bgcolor="#fbf3e0"
style="background: #fbf3e0; border: 1px solid #000000; padding: 0.14in 0.15in"><p><strong>NEXT</strong></p>
<p><em>Scale to multiple tenants, once Now is validated</em></p>
<p><strong>FR-9,14 — Self-Service Onboarding</strong></p>
<p>Concierge MVP first: hand-configure pilot #1, automate once
onboarding #2/#3.</p>
<p><strong>FR-10,15 — Cross-Portfolio View + Admin</strong></p>
<p>Only meaningful once a real multi-program portfolio exists.</p>
<p><strong>FR-11 — On-Demand Trigger</strong></p>
<p>Scheduled-only is a fine MVP; on-demand is a convenience, not a
blocker.</p>
<p><strong>NFR-1,4 — Multi-Tenant Isolation + Scaling</strong></p>
<p>Don't build for tenant #2 until tenant #2 exists.</p>
<p><strong>NFR-5 — Temporal Durable Workflows</strong></p>
<p>Valuable at real volume; low-volume pilot can start simpler.</p>
<p><strong>NFR-6,7 — Per-Tenant Cost Gating + Tracing</strong></p>
<p>The “per-tenant” part only matters once there's more than one
tenant.</p>
<p><strong>NFR-10 — Data Residency Options</strong></p>
<p>Only relevant once a tenant with a specific requirement
exists.</p></td>
<td width="300" data-bgcolor="#e8f0f8"
style="background: #e8f0f8; border: 1px solid #000000; padding: 0.14in 0.15in"><p><strong>LATER</strong></p>
<p><em>Deepen engagement, once adoption is proven</em></p>
<p><strong>FR-12 — Shared Chat Assistant + RAG</strong></p>
<p>The most infrastructure-heavy item on the list — worth it once people
already trust and read the core reports enough to want to interrogate
them further, not before.</p></td>
</tr>
</tbody>
</table>

  

**Sequencing principles applied:** (1) Prove the core value hypothesis
first, with the smallest footprint • (2) Concierge MVP — do the
unscalable thing manually before automating it • (3) Don't build
multi-tenant infrastructure until tenant \#2 actually exists.
