# Handoff: OnePulse Status Report Dashboard

## Overview
OnePulse is an internal tool that generates AI-assisted program status reports and lets a reviewer approve or reject them. This handoff covers the **home screen**: a single-page dashboard with a project selector, a report-generation engine with live step logging, a list of previous reports awaiting review, and a chat assistant for interrogating and revising the current draft.

## About the Design Files
The files in this bundle are **design references created in HTML** — prototypes showing intended look and behavior, not production code to copy directly. The task is to **recreate these designs in the target codebase's existing environment** (React, Vue, Angular, etc.) using its established component library, styling approach, and state patterns. If no environment exists yet, choose the most appropriate framework for the project and implement there.

Do not port the `.dc.html` markup or its `{{ }}` template syntax — it is a prototyping format. Read it as a specification.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and interaction states below are final and exact. Recreate pixel-faithfully using the codebase's own primitives. If the codebase has a design system whose tokens are close to these values, prefer the system's tokens and note the deviation.

---

## Screens / Views

### Home Dashboard (single screen, no routing)

**Purpose:** the reviewer lands here, picks a project, generates a report, watches it build, then approves or rejects prior reports and asks the assistant about the draft.

**Page shell**
- Font stack: `'Helvetica Neue', Helvetica, Arial, sans-serif` throughout
- Page background: `#f6f6f4`; body text `#17191d`
- Container: `max-width: 1280px`, centered, `padding: 22px 30px 24px`, `min-height: 100vh`, `box-sizing: border-box`, `display: flex; flex-direction: column`
- Designed to fit a single viewport without page scroll on a normal window; inner regions scroll instead of the page

**Layout**
```
┌──────────────────────────────────────────────────────────┐
│ HEADER (full width)                                      │
│  OnePulse                                                │
│  AI-generated status reports, human-approved              │
│  [ SELECT PROJECT  (dropdown) ]                           │
├───────────────────┬──────────────────────────────────────┤
│ REPORT ENGINE     │ PREVIOUS STATUS REPORTS  (fixed h.)  │
│ (navy, 40%)       ├──────────────────────────────────────┤
│                   │ STATUS REPORT ASSISTANT (fills rest) │
└───────────────────┴──────────────────────────────────────┘
```
- Two-column grid: `grid-template-columns: minmax(0, 0.4fr) minmax(0, 0.6fr)`, `gap: 18px`, `align-items: stretch`, `flex: 1`, `min-height: 0`
- Right column: `display: flex; flex-direction: column; gap: 14px; min-height: 0` — reports card is `flex: none`, assistant is `flex: 1; min-height: 0`

---

### 1. Header

| Element | Spec |
|---|---|
| Wrapper | `padding-bottom: 14px`, `border-bottom: 1px solid #e2e2dd`, `margin-bottom: 16px` |
| Title | "OnePulse" — 29px / 700 / `line-height: 1.1` / `letter-spacing: -0.02em` / `#1F3864` |
| Subtitle | "AI-generated status reports, human-approved" — 14.5px / 400 / `#63666d` / `letter-spacing: 0.005em` / `margin-top: 7px` |
| Project group | `display: inline-flex`, `align-items: center`, `gap: 11px`, `margin: 18px 0 6px`, `background: #eef1f6`, `border: 1px solid #dde3ee`, `border-radius: 4px`, `padding: 10px 14px` |
| Label | "SELECT PROJECT" — 11.5px / 600 / `letter-spacing: 0.07em` / `text-transform: uppercase` / `#1F3864` |
| Select | 13px / 600 / `#17191d`, white bg, `1px solid #dcdcd6`, `border-radius: 3px`, `padding: 8px 28px 8px 10px`, native arrow suppressed (`appearance: none`) with a CSS-drawn caret; hover + focus border → `#1F3864`, focus `outline: none` |
| Options | `singleSlide`, `LeaveTracker` (default `singleSlide`) |

**Note:** the project selection is currently presentational — see *Known gaps*.

---

### 2. Report Engine (left column)

Navy console panel. `background: #1F3864`, `border: 1px solid #1F3864`, `border-radius: 4px`, `padding: 16px 20px`, `color: #ffffff`, `display: flex; flex-direction: column; min-height: 0`.

**a. Generate button** (top, `flex: none`)
- Full width, white bg, `#1F3864` text, 13px / 700 / `letter-spacing: 0.03em`, `padding: 13px 16px`, `border-radius: 3px`, no border
- Hover `#e7ebf3`; active `#d3dae8`
- Label: "Generate Status Report" → "Generating…" while a run is active; `disabled` and `cursor: default` during a run

**b. Status header row** (`padding: 24px 0 7px`)
- Left label: 11px / 600 / `letter-spacing: 0.08em` / uppercase / `#cfd7e5` — reads **"LAST RUN LOG"** when idle, **"IN PROGRESS"** while running
- Right meta: 11.5px / `#b6bfd0` / `white-space: nowrap` — `"<last run date> · <duration>"` when idle, `"started HH:MM"` while running

**c. Progress bar**
- Track: `height: 3px`, `background: rgba(255,255,255,0.22)`, `border-radius: 2px`, `margin-bottom: 12px`, `overflow: hidden`
- Fill: `height: 3px`, `background: #ffffff`, width = percentage (below)

**d. Run log** — plain text, no icons or graphics
- Scroller: `flex: 1`, `min-height: 0`, `overflow-y: auto`, `overflow-x: hidden`, `padding-right: 10px`, `display: flex; flex-direction: column; gap: 9px`
- Step heading: `"<n>. <Step name>"` — 13px / **700** / `letter-spacing: 0.01em`
  - completed `#d7deeb` · currently running `#ffffff` · not yet reached `#7f8ba4`
- Sub-step lines: 12px / 400 / `line-height: 1.45`, indented by being a nested block with `margin-top: 3px`, `gap: 2px`
  - reached `#b9c3d6` · not yet reached `#7f8ba4`
- Idle state shows the **full log of the last completed run** (all steps + all sub-steps, all in the completed colors); a run in progress reveals sub-steps as they complete
- Auto-scrolls the running step into view on each step change

**Steps and sub-steps (exact content)**
1. **Collect sources** — Pull delivery tracker · Pull finance actuals · Pull risk register
2. **Normalize records** — Match record keys · Flag missing fields
3. **Reconcile variances** — Compare plan vs actual · Resolve conflicts · Compute variance
4. **Synthesis** — Cluster themes · Rank by materiality · Derive RAG signal
5. **Draft narrative** — Compose narrative · Apply tone rules
6. **QA check** — Check figures · Check tone & length

---

### 3. Previous Status Reports (right column, top)

White card: `background: #ffffff`, `border: 1px solid #e2e2dd`, `border-radius: 4px`, `padding: 13px 22px 2px`, `flex: none`.

- Header: "Previous Status Reports" — 15px / 700 / `letter-spacing: 0.02em` / `#17191d`; `padding-bottom: 10px`, `border-bottom: 1px solid #eeeeea`
- Exactly **4 rows**, most recent first, no inner scroll. A new run prepends and drops the oldest.
- Row: `display: flex`, `align-items: center`, `justify-content: space-between`, `flex-wrap: nowrap`, `gap: 16px`, `padding: 6px 0`, `border-bottom: 1px solid #f2f2ef`
- **Left:** the run's date/time IS the link to the generated deck — 14px / 600 / `#1F3864`, `underline` with `text-decoration-color: #c8cedb`, `text-underline-offset: 3px`; hover underline → `#1F3864`; `title="Open deck"`. Format: `"Sep 5, 2026 · 08:41"`
- **Right, pending rows:** two 30×30px icon buttons, `gap: 6px`, `border-radius: 3px`
  - Approve — `#1F3864` bg, white check glyph, hover `#16294a`; `aria-label="Approve"`
  - Reject — white bg, `1px solid #dcdcd6`, `#63666d` ✕ glyph; hover border+text `oklch(0.48 0.15 25)`; `aria-label="Reject"`
- **Right, decided rows:** a single neutral chip reading **"Reviewed"** — 11.5px / 600 / `letter-spacing: 0.06em` / uppercase / `#63666d` on `#f1f1ee`, `padding: 5px 9px`, `border-radius: 3px`. Slot is `height: 30px` so pending and decided rows share one row height.
- No RAG (red/amber/green) indicators appear in this list by design.

---

### 4. Status Report Assistant (right column, bottom)

Tinted panel to distinguish it from the white reports card: `background: #eef1f6`, `border: 1px solid #d8dfeb`, `border-radius: 4px`, `padding: 14px 22px 12px`, `display: flex; flex-direction: column; flex: 1; min-height: 0`.

- Header row: `padding-bottom: 13px`, `border-bottom: 1px solid #d8dfeb`
  - Title "Status Report Assistant" — 15px / 700 / `#1F3864`, `flex: none`
  - Suggested-prompt chips, right-aligned, `gap: 6px`: white bg, `1px solid #e2e2dd`, `#3c3f45`, 11.5px / 500, `padding: 6px 9px`, `border-radius: 3px`; hover border+text `#1F3864`. Labels: **"Why Amber?"**, **"Tighten the summary"**, **"List open risks"**
- Transcript: `flex: 1`, `min-height: 0`, `overflow-y: auto`, `overflow-x: hidden`, `scrollbar-gutter: stable`, `padding: 8px 4px 0 2px`, `gap: 13px`; auto-scrolls to bottom on new messages
  - Each message: column, `gap: 4px`, aligned `flex-end` (user) or `flex-start` (assistant)
  - Role label: 11px / `letter-spacing: 0.07em` / uppercase / `#6b7386` — "You" / "Assistant"
  - Bubble: `max-width: 84%`, 13px / `line-height: 1.45`, `text-wrap: pretty`, `border-radius: 4px`, `padding: 9px 11px`
    - User: `#1F3864` bg, white text, `#1F3864` border
    - Assistant: `#ffffff` bg, `#3c3f45` text, `#dde3ee` border
  - Pending indicator: pulsing 6px `#1F3864` dot + "Assistant is drafting…" (12.5px / `#63666d`), 1.1s ease-in-out opacity pulse
- Composer (`form`, `border-top: 1px solid #d8dfeb`, `padding-top: 9px`, `gap: 10px`):
  - Single-line textarea, fixed `height: 40px`, `resize: none`, `overflow: hidden`, `1px solid #e2e2dd`, `border-radius: 3px`, `padding: 9px 12px`, 13.5px / `line-height: 1.4`; focus border `#1F3864`, `outline: none`
  - Placeholder: "Ask about this run, or request a revision to the narrative…"
  - Send button: `#1F3864` bg, white, 12.5px / 600 / `letter-spacing: 0.03em`, `padding: 12px 15px`, `border-radius: 3px`, hover `#16294a`, `flex: none`
- Seeded first message (assistant): "Draft ready — 612 words, proposed Amber. Ask me anything, or tell me what to change."

---

## Interactions & Behavior

**Generate Status Report**
1. Click → `running = true`, `step = 1`, `sub = 0`, `startedAt` = current `HH:MM`
2. A step timer advances `step` every `stepDurationMs` (default **1300ms**), resetting `sub` to 0
3. A sub-step timer advances `sub` every `stepDurationMs / 3` (min 200ms), clamped to that step's sub-step count
4. After step 6 both timers clear and the run finalizes: a new run is prepended to the list (`pending: true`), the log stays visible as the "last run log", the progress bar sits at 100%, and `lastRun` records date, duration, and RAG
5. Progress percentage = `((step - 1) * 3 + sub + 1) / (6 * 3)` while running; `100%` when idle
6. Clear all timers on unmount

**Approve / Reject (per row)**
- Sets that run to decided; its right slot swaps the icon buttons for the "Reviewed" chip
- Also appends a confirmation message to the assistant transcript:
  - Approved → "Report approved and published to the program workspace. The deck is now marked final."
  - Rejected → "Report rejected. I'll regenerate the narrative on the next run — tell me what should change."
- There is currently no undo and no rejection-reason capture — see *Known gaps*

**Assistant chat**
- Enter sends; Shift+Enter is a newline; empty input and sends while a reply is pending are ignored
- On send: user message appended, input cleared, pending indicator shown, then the reply is appended
- The prototype calls an LLM when one is available and otherwise falls back to canned replies keyed on the input ("rag"/"why", "shorter"/"tighten"/"summar", "risk"). **In production, replace this entirely with the real report-assistant API call.** The prompt should carry the run's metadata, proposed RAG, and the full draft narrative, and instruct the model to answer only from that body in 2–3 plain sentences.
- Suggested-prompt chips simply send their own label as a user message

**Responsive behavior**
Designed for desktop widths. The 40/60 grid, the fixed 4-row report list, and the viewport-fitting height assumptions were not designed for narrow/mobile widths — decide on a stacking rule if mobile is in scope.

---

## State Management

| State | Type | Purpose |
|---|---|---|
| `project` | string | selected project (`singleSlide` \| `LeaveTracker`) |
| `running` | boolean | a generation run is active |
| `step` | number (1–6) | current pipeline step |
| `sub` | number | index of current sub-step within that step |
| `startedAt` | string `HH:MM` | run start time, shown in the status meta |
| `runs` | array | report history; each `{ id, date, rag, pending, decision }`; render the first 4 |
| `lastRun` | object | `{ date, rag, duration, decision }` for the idle status meta |
| `messages` | array | chat transcript; each `{ role: 'you' \| 'assistant', text }` |
| `draft` | string | composer contents |
| `thinking` | boolean | awaiting an assistant reply |

**Data fetching needed in production:** report history per project, the generated report body/narrative + proposed RAG, the deck URL per run, the approve/reject mutation (with reviewer identity), and the assistant completion endpoint. The pipeline run should be a real backend job — poll or stream its step/sub-step progress rather than driving it from client timers.

**Configurable knobs in the prototype:** `stepDurationMs` (400–3000, default 1300), `autoStart` (boolean, default false), `requireRejectReason` (boolean, default true — currently unused in the UI).

---

## Design Tokens

**Colors**
| Token | Value | Use |
|---|---|---|
| Navy (primary) | `#1F3864` | title, engine panel, primary buttons, links, focus |
| Navy hover | `#16294a` | primary button hover |
| Navy active | `#101f39` | primary button active |
| Page bg | `#f6f6f4` | app background |
| Card bg | `#ffffff` | white cards, inputs, chips |
| Tint bg | `#eef1f6` | assistant panel, project selector group |
| Tint border | `#dde3ee` / `#d8dfeb` | selector group / assistant panel borders |
| Card border | `#e2e2dd` | card + input borders |
| Divider | `#eeeeea` | header rules inside cards |
| Row divider | `#f2f2ef` | report row separators |
| Control border | `#dcdcd6` | secondary button / select borders |
| Neutral chip bg | `#f1f1ee` | "Reviewed" chip |
| Ink | `#17191d` | primary text |
| Ink muted | `#3c3f45` | secondary text |
| Ink subtle | `#63666d` | labels, meta |
| Ink faint | `#6b7386` | chat role labels |
| On-navy label | `#cfd7e5` | status label |
| On-navy meta | `#b6bfd0` | status meta |
| Log step done | `#d7deeb` | completed step heading |
| Log substep done | `#b9c3d6` | reached sub-step |
| Log pending | `#7f8ba4` | not-yet-reached step/sub-step |
| Danger | `oklch(0.48 0.15 25)` | reject hover |
| Link underline | `#c8cedb` | resting deck-link underline |

**Spacing** — 2 / 3 / 4 / 6 / 7 / 9 / 10 / 11 / 12 / 13 / 14 / 16 / 18 / 22 / 24 / 30 px (grid gap 18, right-column gap 14, container padding 22/30)

**Typography** — 29 (title) · 15 (section headings) · 14.5 (subtitle) · 14 (row date) · 13.5 (input) · 13 (buttons, step headings, select) · 12.5 (send, drafting) · 12 (sub-steps) · 11.5 (chips, meta, labels) · 11 (status label, chat role). Weights 400 / 500 / 600 / 700.

**Border radius** — 3px (controls, chips) · 4px (cards, panels) · 50% (dots)

**Shadows** — none. The design uses borders and surface tints only, deliberately.

---

## Assets
No images, icon fonts, or external assets. The only glyphs are two inline SVG paths (a check and an ✕) drawn with `stroke: currentColor`, `stroke-width: 2`, `stroke-linecap: square` on a `0 0 16 16` viewBox at 13×13. The select caret is drawn with two CSS gradients. No web fonts — system Helvetica/Arial stack.

---

## Known gaps (intentional, for the implementer to decide)
1. **Project selection is presentational** — it does not filter the report list or scope the assistant. Wire it to real per-project data.
2. **Deck links are placeholders** (`#report-<id>` anchors). Point them at real deck URLs.
3. **No rejection reason and no undo.** An internal review tool likely needs both, plus reviewer attribution on each decision.
4. **The report body is not shown in the UI** — only the assistant references it. Consider a collapsible draft preview so approval is an informed act.
5. **RAG is computed and stored but no longer displayed.** It still drives the assistant's context; decide whether it should surface anywhere.
6. **Keyboard focus states** exist only on inputs and the select; the icon-only Approve/Reject buttons need visible focus rings for accessibility.

---

## Files
- `OnePulse Dashboard.dc.html` — the source prototype (template + logic + configurable props). Read as spec; do not port its syntax.
- `OnePulse Dashboard (standalone).html` — self-contained, offline-openable build. Open this in a browser to interact with the design.
