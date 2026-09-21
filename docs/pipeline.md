# The discovery-to-challenge pipeline

Every question in the app passes through these stages, in this order. Each
stage is a manual action in the UI today (see `frontend-pages.md` for
exactly which button triggers which stage).

```
 Topics (profile)
       │
       ▼
 1. Run a Scout / research task  ──spends ~$0.35──▶  Yutori searches Stack Overflow
       │                                                        │
       │                                              webhook POST /webhooks/yutori
       │                                                        ▼
       │                                              stored as a pending "run" payload
       ▼
 2. Ingest webhooks (POST /candidates/ingest)
       — turns pending run payloads into `question` rows, status = candidate
       — safe to re-run: a question already known by its Stack Overflow ID
         is recognized, not duplicated
       │
       ▼
 3. Enrich pending (POST /candidates/enrich)
       — fetches real data per question from the Stack Exchange API:
         score, answer count, accepted-answer flag, tags, body, dates
       — a question with no content yet cannot be turned into a challenge
       │
       ▼
 4. Re-score (POST /candidates/rank)
       — scores every enriched candidate against the CURRENT profile:
         topic match/weight (30%), preferred/avoided concepts, difficulty
       — an avoided concept anywhere in the question rejects it outright
       — re-running this after changing your topics re-scores everything
       │
       ▼
 5a. Promote one question ──spends 1 LLM call──▶  a challenge
       (POST /questions/{id}/challenge, pick a format)
       — generates: problem summary, why it was selected, concepts,
         starting direction, progressively-revealed hints, difficulty
       — the chosen "format" controls which extra blocks the LLM is asked
         for (see the LLM → Formats page)
       │
 5b. OR generate a digest ──spends N LLM calls──▶  a digest
       (POST /digest/generate)
       — bundles your best-scoring not-yet-used candidates into a batch of
         challenges in one go, sized by your "questions per digest" setting
       — can come back "empty" if nothing cleared the quality bar; the bar
         is never lowered just to fill a digest
       │
       ▼
 6. Send the digest ──sends a real email──▶  your inbox
       (POST /digest/send, via Resend)
       — does not generate a new digest first; sends whatever the latest
         one contains
```

## Rejection and dismissal — two different "no"s

A question that never reaches your candidate pool because it didn't match
any topic, or matched an avoided concept, is **rejected** automatically
(`rejection_reason: "automatic"`). A question you looked at and personally
decided against is **dismissed** (`rejection_reason: "user_dismissed"`,
via the Dismiss button on the Questions page) — it can be brought back with
Restore. Both are filterable separately on the Questions page because they
represent different kinds of decisions.

## Reformatting vs. regenerating

Adding sections to an existing challenge (`POST /challenges/{id}/reformat`)
is not the same as generating a new one. It keeps the challenge's ID and
any already-revealed hints intact, and only asks the model for blocks the
current format wants that the challenge doesn't already have. If nothing
is missing, it makes no LLM call at all.

## What's not automated yet

Nothing in this pipeline runs on a timer. Scheduling every stage
(especially digest generation and sending, on the frequency set on the
Topics page) is tracked as a future milestone — see `build-docs/` for the
roadmap.
