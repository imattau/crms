# Phase 9 external validation and release

**Status:** bounded external-validation lane completed 2026-10-21. The full
section 2 gate and the human-rater gate remain open.
**Code:** `run_phase9_eval.py`.
**Fixture:** `corpus/phase9_eval/fixture.json` (content digest locked).
**Report:** `experiments/reports/phase9_external.json`.
**Scorecard:** `docs/phase9_scorecard.md`.
**Rater packet:** `experiments/reports/phase9_rater_packet.json`.
**Raw outputs:** `experiments/reports/phase9_outputs.json`.

## What Phase 9 adds

Phase 8 proved that a copied release can answer and be inspected. Phase 9 asks
a harder question: what happens when the requests were not written against the
implementation's known shapes?

The lane therefore has three separate measurements:

1. a **gated supported-subset scorecard** covering research, paraphrase,
   compound completion, continuity, reload, abstention, math, units, coding,
   translation, and creative writing;
2. **independent-model-authored literary breadth probes** over four public-domain
   Project Gutenberg excerpts, published as failures rather than tuned into the
   supported subset;
3. a **blind qualitative comparison** against a hosted 70B-class proxy on ten
   probes.

The supported subset is project-authored. The breadth probes are authored by
`opencode-go/qwen3.8-flash` from the source excerpts and a schema-only request;
the prompt digest is recorded in the fixture. The author saw no CRMS code,
fixture, or expected output. This is independent model authorship, not human
authorship.

## Frozen split

`corpus/phase9_eval/fixture.json` is locked by
`corpus/phase9_eval/fixture.sha256`. It contains:

- 35 supported-subset tasks;
- 12 independent-model-authored literary breadth tasks;
- 10 comparison probes;
- a source directory with four public-domain Gutenberg excerpts and six
  project-authored fact sheets.

The supported tasks are not used to tune the breadth tasks. The breadth tasks
were run once through the frozen chat CLI and their failures are in the report.
The fixture is synthetic in the sense that its fact sheets are short, but the
literary sources are real public-domain excerpts with attribution.

## Supported-subset result

| Measure | Result |
|---|---:|
| Tasks | 35 |
| Passed | **35/35** |
| Completion | **100%** |
| Unsafe answers | **0** |
| Median task | 0.27 s |
| p95 task | 0.38 s |

Coverage by category:

- research: direct cited questions, SQLite retrieval, evidence follow-up;
- paraphrase: same fact, different wording;
- compound: two-part questions;
- continuity: question history;
- reload: answer after process restart;
- abstention: absent entities and unsupported math;
- math and units: learned exact arithmetic and conversion;
- coding: bounded Python generated from learned list procedures;
- translation: learned aligned translation frames;
- creative: bounded fictional stories.

These tasks are deliberately inside the declared supported class. They are not
a claim that ordinary open-ended requests pass.

## Independent breadth result

| Measure | Result |
|---|---:|
| Tasks | 12 |
| Passed | **0/12** |
| Completion | **0%** |
| Unsafe answers | **1** |
| Median task | 0.29 s |
| p95 task | 0.33 s |

The failures are the useful Phase 9 result. They cluster into:

- **literary entity and relation grounding:** questions that require a
  multi-sentence interpretation, a character action, or an entity not in the
  subject position are refused or miss the target;
- **exact evidence expectations:** 10 tasks fail because the expected quote or
  required content is absent even when the system finds related text;
- **out-of-excerpt abstention:** one Frankenstein question about the creature's
  first days is answered with unrelated quoted evidence instead of abstaining;
- **compound literary questions:** decomposition runs, but the parts lack
  grounded answers.

See `docs/phase9_failure_taxonomy.md` for the detailed taxonomy.

## Blind 70B comparison

The comparison uses ten probes across breadth, paraphrase, compound completion,
continuity, repair, coding, math, research, translation, and creative writing.

The baseline is `opencode-go/qwen3.8-max`, recorded as a **hosted 70B-class
proxy**. The provider does not disclose parameter count, so this is not a
measured 70B model. Both systems receive the same prompts; responses are
anonymised as A/B and rated by two independent hosted model instances:

- `opencode-go/claude-haiku-5-5`
- `opencode-go/glm-5.3-flash`

The raters are not humans. Their ratings are useful as a blind, external
signal, but they cannot satisfy the plan's human-rater requirement. The packet
and instructions for two human raters are in
`experiments/reports/phase9_rater_packet.json` and
`docs/phase9_rater_protocol.md`.

| Rated system | Mean adequacy | Mean evidence validity | Confident errors |
|---|---:|---:|---:|
| CRMS | 1.20 | 1.80 | 4 |
| 70B-class proxy | 2.00 | 1.80 | 1 |

Interpretation: the proxy is clearly better on open-ended breadth, repair, and
literary research. CRMS is competitive on bounded math, translation, compound
questions, and cited short-source answers. The result is a gap analysis, not a
parity claim.

Rater agreement over 20 rated responses:

| Dimension | Exact agreement | Cohen's kappa |
|---|---:|---:|
| Answer adequacy | 0.90 | 0.75 |
| Evidence validity | 0.85 | 0.51 |
| Confident error | 0.95 | 0.77 |

Evidence validity is the weak agreement point. Raters disagreed about whether
an answer that abstains but shows a closest sentence has valid evidence. That
disagreement is published rather than adjudicated away.

## Licence inventory

`corpus/phase9_eval/licence_inventory.json` records each source:

- four Project Gutenberg excerpts (Alice, Frankenstein, Moby-Dick, Sherlock
  Holmes), public domain in the United States, with URL, edition, attribution,
  retrieval date, revision, and body SHA-256;
- six project-authored fact sheets used only for the supported subset.

All source documents have a documented licence class and content digest. The
Gutenberg excerpts are excerpts, not full redistributions; the inventory keeps
the source URL and edition so a reader can verify the text. Human-readable
summary: `docs/phase9_licence_inventory.md`.

## Reproduce

```sh
python3 run_phase9_eval.py
python3 run_phase9_eval.py --skip-baseline --skip-raters
python3 experiments/v1_565_phase9_external.py
```

The full run calls the hosted baseline and two hosted raters. It is therefore
network-dependent and not deterministic in wording; the frozen fixture, raw
outputs, rater packet, and agreement report are kept for audit.

## Gate status

The bounded machine-checkable gate passes:

- supported completion at least 80%: **yes** (100%);
- zero confident wrong supported answers: **yes**;
- breadth failures published: **yes**;
- two raters attempted and agreement reported: **yes**;
- comparison reported: **yes**;
- licence inventory published: **yes**;
- limitations published: **yes**.

The full external gate does **not** pass:

- the raters are automated model instances, not two independent humans;
- the comparison baseline is a hosted proxy with undisclosed parameter count,
  not a measured 70B model;
- the suite is 35 supported tasks plus 12 breadth probes, not ~300 ordinary
  tasks across ten categories;
- p95 at 1M facts and a 2 GB index is unmeasured.

Those are recorded in `docs/phase9_limitations.md` and in the report's
`section2` block.
