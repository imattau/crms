# Design: learned request frames

**Status:** implemented for the `select-then-procedure` goal. Chat uses request
frames as its only natural-language composition router; the regex compiler in
`crms_task_composition.py` remains as a reference path for parity tests.
**Date:** 2026-10-21

## Why

A regex per wording turns the harness into the composer. A request frame is a
small learned component that maps an exact token template with typed slots to a
goal. It can propose a task, but it never selects evidence, applies a procedure,
or decides an answer. Those remain independently checked plan steps.

## Records

Implemented in `crms_request_frames.py`:

| Record | Purpose |
|---|---|
| `FrameExample` | One marked utterance, goal, source id, optional fixed procedure |
| `RequestFrame` | A licensed literal/slot template and its examples |
| `FrameSlot` | A named, typed slot (`integer-list`, `claim`, `procedure`, `text`) |
| `FrameMatch` | One binding with typed slot values and a procedure-anchor flag |
| `RequestFrameStore` | Example persistence and deterministic frame derivation |

A frame is derived from examples, never stored as an independent fact. Deleting
or failing to license its examples removes it from service.

## Teaching syntax

```text
/teach-frame GOAL|UTTERANCE WITH {name:kind:filler} MARKERS|SOURCE ID[|FIXED PROCEDURE]
```

Example:

```text
/teach-frame select-then-procedure|Send {values:integer-list:1, 2} to {claim:claim:Mira reaches}.|lesson:frame:1|sum every value
```

A frame is licensed when it has:

1. at least two examples;
2. two distinct utterances;
3. at least one slot with two distinct fillers;
4. a source id on every example;
5. a valid filler for every slot kind (for example, an `integer-list` filler
   must parse as integers).

One example returns `need_more_examples`. The store persists examples; licensed
frames are re-derived on load.

## Matching

- Words and signed integers are tokens. Case, commas, brackets, semicolons, and
  most punctuation are boundaries and are ignored.
- A run of `.`, `!`, or `?` is a `<end>` token, so a sentence boundary can
  separate two slots.
- Literal tokens must match exactly. There is no synonym search and no partial
  frame match.
- `integer-list` accepts 1–32 signed integers separated by commas or `and`.
- `claim` rejects numeric spans, sequence connectives, and leading relative
  pronouns that belong to the template.
- `procedure` is anchored by the learned procedure vocabulary. When a template
  has adjacent procedure/claim slots, only a split whose procedure span is a
  learned phrase sequence can be selected. This is how generic forms such as
  `Among VALUES CLAIM PROCEDURE` are disambiguated without a regex.
- A match is accepted only if it consumes the full request, except that a final
  full stop is optional.
- Multiple semantically distinct matches are `ambiguous`; the planner is not
  run. No match returns `None`, so the caller abstains or uses another route.

## Composition

`compose_verified_filter_via_frames` performs:

```text
request text -> licensed frame + typed slots -> VerifiedFilterRequest
             -> select-verified-positive -> apply-learned-procedure
             -> independent step and plan checks -> answer or abstention
```

The frame id and template are recorded in the task plan provenance and on the
composition record (`request_frame_id`). Stored derived compositions also carry
the frame id; revalidation requires the same frame to still match, so removing
or changing a frame marks dependent artifacts stale. Unknown values, explicit
negatives, conflicts, untaught procedures, and tampered outputs are handled by
the same plan actions as the reference path.

## Seed curriculum

`crms_request_frames_seed.json` is packaged teacher data, not code:

- 40 marked examples license 20 `select-then-procedure` frames;
- it covers the explicit filter/procedure wordings, linked aggregate questions,
  method-first forms, and a few generic claim-first and list-first forms;
- the store defaults to `--rules` with a `_frames.json` suffix; pass
  `--request-frames PATH` to choose another file.

`/frames` lists licensed frames, templates, examples, and fixed procedures.

## Migration and limits

- Chat no longer calls the regex compiler for composition. It calls the frame
  route only.
- `compose_verified_filter` and `compose_verified_filter_via_plan` remain as
  reference paths for `v1_552` and direct diagnostics.
- Frames are not yet in the governed rule registry. The next integration should
  record frame lifecycle, validation, use counts, and retirement there.
- Only `select-then-procedure` is implemented. Other goals need their own typed
  actions and slot contracts.
- The seed file is a starting curriculum, not a claim of general paraphrase
  coverage. Unknown wording abstains until a frame is taught.
