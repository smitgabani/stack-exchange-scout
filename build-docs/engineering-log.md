# Engineering Log

A running, dated narration of each work session: what we decided, what got built, the git mechanics used (as a teaching trail), and the concepts introduced along the way. Significant architecture decisions get pulled out into their own ADR in `decisions/` and cross-referenced from here — this log is the day-to-day story, not the formal record of *why* for the big calls.

**Entry template** (copy this for each new session):

```
## <date> — <short title>

**Milestone / tickets:** <e.g. M1-B1..B6, M1-F1..F2>
**Decisions made:** <anything decided this session, even small ones — link an ADR if one was written>
**What got built:** <plain-language summary, not a diff>
**Git:** <branches created/merged, notable commands, anything taught (rebase, conflict resolution, etc.)>
**Concepts introduced:** <Python/FastAPI/Git/DevOps/system-design concepts explained this session, esp. Node.js comparisons>
**Next up:** <what the next session picks up>
```

---

## 2026-09-11 — Team workflow setup

**Milestone / tickets:** Pre-M0 (repo + process setup, not a ticket itself)

**Decisions made:**
- Reframed the engagement: I (Claude) act as the senior engineer executing implementation; the user — a Node.js developer learning Python/FastAPI, advanced Git, DevOps, and system design — reviews, decides, and learns by doing rather than writing most of the code themselves. See `decisions/0001-team-workflow-and-collaboration-model.md` for the full reasoning.
- Backlog lives in `featuresticketlist.md`, organized as vertical-slice milestones (M0–M11) rather than the backend-first/frontend-last phase order in `prd.md` §30 — every milestone ships a backend piece and its matching frontend page together.
- Git workflow: real feature-branch-per-ticket, merged back to `main`, Conventional Commits — chosen specifically as the vehicle for hands-on branching/merging/rebasing practice, not commits straight to `main`.
- Test checkpoints at each milestone combine three things: automated tests I write (tagged 🔒 security / ⚡ performance-lite / 🧩 business logic), manual verification I run myself, and a concrete frontend click-through list for the user.
- Performance testing stays lightweight (response-time sanity checks) given this is a single-user personal tool — no Locust/k6.
- The scheduler (closing the "no scheduler yet" gap) is deliberately placed *after* the MVP checkpoint (M11, post-M10), not interleaved into MVP work.

**What got built:**
- Git repository initialized; existing `build-docs/` and `design-mockups/` content committed as the root commit.
- `.gitignore` added (Python + Node + editor + macOS junk).
- `featuresticketlist.md` populated with the full M0–M11 backlog.
- `decisions/0001-team-workflow-and-collaboration-model.md` — the first ADR.
- This log, seeded with its template and this entry.

**Git:**
```
git init
git add .gitignore build-docs design-mockups
git commit -m "chore: initial project docs and design mockups"
```
This first commit went straight to `main` deliberately — it's a snapshot of pre-existing work, not a ticket. Starting with M0, every ticket gets its own branch (`git checkout -b <ticket-id>-<slug>`), and merging that branch back is where branching/merging/rebasing gets taught for real, on real history.

**Concepts introduced:**
- Conventional Commits (`feat:`/`fix:`/`test:`/`docs:`/`chore:`) as the commit message convention going forward.
- ADRs (Architecture Decision Records) as a real industry pattern for documenting significant technical decisions — lightweight, one file per decision, used sparingly (not for every small choice).

**Next up:** M0 — Foundations & scaffolding (backend skeleton, frontend skeleton, both deployed and talking to each other).
