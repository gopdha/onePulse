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
`onepulse_common`'s proven functions directly, with no REST API layer required. That reasoning was
correct for what the system actually was at the time — a single-user local tool with no requirement
to authenticate anyone. **The requirement has since been stated as a multi-user production system:
real, distinct users, each authenticated, each authorized to see only their own scope of programs
and reports.**

That is the change that actually reverses ADR-010, and it is structural, not a framework preference.
Streamlit has no request-level identity model. It runs as one long-lived Python process per browser
session, driven by a rerun loop triggered by widget interaction — there is no middleware layer and no
per-request object for a caller's identity to attach to. There is nowhere for a function like
`get_current_actor()` to live, because there is no request to resolve it against, only a session
implicitly owned by whoever happens to be connected to that process. A single-user local tool never
had to answer "who is asking, right now, on this specific call," because the answer was always the
one person running it. A multi-user system must answer that question on every request, and
Streamlit's architecture has no place to put the answer.

Everything else that argues for leaving Streamlit — the intent to deploy so the system is reachable
outside a local machine, the intent to share a URL rather than a `git clone`, and the accumulated
cost of running a multi-minute pipeline inside a rerun-based framework — is real, but secondary to
that, and each is independently survivable on its own: a deployed single-user Streamlit instance is
possible, and the rerun-model's own cost was already worked around once without leaving Streamlit
(ADR-009 and Tasks 32/42's threading and worker extraction). The identity gap is not survivable the
same way — there is no bolt-on fix inside Streamlit's own model, because that model has no slot to
bolt one onto. Closing it means moving to a framework whose request lifecycle has that slot built in.

**Decision**: Replace the Streamlit UI with a React single-page application talking to a FastAPI
backend. Plain React built with Vite, not Next.js.

**Reasoning**: React runs in the browser, and nothing in this system can safely run there — the
pipeline is Python, Managed Identity has no browser equivalent, browsers cannot speak Postgres, and
scope resolution must happen server-side or the guarantee is fake (LLD §10.2 already specifies that
the asker's authorized scope is resolved server-side and never client-supplied). A server-side API
layer is therefore mandatory, not optional. FastAPI specifically because it gives that layer the
exact thing Streamlit has no equivalent of: a real per-request lifecycle, with dependency injection
(`Depends(...)`) as the standard place to resolve a caller's identity once per request — the literal,
concrete site `get_current_actor()` occupies from Phase 8 on. It is also the natural choice because
the codebase is async throughout — `mcp.ClientSession`, Agent Framework calls, anyio task groups —
and a sync framework would reintroduce the class of complexity ADR-009 already documents the cost of.
Next.js was rejected because its principal features (server components, API routes, SSR) exist to
let the frontend be its own backend, which conflicts with having a Python backend; and because SSR
would require a second always-on Node server for an internal tool with no SEO or first-paint
requirement.

**Consequences**: This reverses ADR-010's central benefit. The REST layer that decision existed to
avoid must now be built, and it is the bulk of the work — the React portion is comparatively small.
Bought in exchange: a request-level identity model with somewhere for `get_current_actor()` to
actually run, a durable execution boundary, and a UI that is not fighting a rerun model. The endpoint
contract is not new design work — LLD §10.2 specified these endpoints during the design phase and
they were never implemented.

**ADR-010 itself is not being second-guessed here.** Its choice was the right one under the
constraints that actually held at the time — no authenticated users, no per-user authorization,
nothing for a REST layer to protect that direct function calls couldn't already do more simply. This
ADR records that the constraint changed, not that the earlier judgment was wrong.

**Amendment to ADR-010**: ADR-010 records Azure Static Web Apps as deferred Next-scope work. That is
now incorrect in both directions. ASWA was never viable for Streamlit at all — it hosts static assets
and Azure Functions, and cannot run a stateful Python websocket server — so it was never pending work
to be resumed. It becomes viable again for a React build, which produces exactly static assets. It is
nonetheless **not chosen**: FastAPI will serve the built bundle, because a single origin avoids a
second deployment and a CORS surface, and a CDN provides no measurable benefit for an internal tool
with a handful of users.

**Real finding, Migration Plan Phase 9, that turns "avoids a CORS surface" from a preference into a
requirement**: a cross-origin architecture (the React build on one origin, `bff` on another) was tried
first, on the reasoning that Phase 10's same-origin serving could wait. It cannot. Container Apps' own
Easy Auth intercepts every request — including a CORS preflight `OPTIONS` — before it ever reaches this
project's own FastAPI code, and its own unauthenticated response carries no `Access-Control-*` headers
at all. That defeats every credentialed, preflight-requiring cross-origin request outright, regardless
of sign-in state — every real POST this frontend makes (trigger, approve, reject, chat) sends a JSON
body, which is exactly what forces a preflight. No `CORSMiddleware` inside this project's own app can
fix this, because Easy Auth sits in front of the app, not behind it. Confirmed live: an `OPTIONS`
preflight with a real `Origin` header returned a bare `401` with zero CORS headers, from Easy Auth
itself, before this project's own request handling ever ran. Same-origin serving was therefore pulled
forward into Phase 9 itself, in minimal form (a `StaticFiles` mount in `bff/main.py`, not yet the full
build/deploy pipeline Phase 10 will formalize) — not because the original reasoning above was wrong, but
because "avoids a CORS surface" turned out to be load-bearing immediately, not merely a tidiness
preference for later.

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
scale to zero, so a plan bills around the clock. AKS was rejected because nothing in this system's
real requirements needs Kubernetes' own primitives — no custom controllers, no StatefulSet-shaped
workloads, no multi-cluster or service-mesh requirement the project's four backend services don't
already get from Container Apps' simpler model. That is a statement about what Kubernetes offers
that this system has no use for, not about how many people use the system — the same rejection holds
regardless of user count, since Container Apps scales the same way AKS would for this workload shape.

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

**Retroactive note (2026-09-10, ADR-015's own multi-user pass)**: The requirement now stated in
ADR-015 — a multi-user production system with authenticated users and per-user authorization — gives
this same boundary a real functional justification it did not have when this decision was made:
separating session and identity handling from the domain is exactly the shape a real per-user
authorization model needs, and the boundary definition above (BFF owns session/identity/response
shaping, never a data store; the core API owns the domain and every data connection) already matches
it without modification. **This is recorded as new information arriving after the fact, not as a
correction to the decision's own history.** The split was made before that requirement existed, for
the reasons stated above — learning Azure hands-on and leaving room for later services — and the
requirement caught up with it afterward. The original Reasoning is left exactly as written above, not
softened or reframed: it was true when written (no functional requirement demanded this split at
decision time), and the honest value of this ADR is that it says so plainly rather than dressing up a
learning exercise as necessity it didn't yet have. What's added here is simply that the exercise
turned out, later, to have built the right shape for a real reason — which is worth knowing, but is
not the same claim as "the requirement drove the decision."

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

**Real consequence found only at implementation time (Migration Plan Phase 7, ADR-025):** the
platform-authentication mechanism this decision chose requires a real client secret for its own
inbound OAuth exchange with Entra — a genuine, permanent exception to this project's zero-static-
secrets principle, not something this ADR's own original reasoning anticipated. See ADR-025 for the
full account of why no version of this decision avoids it, and what bounds the exception.

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
  AI Search is derived and must be rebuildable. **Real as of ADR-029**: `ingest_reports_to_search.py`
  is that command — it upserts every current, non-fixture report/finding and, on every run, prunes any
  document Postgres no longer accounts for, which is what makes "derived" actually mean reconcilable
  rather than merely rebuildable-in-principle. See ADR-029 for the prune mechanism, its guard against a
  partial listing, and the deferred alias-based rebuild for a schema change that can't be applied in
  place.

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

---

## ADR-025: A real client secret for `bff`'s built-in Entra authentication — an unavoidable, permanent exception, not a disclosure footnote

**Context**: ADR-018 decided that sign-in for the BFF happens via Azure Container Apps' own built-in
authentication (Easy Auth) at the ingress, not a token held in the browser. Migration Plan Phase 7
implemented that decision for real for the first time. Implementing it required registering a real
Entra app for interactive sign-in (`onepulse-bff-signin`, distinct from `onepulse-core-api`, which
represents an API for service-to-service tokens, not a principal a browser signs into) and configuring
the platform's AAD identity provider against it. The only parameters `az containerapp auth microsoft
update` accepts for that provider are a client secret or a certificate (`--client-secret`,
`--client-secret-certificate-thumbprint`/`-issuer`/`-san`) — there is no Managed-Identity-federated or
otherwise secretless option in the current API surface, confirmed by reading the actual parameter set
before assuming one existed.

**Decision**: Use a real client secret, generated once (`az ad app credential reset`) and stored only
in the container app's own managed secret store (`az containerapp auth microsoft update
--client-secret ...`), never echoed to a log, a commit, or `.env` — the same handling discipline this
project already applies to every other real secret it has ever touched (Governance & Security
Reference §7). Treat this as a second, permanent, explicitly-tracked exception to the zero-static-
secrets principle, not a disclosure line inside a task summary — recorded here, and in Governance &
Security Reference §1/§4, with the same weight the ADO PAT already gets.

**Reasoning**: This is a structurally different problem from every case Managed Identity already
solves in this project, and no version of ADR-018's own decision avoids it. Managed Identity lets a
service prove *its own* identity when it calls *another* Azure resource — every real credential this
project eliminated (Postgres, Foundry, Search, Storage Queues, the ADO PAT's own replacement path)
was exactly that shape: an outbound call, this project's own code presenting a token it obtained for
itself. Easy Auth is the opposite shape: the *platform*, on behalf of a *browser*, performs a
server-side OAuth confidential-client authorization-code exchange with Entra — proving to Entra that
the party redeeming the code is who it claims to be, which is precisely what a client secret (or
certificate) exists to do, and which nothing about the caller's own identity (there isn't a caller's
own identity yet — that is the entire thing being established) has any bearing on. Managed Identity
has no role to play in this exchange because there is no "this project's own service" on either side
of it at the moment it happens — only the platform and Entra.

Two options were considered before accepting the secret:

1. *A real client secret (chosen).* Genuinely unavoidable for the specific mechanism Container Apps'
   own AAD provider implements — confirmed by reading the real parameter surface, not assumed from a
   general aversion to secrets. Stored only in the platform's own secret store, never in this
   project's code or config.
2. *A client certificate instead of a secret — considered, not chosen for this phase, not ruled out
   permanently.* `--client-secret-certificate-thumbprint`/`-issuer`/`-san` are real, supported
   alternatives — a certificate is arguably a stronger credential shape (asymmetric, more naturally
   scriptable rotation via Key Vault) but is real additional infrastructure (issuing and rotating a
   certificate, wiring it through Key Vault) for a security property Governance & Security Reference
   §4's own bar for a real exception doesn't demand: this is not a case of "any static credential is
   too risky," it is a case of "the platform's own mechanism requires one kind or another" — a secret,
   generated once and held only in Container Apps' own managed secret store, meets that bar today
   without the extra infrastructure. Worth revisiting if this project ever needs real secret rotation
   automation for other reasons; not a reason to build it solely for this.

**This does not reopen or weaken ADR-024's own rejection of a Service Principal secret.** ADR-024
rejected an SP secret specifically because it would have stood in *for Managed Identity itself* —
authenticating this project's own outbound service calls, the exact thing Managed Identity already
solves, for no reason but to satisfy a bar that turned out to be unachievable as worded. This secret
authenticates a categorically different, real mechanism — the platform's own inbound sign-in exchange
— that Managed Identity was never going to be able to touch regardless of how Phase 6/7 had gone. The
two decisions are consistent, not in tension: reject a static credential when a real, live alternative
(Managed Identity) already does the job; accept one, explicitly and boundedly, when the mechanism
genuinely has no such alternative.

**What bounds this exception, so it does not become a template for reaching for a secret elsewhere**:
scoped to exactly one purpose (the AAD identity provider's own confidential-client exchange for one
app registration, `onepulse-bff-signin`); held in exactly one place (Container Apps' own managed
secret store for the `bff` app, never in this project's own code, `.env`, or version control); never
presented by this project's own code to anything — the platform's Easy Auth sidecar is the only thing
that ever reads it, at the same layer Governance & Security Reference already treats as the security
boundary (Container Apps' own built-in authentication, ADR-018); set with a real 1-year expiry, not
indefinite, giving it at least a bounded rotation cadence even though the underlying need for *a*
secret here does not expire the way the ADO PAT's diagnostic need eventually should.

**What would change if this ever became avoidable**: if Container Apps' own AAD provider ever adds a
genuinely secretless authentication mode for its own inbound OAuth exchange (workload-identity
federation on the platform side, not merely on this project's own outbound calls), or if this project
moves off Container Apps' built-in authentication toward a model where this service itself validates
tokens (reopening ADR-018's own choice, not merely this implementation detail), this exception would
be removed then, not before — the same standard Governance & Security Reference §4 already applies to
the ADO PAT.

**Consequences**: Governance & Security Reference §1 now states two exceptions, not one — the count
itself matters, since the document's own opening sentence is a specific, checkable claim. §4's
structure (what it is / why it's unavoidable / what bounds it / what would change) is extended with a
second entry at the same weight, not folded into a shorter note, precisely because this exception is
**permanent** by its own nature (the mechanism does not expire the way a diagnostic PAT does) where
the ADO PAT is explicitly time-boxed — the two exceptions are not interchangeable instances of "one
kind of thing," and the document should not read as though they are.

**Not chosen**: a certificate-based alternative (real, available, deferred rather than rejected — see
Reasoning above); reopening ADR-018's own choice of Easy Auth over an application-level token
validator, which would trade this exception for a different, larger scope of code this project would
then own and have to get right itself.

---

## ADR-026: `reporting`'s outer trigger becomes queue-driven — the last `minReplicas: 1` exception removed, and redelivery made cheap, not just safe

**Context**: Migration Plan Phase 7's own deployment gave every service `minReplicas: 0` except
`reporting`, for a real, disclosed reason: `reporting`'s outer loop was a plain Postgres `cycles`-table
poll (`FOR UPDATE SKIP LOCKED`, unchanged since Phase 3), triggered by nothing the platform could ever
observe — no HTTP request, no queue message — so nothing could ever wake it from a scaled-to-zero
state. That exception cost roughly $21.71/month (Task 47's own real Azure Retail Prices calculation),
the dominant line item in the ~$30-40/month this phase added against the ~CA$35 baseline. A same-turn
report (recorded in Task 47's own follow-up, CLAUDE.md) found converting this to queue-driven was a
small, bounded change: `onepulse_common/queues.py` was already generic and reusable, and
Investigation's own consumer-loop shape (lease renewal, poison dead-lettering, delete-only-after-
terminal — Phase 4, ADR-019/020) was an already-proven pattern to copy, not a design to invent. That
report also named one real property worth a deliberate decision rather than silently accepting:
Investigation dispatch is ~80% of a real cycle's runtime and where its real Foundry/ADO token spend
concentrates — a message redelivered after a kill (the same real property Phase 4's kill test proved
for Investigation) would, under a naive copy of that pattern, simply re-run the whole cycle from
scratch, including a full, real, paid-for re-investigation. Safe (nothing corrupts), but not free.

**Decision**: Convert `reporting`'s outer trigger to a real Azure Storage Queue consumer on a new
`report-cycles` queue (core_api's trigger endpoint publishes a real, thin message — `cycle_id` only —
immediately after its existing `cycles` INSERT), matching Investigation's already-proven shape exactly:
`CYCLE_VISIBILITY_TIMEOUT_SECONDS = 90`, `CYCLE_LEASE_RENEWAL_INTERVAL_SECONDS = 45`, poison
dead-lettering at the same shared `MAX_DEQUEUE_COUNT`, and delete-only-after-terminal (`cycles` reaching
either a real success outcome via `mark_cycle_terminal` or a real, recorded application failure via
`mark_cycle_failed` — both terminal, both correctly stop redelivery; only a genuine crash before either
of those writes leaves the message to redeliver). `reporting` moves to `minReplicas: 0` with a real KEDA
`azure-queue` custom scale rule on `report-cycles` (the identical no-identity-block configuration
already proven for Investigation — the platform falls back to the container app's own attached Managed
Identity automatically). The Phase 3 DB-polling claim, `claim_next_queued_cycle`
(`FOR UPDATE SKIP LOCKED`), is retired outright and removed from the codebase, not left dormant — the
queue's own visibility-timeout lease is now the real concurrency control, replacing the SQL row lock the
same way it already replaced it for Investigation.

**The redelivery-is-cheap fix, the actual new design work**: before ever dispatching to Investigation,
`reporting` now asks whether Investigation's own store already has a real, completed result for this
exact `cycle_id` — over the identical real HTTP route (`GET /internal/investigations/{cycle_id}`)
Reporting already uses to fetch results once dispatch has happened, extended to also serve as the resume
check (a 404 means "not yet," a real body means "already answered — use it"). No new state was added to
`cycles` for this: Investigation's own `investigation_runs` table is already keyed on `cycle_id`
(`ON CONFLICT DO UPDATE`, Phase 4's own upsert design, specifically so redelivery there overwrites
rather than accumulates) and is therefore already the single, authoritative place to ask "has this
finished." Reusing it here means the resume check needed exactly one new function
(`_resolve_investigation_result`) wrapping the existing fetch, not a second tracking mechanism that
could drift out of sync with the first. The result: a redelivered `report-cycles` message (Reporting
killed mid-cycle, the message's lease expiring and becoming visible again) now skips the expensive
re-dispatch entirely whenever Investigation already answered, and resumes straight into rendering off
the real, already-paid-for findings — turning "redelivery is safe" into "redelivery is cheap," the
property that makes at-least-once delivery comfortable to rely on rather than merely tolerable.

**Reasoning — why this belongs in `cycles`/`investigation_runs`'s existing shape rather than a new
mechanism**: the alternative (e.g., a separate "has Investigation been dispatched for this cycle" flag
written by `reporting` itself before dispatching) would create two sources of truth that could disagree
— `reporting`'s own flag saying "dispatched" while Investigation's own store says "never received it,
or received it and crashed before completing" — exactly the kind of drift this project's own governance
record (Governance & Security Reference §6) has repeatedly found and corrected elsewhere (documented
privilege assumptions, ownership assumptions) never checked against what the code actually does. Asking
Investigation directly, every time, is slower by exactly one real HTTP round-trip per cycle (negligible
against a multi-minute real run) and structurally cannot drift, because there is only ever one place the
answer lives.

**Consequences**:

- **`reporting` was the last `minReplicas: 1` exception in this deployment.** Every one of the four
  backend services (`core_api`, `bff`, `investigation`, `reporting`) now scales to zero on the same
  basis — a real KEDA `azure-queue` custom scale rule, Managed-Identity-authenticated, `minReplicas: 0`
  — not merely "each happens to be able to go to zero for its own reasons." No service is special or
  carries a standing always-on cost by design anymore; the deployment model is uniform. The
  ~$22/month `reporting`-specific idle cost this removed is a real consequence of that uniformity, not
  the goal itself — the real, revised total is reported in CLAUDE.md's Task 48 entry against the same
  ~CA$35 baseline, not asserted here, and is itself a projection pending the scale-to-zero item that
  same entry keeps open.
- A `report-cycles` message now genuinely can be delivered to more than one `reporting` replica at once
  (KEDA queue-depth scaling, same as Investigation) — this is correct and safe under the queue's own
  exclusive-lease-per-message semantics, the same real guarantee Investigation has relied on since
  Phase 4; `reporting` was never actually single-consumer by any code-level guarantee, only by
  `minReplicas: 1`'s own accident.
- A real, permanent trade-off, stated plainly rather than glossed over: the resume check adds one real
  HTTP round-trip to `investigation`'s own service at the start of every cycle, dispatched or resumed —
  a real, small, constant cost paid on every run (not only redeliveries) in exchange for redelivery
  never re-paying the ~80%-of-runtime cost. Judged worthwhile given how much more expensive a
  redelivered full re-investigation would be, but not free.
- `claim_next_queued_cycle` is gone; any future code that assumed a `cycles`-table poll still existed as
  Reporting's own trigger mechanism would need to be aware of this — `get_cycle_for_execution` is its
  real replacement, called on every `report-cycles` delivery (first or redelivered) rather than only
  when claiming fresh work.

**Not chosen**: a separate `reporting`-owned "already dispatched" flag (rejected — see Reasoning, a
second source of truth that could drift from Investigation's own real record); keeping `reporting` at
`minReplicas: 1` and only fixing the redelivery-cost problem (rejected — the always-on cost was the
original, stated motivation for doing this work at all, not a side effect to leave standing once the
resume logic existed).

**A real, live-discovered CLI gap found while deploying this, extending Phase 7's own "omit the
identity block" finding rather than repeating it:** `az containerapp update --scale-rule-name ...
--scale-rule-type azure-queue --scale-rule-metadata ...` (no `--scale-rule-auth` passed) does not, in
fact, produce a scale rule with no auth/identity block at all — it produces one with an explicit,
present-but-empty `"auth": []` array. Investigation's own real, working rule (Phase 7) has no `auth`
key whatsoever. Deployed this way, `reporting` sat at a real, live-confirmed `minReplicas: 1`
equivalent — never scaling down — with Container Apps' own system log recording a real, repeated
`KEDAScalerFailed`: `error parsing azure queue metadata: no connection setting given`. The empty array
is evidently not treated as "no auth specified, fall back to the attached Managed Identity" the way an
absent key is — a real, narrow distinction between "empty" and "absent" in how Container Apps'
CLI-generated payload differs from a direct ARM PATCH. **Fixed** the same way Phase 7's own original
finding was fixed: a direct `az rest --method patch` against the `Microsoft.App/containerApps` resource,
setting the scale rule's `custom` object with only `type` and `metadata`, omitting `auth` from the JSON
body entirely rather than passing an empty value for it — confirmed live: the `KEDAScalerFailed` errors
stopped immediately after, and `reporting` scaled to zero on its own within one real cooldown period.
Worth carrying forward: for this project's own real Managed-Identity-fallback KEDA pattern, prefer a
direct ARM PATCH over `az containerapp update --scale-rule-*` for the auth-sensitive part of a custom
scale rule, or verify the resulting JSON has no `auth` key at all (not merely an empty one) before
trusting it.

**A second, real, more consequential finding, surfaced only because this deployment was watched for
scale-to-zero this closely and this patiently for the first time:** even with the ARM shape corrected
(no `auth` key, byte-for-byte matching Investigation's own real, working rule), `reporting`'s system
log kept recording the identical `KEDAScalerFailed: error parsing azure queue metadata: no connection
setting given` sporadically — roughly every 5-15 minutes — well after the fix. Checked directly whether
this was specific to the new rule, not assumed: Investigation's own already-proven, unchanged-since-
Phase-7 `investigation-requests-queue-scale` rule shows the **identical** error, at the identical
cadence, in the same real time window (confirmed via a direct Log Analytics query against
`onepulse-investigation`'s own system logs). **This is a real, intermittent Azure Container Apps
platform behavior in the KEDA-to-Managed-Identity resolution path, affecting both queue-scaled services
equally — not a defect introduced by this task, and not something client-side RBAC, ARM shape, or
identity-attachment configuration can fix** (all three independently confirmed correct for both apps
before this was found). The practical consequence: `cooldownPeriod`'s 300-second countdown appears not
to survive a failed scaler evaluation cleanly — a single sporadic failure seems to interrupt or reset
accumulated "confirmed empty" time, so a service whose failures recur more frequently than the cooldown
window can complete (as `reporting`'s did during this task's own observation) can be kept at a
persistent 1 replica indefinitely by an error that never actually reflects real work. Investigation's
own sparser failure cadence apparently leaves it enough clean windows to reach zero in practice (this
project's own prior real deployment history shows it scaling from zero repeatedly), but this had never
been watched continuously long enough before to notice the same underlying flake was present there too.
**Not a client-side bug to chase further; recorded here as a real, disclosed platform characteristic**
worth knowing before assuming a stuck-at-N-replicas Consumption app is a code or config defect —
check the app's own `KEDAScalerFailed` history in its system logs before assuming that.

**Follow-up, same task, 2026-09-10/11 — the platform-flake conclusion checked with real evidence
before proceeding, not assumed, per an explicit instruction to rule out the alternative explanation
first: the services could simply be legitimately busy, not stuck.** Checked directly, not inferred:
`report-cycles` and `investigation-requests` (the two queues each app's own scale rule watches) both
showed `approximate_message_count=0` — a count that includes invisible/leased messages, so this rules
out "a message is mid-lease and correctly keeping the app warm." Investigation's own real, live SDK-
level HTTP logs (`azure-storage-queue`'s own request/response tracing) showed it performing a genuine
empty poll (`GET .../investigation-requests/messages... → 200`, no message body) at the exact moment
checked — direct proof of idleness, not absence of evidence. A `findings-ready` message that did
exist (1 message, `dequeue_count=0`) was traced to its real, harmless origin: the earlier local kill
test's own redelivered attempt took the resume shortcut and never called `_await_findings` again,
orphaning the original completion notification (7-day TTL, irrelevant to either scale rule). With the
"legitimately busy" alternative ruled out by direct evidence, the platform-flake conclusion stood, and
work proceeded exactly as authorized: real full-scope AOP run, kill test, and redelivery proof against
deployed compute, with the zero-replica/cold-start items measured via a real, disclosed proxy
mechanism where KEDA's own scale-from-zero stayed blocked by the flake for the remainder of this
session.

**The real full-scope AOP run, triggered through the deployed `bff`, completed end to end through the
new queue-driven path:** 115 items across 7 committed features, `route_to_human_review after 1
revision`, correctly hit the pre-existing weekly collision (`not_persisted_already_exists`, report
454), 2m59s total — `core_api` → `report-cycles` → `reporting` → `investigation-requests` →
`investigation` → `findings-ready` → `reporting` (resume fetch) → rendering/persistence, all on real
deployed compute.

**The kill test, done for real against deployed compute, took five real attempts to get a genuine hard
kill — each failed mechanism reported here rather than silently discarded, since the failures
themselves are real findings about this platform:**
1. `az containerapp exec --command "kill -9 1"` — connected, appeared to execute, but the target cycle
   completed uninterrupted (`restartCount: 0`, identical replica start time before and after). A
   follow-up `ps aux` via the same mechanism produced the identical generic `ClusterExecFailure`
   disconnection error with no output at all — for a completely harmless command — proving the error
   is generic exec-session teardown noise in this environment, not evidence the kill command itself
   ran inside the real app's PID namespace. **`az containerapp exec` is not a reliable hard-kill
   mechanism for this platform** — recorded as a real, disclosed platform characteristic, not chased
   further.
2. `az containerapp revision restart` — a real, live-discovered behavior distinct from what a name
   like "restart" implies: it performs a **rolling** restart (a new replica is created alongside the
   existing one; the original keeps running, untouched, until it becomes idle). The in-flight cycle
   completed normally on the original, never-interrupted replica. Not a hard kill; not used further
   for this purpose.
3. `az containerapp update --min-replicas 0 --max-replicas 0` — rejected outright by the CLI itself
   (`--max-replicas must be in the range [1,1000]`) — Container Apps does not allow `maxReplicas: 0`
   at all. A real, simple constraint, not a bug.
4. **The real, working mechanism: `az containerapp revision deactivate`.** Confirmed live, twice,
   independently: issuing it against the currently active revision reliably tears every one of its
   replicas down to zero within roughly 15-20 seconds — a genuine, disruptive stop, not a graceful
   drain. `az containerapp revision activate` on the same revision brings it back under normal KEDA
   control. **One real self-inflicted gap along the way, disclosed rather than smoothed over:** after
   the first genuine kill attempt, the revision was left deactivated without being reactivated before
   triggering the next cycle — that cycle sat `queued` for several minutes, never claimed, until the
   oversight was caught via an empty `az containerapp revision list` result and fixed by reactivating.
5. **Timing, not mechanism, was the remaining obstacle on four separate real attempts:** `reporting`'s
   own stages 2-7 take anywhere from ~30-70 seconds depending on whether Self-critique's one permitted
   revision fires, and issuing `revision deactivate` even a few seconds after Stage 1 (Investigation
   resolution) completed was, on four consecutive real tries, still too late — the cycle finished
   before the teardown took effect. The fifth attempt, polling every 8 seconds (not 10) and issuing
   the deactivate command the instant Stage 1's `done` status was observed, caught the cycle
   genuinely mid-flight, during Self-critique's own revision call.

**The successful kill test, full result:** `reporting` was confirmed torn down to zero real replicas
(`az containerapp replica list` → `0`) while the cycle's own status was independently confirmed
`running`, `finishedAt: null`, with Stage 5 mid-`"revising for tone (1 of 1 permitted)"` — a genuine,
verified mid-cycle crash, not an assumption from the deactivate command merely succeeding. The
`report-cycles` message for this cycle was confirmed still present and invisible
(`approximate_message_count=1`, nothing returned by `peek_messages`) — the lease outliving the dead
consumer, exactly as designed. After reactivating the revision, the message's lease expired and it
was redelivered to a freshly claimed replica (a second, distinct `"[reporting] claimed cycle ..."`
log line for the identical `cycle_id`), and the cycle reached a real terminal state
(`not_persisted_already_exists`, report 454) roughly 3.5 minutes after the kill.

**Redelivery proven NOT to re-dispatch Investigation — shown via two independent real log trails, not
asserted from the design:**
- **Reporting's own log, the redelivered attempt:** `[STAGE 1/7] Investigation — already completed
  for this cycle, resuming for 'Agentic AI Observability Platform' (no re-dispatch)` — the literal
  resume-path text, printed for real, with the real elapsed time for this stage measured at **0.15
  seconds** (`start_ts`/`end_ts` a fraction of a second apart in the `cycles.stages` JSON) — versus
  85-110 seconds for every genuine fresh Investigation dispatch observed this session.
- **Investigation's own log, independently, for the identical `cycle_id`:** exactly ONE `received
  investigation request: cycle_id=...` line and exactly ONE `cycle ... completed: 115 finding(s)`
  line, despite two separate real reporting execution attempts (the original, killed mid-flight, and
  the redelivered one) — proving Investigation itself was dispatched, and did its real Foundry/ADO
  work, exactly once. Two `GET /internal/investigations/{cycle_id}` calls appear (200 OK each) — one
  from the original attempt's own post-dispatch fetch, one from the redelivered attempt's resume
  check — the second one being the real, observed mechanism that let it skip re-dispatch.

**Real cold start, `reporting`, measured via a disclosed proxy mechanism (`revision deactivate` /
`activate`) since KEDA's own scale-from-zero stayed blocked by the platform flake for the remainder of
this session:** confirmed a genuinely fresh replica (a new pod name, distinct from any prior one) was
created at the moment of reactivation, and that replica claimed a real `report-cycles` message
**~21.6 seconds** after its own creation (~27.4 seconds counting from the moment the message was
published, including real Azure API scheduling latency before the replica even appeared) — faster
than either `bff`→`core_api`'s chained 55.7 seconds or `investigation`'s own ~50-second figure (both
Phase 7), despite `reporting` carrying the bulk of the real business logic. See the Runbook's own
warm-up section for the full, honestly-caveated writeup and the resulting change to demo warm-up
guidance (`reporting`'s trigger is a queue message, not an HTTP endpoint — warming it now needs a real
throwaway report-cycle trigger, not just a `curl` against `bff`).

**Revised cost, against the same ~CA$35 baseline and the same Azure Retail Prices methodology Task 47
used:** removing `reporting`'s forced `minReplicas: 1` exception removes its ~$21.71/month idle-vCPU
line item outright — the dominant term in Phase 7's own ~$30-40/month total. The remaining real costs
are unchanged by this task: ACR Basic (~$5.00/month), Log Analytics (a few dollars/month, the one
real usage-based unknown, same as Phase 7), and real active-request Consumption usage across all four
now-uniformly-scale-to-zero services — each individual real cycle's active compute cost is small
(well under a cent per triggered run, by the same per-second Consumption rate arithmetic Task 47
used), so this line item is expected to stay a few dollars a month at this project's current real
usage volume. **Revised estimate: roughly $10-18/month**, down from Phase 7's ~$30-40/month — a
genuine, large reduction, not a rounding correction, driven almost entirely by removing the one
`minReplicas: 1` exception this whole task exists to close. **One real, honest caveat on this
number:** it assumes `reporting`'s KEDA scaler eventually behaves the way Investigation's own
historical pattern shows it can (reaching zero in practice despite the same intermittent flake) — for
as long as the platform-level `KEDAScalerFailed` flake keeps a queue-scaled app pinned at 1 replica,
that app bills at the old always-on idle rate regardless of its `minReplicas: 0` configuration being
byte-for-byte correct. Recommend checking Azure Cost Management after a real billing cycle for ground
truth, same recommendation Task 47 made and for the identical reason.

**Bar-for-done status, honest and itemized:** real full-scope AOP run end-to-end on deployed
compute — done. Kill test on `reporting`, mid-cycle, confirmed redelivery and completion — done, five
real attempts, the failures reported above. Redelivery proven not to re-dispatch Investigation — done,
shown two independent ways. Cold start measured, Runbook updated — done, via the disclosed proxy
mechanism above. Revised cost figure — done, with the platform-flake caveat stated plainly. Full suite
and `verify_migration.py` green — done (134/134, 119/119; five tests showed transient
`AzureCliCredential`-related errors under this session's own heavy concurrent `az` CLI load during the
kill-test attempts, confirmed non-reproducing on an immediate individual re-run — the same class of
environment noise already documented in Task 45). **Kept open, not settled here: `reporting` has not
been directly, visually confirmed reaching a KEDA-triggered zero-replica state.** Its configuration is
confirmed correct (byte-for-byte matching Investigation's own proven rule), and the mechanism blocking
that specific observation was checked against the real alternative (legitimately busy, not stuck) with
direct evidence before being attributed to a real, external, intermittent Azure platform behavior
affecting both queue-scaled services equally — but that conclusion is deliberately tracked as a dated
open follow-up in CLAUDE.md's Task 48 entry, with a concrete next check named, rather than closed out
by the strength of this investigation alone. The revised cost figure above is a projection contingent
on this actually being observed, not an already-realized result.

---

## ADR-027: Real reviewer identity, the Owner/Visitor role model, and RLS finally enforcing (Migration Plan Phase 8)

**Context**: this is the phase the whole migration has been building toward, and everything else was
gated behind it (ADR-018's own stated dependency, Governance & Security Reference §5). Every piece
this decision touches was already designed and installed, and none of it had ever been exercised:
`reports`' `tenant_isolation` RLS policy (Phase 2, `FORCE`d pre-Phase-6) had never had
`app.current_tenant_id` set by any real request in this project's history; `actors`/`actor_scope`
existed with exactly one real tenant and zero real scope rows; `core_api`'s trigger/approve/reject
routes resolved a real actor but never checked what that actor was actually allowed to do; `bff`
forwarded a stubbed identity regardless of who was really signed in. This is this project's own fifth
instance of "designed correctly, documented confidently, never exercised" (Governance & Security
Reference §6) — verifying tenant isolation against a single tenant, with no genuine second tenant's
data behind it, would have been a sixth.

**Decision, four real, separate pieces**:

1. **Seed a genuine second tenant first, with real data, before touching any code** (per the Migration
   Plan's own Phase 0 prerequisite). `scripts/seed_phase8_test_data.py`: a real fictional tenant
   ("Meridian Health"), its own portfolio and program, two real seeded reports with real findings, a
   real Tenant-B Owner actor scoped to it — plus a real Tenant-A Visitor actor and, filling a real gap
   found while writing this (the existing Tenant-A stand-in reviewer had *no* `actor_scope` row at
   all, predating this phase), a backfilled scope for it too. With one tenant, a policy that filters
   correctly and one that silently matches everything produce identical results; the interesting
   failures are in retrieval — the report list, the chat assistant's filter, a SAS request — not in
   the table, which is why seeded *reports*, not just structure, were the real requirement.

2. **`get_current_actor()`, one real FastAPI dependency, on every route in `core_api`.** Resolves the
   platform-verified Entra object ID (never an internal `actor_id` — unchanged since ADR-017) against
   `actors.entra_object_id`, then resolves the real tenant this actor's own `actor_scope` maps to
   (`actor_scope` -> `portfolio_id`/`program_id` -> `portfolios.tenant_id` — the IDENTICAL join
   `tenant_isolation`'s own policy performs, deliberately not `actors.tenant_id` directly, so the
   value this sets and the value the policy checks can never structurally disagree), and the real set
   of `program_id`s the actor may see (direct `program_id` scope rows, plus every program under a
   `portfolio_id` scope row — the program-granular half of "scope" that tenant-only RLS cannot
   express on its own). **Resolved fresh on every single request, with no session-lifetime cache of
   any kind** — revoking access by deleting an `actor_scope` row takes effect on the very next
   request, which is the real advantage a server-side session model has over a browser-held token
   that can't be invalidated server-side; caching this resolution for any period would give that
   advantage back, which is exactly why it wasn't cached.

3. **RLS finally enforces**, exactly where the Migration Plan's own strengthened Phase 8 DoD said it
   would: `SET LOCAL app.current_tenant_id` (in practice, `SELECT set_config(..., true)` — see the
   real, live-discovered fix below) inside a real transaction, in `core_api` and `reporting` only
   (`bff` has no data-store access by design; `investigation` has no access to `public` by design).
   Three functions already wrapped in a transaction (`approve_report`, `reject_report`,
   `persist_report`) just needed the `set_config` call added; three were bare reads that needed an
   explicit transaction wrap first (`get_report_detail`, `list_pending_reviews`, `list_recent_reports`).
   `persist_report` resolves its own tenant directly from `program_id` (via the identical portfolio
   join) rather than taking it from a caller — `reporting` is a queue consumer with no authenticated
   actor of its own; "which tenant owns this program" is a fact about the program, not about who
   asked.

4. **Owner/Visitor, the real role model, enforced entirely in `core_api`.** Owner: generate, approve,
   see everything in scope. Visitor: view and chat, within scope, never generate or approve. Real,
   deliberate schema choice, not a new column: `actors.role` keeps its three original
   organizational-title values (`portfolio_lead`/`program_lead`/`platform_admin`) and gains two new
   literal ones (`owner`/`visitor`) — every legacy value is treated as Owner-tier
   (`onepulse_common.roles.is_owner_role`, an exclusion check: `role != 'visitor'`), since every actor
   seeded before this phase was, in practice, a full-capability reviewer/admin; no backfill needed, no
   second role-shaped column with an unclear precedence rule against the first. Enforced with
   `_require_owner` at exactly two real points — the trigger endpoint and approve/reject — and
   deliberately nowhere else: view/chat/download routes are open to both roles within scope. **No
   Streamlit UI change of any kind** — a hidden button is usability, not security, and React
   (Phase 9) is where a real Visitor-mode UI belongs; the API refusing the request is the actual
   enforcement, proven with real requests below, not a UI affordance.

**Two real bugs found live while implementing this, neither hypothetical**:

- **`SET LOCAL app.current_tenant_id = $1` is not valid syntax over a bind parameter** — Postgres's
  `SET`/`SET LOCAL` statement does not accept a query parameter as its value at all (`asyncpg`
  raises a plain `PostgresSyntaxError`, live, on the very first real call). Fixed everywhere via
  `SELECT set_config('app.current_tenant_id', $1, true)` — a real function call, not a `SET`
  statement, fully parameterizable, and `true` as the third argument gives it the identical
  transaction-local (`SET LOCAL`) scope.
- **A second, more consequential real bug, found only because Phase 8's own seed script was the
  first real workload to call `set_config` on this GUC more than once on the same pooled
  connection**: `current_setting('app.current_tenant_id', true)` returns real SQL `NULL` only the
  *first* time it is ever referenced in a session that has never touched this custom GUC. Once any
  `set_config(..., true)` call has ever set it — even transactionally, even after that transaction
  committed and the LOCAL value reverted — Postgres has created a real placeholder variable for this
  GUC in the backend, and the "reverted" value is the empty string `''`, not `NULL`. Confirmed live,
  directly, on the same connection: `NULL` before any `set_config` call, `''` after one committed
  transaction touched it. Migration 0005's own fix (`current_setting(..., true) IS NULL`) is
  therefore correct only for a connection's *very first* tenant-scoped query — every subsequent
  *unscoped* query on the same pooled connection (exactly what a real connection pool with
  `min_size`/`max_size` > 1, i.e. every one of `core_api`'s and `reporting`'s real deployed
  processes, does routinely) would hit the second branch and error on `''::uuid`, rather than the
  intended permissive fallback. **Fixed in migration 0008**: `NULLIF(current_setting(...), '') IS
  NULL`, treating both real "unset" representations identically, in both places the check appears
  (the `OR`'s own non-short-circuit evaluation, the same real subtlety migration 0005 already
  documented once). Not a hypothetical edge case — this project's own real connection pools would
  have hit it in production the first time any two tenant-scoped requests landed on the same pooled
  connection in sequence, which for a `min_size=1` pool under real, sequential traffic is not a rare
  event at all.

**The real SAS/Blob-Storage mechanism, built now because this phase's own bar required it, not a
speculative pre-build**: ADR-021 designed `rendered_artifact_uri` holding a real blob path and
download by real user-delegation SAS back in the Phase 3/4 planning, but neither Phase 4 nor Phase 7
ever built it — every real report still renders to local/`file://` disk. Phase 8's own bar-for-done
("a visitor role... cannot retrieve a SAS for a report outside its scope") is what finally required a
real, working mechanism to test that claim against. **Deliberately scoped, not a full pipeline
migration**: `onepulse_common/blob_storage.py` (`upload_report_blob`/`issue_download_sas`, a new real
`reports` blob container on the existing `onepulsequeuesdev` storage account, `Storage Blob Data
Contributor` + `Storage Blob Delegator` RBAC granted to `id-onepulse-app-dev`) and a new
`GET /api/v1/reports/{reportId}/download` route — authorization (RLS tenant scope + program
membership) happens fully before issuance, per ADR-021's own stated constraint, and the route itself
never touches a rendering pipeline. Every report rendered before this phase, and any rendered since
without a real blob upload, correctly has no SAS-downloadable artifact (`rendered_artifact_uri` isn't
a real `blob://` URI) — a real, honest `404`, not a broken link. Migrating the rendering pipeline
itself onto Blob Storage end to end is real, disclosed, not-yet-done follow-up work, same as it was
before this phase.

**The real, mandatory Chat Assistant retrieval filter LLD Section 2.3/ADR-022 always required, finally
built**: `hybrid_search` gained a real `authorized_program_ids` filter (`search.in(program_id, ...)`
OData), passed through unconditionally from `core_api`'s chat route's own `get_current_actor`
resolution — the model is never even shown a chunk from a program outside the caller's scope, since
filtering an already-generated answer would be too late (a chunk the model has already read cannot be
un-read from its own reasoning). Proven live, not merely by code inspection: the identical question
("Is the Meridian patient records migration blocked?"), asked as the real Tenant-A Visitor, got "I
could not find any mention of a Meridian patient-records migration... The search returned unrelated
singleSlide items only" (zero citations) — asked as the real Tenant-B Owner, got a fully grounded,
correctly cited answer from the real seeded Meridian findings. The positive control matters as much as
the negative one: an always-empty answer would trivially, uselessly "pass" the isolation test even if
the filter were completely broken.

**FR-11's rate limit, built; NFR-6's usage ledger, deliberately not** — a plain, real count against
`cycles.requested_by_actor_id`/`created_at` (already threaded through the queue envelope since Phase
4/ADR-019, specifically so this wouldn't need a retrofit), a rolling 24-hour window, 2 triggers per
actor. Applied to every Owner-tier actor able to trigger at all, not narrowed to the literal legacy
role value `portfolio_lead` — a `platform_admin` or a new `owner` actor triggering unlimited runs
while a `portfolio_lead` alone was capped would be a real, silent gap in the exact protection FR-11
exists for. `usage_ledger` (Phase 2's own cost-based governance table) stays real, installed, and
unused — real cost tracking is a separate, materially larger concern (tying into Foundry's own
per-run token cost, not a request count) that this phase's own rate limit does not need and was not
asked to build.

**Real requests, real errors, proven live — the actual bar, not asserted**:

- An authenticated identity with no `actors` row: real `403 {"error": "no_access", ...}` — the
  literal common-case path, not a crash, not a 401 (this project's own prior code used 401 here;
  corrected to 403 this phase, since the caller *is* authenticated, just not authorized).
- Forging a different `actor_id`: attempted via an extra `actorId` field in the real `reject` request
  body — real `422 {"detail":[{"type":"extra_forbidden", "loc":["body","actorId"], ...}]}` (a new
  `model_config = ConfigDict(extra="forbid")` on `RejectRequest`, so this is a real, visible
  rejection, not Pydantic's default silent drop). No endpoint anywhere accepts an `actor_id` from the
  caller at all, by the original ADR-017 design — this test proves the boundary is real, not merely
  undocumented.
- A Visitor attempting to trigger a run: real `403 {"error": "visitor_cannot_generate_or_approve"}`.
- Cross-tenant isolation, three separate real proofs, each with a real positive control alongside the
  real negative one (an always-empty result would trivially pass a negative-only test): the report
  list (Tenant-A Visitor's own listing never contains a Meridian row; requesting Meridian's
  `programId` explicitly is a real `404`; Tenant-B Owner correctly sees both real Meridian reports),
  the chat retrieval filter (above), and the SAS download (`404` for Tenant-A Visitor against
  Tenant-B's report 997; a real, working SAS URL for Tenant-B Owner against the same report,
  independently confirmed by fetching the real blob content through it directly, no `core_api`
  involved).
- FR-11's rate limit: two real triggers succeed (`202`), a third within the same 24-hour window is a
  real `429 {"error": "rate_limit_exceeded", ...}`.
- The provisioning path, written down and exercised for real, not just asserted: inserting a real
  `actors` row (this session's own real signed-in Entra object ID, previously provisioned nowhere)
  mapped to a role and a real `actor_scope` entry, then that identity's own first authenticated
  request shown succeeding where it previously got the real `403` above.

**Not chosen**: a separate `access_level` column alongside `actors.role` (rejected — two role-shaped
columns with no clear precedence rule, for no real benefit Now-scope needs); scoping the rate limit to
the literal `portfolio_lead` role value only (rejected — a real, silent gap for every other Owner-tier
role, see above); building `usage_ledger`'s real cost tracking in this phase (rejected — materially
larger, separate scope, not required for the rate limit to work correctly); migrating the full
rendering pipeline onto Blob Storage (rejected — the bar needed a real, working SAS mechanism to test
isolation against, not a full storage migration; every existing `file://` report is unaffected and
stays exactly as it was).

---

## ADR-028: The append-only guarantee on `approval_records` was correctly built and tested, incompletely described, and is now closed unconditionally by a trigger

**Context**: while checking whether the newly-discovered "an admin-privileged connection can delete
fixture rows" fact (surfaced incidentally during Phase 8's own reviewer-identity work, while deciding
how to clean up historical test debris in `reports`) had any bearing on `approval_records`'
append-only guarantee — the single most-tested guarantee in this project (Governance & Security
Reference §2, three separate prior adversarial attempts, Task 31) — a direct, live check found that
it does not hold against the real Postgres Entra Administrator role on this server, and has most
likely never held there.

**The investigation, including a real, corrected hypothesis, not the first one reached for**: the
first plausible-looking explanation was that ADR-023's retroactive ownership transfer
(`approval_records`'s owner moved from `app_role_local_dev` to `app_role`) gave the administrator a
new path to `app_role`'s own privileges via role membership. **This was checked directly and is
wrong**: `has_table_privilege('app_role', 'approval_records', 'DELETE')` and the same for
`app_role_local_dev` both correctly return `false` — the explicit `REVOKE UPDATE, DELETE` from
migration 0001, reasserted by ADR-023's own migration 0004, genuinely holds for both application
roles, exactly as documented. The real mechanism, found by checking `has_table_privilege` for the
administrator's own role name directly: `azure_pg_admin` — the role every Entra Administrator on this
Postgres Flexible Server, including this project's own human operator, is a member of — is itself a
member of PostgreSQL's built-in `pg_write_all_data` role. That predefined role grants `INSERT`/
`UPDATE`/`DELETE`/`TRUNCATE` on every table in every schema, unconditionally, to every member, via a
mechanism that never creates a corresponding row in `pg_class.relacl` or
`information_schema.role_table_grants` — confirmed live: `pg_default_acl` for this database is
completely empty (ruling out a default-privileges grant), and `azure_pg_admin`'s own `pg_auth_members`
row shows direct membership in `pg_write_all_data` alongside `pg_read_all_data`, `pg_monitor`, and
several other real built-in administrative roles. This is very likely present since this Postgres
server was first provisioned — long before this project's own schema existed — not something any
migration in this project introduced or changed.

**Why this was never caught by three prior adversarial tests (Task 31) that specifically tried to
defeat this guarantee**: every one of those tests connected as `app_role_local_dev` (matching this
project's own established, correct discipline that local testing should use the real application
role, not a human's own elevated session) or checked the ACL layer directly. None of them tested the
guarantee against a connection authenticated as the raw administrator identity itself. The guarantee
was real, and rigorously tested, for the identity class it was actually built to constrain — it was
simply never tested against a different identity class that turns out to bypass it by a completely
unrelated mechanism.

**Confirmed the gap cannot be closed by revoking anything, not merely assumed**: a real, live
`REVOKE DELETE, UPDATE ON approval_records FROM azure_pg_admin` was executed directly — it completes
with no error (there was no ACL entry for `azure_pg_admin` to revoke in the first place) and
`has_table_privilege` reports `true` immediately afterward, unchanged. `pg_write_all_data`'s grant is
not a per-table ACL entry that a `REVOKE` can remove; it is a structural property of PostgreSQL's
predefined-role system.

**`verify_migration.py` now asserts this directly, and honestly fails today**: `check_real_privilege_
denied` (using `has_table_privilege`, which accounts for every real grant path — ACL, ownership, and
predefined-role membership — unlike the existing `check_privilege_revoked`, which only reads
`information_schema.role_table_grants` and would report "safe" for `azure_pg_admin` on
`approval_records` right now, since no ACL entry exists to find) is asserted against `azure_pg_admin`
specifically. Demonstrated failing against the real, current, unfixed state before any decision was
made about what to do next — per explicit instruction, this ADR records the finding and the real
option set; it does not itself apply a fix.

**Real fix options, none applied here — a decision, not a default**:

1. **Accept and document this as an inherent platform boundary**, scoping the guarantee's own stated
   claim precisely to "holds against the application's own service identity; does not and structurally
   cannot hold against this server's designated super-administrator role" — the real, corrected
   framing Governance & Security Reference §2 now states. A real, defensible position: an
   append-only guarantee that even a legitimate database administrator could never override in a
   genuine emergency (a legal hold, a compliance-mandated erasure, disaster recovery) would itself be
   an operational risk, and `pg_write_all_data`-style administrative bypass is standard, expected
   PostgreSQL/Azure behavior, not a defect specific to this project.
2. **A `BEFORE DELETE OR UPDATE` trigger on `approval_records` that unconditionally raises an
   exception.** Real, load-bearing distinction checked, not assumed: Postgres triggers fire for every
   role executing DML against a table, independent of the ACL/predefined-role layer that grants
   `pg_write_all_data`'s bypass — a trigger cannot be skipped by having broader read/write privilege
   the way an ACL check can be. Disabling a trigger requires `ALTER TABLE`, which requires table
   ownership (`app_role`, not `azure_pg_admin`) or genuine superuser (`azure_pg_admin` is confirmed
   `rolsuper = false`) — meaning `azure_pg_admin` could not disable this trigger to route around it
   without first being granted ownership or superuser, neither of which exists today. This would be
   real, table-level, ACL-independent enforcement — a materially different and stronger mechanism than
   another `REVOKE`, not evaluated further than this design note pending the user's decision.
3. **Reduce membership in `azure_pg_admin` to the minimum real operators needed.** Does not close the
   structural gap (anyone who legitimately needs to be the Entra Administrator still carries it), but
   reduces blast radius. Likely already minimal today (one real human operator).
4. **Real-time auditing** (e.g. `pgaudit`) to at least detect if this bypass is ever exercised against
   `approval_records`, given it cannot be prevented at the grant level. Not currently installed on this
   server (a real, pre-existing gap independently noted in CLAUDE.md Task 39's own "not determined"
   finding about historical DELETE activity) — a heavier, likely Next-scope lift.

**Not chosen, yet — this ADR reports the option set for a decision, not a conclusion.**

---

**Decided, built, and adversarially verified, 2026-09-11 — Option 2 (the trigger), with the framing
corrected.** Option 2 was chosen: it closes the gap rather than describing it, and the alternative
(Option 1, re-scoping the guarantee's own documented claim) would have left this project's own
most-cited guarantee needing a permanent footnote about which identity it covers. Building it was
judged worth that.

**The framing itself needed correcting first, and it is a different kind of correction than every
prior instance of this project's own "designed correctly, documented confidently, never exercised"
pattern (Governance & Security Reference §6).** This ADR's own first draft (and the conversation that
produced it) described the gap as the guarantee having "decayed" or been "undone by a later change."
Neither is true. The `REVOKE UPDATE, DELETE` on `approval_records` held continuously, for the
identity it was written to constrain, from Phase 2 onward — confirmed unchanged before and after
ADR-023's ownership transfer, the specific change first (wrongly) suspected as the cause. **What
actually happened: Task 31 asked and rigorously, adversarially answered a real, correctly-posed
question — can the application (`app_role`/`app_role_local_dev`, the only identity any real code path
in this project ever authenticates as) mutate this table — and this document's own conclusion then
generalized that specific, well-tested answer into a claim about the guarantee overall, which the
four tests underlying it never established.** The other five instances in Governance & Security
Reference §6 are all guarantees nobody had exercised at all. This one was exercised thoroughly and
correctly, against the right identity, for the right reason — the gap was one sentence claiming more
than the tests behind it proved, not a lapse in testing rigor. Worth keeping distinct: the fix for
"never tested" is running the test; the fix for "tested narrowly, described broadly" is narrowing the
claim to match the evidence, or — as chosen here — widening the enforcement to actually match the
broader claim that had already, if prematurely, been made.

**Real implementation** (`scripts/migrations/0011_approval_records_append_only_trigger.sql`):
`reject_approval_records_mutation()`, a trivial `plpgsql` function that unconditionally
`RAISE EXCEPTION`s naming the real operation and the real calling role, attached as
`approval_records_append_only`, `BEFORE UPDATE OR DELETE ... FOR EACH ROW`. **A second, real,
previously-unknown consequence of ADR-023's own "REVOKE ALL then re-GRANT exact intended profile"
fix, found while writing this migration, not assumed:** `app_role` — the real, current table owner —
does not itself hold `TRIGGER` privilege on `approval_records`; `has_table_privilege('app_role',
'approval_records', 'TRIGGER')` is `false`, confirmed live, because ADR-023's own REVOKE ALL stripped
even the owner's default at-creation-time grant of it, and nothing re-granted it back (the intended
profile never included it, since nothing before this needed it). `CREATE TRIGGER` genuinely requires
that ACL bit, ownership alone is not sufficient once it has been explicitly revoked. Resolved with the
minimal-footprint form: `SET ROLE app_role` (session-level, reachable since `gopi` is a real, confirmed
member — no interactive AAD auth needed, unlike connecting AS `app_role` directly), `GRANT TRIGGER ...
TO app_role`, create the trigger, `REVOKE TRIGGER ... FROM app_role` again in the same migration —
`app_role`'s own real, documented, minimal profile (`verify_migration.py`'s `PUBLIC_TABLE_PROFILES`)
is unchanged before and after; only the trigger's own continued existence and firing persists, which
needs no standing privilege once created.

**Adversarial verification, the same rigor Task 31 applied to the application roles, now applied to
the one identity that had never been covered — a real mutation attempt against a real, existing row,
not a zero-match probe** (a first attempt using a deliberately nonexistent `report_id` was a real,
disclosed methodology mistake — `FOR EACH ROW` triggers do not fire when zero rows match, so that
attempt "succeeded" vacuously and proved nothing; caught and redone against a real row before drawing
any conclusion):

- Connected as `gopi@gopdhagmail.onmicrosoft.com` (this server's real Entra Administrator identity).
- `UPDATE approval_records SET notes = 'tampered' WHERE approval_id = <a real, existing row>` →
  `RaiseError: approval_records is append-only: UPDATE is not permitted (role=gopi@gopdhagmail.onmicrosoft.com)`.
- `DELETE FROM approval_records WHERE approval_id = <the same real row>` → the identical real error,
  naming `DELETE`.
- The real row independently re-queried afterward and confirmed byte-for-byte unchanged — not merely
  that an exception was raised for some unrelated reason.
- **Confirmed the trigger does not interfere with legitimate use:** the full `tests/test_human_
  governance.py` suite (real `approve_report`/`reject_report` end-to-end, both of which `INSERT` into
  `approval_records`) re-run and passing unchanged — the trigger is scoped to `UPDATE`/`DELETE` only,
  `INSERT` was never touched.
- Both proofs are now permanent, repeatable tests, not one-off manual checks:
  `tests/test_human_governance.py::test_approval_records_append_only_holds_against_the_real_admin_identity`
  (a new `admin_conn` fixture, authenticated as the real administrator role, same transactional-
  rollback discipline as every other test in that file) and `tests/test_verify_migration.py`'s two new
  cases for `check_trigger_exists_and_enabled`.

**`verify_migration.py` now asserts the real, current enforcement mechanism, not an assertion that can
never be satisfied.** The prior check (`check_real_privilege_denied` against `azure_pg_admin`) was
replaced, not merely fixed — it was asserting the *absence* of a privilege that structurally cannot be
absent (`pg_write_all_data` membership is unconditional; no `REVOKE` reaches it), so it would have
failed forever regardless of any real fix. The new check, `check_trigger_exists_and_enabled`, asserts
the thing that actually determines whether the guarantee holds: does the real trigger exist and remain
armed. `check_real_privilege_denied` itself is kept, unchanged, as a correct, reusable function — used
elsewhere for claims that are actually achievable at the ACL level, not removed just because one use of
it turned out to be asserting an impossibility. **`verify_migration.py`: 122/122** — the one check that
had been the sole, documented, expected failure now passes for the right reason (a real trigger exists
and blocks it), not by weakening what it asserts.

**Governance & Security Reference §2 rewritten** with the corrected framing above — not "the guarantee
decayed," not "it holds for one identity and not another," but "it was proven exactly as far as it was
tested, the tests were correctly chosen, and the document's own conclusion overstated their reach; both
the test coverage and the claim now match, and the guarantee holds unconditionally."

---

## ADR-029: The RAG index gets a real prune step, and near-duplicate weekly findings are resolved by ranking, not by discarding history

**Context**: the RAG index report (Task 48, pre-Phase-9) surfaced two real gaps, both traced back to the
same root cause — the index has only ever grown. `ingest_reports_to_search.py` calls
`merge_or_upload_documents` exclusively; nothing has ever deleted a document from it. Two concrete,
observed consequences: (1) report 999, a fixture row from an earlier, since-abandoned test ingestion,
was still live in the index and retrievable by the chat assistant, with no mechanism to ever remove it
short of a manual, out-of-band delete; (2) Agentic AI Observability Platform's own weekly
re-investigation of the same ~115 committed items produces near-identical finding-level chunks across
consecutive weeks, differing mainly in `week_of` and sometimes status — a retrieval-quality risk once
that program is actually reindexed, since an older, superseded chunk can rank close enough to the
current one for the model to cite either with equal confidence.

**Decision, prune step (Option A — reconcile against real Postgres state, not a targeted delete)**: the
property this closes is "what's in the index that Postgres no longer accounts for" — not a one-off fix
for report 999 specifically. `ingest_reports_to_search.py` now computes the real, full, unscoped set of
document IDs Postgres says should exist (every non-fixture `reports`/`findings` row,
`fetch_real_document_ids`), lists the real current index contents, and deletes the difference
(`prune_stale_documents`) — on every real ingest run, not as an opt-in flag. This is what makes ADR-022's
own "Postgres is the source of truth; AI Search is derived and must be rebuildable" claim actually true:
derived means reconcilable back to the source of truth on an ongoing basis, not merely rebuildable in
principle by adding whatever's missing. A purely additive reindex can leave a retired or reclassified row
in the index forever; this prune step is what closes that gap for real, going forward, not just for the
one report that happened to trigger this investigation.

**The `$top=1000` cap is a guard in the code, not a note in a report.** Azure AI Search's own real
per-request cap on a `search_text="*"` listing call means a listing above `MAX_INDEX_LISTING_PAGE` (1000)
can no longer be trusted to be a complete enumeration — computing a prune set from a partial listing
risks deleting documents that are still genuinely valid, just not on the page that was read. The real
corpus will eventually cross this threshold silently; the failure mode of not guarding it is a wrong,
over-broad deletion, not a loud error — worse than doing nothing. `prune_stale_documents` therefore raises
`IndexListingTooLargeError` and refuses to prune at all once the listing reaches the cap, rather than
proceeding against a listing it cannot vouch for. This project isn't at that scale, and real pagination
(`$skip`, or an orderby-based keyset) is deliberately not built preemptively for a corpus size this
project doesn't have yet — but the refusal-to-proceed is real code, live today, not a comment promising
future caution.

**Deferred, not silently dropped: index aliasing for a real schema-change rebuild.** Azure AI Search's
real zero-downtime reindex mechanism — build a new index under a new name, then repoint a stable alias at
it — is not used by this project today; `INDEX_NAME` is a hardcoded constant referenced directly by every
caller, with no alias layer. The prune step above handles ongoing reconciliation against a stable schema;
it does not handle a schema change that can't be applied in place to the live index (e.g. a new required
field with no safe default, or a field whose type must change). **The explicit trigger for building the
alias mechanism is exactly that condition** — a schema change unappliable in place — not a general
"someday" item. Recording the trigger condition here is what turns this into a decision deferred with a
condition attached, rather than an option left for someone to rediscover from scratch when the need
arrives.

**Decision, near-duplicates (scoring profile + prompt instruction, not index-time deduplication)**: the
alternative seriously considered — index only the latest report per program, discarding older weeks'
chunks entirely — was rejected. LLD Section 2.3 frames this assistant as an archive of what has already
been reported, and "how has this item's status changed across weeks" is a real, intended question this
system should stay well-placed to answer; discarding history to fix a ranking problem solves the wrong
problem; the corpus is small (a handful of documents per item per week), so the storage/retrieval cost of
keeping full history is real but not the constraint that decides this.

Instead: a real Azure AI Search `ScoringProfile` (`RECENCY_SCORING_PROFILE_NAME`, `search_index.py`)
applies a `FreshnessScoringFunction` on `week_of` — `boost=3.0`, `interpolation="quadratic"`,
`boosting_duration=90 days` — biasing ranking toward the most recent week without excluding older weeks
from being retrieved or cited when a question is actually about history. Applied explicitly at the
`hybrid_search()` call site (`scoring_profile=RECENCY_SCORING_PROFILE_NAME`), not as a silent
`default_scoring_profile` on the index, so the choice is visible at the point it takes effect. Paired with
an explicit `CHAT_INSTRUCTIONS` addition (`chat_assistant.py`, instruction 5): when multiple retrieved
chunks describe the same real item across different weeks, prefer the most recent one for a question
about current status, and use the full set — stating explicitly what changed and when — for a question
about history.

**Why ranking, not the model, is where this gets fixed — the fourth instance of this project's own
consistent pattern.** Relying on the model to notice which of several similar chunks is current and
silently prefer it, unaided, is exactly the class of judgment call this project has repeatedly chosen not
to leave to the model when a deterministic or structural fix is available instead:

- **ADR-007**: deterministic scoping over adaptive summarization — the system decides what's in scope by
  rule, not by asking a model to infer it well.
- **The code-enforced risk floor** (`onepulse_common/quality_gate.py`, `code_enforced_risk_floor_check`):
  a report cannot be approved with findings a deterministic check can prove are missing or incomplete,
  regardless of how confident the model's own narrative sounds.
- **The sha256 status-deck integrity pin** (Task 44, `STATUS_DECK_SHA256_BY_PROJECT`,
  `reporting/main.py`): which deck is authoritative for a project is settled by a content hash, not by a
  text heuristic asking whether a deck "looks like" it belongs to the right project.
- **This decision**: which chunk is current is settled by a scoring function operating on `week_of`
  before the model ever ranks or reads the results, not by a prompt instruction trusted to catch every
  case unaided.

The prompt instruction (point 5 above) is real and included — it is not redundant with the scoring
profile, since a genuinely history-focused question still needs the model to reason correctly across
multiple weeks' chunks once ranking has surfaced them. But for the specific failure this task set out to
close — citing a stale status with the same confidence as a current one — the fix is structural, applied
before the model can get it wrong, not a instruction trusted to catch it after the fact. Same reasoning,
arriving in a fourth place.

**Real constraint found at corpus scale: the embedding deployment rate-limits a single large batch call,
not just a note in this task's own history but something the next reindex at a larger corpus will hit
again.** The first live reindex attempt against the full, unscoped real corpus (963 texts — 21 real
reports + 942 real findings, embedded in one `client.embeddings.create(...)` call) failed with
`openai.RateLimitError`: the `onePulse-text-embedding-3-small` deployment's GlobalStandard S0 tier rejects
a single request of this size outright, not merely slows it down. This is a real property of the
deployment's own tier, not a bug in `embed_texts` or a one-off fluke — any future reindex against a corpus
at or above roughly this size will hit it again unless deliberately worked around, which is exactly why
it's recorded here rather than left to be rediscovered as a fresh, surprising failure. **The fix**:
`ingest_reports_to_search.py` gained `embed_all()` — splits the real texts into fixed-size batches
(`EMBEDDING_BATCH_SIZE = 16`) and, on a `RateLimitError` for any one batch, sleeps
`EMBEDDING_RETRY_SECONDS` (60) and retries that batch before continuing — a small, deliberate addition
scoped to the one caller that actually does bulk embedding. `onepulse_common.embeddings.embed_texts` itself
is deliberately left untouched as a plain single-batch call: every other real caller in this project (the
chat assistant, one question at a time) never approaches this limit, and batching there would be
unnecessary complexity for a call shape that doesn't need it. If a future corpus grows large enough that
even 16-text batches start rate-limiting, or the run becomes slow enough that batch-by-batch retries add up
to an unacceptable wall-clock cost, the real next step is requesting a quota increase for this deployment
(the service's own error message names the exact mechanism, `https://aka.ms/oai/quotaincrease`) rather than
shrinking the batch size further — noted here so that's a deliberate choice next time, not a guess.

**Verification, real reindex against the real corpus, run only after the code above (prune step, scoring
profile, prompt instruction, and the batching fix above) was in place and the full 153-test suite was
green**: `python scripts/ingest_reports_to_search.py --target dev`, no `--report-ids` scoping — the full,
unscoped path.

The real, completed run: **963/963 documents uploaded** (21 report chunks + 942 finding chunks), and **50
stale documents pruned** — `report-999` (the fixture that started this investigation) plus 49 superseded
`report-1` through `report-50` chunks from Task 17's original singleSlide ingestion (`report-51`, still a
real report, was correctly NOT pruned). **What the index reconciled to, and why that number is the real
evidence:** 963 is the exact real, current non-fixture count in Postgres — 21 rows in `reports` plus 942
rows in `findings`, both `WHERE NOT is_test_fixture`, confirmed by the same query `fetch_real_document_ids`
itself runs. The index ending at precisely that number, not merely "having grown" or "having had some stale
rows removed," is what demonstrates the prune step is a real reconciliation against Postgres's current
state — not a partial cleanup that happened to catch report 999 and stop there. A step that only deleted
report 999 specifically would have left the index at 964 (963 real + the one, now-gone, fixture); a step
that pruned too aggressively would have landed below 963. It landed exactly on 963, matching Postgres
exactly, which is the property ADR-022's "derived means reconcilable" claim actually requires. **Report 999
confirmed gone by a direct, targeted post-reindex query** (`get_document(key="report-999")` → real
`ResourceNotFoundError`), closing the specific instance that started this whole investigation.

**The near-duplicate fix proven with a real question against real data**, not a synthetic case: found the
real work item (`source_item_ref=332`, "Testing: Write automated tests for workload identity
authentication") whose `status_label` genuinely differs across real weekly Agentic AI Observability
Platform reports — `Needs Human Review` in the weeks of 2026-08-21/22, `On Track` in every other real week
including the current one (2026-09-07, report 454). Asked "What is the current status of the work item
about writing automated tests for workload identity authentication in the Agentic AI Observability
Platform program?" — the real assistant answer: *"Current status (most recent): ... On Track with
System.State = Resolved... Previously (week of 2026-08-22) the program report listed WI 332
(authentication/workload-identity tests) as pending human review."* Citations: `report_id=454,
week_of=2026-09-07` (the current status, correctly primary) and `report_id=361, week_of=2026-08-22` (the
superseded status, correctly offered as historical context rather than omitted or given equal weight) —
exactly the behavior instruction 5 in `CHAT_INSTRUCTIONS` specifies. The reindex completing proves the
mechanism; this answer picking the current week as primary, while still correctly surfacing the real
history, proves the fix. Full detail recorded in CLAUDE.md's own phase-status log.
