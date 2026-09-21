# 0005 — User-Defined Blocks and Editable Block Instructions

**Status:** Accepted
**Date:** 2026-09-21
**Scope:** Amends the design stated in `challenge_blocks.py`'s module docstring ("the registry lives in code") and extends `prd.md` §17 and the formats work from M12.

## Context

A challenge format is a named selection of blocks. Each block declares, in one place in code, its `schema`, its `instruction`, its `kind` (which renderer draws it) and whether it is `gated`. The format stores only a list of keys; the instruction list and the JSON Schema are compiled from the registry on every generation.

That design was chosen deliberately, and the reasoning is worth restating because this ADR does not discard it:

> An arbitrary schema would leave the UI rendering key/value dumps and would leave every new field unvalidated, because the app would have no idea what the field meant.

Two limitations followed from it.

**1. The per-block instructions are invisible and fixed.** `system_instruction` and `user_preamble` are editable and versioned in `prompt_templates`. The text that actually asks for each block — "Provide exactly three progressive hints…" — is not editable anywhere, and is not even displayed. Tuning what a block asks for requires a deploy.

**2. A new block requires a deploy.** The vocabulary is a frozen tuple. Adding "a checklist of things to verify before you call this done" means editing Python, even though the app already has a checklist renderer and the block would need no new code at all.

Both are ordinary product requests. The question was whether satisfying them costs the guarantee above.

## Decision

### 1. A block's shape comes from its `kind`, not from a schema anyone writes

`_SCHEMA_BY_KIND` maps each of the eleven renderer names to the shape it implies. A user-defined block **names a kind and never writes a schema**; the shape is looked up.

This is the crux of the ADR. The guarantee the code-only registry protected was never "only programmers may add blocks" — it was "no value reaches the page in a shape the UI cannot draw". Deriving the schema from the kind preserves that exactly, because the set of kinds is still the set of renderers that exist.

Every built-in block now builds its schema from the same map, so a custom `checklist` and the built-in `self_check` are guaranteed to ask for the same shape rather than merely happening to agree. (Verified behaviour-preserving when introduced: all fifteen schemas were byte-identical before and after.)

Two kinds are withheld from the picker. `progressive_hints` is special-cased by `_normalise_hints` and demanded by `validate`; `rating` is bound to the `estimated_difficulty` column. A second block of either kind would be silently mishandled rather than merely rendered.

### 2. Structure stays in code; wording and selection move to the database

| | Lives in | Editable |
|---|---|---|
| Which kinds exist | code (`KINDS`) | no — a kind is a React component |
| A kind's schema | code (`_SCHEMA_BY_KIND`) | no |
| A built-in block's kind, core/gated flags | code (`BLOCKS`) | no |
| A built-in block's instruction | `block_instructions` | **yes** |
| A custom block's label, kind, instruction, gated | `custom_blocks` | **yes** |
| Which blocks a format selects | `challenge_formats` | yes (already) |

`block_service.resolve` merges them: start from the code registry, overlay instruction overrides, append custom blocks. `challenge_blocks.resolve` remains as the pure path for defaults and tests.

Only the instruction is overridable for a built-in block. This is the load-bearing restriction: a reworded `concepts` can ask for different ideas, but cannot start returning a string and fail `validate` on every generation until someone notices.

### 3. Two tables, not one

`custom_blocks` and `block_instructions` are separate rather than one table with nullable columns. A custom block must have a kind and a label; an override must have neither. Two tables say that with `NOT NULL`; one table would need a `CHECK` constraint that has to be read to be believed.

### 4. Provenance is per generation, not per challenge

`challenges.generations` is a JSONB **list** of `{at, blocks, system_instruction, prompt_version, provider, model}`.

A list rather than a single column because a challenge is not always one generation: `reformat_challenge` tops a challenge up with a second, different instruction covering only the blocks that were missing. A single column would have to either lose the original or omit the addition.

This is what makes instructions safely editable after the fact. Rewording a block changes what the *next* challenge is asked for; the ones already made still say exactly what produced them. `challenges.prompt_version` alone can no longer answer that question, because the composed instruction now depends on block wording too.

## Consequences

**The frontend's `BLOCK_META` must go.** `blocks.tsx` hardcodes a map from block key to `{label, kind, gated}` and returns `null` for anything absent — so a custom block would render nothing. Its own docstring already claims the switch is on `kind` rather than the key; this makes that true. The metadata has to be served with the challenge instead. `labelFor`, `isGated` and `SPECIAL_BLOCKS` are used at four further sites in the challenge page and all need the same treatment.

**`format_service._validate` became async.** It has to ask the database which custom keys exist. Formats naming an unknown key are still rejected; the set of known keys is just larger now.

**A deleted custom block behaves like one removed from the code.** Its values stay in `challenges.content` but nothing resolves the key, so it stops rendering. `resolve` skips unknown keys rather than raising, so a format naming it still generates — the same tolerance the built-in `resolve` already had, and for the same reason: failing here means discovering the problem an hour after the run that paid for the question.

**A gated custom block opts out of the spoiler scan.** `validate` exempts gated blocks by design — "If you're stuck" exists to point at the answer. A user can therefore deliberately create a block that asks for solution-shaped material. This is consistent with the existing built-in rather than a new hole, but it is the one place where a user's choice loosens a safety control, so the UI must say so plainly rather than offering a quiet checkbox.

**Block instructions are an injection surface.** They are concatenated into the system instruction, so they carry the same `<QUESTION>` check as `prompt_service`. As there, this is not the security boundary — the fence is added in code around whatever the instruction says — but a block carrying its own fence would produce a nested, confusing structure.

## Alternatives considered

**Raw JSON Schema per block.** Rejected: it hands back exactly the key/value dumps the original design existed to prevent, and every custom field would be unvalidated because nothing would know what it meant.

**Per-format instructions** (the same block worded differently in different formats). Genuinely more expressive, and rejected for now as premature: it moves the instruction into a format/block join, gives every format its own copy to maintain, and no concrete need for it has appeared. Revisit if one does.

**Versioning custom blocks like `prompt_templates`.** Rejected in favour of per-generation provenance. Immutable block rows would make every edit a new version to activate, and the question that actually needs answering — "what produced *this* challenge?" — is answered better by recording what was sent than by reconstructing it from versions.
