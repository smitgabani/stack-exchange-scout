# 0002 — Command Execution Boundary: Git and DevOps Commands Are User-Run

**Status:** Accepted
**Amends:** 0001 (Team Workflow and Collaboration Model)

## Context

Within the first minute of M0, Claude ran `git checkout -b ...` directly instead of having the user run it. The user caught this immediately: the stated goal is to *learn* Git (and DevOps), and watching Claude execute commands doesn't teach that — typing them, seeing the output, and making the small mistakes that come with it does. ADR 0001 established the roles (Claude implements, user decides/learns) but didn't draw an explicit line around *which* actions are "implementation" (fine for Claude to just do) versus "the actual learning objective" (must be done by the user).

## Decision

Split by category, not by file type:

- **Application code** (Python, TypeScript, config files, tests) — Claude writes these directly. This matches the user's own framing: "I would like to code less and use you as a coding agent."
- **Git commands** (branch, add, commit, merge, rebase, log, diff, etc.) — the **user** runs every one of these. Claude gives the exact command, explains what it does and why this one, and waits for the user to run it and report the result before giving the next command.
- **DevOps/infra commands** (`uv`, `flyctl`, `vercel` CLI, `docker`, anything that provisions or deploys) — same treatment as Git: user-run, Claude-instructed. This was grouped with Git because the user named "advanced git and devops" together as explicit learning goals — the reasoning for not executing Git commands applies equally here.
- **Delivery cadence:** one command at a time, explained, with the user's confirmation/output before the next — not batched — so each step is actually absorbed rather than skimmed.

## Consequences

- Slower wall-clock progress through tickets than Claude just running everything — accepted deliberately, same tradeoff as ADR 0001.
- Claude needs to pause and hand off at every git/infra step rather than completing a ticket end-to-end in one pass; plan narration should anticipate this (e.g., "next you'll run X, then I'll continue with the file changes") rather than assuming a command just happened.
- If a command's output isn't what's expected (a merge conflict, a failed deploy), that becomes a real, in-the-moment teaching opportunity rather than something Claude silently resolves — this is a feature of the setup, not friction to route around.
