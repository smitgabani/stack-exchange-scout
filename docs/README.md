# Stack Exchange Scout — Documentation

Stack Exchange Scout is a personal, single-user tool that discovers Stack
Overflow questions matching your interests, scores and enriches them, and
turns the best ones into coding challenges delivered by email.

This `docs/` root holds **application documentation** — what the product
does, how its pieces fit together, and what every screen and button is for.
It's aimed at anyone reading or operating the app (including future-you).

Process documentation — the roadmap, the session-by-session engineering log,
and architecture decision records — lives separately in
[`build-docs/`](../build-docs/) and isn't duplicated here.

## Contents

- [`architecture.md`](architecture.md) — system overview: services, data
  flow, and how the frontend, backend, and third parties (Yutori, Stack
  Exchange, an LLM provider, Resend) fit together.
- [`pipeline.md`](pipeline.md) — the discovery-to-challenge pipeline in
  detail: every stage a question passes through and what triggers each one.
- [`frontend-pages.md`](frontend-pages.md) — every page in the app, and
  every action button on it: what it does, what it costs, and what it
  affects.
- [`api-reference.md`](api-reference.md) — the backend's HTTP surface,
  grouped by resource.

## The one-paragraph version

A **Scout** (a saved Yutori search built from your topics) runs on demand
and returns candidate Stack Overflow questions. Each candidate is
**ingested**, **enriched** with real Stack Exchange data, and **scored**
against your profile (topics, preferred/avoided concepts, difficulty range).
You can turn any candidate into a **challenge** — an LLM-generated writeup
with hints — one at a time, or in bulk via a **digest**, which bundles the
best-scoring candidates and can be **emailed** to you. Nothing runs on a
schedule yet; every stage is triggered by hand from the UI.
