# Standing Rules

Small, durable collaboration rules that apply across every session — narrower than an ADR (`decisions/`), more permanent than a one-off note in `engineering-log.md`. Add to this list whenever the user states a rule that should hold from then on.

---

## New dependencies must be explained

Whenever a new package/library is added to either `backend/` or `frontend/` (e.g. `uv add`, `npm install`), explain in-chat what it is and why it's needed before or as it's added — not just that it's being installed.

**Why:** the user is learning as we go and wants to understand what's entering the codebase, not just see it appear in a lockfile.

**Added:** 2026-09-15, during M0-F1 (adding `@tanstack/react-query`).
