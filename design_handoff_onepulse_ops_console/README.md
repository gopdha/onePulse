# Handoff: OnePulse — Ops Console (option 1c)

## Overview
OnePulse is a single-page internal dashboard for AI-generated project status reports. A user picks a
project, reviews the most recent AI-written report (approve/reject), scans the last three reports,
triggers a new report generation (a real multi-stage job that can take 60–90s), and asks a chat
assistant questions grounded in that project's past reports.

This bundle documents the **Ops Console** direction: a navy app bar with an always-visible project
selector, a dense four-row report table (latest row pinned and emphasized), a terminal-style run
console that streams real generation stages, and an assistant docked in a right rail.

Two product decisions are load-bearing and must survive implementation:

1. **No eager loading.** The page opens in a deliberate empty state. No project is auto-selected and
   no data is fetched until the user chooses one. The empty state is designed content, not a spinner.
2. **Every async action shows immediate feedback.** Project selection, generation, approve/reject,
   and assistant questions each get a visible indicator on the same tick the action starts. There is
   never a static screen while work is happening.

## About the Design Files
The file in this bundle is a **design reference created in HTML** — a prototype showing intended
look and behavior, not production code to copy. The task is to **recreate this design in the target
codebase's existing environment** (React, Vue, SwiftUI, native, etc.) using its established
patterns, component library, and data layer. If no environment exists yet, choose the most
appropriate framework and implement the design there.

All async behavior in the prototype is simulated with timers. In the real app these map to actual
API calls; the *timing-independent* requirement is that each state (queued → in-progress → done)
renders exactly as specified below regardless of how long the backend takes.

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and interaction states are final and are
listed exactly below. Recreate the UI pixel-accurately using the codebase's libraries where they
exist (buttons, selects, chat primitives) and match these values where they don't.

## Screens / Views

The design is one screen with four mutually exclusive top-level states, plus per-row and per-action
sub-states.

### Shell (always present)
- Outer card: `1340px` wide, `border: 1px solid #dfe3e8`, `border-radius: 14px`, `overflow: hidden`,
  `background: #fff`, `box-shadow: 0 1px 2px rgba(23,27,34,.04)`. Page background `#eceef1`,
  page padding `40px`.
- **App bar**: `background: #1F3864`, `height: 70px`, horizontal padding `26px`, flex row,
  `space-between`, `align-items: center`, `gap: 32px`.
  - Left: wordmark `OnePulse` — 20px / 600 / `letter-spacing: -0.015em` / `#fff`; beside it (baseline
    aligned, `gap: 16px`) the subtitle `AI status reports · review queue · one project at a time` —
    13.5px / 400 / `#a9b8d4` / `white-space: nowrap`.
  - Right: label `PROJECT` — mono, 11px, `letter-spacing: .1em`, `#8fa2c4`; then the project
    `<select>`: width `280px`, padding `10px 12px`, 14px text, `color: #fff`,
    `background: rgba(255,255,255,.10)`, `border: 1px solid rgba(255,255,255,.26)`,
    `border-radius: 7px`. Placeholder option label: `Select a project…`. Option text color `#171b22`
    (native menus render on white).
  - Projects in the prototype: Atlas Migration, Payments Platform, Customer 360, Mobile Reboot.

### State 1 — Empty (no project selected) — the default on open
Two-column grid `1fr 360px`; the divider is `border-right: 1px solid #eceef2` on the left cell.
- Left cell: padding `96px 40px`, column flex, `gap: 12px`, centered.
  - `NO PROJECT SELECTED` — mono, 12px, `letter-spacing: .12em`, `#9aa3b1`
  - `Nothing is loading` — 18px / 600 / `-0.015em` / `#171b22`
  - `Reports, review state and the run console stay dark until you pick a project — no default fetch
    on open.` — 14px / `#6b7482` / `line-height: 1.6` / `max-width: 400px` / centered
- Right cell (rail): `background: #fafbfc`, padding `32px 26px`.
  - `ASSISTANT` — mono, 11px, `.12em`, `#9aa3b1`
  - `Available once a project is loaded.` — 13.5px / `#8b95a4`

### State 2 — Loading a project
Shown the instant the select changes; replaces the whole body (padding `26px 26px 30px`).
- Status line: 13px spinner (`border: 2px solid #ccd3dd`, `border-top-color: #1F3864`,
  `border-radius: 50%`, `animation: spin .7s linear infinite`) + mono 12px `#4a5462` text
  `fetch reports · <Project Name>`; `margin-bottom: 18px`.
- Five skeleton rows, `height: 46px`, `border-radius: 7px`, `gap: 8px`, shimmer:
  `linear-gradient(100deg,#f5f6f8 30%,#e9ecf0 50%,#f5f6f8 70%)`, `background-size: 600px 100%`,
  animated `background-position: -260px → 340px` over `1.1s linear infinite`.
- Prototype duration 900ms; real implementation shows this until the fetch resolves.

### State 3 — Loaded
Two-column grid `1fr 360px` (left cell `border-right: 1px solid #eceef2`).

#### Report table (left cell, top)
Shared grid across header and all rows: `grid-template-columns: 1fr 190px 88px 250px`, `gap: 16px`,
horizontal padding `26px`.

- **Header row**: `background: #fafbfc`, padding `13px 26px`,
  `border-bottom: 1px solid #e6e9ee`; labels `RUN · STATE · REPORT · REVIEW` — mono, 10.5px,
  `letter-spacing: .12em`, `#8b95a4`; the REVIEW label is right-aligned.
- **Pinned latest row**: `background: #f4f7fb`, padding `22px 26px`,
  `border-bottom: 1px solid #e6e9ee`, `align-items: center`.
  - Col 1: a `LATEST` tag — mono 9.5px, `.12em`, `#fff` on `#1F3864`, padding `3px 7px`,
    `radius 4px` — then `Fri, Sep 4 2026 · 06:00` at 17px / 600 / `-0.015em` / `#171b22`
    (`gap: 10px`). Sub-line: mono 11.5px `#7b8795` — `4 hours ago · run 1m 08s · 6 sources`.
  - Col 2: state chip, 13px, padding `5px 11px`, `radius 5px`, `justify-self: start` (colors below).
  - Col 3: `Open` link — 13.5px, no underline, `border-bottom: 1px solid #ccd4e2`,
    `padding-bottom: 1px`.
  - Col 4 (right-aligned): `Reject` then `Approve`, `gap: 9px`.
    - Approve: padding `9px 20px`, 13.5px / 500, `#fff` on `#1F3864`, no border, `radius 6px`.
    - Reject: padding `9px 16px`, 13.5px, `#8A2F2F` on `#fff`, `border: 1px solid #e0cccc`,
      `radius 6px`.
- **History rows (exactly 3)**: padding `15px 26px`, `border-bottom: 1px solid #f1f3f6`.
  - Col 1: mono 13px `#2a3140` `Fri, Aug 28 2026 · 06:00`, then mono 11px `#9aa3b1` relative age
    (baseline aligned, `gap: 10px`).
  - Col 2: state chip at 12.5px, padding `4px 10px`.
  - Col 3: `Open` at 13px.
  - Col 4: buttons at padding `7px 15px` / `7px 13px`, 12.5px — otherwise identical to the latest row.
- The latest row is the *only* emphasized row: tinted background, larger type, the LATEST tag, and
  taller padding. History is deliberately quiet.

**Report row sub-states (apply to latest and history alike):**
| Sub-state | Renders |
|---|---|
| `pending` | Reject + Approve buttons; state chip `Awaiting review` |
| `busy` (approve/reject in flight) | Buttons replaced in place by spinner + mono text `approving…` / `rejecting…` (11.5px latest, 11px history, `#4a5462`) |
| `reviewed` | Buttons replaced by mono text `Already reviewed · Approved` / `· Rejected` — 11.5px/11px, `#6b7482` (latest) / `#9aa3b1` (history) |

Row-height stability matters: the busy and reviewed treatments must not change row height or shift
the columns.

#### Generate status report (left cell, below the table)
Padding `24px 26px 28px`.
- Header row (`space-between`, `align-items: center`, `margin-bottom: 14px`):
  - Left: `GENERATE STATUS REPORT` — mono 10.5px, `.12em`, `#8b95a4`; beside it a live mono 11.5px
    `#1F3864` status string — idle `no run in progress`, running `investigation · 34%`, done
    `done in 1m 08s`.
  - Right: primary button — padding `10px 20px`, 13.5px / 500, `#fff` on `#1F3864`, `radius 7px`,
    hover `#16294b`. Label: `Generate report` (idle) → `Running…` (in flight) → `Run again` (done).
- Overall progress bar: `height 4px`, track `#eceef2`, `radius 3px`, fill `#1F3864`,
  `transition: width .25s linear`, `margin-bottom: 12px`.
- Console: `background: #111722`, `radius 9px`, padding `16px 18px`, fixed `height 186px`,
  `overflow-y: auto`, column flex `gap: 5px`, mono 11.5px, `line-height: 1.6`. Auto-scrolls to the
  newest line (set `scrollTop = scrollHeight` on append — do not use `scrollIntoView`).
  - Idle line: `$ awaiting run — investigation · drafting · quality review · render` in `#5a6577`.
  - Each log line: timestamp `mm:ss` in `#4d5a70` (fixed, `flex: none`) + `gap: 12px` + message.
  - Stage banner lines: `— INVESTIGATION` etc. in `#8fb0e8`.
  - Detail lines: `#c3ccda`.
  - Completion line: `✓ report ready · awaiting review` in `#7fc9a2`.
  - While running, a live footer line: timestamp + 11px spinner (`#2c3648` ring, `#7d9cd6` head)
    + `#7d9cd6` text `<Stage name> — stage 2 of 4`.

**The four generation stages** (names, sub-copy, prototype durations, and the log lines each emits):
1. **Investigation** — "Reading Jira, Git history, incidents and decision records" — 3400ms —
   `connect jira — 48 issues in window`, `git: 213 commits · 11 authors`,
   `incidents: 2 open · 1 resolved`, `decision records: 3 read`
2. **Drafting** — "Composing the narrative, risks and asks" — 2400ms —
   `outline: progress · risks · asks · next`, `draft v1 — 618 words`
3. **Quality review** — "Every claim checked back to a source" — 1900ms —
   `claims verified 17/17`, `1 unsupported claim rewritten`
4. **Rendering** — "Building the shareable report and link" — 1200ms —
   `render html + pdf`, `share link minted`

In production these are real backend stages; stream them (SSE/WebSocket/polling) and render each
event as a line. Progress percent should be derived from stage completion, not faked — but never
leave the bar at 0 while a stage runs; if the backend gives no sub-stage progress, interpolate
within the current stage's expected duration.

**On completion**, the new report is prepended as the pinned latest row with state `pending`,
`ago: just now`, and the run's real duration; the table keeps 4 rows total (latest + 3 history), so
the oldest history row drops off.

#### Assistant (right rail, 360px)
Column flex, `background: #fafbfc`.
- Header: padding `15px 22px`, `border-bottom: 1px solid #e6e9ee`, `STATUS REPORT ASSISTANT` — mono
  10.5px, `.12em`, `#8b95a4`.
- Transcript: `flex: 1`, padding `20px 22px`, `gap: 13px`, `height 430px`, `overflow-y: auto`,
  auto-scrolled to bottom.
  - Empty copy: `Grounded in this project's 4 reports. Ask anything.` — 13.5px `#8b95a4`.
  - User bubble: `align-self: flex-end`, `max-width: 86%`, `#fff` on `#1F3864`, padding `10px 13px`,
    `border-radius: 11px 11px 3px 11px`, 13px, `line-height: 1.5`.
  - Assistant bubble: `align-self: flex-start`, `max-width: 94%`, `#fff`,
    `border: 1px solid #e3e6eb`, `color: #2a3140`, padding `11px 13px`,
    `border-radius: 11px 11px 11px 3px`, 13px, `line-height: 1.6`.
  - Thinking bubble (replaces nothing — appended, then swapped for the answer): assistant-bubble
    chrome containing three 5px `#1F3864` dots (`gap: 4px`, bounce animation, delays `0 / .15s /
    .3s`) + mono 11px `#8b95a4` caption. Caption changes over time: `searching 4 reports…` →
    (after ~700ms) `reading Aug 14 – Sep 4 · citing sources`. Use real progress text if the backend
    exposes it.
- Composer: padding `14px 16px`, `border-top: 1px solid #e6e9ee`, `background: #fff`.
  - Input: `flex: 1`, padding `10px 12px`, 13px, `border: 1px solid #d9dee5`, `radius 7px`,
    placeholder `Ask about past reports…`; Enter submits.
  - Send button: padding `10px 15px`, 13px / 500, `#fff` on `#1F3864`, `radius 7px`, label `Ask`.
  - Suggestion chips below (`gap: 7px`, wrap): padding `6px 10px`, 11.5px, `#4a5462` on `#f4f6f8`,
    `border: 1px solid #e3e6eb`, `radius 20px`. Chips: `Why did the schedule slip?`,
    `Summarize the last 3 reports`, `Why was one rejected?` — clicking a chip submits it.

## Interactions & Behavior
- **Select a project**: on `change`, clear all prior project state (reports, generation run, chat)
  and switch to the loading state in the same render. Selecting the blank option returns to the
  empty state. Any in-flight generation for the previous project is cancelled.
- **Approve / Reject**: optimistic-feel but honest — the row immediately enters `busy` (spinner +
  `approving…`), and resolves to `reviewed` when the request returns (prototype: 800ms). Both
  buttons are removed while busy so a second click is impossible.
- **Generate**: button becomes `Running…` and is inert; progress bar, stage banner lines, and the
  live footer line all appear on the first tick (<150ms), before any backend response.
- **Assistant**: on submit the user bubble + thinking bubble append instantly; when the answer
  arrives it replaces the thinking bubble and streams in (prototype: 3 words every 60ms). Stream
  real tokens if available.
- **Animations**: spinner `rotate 360deg` / `.7s linear infinite`; skeleton shimmer `1.1s linear
  infinite`; thinking dots `1s` staggered bounce; progress bar `width .25s linear`. Buttons have a
  hover darkening only (`#1F3864 → #16294b`); no transforms, no easing beyond the above.
- **Responsive**: designed at 1340px fixed. If a narrower breakpoint is needed, collapse the
  `1fr 360px` grid to a single column with the assistant last, and let the table's col 1 flex; do
  not shrink the 250px review column (the busy/reviewed labels need it).
- **Accessibility**: state changes should be announced (`aria-live="polite"` on the console and the
  transcript); spinners need accessible labels; the LATEST tag is decorative and can be
  `aria-hidden` if the row is otherwise labelled.

## State Management
Per project view:
- `projectId: string | null` — drives everything; `null` = empty state.
- `loading: boolean` — true from select until reports resolve.
- `reports: Report[] | null` — `null` until loaded; exactly 4 entries after load
  (`[0]` is the pinned latest).
  `Report = { id, date, time, relativeAge, runDuration, status: 'pending'|'approved'|'rejected',
  busy?: 'approved'|'rejected', url }`
- `run: { running, done, stageIndex, percent, elapsedMs, log: {t, line, kind}[] } | null` — `null`
  when idle.
- `chat: { messages: {id, role:'user'|'assistant', text}[], pending: boolean, pendingCaption }`
- `draft: string`

Transitions: `select → clear + loading` · `reports resolve → loaded` ·
`approve/reject → row.busy → row.status` · `generate → run stream → prepend report + trim to 4` ·
`ask → append user + pending → stream assistant`.

Data needs: list of projects; reports for a project (most recent first); review mutation
(approve/reject); generation trigger with a progress stream; assistant Q&A grounded in that
project's reports.

## Design Tokens
**Colors**
| Token | Value | Use |
|---|---|---|
| navy | `#1F3864` | app bar, primary buttons, bar fill, LATEST tag, user bubble |
| navy-hover | `#16294b` | primary button hover |
| navy-on-dark-text | `#a9b8d4` | app-bar subtitle |
| navy-on-dark-label | `#8fa2c4` | app-bar `PROJECT` label |
| ink | `#171b22` | headings, primary text |
| ink-2 | `#2a3140` | table mono text, assistant bubble text |
| muted | `#6b7482` | body copy, reviewed label (latest) |
| muted-2 | `#7b8795` / `#8b95a4` / `#9aa3b1` | sub-lines, mono labels, quiet labels |
| line | `#e6e9ee` (structural) · `#eceef2` · `#f1f3f6` (row) · `#dfe3e8` (card) | borders |
| canvas | `#eceef1` (page) · `#fafbfc` (rail/header) · `#f4f7fb` (pinned row) · `#f5f6f8` (chips) | surfaces |
| console-bg | `#111722` | run console |
| console-ts / stage / body / ok | `#4d5a70` / `#8fb0e8` / `#c3ccda` / `#7fc9a2` | console text |
| approved | fg `#1F6B4A`, bg `#EEF5F1`, border `#cfe3d7` | approved chip |
| rejected | fg `#8A2F2F`, bg `#FAF1F1`, border `#e6d1d1` | rejected chip, Reject button |
| pending | fg `#7A5417`, bg `#FBF5EA`, border `#eadfc9` | awaiting-review chip |

**Typography** — UI: `'Helvetica Neue', Helvetica, Arial, sans-serif`. Data/labels:
`ui-monospace, SFMono-Regular, Menlo, monospace`.
Scale: 20/600 wordmark · 17/600 pinned row · 14 select · 13.5 body + links · 13 rows/bubbles ·
12.5 chips · 11.5 mono sub-lines · 11 mono captions · 10.5 mono column labels (`.12em`) ·
9.5 LATEST tag. Negative tracking `-0.015em` on 17px+ headings only.

**Spacing** — 4 / 5 / 7 / 9 / 10 / 12 / 13 / 16 / 18 / 20 / 22 / 26 / 32 / 40 px. Card padding
`26px` horizontal throughout; rail `22px`.

**Radii** — 4 (tag) · 5 (chips) · 6 (row buttons) · 7 (select, primary button, skeleton) ·
9 (console) · 11 (bubbles, one corner 3) · 14 (outer card) · 20 (suggestion chips) · 50% (spinners,
dots).

**Shadow** — `0 1px 2px rgba(23,27,34,.04)` (outer card only). No other shadows.

## Assets
None. No images, no icon font, no SVG. The only glyphs used are the text characters `✓`, `·`, `—`,
`→`, and `$`. If the codebase has an icon set, substitute icons for `✓` and the spinner.

## Screenshots
`screens/` captures the real states in order: empty (01), project loading (02), loaded review
queue (03), generation mid-run at stage 2 with the streaming console (04), assistant thinking (05),
assistant answer + run complete with the new report pinned (06), approve in flight (07), already
reviewed (08). They are DOM re-renders, so a few mono labels wrap early and the native select shows
its placeholder — trust the README values and the HTML over the pixels in those two spots.

## Files
- `OnePulse Ops Console.dc.html` — the design reference for this option (self-contained; open in a
  browser). Includes the empty, loading, and loaded states plus all live behavior.
- Demo controls exposed on the prototype: `demoSpeed` (time multiplier, 0.5–4×),
  `autoLoadDefaultProject` (off by default — turning it on demonstrates the eager-load behavior this
  design deliberately removes), `showReasoningCaptions`.
