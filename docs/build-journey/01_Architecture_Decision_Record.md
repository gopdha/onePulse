# OnePulse — Architecture Decision Record (ADR)

Each entry follows: **Context → Decision → Reasoning → Consequences**. These are real decisions made during the actual build, not retrospective rationalization — most were debated explicitly before being made.

---

## ADR-001: Foundry Agent Service over direct Anthropic API

**Context**: OnePulse needed an LLM runtime. The original design assumed Claude Agent SDK calling Anthropic's API directly.

**Decision**: Route through Microsoft Foundry, Azure-hosted, rather than Anthropic's own endpoint.

**Reasoning**: Enables Managed Identity authentication (zero static API keys), keeps inference traffic inside Azure's network boundary (data residency), and unifies billing/governance under the same cloud tenant as everything else in the stack.

**Consequences**: Real, live-verified — confirmed the Azure-hosted option means literally zero egress to Anthropic's own infrastructure (Physical Architecture's single-egress-path claim is *stronger* than originally designed, not weaker). Cost: real quota/region friction (Claude Sonnet/Haiku were unavailable in the subscription's default region), which cascaded into ADR-005.

---

## ADR-002: Migration from classic AgentsClient to Microsoft Agent Framework

**Context**: The classic `azure.ai.agents.AgentsClient` (thread/run/message pattern) was proven working for the Foundry Agent Service go/no-go checkpoint and the full Investigation → Self-critique chain.

**Decision**: Migrate the entire agent runtime to Microsoft Agent Framework.

**Reasoning**: No OpenInference instrumentor exists for classic `AgentsClient` (confirmed via an open, unresolved GitHub feature request) — meaning Arize's quality-eval dashboard would never see properly-shaped span data on the old framework. Microsoft Agent Framework has a real, working `openinference-instrumentation-agent-framework` package. Additionally, classic `AgentsClient` has an announced retirement date (March 2027).

**Consequences**: Real migration work — researched the actual current API before writing code, hit and fixed three real `camelCase`/`snake_case` compatibility bugs in Agent Framework's native MCP client, and made a deliberate architectural choice (ADR-006) to bypass that native client rather than keep patching an immature integration. The migration was fully verified: all existing tests passed unchanged, and the exact mechanism behind the original 10x-cost bug was re-examined and found not to recur under the new architecture's explicit-only design (a hypothesis, not yet formally disproven, but consistent with everything observed).

---

## ADR-003: Deterministic orchestration over Connected Agents for the core pipeline

**Context**: Foundry Agent Service (and later, Agent Framework) offers Connected Agents — dynamic, LLM-driven routing between sub-agents.

**Decision**: The core report-generation pipeline (Investigation → Synthesis → Self-critique → Render → Persist) uses plain, deterministic Python orchestration calling each agent directly, in a fixed sequence.

**Reasoning**: The pipeline's sequence is fully known at design time — nothing about "what runs next" requires a model's judgment. Paying for an LLM call to decide something already decided is both wasteful and reintroduces the same class of risk as the original 10x-cost bug (unintended LLM involvement in something that should be deterministic).

**Consequences**: Predictable cost and behavior. This decision was later validated by real evidence: Task 27's stress test showed non-deterministic LLM behavior at scale (two runs on identical 465-item data producing wildly different, both-unsatisfactory outcomes) — reinforcing that keeping orchestration itself deterministic was the right call, even before this scale issue was found.

---

## ADR-004: Connected Agents reserved for the Chat Assistant, not rejected outright

**Context**: Having ruled out Connected Agents for the core pipeline (ADR-003), the question remained whether the pattern had any real use in this system.

**Decision**: Use Connected Agents (or an equivalent single-agent-plus-tool pattern) specifically for the RAG-based Chat Assistant.

**Reasoning**: A user asking varied, open-ended questions about past reports is a genuine dynamic-routing problem — the opposite shape from the core pipeline's fixed sequence. This is the correct, narrow use case for the capability, not a blanket rejection of it.

**Consequences**: When actually implemented (see ADR-008), the team chose a simpler single-agent-plus-FunctionTool pattern over literal Connected Agents, judged more honest for the actual need — showing this decision was revisited empirically rather than dogmatically enforced.

---

## ADR-005: Model choice — GPT-5-mini over Claude Sonnet/Haiku, by necessity not design intent

**Context**: Claude Sonnet 5 and Haiku 4.5 both hit real quota exhaustion in the subscription's default region (Australia East) — confirmed via Azure's own quota dashboard, which additionally revealed Claude models don't even appear on the standard Azure OpenAI quota page (a different quota mechanism entirely for partner models).

**Decision**: Deploy and use `gpt-5-mini` (later `onePulse-gpt-5-mini`) for the live demo and subsequent development, rather than block on quota resolution.

**Reasoning**: Under real time pressure (an imminent stakeholder demo), the actual goal — proving Foundry Agent Service mechanics, the MCP bridge, and the quality-gate logic — did not require Claude specifically. AT&T's own real disclosed stack includes Azure OpenAI models alongside Microsoft Agent Framework, making this an authentic architectural choice, not just a fallback.

**Consequences**: **This remains an open item.** The system runs on GPT-5-mini today by necessity. Whether to pursue Claude quota/region resolution or adopt GPT-5-mini as the permanent, intentional choice is an explicit, undecided question — tracked in the Project Plan.

---

## ADR-006: Manual MCP bridge over Agent Framework's native MCPStdioTool

**Context**: Agent Framework ships a native `MCPStdioTool` for MCP server integration — the "proper," idiomatic way to wire up MCP under the new framework.

**Decision**: Bypass the native `MCPStdioTool`. Keep the project's own already-proven manual bridge (using `mcp.ClientSession` directly), wrapped as plain `agent_framework.FunctionTool`s.

**Reasoning**: Three real, confirmed `camelCase`/`snake_case` compatibility bugs were found in the native client against the installed `mcp` library version — the same class of bug this project had already fixed once in its own code. The extent of remaining incompatibility was unknown; writing a general shim to patch an unmapped compatibility surface was judged genuinely risky (could silently mask a fourth, non-naming-related mismatch). The manual bridge was the single most hard-won, real-data-proven piece of code in the entire project (it survived the full ADO identity investigation and produced the first evidence-grounded, non-hallucinated agent output). Routing around an immature native integration, rather than risking that proven code, was the correct trade.

**Consequences**: Slightly more integration code to maintain, in exchange for zero risk to the most battle-tested component in the system. The Arize/OpenInference benefit (the actual reason for the whole migration) was confirmed to come from Agent Framework's own reasoning/tool-invocation spans regardless of which tool-calling mechanism feeds it — so nothing was lost by this choice.

---

## ADR-007: Deterministic Committed-Feature scoping over hierarchy-aware summarization

**Context**: A real stress test against a 465-item ADO project (Agentic AI Observability Platform, full backlog) revealed the flat "investigate everything" approach was both non-deterministic (two runs on identical data produced wildly different results) and impractical (one run returned 0 findings and was rubber-stamped approved due to a separate check defect; the other covered only ~4.3% of items despite reading everything).

**Decision**: Filter Investigation's scope *before* any agent call, deterministically, to only Features tagged `Committed` (via a real ADO tag) plus their real children (via `System.Parent`). No fallback to full-project investigation — if zero Committed Features exist, the system says so honestly rather than falling back to the broken flat approach.

**Reasoning**: Reducing the actual input size deterministically sidesteps the non-determinism problem at its root, rather than asking a model to reliably summarize hundreds of items after the fact (which was tried conceptually and rejected — see Trade-offs Log).

**Consequences**: Real, measured results: ~5.9x token reduction and ~59% latency reduction against the same 465-item project, with the coverage problem genuinely solved (100% of the filtered scope investigated, not just cheaper). This decision directly enabled ADR-012 (the Tower View report format), since the Committed-Feature scope naturally maps onto a real Epic → Feature → Story hierarchy.

---

## ADR-008: RAG-based Chat Assistant scoped to persisted reports only, not live ADO

**Context**: The Chat Assistant needed a data source. Two options existed: index the persisted `reports`/`findings` tables in Postgres, or let the assistant query ADO directly (like Investigation does).

**Decision**: Index only Postgres — the assistant answers questions about the *archive* of what's already been investigated and reported. It never performs live ADO lookups.

**Reasoning**: Indexing raw ADO directly would duplicate Investigation and Status Analysis's job, throw away their already-synthesized, already-quality-gated output, and blur a clean architectural boundary (Investigation does live work against current state; the Chat Assistant answers questions about history). If a report never mentions something, the honest answer is "not found in any generated report" — not a live fallback that would make this a second, less rigorous Investigation agent.

**Consequences**: Real, two-level chunking (report-level summaries + individual finding-level chunks), with every answer citing real `report_id` + `source_item_ref` identifiers. Proven both directions in testing: a real grounded answer with citation, and an honest "not found" with zero fabrication.

---

## ADR-009: Single-threaded pipeline execution preserved via explicit cancellation, chosen over simpler alternatives

**Context**: Adding live-ticking progress timers to the UI required either keeping the pipeline synchronous on Streamlit's own script thread (limiting timer granularity) or moving execution to a background thread (enabling smooth ticking but risking the already-proven "project-switch genuinely terminates the backend call" guarantee).

**Decision**: Background thread, with real, explicit cancellation plumbing (a `threading.Event` checked inside every `on_stage`/`on_detail` callback) — chosen over staying single-threaded (which would have meant uneven timer updates) and over accepting silent backend continuation (which would have reintroduced a previously-eliminated risk).

**Reasoning**: This was the only option meeting the live-ticking requirement without silently degrading the termination guarantee. It required additional real engineering (fixing `contextvars` propagation across the thread boundary for observability routing) but kept the core safety property intact, verified via real measurement rather than assumed.

**Consequences**: The termination guarantee's *character* changed, and this is documented precisely rather than glossed over: switching projects always **eventually** stops the backend (never silently completes and persists a surprise report), but the actual stop time is now bounded by whatever work is in flight — measured at ~4s and ~16.5s in two real test scenarios, not instant. This is a genuine, permanent trade-off of the threaded architecture, not a bug.

**Superseded (Migration Plan Phase 3, Task 42, 2026-09-09):** this entire decision no longer applies. Once pipeline execution moved to a real, separate worker process — not a background thread inside Streamlit — the problem this ADR exists to solve (smooth UI ticking vs. a real termination guarantee, both constrained to one process) stopped being real: the worker is not a thread Streamlit spawns and cannot cancel or race with, so there is nothing left to bound. The `threading.Event`/`contextvars.copy_context()` plumbing this ADR chose was removed outright, not left inert. The bounded-by-in-flight-work guarantee this ADR measured (~4s/~16.5s) is superseded by an unconditional one: closing the client entirely does not affect the worker at all, proven live in Task 42. Kept here for real historical reference, same treatment as every other superseded decision in this log — not deleted just because the architecture moved on.

---

## ADR-010: Streamlit for the UI, not Azure Static Web Apps

**Context**: Physical Architecture originally specified Azure Static Web Apps for the Review UI.

**Decision**: Build a local-first Streamlit application instead, treating Azure Static Web Apps deployment as a separate, later concern.

**Reasoning**: Matches this project's consistent pattern of proving logic locally before taking on cloud deployment complexity (the same approach used for Postgres via `az login` before any Managed-Identity workload deployment, and for Foundry before AKS). Streamlit's pure-Python model let the UI reuse `onepulse_common`'s already-proven functions directly, with no new REST API layer required.

**Consequences**: A fully functional, iteratively redesigned UI (culminating in the Ops Console layout) was built and demo-ready quickly. Real cloud deployment via Azure Static Web Apps remains a deliberate, undone Next-scope item.

**Amendment (recorded in full in ADR-015)**: the Consequences above are no longer accurate. Azure Static Web Apps was never actually viable for a Streamlit deployment in the first place — it hosts static assets and Azure Functions, and cannot run a stateful Python websocket server — so it was never real pending Next-scope work waiting to be resumed; that framing was wrong from the start, not merely overtaken by events. This decision is superseded by ADR-015 (React + FastAPI replaces the Streamlit UI) and ADR-016 (Azure Container Apps as the compute target). ASWA becomes viable again once the frontend is a React build (which produces exactly static assets), but it is still **not chosen** — FastAPI serves the built bundle directly instead, per ADR-015's own reasoning (one origin, no separate CORS surface, no CDN benefit at this scale).

---

## ADR-011: Azure DB for PostgreSQL Flexible Server over Neon

**Context**: Neon was the originally-designed Postgres provider.

**Decision**: Switch to Azure DB for PostgreSQL Flexible Server.

**Reasoning**: Neon does not support Azure Managed Identity authentication — a hard requirement for the project's zero-static-secrets discipline.

**Consequences**: Real, live-proven Entra ID-only authentication throughout the project, including a full local-dev bootstrap (`app_role`, `app_role_local_dev`) and a real, stress-tested append-only guarantee on `approval_records` (see Governance & Security Reference).

---

## ADR-012: Tower View executive report format for hierarchical projects, with deterministic fallback

**Context**: The default one-page report format (flat findings list) broke down at scale — a 115-item real project produced a report extending far past one visible page, with near-identical repeated evidence text for "On Track" items.

**Decision**: Build a second, business-language report format ("Tower View") that groups findings by real Epic → Feature hierarchy, showing per-tower completion percentages and flagged-item counts computed deterministically (no model call). Projects without a real Epic hierarchy (like `singleSlide`) continue to use the original flat-findings format automatically.

**Reasoning**: An executive reader needs a 5-second read organized around real business structure (Towers, Features, Initiatives), not ADO mechanics (work item IDs, states). The health-color rule was made an explicit, documented decision (Green only at zero flagged items; Amber for any nonzero flagged count; Red reserved for genuinely Blocked items) rather than an arbitrary percentage threshold — real counts differentiate severity within a color tier.

**Consequences**: A real bug was found and fixed during verification — the hierarchy-detection query needed to check `WorkItemType == "Epic"` explicitly, since a stray legacy parent link on `singleSlide` (a Task, not an Epic) was incorrectly triggering the new format. Fixed and verified: the Tower View renders correctly for the real hierarchical project, and the fallback format renders correctly, unaffected, for the non-hierarchical one.

---

## ADR-013: No egress to Anthropic's infrastructure, given Azure-hosted Claude

**Context**: The original Physical Architecture diagram showed two egress paths: one to Anthropic's API, one to Arize.

**Decision**: Remove the Anthropic API egress path entirely from the architecture diagram and the real deployment.

**Reasoning**: Confirmed via Microsoft's own documentation that Azure-hosted Claude deployments process inference entirely within Azure's own infrastructure — there is no real network path to Anthropic's servers for model calls under this configuration.

**Consequences**: A stronger, more accurate security posture than originally designed: "only one real outbound path" (to Arize) is a true and better claim than the original "only two," not a downgrade.

---

## ADR-014: Content Safety — reliance on Foundry's default filtering, with an explicit residual gap

> **Status: draft — one input pending verification.** The claim about this deployment's actual
> filter configuration (see Context, item 3) has not yet been confirmed against the real Azure AI
> Foundry resource. This ADR should not be treated as final until it has. Recorded in draft form
> because the absence of *any* documented reasoning for NFR-8 was itself the larger gap.

**Context**: NFR-8 requires that all model-generated content pass an explicit content-safety check
before reaching a human reviewer, and the Physical Architecture specified a mandatory call to Azure
AI Content Safety after QA and before Human Governance. This was never built — Content Safety
integration stands at 0% in the Project Plan. Unlike every other open item in this project, its
absence had no recorded decision behind it.

Three facts bear on it:

1. NFR-8's original justification was model-specific: Foundry was confirmed at design time not to
   apply automatic content filtering to Claude. That was the gap the requirement existed to close.
2. The system does not run Claude. Per ADR-005 it runs `onePulse-gpt-5-mini`, an Azure OpenAI
   model. Microsoft's documentation states that models deployed to Foundry receive default safety
   settings — a filtering system itself powered by Azure AI Content Safety, applied to both prompts
   and completions, blocking Medium severity and above by default.
3. **Pending verification**: whether this specific deployment uses the default filter configuration
   or a modified one. To confirm: Azure AI Foundry → the OnePulse project → Guardrails + controls →
   Content filters → the configuration bound to the `onePulse-gpt-5-mini` deployment.

**Decision**: Rely on Foundry's platform-level content filtering rather than building the separate,
explicit Azure AI Content Safety call the Physical Architecture specified. Do not treat NFR-8 as
fully satisfied. Record the residual gap below rather than closing the requirement.

**Reasoning**: The specific gap NFR-8 was written to close no longer exists in the same form — it
was a property of Claude-on-Foundry, and the model changed. Building a separate Content Safety call
would duplicate a check the platform already performs on every model call, adding real cost and
latency to close a gap that has substantially moved. This mirrors ADR-003's reasoning: don't pay for
work already determined elsewhere.

**Consequences and the residual gap, stated plainly**:

- Filtering operates *inline, per model call*. The final report artifact is assembled
  deterministically afterward (rendering, Tower rollup, per-tower percentages, flagged counts). The
  assembled artifact as a whole is never safety-checked — only its constituent model outputs were.
  NFR-8 as written asks for a check on content before it reaches a human reviewer, and that specific
  reading is **not** satisfied.
- Default filtering allows Low-severity content through. Whether that threshold is appropriate for
  executive status reporting is a deliberate, unexamined acceptance, not a verified fit.
- **This ADR is coupled to ADR-005.** If the Claude quota question is resolved in Claude's favour,
  the original NFR-8 gap returns in its original form and this decision must be reopened, not
  inherited. Any future ADR revisiting the model choice must revisit this one in the same breath.
- The Demo Narrative's existing guidance stands unchanged: do not imply Content Safety is handled.
  The accurate statement is now more precise — platform-level filtering applies to every model call;
  a dedicated end-of-pipeline safety gate was deliberately not built.

**Alternative considered and rejected**: implementing the explicit post-QA Content Safety call as
originally designed. Rejected as duplicative given fact 2 above — but this is the correct thing to
build if the residual gap on the assembled artifact is judged to matter, or if the model reverts to
Claude.

---

## ADR-015: React + FastAPI, replacing the Streamlit UI

**Context**: ADR-010 chose a local-first Streamlit application over the Physical Architecture's
Azure Static Web Apps design, explicitly because Streamlit's pure-Python model let the UI reuse
`onepulse_common`'s proven functions directly, with no REST API layer required. That reasoning held
while the system was single-user and local. Three things changed it: the intent to deploy so the
system can be reached from anywhere, the intent to share a URL with external people, and the
accumulated cost of running a multi-minute pipeline inside a rerun-based framework.

**Decision**: Replace the Streamlit UI with a React single-page application talking to a FastAPI
backend. Plain React built with Vite, not Next.js.

**Reasoning**: React runs in the browser, and nothing in this system can safely run there — the
pipeline is Python, Managed Identity has no browser equivalent, browsers cannot speak Postgres, and
scope resolution must happen server-side or the guarantee is fake (LLD §10.2 already specifies that
the asker's authorized scope is resolved server-side and never client-supplied). A server-side API
layer is therefore mandatory, not optional. FastAPI specifically because the codebase is async
throughout — `mcp.ClientSession`, Agent Framework calls, anyio task groups — and a sync framework
would reintroduce the class of complexity ADR-009 already documents the cost of. Next.js was
rejected because its principal features (server components, API routes, SSR) exist to let the
frontend be its own backend, which conflicts with having a Python backend; and because SSR would
require a second always-on Node server for an internal tool with no SEO or first-paint requirement.

**Consequences**: This reverses ADR-010's central benefit. The REST layer that decision existed to
avoid must now be built, and it is the bulk of the work — the React portion is comparatively small.
Bought in exchange: real multi-user authentication, a durable execution boundary, and a UI that is
not fighting a rerun model. The endpoint contract is not new design work — LLD §10.2 specified these
endpoints during the design phase and they were never implemented.

**Amendment to ADR-010**: ADR-010 records Azure Static Web Apps as deferred Next-scope work. That is
now incorrect in both directions. ASWA was never viable for Streamlit at all — it hosts static assets
and Azure Functions, and cannot run a stateful Python websocket server — so it was never pending work
to be resumed. It becomes viable again for a React build, which produces exactly static assets. It is
nonetheless **not chosen**: FastAPI will serve the built bundle, because a single origin avoids a
second deployment and a CORS surface, and a CDN provides no measurable benefit for an internal tool
with a handful of users.

---

## ADR-016: Azure Container Apps as the compute target

**Context**: The original Physical Architecture specified AKS. The real build never deployed
anywhere, running local-first per ADR-010. Deploying the FastAPI backend requires choosing a
compute target.

**Decision**: Azure Container Apps, Consumption plan.

**Reasoning**: A custom container is mandatory regardless of the platform, because ADR-006's manual
MCP bridge spawns `@azure-devops/mcp` as a Node stdio subprocess — the image must carry both Python
and Node. Container Apps supports Managed Identity, HTTP ingress with websockets, built-in Entra
authentication, internal-only ingress for non-public services, and scale-to-zero. Scale-to-zero
matters concretely: usage is bursty (demos and development sessions), and the Consumption plan's
per-subscription free grant of 180,000 vCPU-seconds and 360,000 GiB-seconds covers roughly 50 hours
per month at 1 vCPU / 2 GiB — well beyond real usage. App Service was rejected because it cannot
scale to zero, so a plan bills around the clock. AKS was rejected as disproportionate for a system
with one real user.

**Consequences**: Compute cost is expected to be zero within the free grant, with Azure Container
Registry (~US$5/month) and Log Analytics ingestion as the real added spend. The trade-off is cold
starts on a heavy Python-plus-Node image; mitigated by raising `minReplicas` to 1 temporarily before
a demo and returning it to 0 afterward, rather than paying idle rates continuously. Note that
deploying the UI largely cancels the option of stopping the Postgres server between sessions, since
the database must be available whenever the app might be opened.

---

## ADR-017: Separate BFF and core API, for learning and future extensibility

**Context**: A single FastAPI service would satisfy every current requirement. This system has one
frontend, one backend, and one real user.

**Decision**: Split the backend into two services — a BFF with external ingress, and a core API with
internal ingress only. Build the single service first, prove it working, then split it as a
deliberate step.

**Reasoning**: This decision is **not** driven by a current functional requirement, and that is
recorded deliberately rather than dressed up as necessity. It is driven by two stated goals: using
this project to learn Azure cloud services hands-on, and leaving room to add further services later.
The split exercises concepts a single service never would — external versus internal ingress,
service-to-service authentication with Managed Identity (acquiring an Entra token for another
service's own app registration, rather than sharing a secret or trusting a header), and distributed
trace propagation across a process boundary via W3C `traceparent`. That last one extends work already
done twice: `contextvars` propagation across the UI thread boundary, and root-span re-verification
under the threaded architecture.

Building one service first and splitting it afterward follows the same prove-one-thing-at-a-time
pattern ADR-010 established for Postgres and Foundry: splitting something known to work reveals what
the boundary actually costs, in a way that starting split does not.

**Boundary definition, to prevent the split becoming meaningless**: the BFF owns session, identity
resolution, and response shaping for the frontend. It owns **no data stores** and never connects to
Postgres, Azure AI Search, or Foundry directly. The core API owns the domain and every data
connection, and dispatches work to the pipeline worker. A single "just this one query" connection
from the BFF to Postgres collapses the boundary and forfeits the entire reason for the split.

**Open question, to be decided explicitly during implementation**: whether the BFF resolves the actor
and passes it to the core API, or the core API resolves identity independently. If the core trusts a
BFF-supplied actor ID, the core is only as secure as the network boundary — structurally the same
mistake Governance & Security Reference §5 documents at the UI layer, one level up.

**Consequences**: Every schema or field change touches two services. Debugging spans two log streams.
With both services scaled to zero, a first request pays two chained cold starts. Accepted knowingly,
in exchange for the learning outcome, which is the actual objective here.

---

## ADR-018: Cookie-based session via platform authentication; no token in the browser

**Context**: With a React SPA there are two standard authentication shapes: a public-client SPA that
holds an access token in browser memory and sends it as a bearer header, or a BFF pattern where
sign-in happens server-side and the browser holds only an opaque session cookie.

**Decision**: BFF pattern. Sign-in is handled by Azure Container Apps built-in authentication at the
ingress; the session rides on an HttpOnly, Secure, SameSite cookie; no access token is ever exposed
to browser JavaScript.

**Reasoning**: The intent to share a URL with external people widens the population of browsers this
runs in, making token exposure a real rather than theoretical concern. It compounds badly with the
system's strongest guarantee: `approval_records` is append-only by explicit `REVOKE`, so an approval
made with a stolen token is permanently unerasable — the guarantee working against its owner.
Platform authentication also forwards the verified identity to the container in request headers,
which means `get_current_actor()` reads a trusted, platform-validated value rather than parsing and
validating a JWT in application code. That is less code and a stronger property: the identity cannot
be forged by the client, which is precisely what Governance & Security Reference §5 states the real
fix requires.

**Consequences**: The React application contains no authentication library and no token handling.
This is a decision that is easy to silently reverse later by adding MSAL to the frontend because a
tutorial suggested it; it is recorded here so that reversal has to be a conscious one.

---

## ADR-019: Investigation extracted as its own service, coordinated by a storage queue

**Context**: ADR-017 split the backend into a BFF and a core API for learning and extensibility
reasons, with no functional requirement behind it. The question of whether to decompose further —
toward the eight-service design the original Physical Architecture specified — was left open.

**Decision**: Extract exactly one further service, Investigation, and stop there. The remaining
pipeline stages (synthesis, self-critique, rendering, persistence) stay together as a **Reporting
service**. Coordination between the core API and both services runs through Azure Storage Queue, not
synchronous HTTP.

**Reasoning**: Unlike ADR-017, this split has evidence behind it. A real run against the 465-item
`Agentic AI Observability Platform` project took 378 seconds end to end, of which Investigation was
302 — 80% of the total, with every other stage measured in seconds. That is a genuine, measured
scaling asymmetry rather than a theoretical one.

> **Measurement conditions, recorded so this figure is not misread later.** The 302/378 split was
> measured on 2026-09-09 against AOP scoped to **6 Committed Features and 115 child items**, with
> `@azure-devops/mcp` 2.10.0 and `onePulse-gpt-5-mini`. AOP has since been re-tagged to **1
> Committed Feature and 11 children** to shorten the development cycle, and at that scope
> Investigation takes seconds and the asymmetry is invisible. Re-tag to the 6-feature scope before
> attempting to reproduce this measurement. The asymmetry is a property of scale; it does not
> disappear because a smaller run does not show it.

Three further properties make Investigation the right seam:

- It is the only stage requiring the Node runtime, since ADR-006's manual bridge spawns
  `@azure-devops/mcp` as a stdio subprocess. Extracting it lets every other container drop Node
  entirely, and confines the blast radius of an `@azure-devops/mcp` version change — of the kind
  that caused a real outage — to one service.
- It is the only consumer of the ADO Personal Access Token, so the Governance & Security Reference
  §4 exception narrows from "the application" to a single container.
- Its long, bursty profile is a real reason to use KEDA queue-depth scaling rather than a contrived
  one.

A queue rather than synchronous HTTP because a five-minute call needs implausible timeouts and dies
on any restart. With a queue, a message stays until the consumer deletes it, so a service that dies
mid-run has its work redelivered rather than lost.

**Consequences**:

- Two named queues, not one: `investigation-requests` and `findings-ready`. A single queue with
  mixed message types forces each consumer to inspect and discard the other's messages, and prevents
  KEDA from scaling each service on its own backlog.
- At-least-once delivery means Investigation can legitimately process the same request twice. Its
  results must be keyed on the cycle ID so redelivery overwrites rather than accumulates. Downstream
  is already protected: `UNIQUE(program_id, week_of)` blocks a duplicate report, and `findings` is
  INSERT-only with no upsert, so a repeat run reports "not persisted" rather than corrupting data.
- Poison messages become a real failure mode. A dequeue-count limit and a dead-letter path must be
  built deliberately, not discovered.
- **A stalled-but-alive consumer is a worse failure mode than a dead one, and the dequeue-count
  limit does not catch it.** Confirmed live (Migration Plan Phase 4, CLAUDE.md Task 43): the queue's
  own visibility-timeout mechanism only recovers a message when the consumer holding it actually
  dies — a hard-killed Investigation process stops renewing its lease, the message goes visible
  again, and a fresh consumer picks it up. A consumer that is *alive but stuck* (the pre-existing,
  unresolved MCP-child-stall finding from Migration Plan Phase 3, CLAUDE.md Task 42 — a spawned
  `node.exe` process silently exits while the parent Python process never notices and never returns
  from its next read) keeps calling `update_message()` on its own lease-renewal schedule
  indefinitely, because the renewal loop has no way to know the work it's renewing for has stopped
  progressing. The message therefore never becomes visible again on its own, and the dequeue-count
  limit never fires either, since the message is never redelivered in the first place for a fresh
  attempt to count against. Once deployed, this is the most likely way a run hangs invisibly: not a
  crash anyone gets paged for, just a `cycle_id` stuck at `running` forever with a real, silently
  renewing lease behind it. The real fix is a lease-renewal cap (stop renewing, and let the message
  go visible, after some bounded number of renewals) or a wall-clock ceiling on a cycle's total
  processing time (fail the cycle outright past a generous real-world bound, independent of whether
  the lease is still being renewed) — not built now; recorded here so it is designed for
  deliberately in whichever phase first puts this system somewhere nobody is watching it live.
- **The rule that makes the split real**: the Reporting service obtains findings from the
  Investigation service over HTTP. It never connects to the investigation schema. See ADR-020 for
  how that is enforced.
- The eight-service decomposition in the original Physical Architecture stays on paper. The
  Deterministic Status Rollup remains a shared library rather than a service, for the reason that
  design already gave: it is a pure function, and a network call adds latency and a failure mode for
  no benefit.

---

## ADR-020: Schema-per-service in one Postgres server, not database-per-service

**Context**: ADR-019 splits Investigation from Reporting. The microservices convention is
database-per-service, so that no service can read another's data directly.

**Decision**: Each service owns its own **schema** with its own database role, inside the single
existing Azure Database for PostgreSQL Flexible Server. Not separate servers.

**Reasoning**: A second Flexible Server means a second B1MS compute instance plus storage —
approximately CA$25–30 per month, close to doubling the current bill for a learning exercise — and a
duplicated bootstrap of `migrate.py`, `verify_migration.py`, and the Entra role setup. Separate
schemas with separate roles deliver the property that actually matters: the Reporting service's role
holds no grants on the investigation schema and vice versa, so cross-access is rejected by Postgres
rather than avoided by convention. This is the same permission-level enforcement discipline already
applied to `approval_records` via `REVOKE` and to `app_role`.

Promotion to a separate server later is a connection-string change rather than a redesign, precisely
because no code assumes a shared connection.

**Consequences**:

- `findings` currently holds a foreign key to `reports`. Across the service boundary that FK cannot
  exist: Investigation stores raw per-item results keyed by its own run ID, and the Reporting service
  fetches them and persists them into core `findings` linked to a real report. The same information
  now lives in two places. That duplication is the actual trade of database-per-service — referential
  integrity given up in exchange for autonomy — and is accepted knowingly.
- Unaffected: RLS on `reports`, the `REVOKE UPDATE, DELETE` on `approval_records`, and
  `UNIQUE(program_id, week_of)` all live entirely in the core schema. The project's strongest
  guarantees do not cross the boundary.
- The definition of done for this work includes a **real query from the Reporting service's role
  against the investigation schema, shown failing with a permission error** — tested adversarially,
  in the same spirit as the append-only guarantee, rather than asserted.

---

## ADR-021: Run status by polling a status table; report download by user-delegation SAS

**Context**: Streamlit could display live progress because the pipeline ran in the same process.
Once execution moves behind a queue, the browser has no connection to the worker. Separately,
rendered `.pptx` files currently land on local disk under `output\<project>\`, which does not
survive an ephemeral container filesystem.

**Decision**: Progress is written by the worker to a status table in Postgres and polled by the
client through the core API, roughly every three seconds. Rendered reports are written to Azure Blob
Storage; download is by a short-lived user-delegation SAS issued by the core API after an
authorisation check, with the browser fetching directly from Blob Storage.

**Reasoning**: Because status lives in Postgres, any replica of the core API can answer the
question. Server-sent events or websockets would pin the browser to whichever replica holds the
connection, which fights both scale-to-zero and multi-replica ingress. Polling also handles the
closed-laptop case for free. For a six-minute run, roughly 120 requests is negligible load.

A user-delegation SAS is signed by the Managed Identity rather than a storage account key, so it
does not breach the zero-static-secrets discipline of Governance & Security Reference §1, and the
file transfer never passes through a container.

**Consequences**:

- The status table must represent **four distinct terminal outcomes**, not a boolean: persisted;
  persisted and routed to human review; not persisted because a report for that week already exists;
  and `hard_stop_defect` where nothing was rendered. "Not persisted, already exists" is frequently
  the correct result rather than a failure.
- Progress must be written **during** long stages, not only at stage boundaries. A real run dispatches
  115 concurrent `list_comments` calls in 70ms and then produces no output for 4m17s — 68% of the
  run. A status table updated only per stage would make a healthy run indistinguishable from a hang,
  which is precisely what happened once already.
- Once issued, a SAS URL is a bearer credential. Expiry must be short (minutes), authorisation must
  happen before issuance, and the URL must not be logged.
- `rendered_artifact_uri` begins holding a blob path rather than a local file path — a change of
  semantics, not a schema migration.
- The Storage Queue (ADR-019) and the blob container share one Azure Storage account, which is also
  the natural home for the run log files that would otherwise vanish with the container.

**Not chosen**: Azure Web PubSub or SignalR for real server push. A legitimate option and a real
learning opportunity, but a managed service to provision and pay for, solving a problem polling
already solves adequately at this scale. Revisit if push becomes genuinely needed.

---

## ADR-022: The chat assistant stays synchronous and off the queue

**Context**: With a queue introduced for pipeline execution (ADR-019), the question arises whether
the RAG chat path should use it too, for consistency.

**Decision**: No. The chat request path runs synchronously through the core API: embed the question,
query Azure AI Search, generate the answer with Foundry, return it.

**Reasoning**: A user is waiting, the answer takes seconds, and there is no long-running work to
survive a restart. Routing it through a queue would make it slower and no more reliable. The queue
exists for the six-minute pipeline specifically, not as a general communication mechanism — a
distinction worth recording, because "we have a queue, so everything goes through the queue" is the
easy default.

**Consequences and boundaries reaffirmed under the new architecture**:

- **Scope resolution stays server-side, in the core API.** LLD §10.2 requires that the asker's
  authorized scope is resolved server-side and applied as a mandatory retrieval filter, never a
  client-supplied parameter. With a visitor role (migration plan Phase 7), this is the only thing
  standing between a visitor and reports they are not entitled to see, so it must sit on the server
  side of the BFF boundary.
- **No path to Azure DevOps.** ADR-008 stands: the assistant answers from the persisted report
  archive only. Its absence from the RAG diagram is the decision, not an omission.
- Indexing sits on the **write path**: when the Reporting service persists a report, the report is
  chunked two ways (report-level summary, finding-level detail), embedded through Foundry, and
  written to AI Search. Whether indexing is a separate service or a step inside Reporting is left
  open; separate is cleaner for reindexing, folded-in is one fewer container.
- A `reindex` command that rebuilds the index from persisted reports should be built alongside
  `migrate.py` and `verify_migration.py` rather than improvised. Postgres is the source of truth;
  AI Search is derived and must be rebuildable.

---

## ADR-023: `migrate.py` connects as `app_role`, not `app_role_local_dev` — retroactive ownership fix plus a root-cause change

**Context**: A pre-Phase-6 audit found that every real object in the `public` schema — all 12 tables
and their 6 sequences — was owned by `app_role_local_dev`, the local-dev role, not `app_role`, the
role Phase 2 created specifically for the deployed workload identity (`id-onepulse-app-dev`, a real,
already-provisioned Managed Identity that has simply never been attached to a running workload).
Ownership bypasses every GRANT/REVOKE layered on top of it — the third real instance of this bug
class in this project (`app_role_local_dev`'s undocumented excess privileges; `investigation.
investigation_runs`'s wrong table owner; this). Root cause: `migrate.py --target dev` has always
defaulted to connecting as `app_role_local_dev`, since `app_role` requires a genuine Managed Identity
token no interactive session can present — whichever role runs a migration becomes the owner of
whatever it creates, and `app_role_local_dev` is the only role anything has ever run migrations as.

**Decision**: Two parts, not one. (1) Retroactively reassign ownership of all 35 real objects (12
tables, 6 sequences — indexes follow their table's owner automatically, confirmed by direct
before/after query, not assumed) to `app_role`, run once by the real Postgres Entra Administrator.
(2) Change `migrate.py`'s default connecting role for the `dev` target from `app_role_local_dev` to
`app_role`, so every object created by a fresh migration run from this point on is owned correctly
from the start — closing the root cause, not just its one visible symptom.

**Reasoning**: The two application roles were never a real isolation boundary to begin with — the
human Entra Administrator is a member of both (confirmed via `pg_auth_members`), so anyone who can
act as `app_role_local_dev` can already `SET ROLE app_role`. What the two roles genuinely provide is
different, deliberately narrower grant sets for `app_role`, matching least-privilege design; changing
`migrate.py`'s connecting role leaves that distinction fully intact. Weighed against the alternative
(leave the default alone and accept that the next schema change reintroduces the identical ownership
drift by default, not by exception), the trade is clearly worth it. A third option — a self-asserting
`OWNER TO app_role` block embedded directly in the routinely-executed migration file — was rejected:
it can only succeed if the connecting role is already a member of `app_role` (Postgres requires this
to reassign ownership), which `app_role_local_dev` is not, and is not planned to become, since
granting that membership would let any local developer assume the production role outright — a
materially bigger, undiscussed change to make solely in service of a self-healing migration step.

**Consequences, three real and unanticipated, found only by actually performing the fix, not assumed
from how ownership transfer "should" behave — all fixed in the same pass**:

- **Granting a privilege to an object's own current owner is a genuine Postgres no-op that never
  materializes a real ACL entry.** `app_role_local_dev`'s own `GRANT SELECT, INSERT ...` statements in
  the original migrations had "succeeded" every time they ran, while it was the owner, without ever
  producing a real grant — confirmed directly via `pg_class.relacl`: every table showed zero ACL
  entries for `app_role_local_dev` immediately after ownership moved away. A real test
  (`test_approve_report_end_to_end`) failed with a genuine `permission denied for table programs` the
  moment ownership transferred, proving this wasn't theoretical. Fixed by re-running the same GRANT
  statements now that they are no longer no-ops (`0004_reassert_public_schema_ownership_and_grants.sql`).
- **The new owner automatically inherits every owner-implicit privilege it was never intended to
  have.** `app_role`, as the new owner, silently gained `TRUNCATE`/`REFERENCES`/`TRIGGER`/`MAINTAIN` on
  all 12 tables plus `DELETE` and unintended `UPDATE` — confirmed via `has_table_privilege`, not
  assumed. The one bright spot: the original `REVOKE UPDATE, DELETE ON approval_records FROM
  app_role` survived the ownership transfer intact, confirmed live — Postgres honors an explicit
  REVOKE against a role even after it becomes an object's owner. Fixed by `REVOKE ALL` then
  re-`GRANT`ing exactly the intended profile for both roles, rather than trying to enumerate every
  owner-implied bit individually.
- **Two more previously-invisible bugs surfaced only because a genuinely non-owner role finally tried
  to use these tables for real.** (a) The `reports.tenant_isolation` RLS policy — enabled since Phase
  2 but never actually evaluated, since its owner was always exempt — calls `current_setting('app.
  current_tenant_id')` with no `missing_ok` flag in two places; nothing anywhere sets that GUC, so the
  policy raised `unrecognized configuration parameter` the instant a non-owner role touched `reports`.
  Fixed (`0005_fix_tenant_isolation_policy_unset_guc.sql`) to be permissive when the tenant context is
  unset, matching this project's own Now-scope reality (single tenant, active enforcement deliberately
  deferred) rather than either erroring or silently filtering every row to zero. (b) Postgres's
  internal FK-check row lock (`SELECT ... FOR KEY SHARE`, run automatically on every INSERT into a
  table with a foreign key) requires `UPDATE` privilege on the referenced table, not merely `SELECT` —
  this is the exact question Task 31 hit and left unresolved for `approval_records`/`reports`, now
  answered definitively by direct empirical test. Fixed with column-level grants scoped to just the
  referenced primary-key column of each of the five real tables this schema's FKs reference (`tenants`,
  `portfolios`, `programs`, `actors`, `findings`) — confirmed sufficient by direct test, avoiding a
  blanket table-level `UPDATE` that would let these roles modify columns no FK check ever touches.
- **A fourth consequence of this same ownership transfer, not a separate issue: `app_role` — now the
  real owner of `reports` — would itself have been exempt from `tenant_isolation`, the identical bug
  one level up, on the very table where owner exemption was just discovered as the root cause of RLS
  having never been evaluated.** `FORCE ROW LEVEL SECURITY` was never set on `reports`
  (`relforcerowsecurity = false`), so ownership exemption applied unconditionally to whichever role
  owned the table — first `app_role_local_dev`, now `app_role`, with nothing about the transfer itself
  changing that. Fixed (`0006_force_row_level_security_on_reports.sql`): `ALTER TABLE reports FORCE ROW
  LEVEL SECURITY`, confirmed live via direct query (`relforcerowsecurity = true`). **Stated precisely,
  so it is not read as more than it is: this makes RLS un-bypassable by ownership once it enforces
  something. It does not make RLS enforce anything today.** `tenant_isolation`'s own policy body
  (0005) is still permissive whenever `app.current_tenant_id` is unset, and nothing in this codebase
  sets it yet — real per-request tenant resolution is deliberately deferred to Phase 8's own
  `get_current_actor()` work (see `12_Migration_Plan.md`'s Phase 8 Definition of Done), not wired in
  now. Validating a tenant-setter against this project's one real tenant row today would be code whose
  correctness cannot be verified — the same pattern this whole finding is about, just a smaller
  instance of it — so it was deliberately not built as part of this fix.
- **`migrate.py --target dev` cannot be run interactively under its own new default.** Confirmed live:
  `InvalidAuthorizationSpecificationError: Service principals cannot generate AAD_AUTH_TOKENTYPE_APP_USER
  tokens for role "app_role"` — a real Azure AD token-type restriction, not a bug, and exactly the
  correct behavior (`app_role` should only ever be usable by a genuine deployed identity). This means
  the literal command cannot be exercised end-to-end until Phase 6 attaches `id-onepulse-app-dev` to a
  real running workload; the underlying ownership mechanism was instead verified honestly via `SET
  ROLE app_role` (a real, granted membership) creating a real table and confirming its owner, not by
  papering over the limitation.
- `verify_migration.py` gained its first positive-ownership check (`check_object_owner`), covering all
  12 tables and 6 sequences — the gap that let all three real instances of this bug class go
  undetected until something else happened to expose them. Demonstrated live catching a real,
  deliberately wrong owner before being accepted as a permanent check.
- **A second, distinct grant-to-owner mechanic, found live during the pre-Phase-7 audit
  (2026-09-10) while demonstrating `verify_migration.py`'s new ownership checks against a
  deliberately wrong state — the reverse of the one above, not the same bug restated.** The
  original finding is that granting a privilege to a role that is *already* the owner is a no-op:
  it silently fails to add a real ACL entry. This one runs in the opposite direction: when a
  role that *already held a real, explicit grant* (`investigation_role_local_dev`, which genuinely
  had `SELECT`/`INSERT`/`UPDATE` on `investigation.investigation_runs` and real `USAGE` on the
  `investigation` schema) was temporarily made the *owner* of that table and schema — to
  demonstrate the new ownership checks catching a wrong state, then reverted — its own
  pre-existing grants were silently stripped by the round-trip and did not come back on their own
  once ownership reverted. Confirmed directly via `relacl`/`nspacl`: after the revert, the table
  and schema ACLs showed nothing for `investigation_role_local_dev` at all. Not a hypothetical —
  it surfaced as a real, failing `test_verify_migration.py` assertion on the very next full-suite
  run, not caught by inspection. Fixed by re-applying the idempotent
  `investigation_migrations/0001_initial_schema.sql`/`0002_reassert_investigation_grants.sql`
  (the same self-healing migrations already designed for this bug class), confirmed restored by
  direct query, not just by the check passing again. **The two mechanics are opposite failure
  directions of the identical underlying cause (ownership and ACL grants are two separate,
  independently-tracked things in Postgres, and moving one can silently desynchronize the other):
  the original bug silently fails to ADD access when granting to a current owner; this one
  silently REMOVES a role's own pre-existing access when that role passes through ownership and
  back out again.** Worth recording here, not left living only inside a migration file's comment
  — this ADR is the reference for this whole bug class, and a reader relying on it should see both
  directions the class actually takes, not just the one that motivated the original fix.

**Not chosen**: A dedicated third "schema owner" role, separate from both `app_role` and
`app_role_local_dev`, matching a common enterprise Postgres pattern (a DDL-only identity distinct from
every runtime role). Cleaner in the abstract, but more infrastructure to stand up for a problem the
existing two-role design already has a correct answer for once its migration-runner default is fixed
— not pursued without a concrete reason the existing roles can't serve this purpose.

---

## ADR-024: Phase 6 provisions real identities without proving Managed Identity works; a Service Principal secret is rejected as the substitute

**Context**: Migration Plan Phase 6's original Definition of Done asked for "a full run with zero
interactive credentials available." Before implementing, a direct test was run rather than assumed:
from inside a real local container, a request to Azure's Instance Metadata Service
(`169.254.169.254`, the real endpoint `ManagedIdentityCredential` calls to obtain a Managed-Identity
token) failed to connect entirely — not an auth failure, a routing failure. IMDS is reachable only
from genuine Azure compute; it verifies the caller against the specific Azure resource an identity
is attached to, and there is no way to present a local process as that resource from outside Azure's
own compute fabric. "Containers stay local" (this phase's own stated constraint) and "prove Managed
Identity auth end to end" are therefore mutually exclusive for the actual runtime mechanism, not a
gap that more Entra permissions, more RBAC assignments, or more careful configuration could close.

**Decision**: Split Phase 6's bar into what is real and provable locally, and what genuinely is not.
Provision every real identity, RBAC grant, Postgres role mapping, and Key Vault secret this phase
calls for, and verify all of it live — by direct query, by a real end-to-end pipeline run, never by
configuration alone. Do **not** attempt to prove Managed Identity authentication itself works end to
end from a local container. That proof is real, necessary, and explicitly assigned to Phase 7 (see
its own amended Definition of Done), the first point these containers are genuine Azure compute with
IMDS actually reachable.

**Reasoning**: Three real options were considered before deciding, not one accepted by default.

1. *Split the bar (chosen).* Honest about what a local container can and cannot prove; wastes no
   effort chasing a proof that cannot exist in this environment; the real infrastructure work (the
   overwhelming majority of the phase) proceeds unblocked.
2. *A Service Principal with a client secret or certificate, standing in for Managed Identity
   locally — rejected.* This would genuinely satisfy "zero interactive credentials, no `az login`"
   — but it is a second static credential in a project whose Governance & Security Reference §1
   opens with zero static secrets and tracks exactly one named, deliberately time-boxed exception
   (the ADO PAT). That exception exists because a real constraint forced it: four independent,
   failed Managed-Identity authentication attempts against a genuinely misconfigured ADO org (see
   Governance & Security Reference §4, Challenges & Real-World Findings #2). A Service Principal
   secret here would exist for a categorically different reason — to satisfy a bar that turned out
   to be unachievable as originally worded, not because a real technical constraint left no other
   option. Introducing a second static credential to make a phase whose entire purpose is
   *eliminating* credentials look complete would be self-defeating, not a proportionate trade.
3. *Real local OIDC federation (Workload Identity Federation with a locally-issued, verifiable
   token) — rejected, not because it wouldn't work, but because it isn't worth building now.* This
   would genuinely avoid both a static secret and `az login`. It requires standing up a real,
   trusted local OIDC issuer this project has no existing pattern for — novel infrastructure to
   close a gap Phase 7 closes for free, for a single phase's local verification. Revisit only if a
   concrete, recurring need for local MI testing emerges beyond this one phase.

**A related decision, restated explicitly here so it reads as deliberate rather than an
inconsistency against this same phase's own "give each service its own identity" principle**:
`core_api` and `reporting` share one Managed Identity (`id-onepulse-app-dev`), not two. This was
never in tension with "each service its own identity" — that principle is about not giving
Investigation's real blast radius (the ADO PAT, the `investigation` schema) back by sharing an
identity with services that have neither. `core_api` and `reporting` were never split at the
schema/role level in the first place (ADR-020: both are `public`-schema, `app_role` consumers by
design) — giving them two *separate* Managed Identities mapped to the *same* Postgres role would add
a real operational cost (two identities to rotate, audit, and reason about) for zero real isolation
benefit, since `pgaadauth_create_principal_with_oid` maps one role name to exactly one object ID
regardless — two identities sharing `app_role` would mean one of them silently cannot authenticate
as it at all. Investigation and BFF each get their own identity because each has a real, distinct
resource only it should reach (the ADO PAT; core API's own service-to-service app role,
respectively) — `core_api`/`reporting` have no equivalent distinct resource to separate.

**Consequences**:

- Migration Plan Phase 6's and Phase 7's own Definition of Done sections are both amended to state
  this split directly — a reader arriving at either section later, without this conversation's
  context, should not be able to come away believing Phase 6 proved Managed Identity works.
- Phase 7 inherits a real, explicit, load-bearing verification item it would otherwise have had to
  rediscover: prove a real run completes with the `azure_cli_state` volume absent or demonstrably
  unused, exercising the exact identities and grants Phase 6 already put in place.
- `docker-compose.yml` carries real, correct `AZURE_CLIENT_ID` values per service now — inert
  locally (nothing can present them to an unreachable IMDS), real configuration for Phase 7.

**Not chosen**: see Reasoning above — a Service Principal secret and local OIDC federation, both
considered and both rejected for stated, specific reasons, not merely unconsidered.
