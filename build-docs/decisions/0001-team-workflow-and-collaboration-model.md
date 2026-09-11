# 0001 — Team Workflow and Collaboration Model

**Status:** Accepted

## Context

Up to this point, the project had a complete spec (`prd.md`, `tdd.md`, `deployment-setup-guide.md`, `design.md`) and a working interactive frontend design canvas, but zero code and no git repository. The original ask was to write a ticket list. That request was reframed once the actual goal became clear: the user wants to build the real application from here, with two explicit, sometimes competing, goals:

1. **Ship the product** — a working, deployed Stack Overflow Challenge Scout, per the existing spec.
2. **Learn by doing** — the user is a Node.js developer who wants hands-on practice with Python/FastAPI, advanced Git, DevOps, and system design, in a setup that genuinely simulates a professional team rather than a tutorial. They want to write less code themselves and act more as the decision-maker/reviewer, with Claude acting as the senior engineer who implements and narrates reasoning as it goes.

This needed a concrete answer to three questions: how work gets tracked, how technical decisions get recorded, and how Git gets used — since all three double as the teaching surface.

## Decision

**Roles:** Claude acts as the senior engineer — proposes approaches, implements, explains Python/FastAPI concepts (especially where they diverge from Node.js equivalents), and flags decisions worth discussing before proceeding. The user reviews, decides, and tests — both by reading/approving proposed approaches and by manually exercising the frontend at each milestone checkpoint.

**Backlog:** `featuresticketlist.md`, organized as vertical-slice milestones (M0–M11) rather than `prd.md` §30's backend-first/frontend-last phase order — every milestone ships a backend piece and its matching frontend page together, so there's always something real to click through, and backend/frontend development proceed simultaneously rather than frontend being deferred to the end.

**Decision record:** a hybrid of two documents:
- `engineering-log.md` — a running, dated narration (what happened, git commands used, concepts introduced) for day-to-day session history.
- `decisions/NNNN-*.md` (this file's format) — used sparingly, only for decisions with lasting architectural consequence, following the standard ADR shape (Context/Decision/Consequences).

This mirrors how real teams actually document things: a lightweight log/standup trail for everything, formal ADRs only for the calls that matter later.

**Git:** a real repository, feature-branch-per-ticket, merged back to `main`, using Conventional Commits. Chosen deliberately over committing straight to `main` — branching, merging, and (when they arise) resolving conflicts and rebasing are exactly the mechanics the user wants practice with, so they need to actually happen rather than being skipped for convenience.

**Testing at checkpoints:** each milestone's test checkpoint combines automated tests (tagged 🔒 security / ⚡ performance-lite / 🧩 business logic — lightweight performance checks only, given this is a single-user tool with no real concurrent load), manual verification steps, and a concrete frontend click-through list handed to the user.

**Sequencing:** the scheduler milestone (M11 — converting manually-triggered endpoints into real scheduled jobs, closing the gap already flagged in `prd.md` §23/§35) is placed *after* the MVP checkpoint (M10), not interleaved into MVP work — the user's explicit call, keeping the MVP path focused on reaching `prd.md` §33's Definition of Done first.

## Consequences

- More process overhead than a solo hack session would need (branch-per-ticket, a log entry per session, occasional ADRs) — accepted deliberately, since the overhead *is* the point for the learning goals.
- The backlog's milestone order deviates from `prd.md` §30's phase list; `prd.md` remains the source of truth for *what* the product does, `featuresticketlist.md` for *in what order we build it*. These can drift apart if `prd.md` is later revised without updating the backlog — worth a periodic cross-check (already the closing verification step whenever the backlog is materially edited).
- System-design concepts get taught opportunistically, tied to whatever milestone is in front of us (e.g., webhook idempotency at M4, prompt injection at M7), rather than as a structured curriculum — appropriate for learning-by-building, but means coverage follows the roadmap's shape, not a syllabus.
