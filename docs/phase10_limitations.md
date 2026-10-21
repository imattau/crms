# Phase 10 limitations and open gates

Phase 10 has a completed bounded lane and an open full external gate. The
aggregate report is `experiments/reports/phase10_external.json`.

## Human raters

The comparison and clarity panel used two hosted model instances:

- `opencode-go/claude-haiku-5-5`
- `opencode-go/glm-5.3-flash`

They are not humans. Agreement was weak on clarity (kappa 0.0) and coverage
(kappa -0.07), and moderate on adequacy (kappa 0.32) and confident error (kappa
0.57). The human clarity/comprehension gate remains open.

## 70B comparison

The baseline is `opencode-go/qwen3.8-max`, a hosted 70B-class proxy whose
parameter count is not disclosed. It is not a measured 70B checkpoint with a
published quantization and hardware profile. The comparison is directional, not
a parity claim.

## Suite size and provenance

The bounded suite has 12 frozen cases covering all ten declared genres plus
abstention and clarification. It is project-authored. The plan's full gate asks
for an independently authored 300-prompt suite over two source-disjoint
corpora; that suite does not exist yet.

## Input representation

Generation accepts structured propositions. General source-to-proposition
extraction from arbitrary documents is not connected. `/compose PATH` in chat
takes a structured JSON request; it is not a natural-language route over an
arbitrary indexed document.

## Clarity

Clarity is checked by sentence-length and jargon heuristics plus automated
raters. It is not yet measured by reader comprehension questions or recall. The
plain-language research summarised in the design shows readability alone is
insufficient.

## Generalisation

`crms_generalisation.py` provides class hierarchy, back-off, report-only
analogical candidates, evidence-count weights, and a small fact-coverage curve.
The full 10^2–10^5 rule-scaling curve and per-mechanism ablations are not
measured. The design's scaling hypothesis remains a research programme.

## Content and style

Outputs are clear, structured, and source-grounded, but still more list-like and
less fluid than the comparison proxy, especially for narrative and open-ended
professional writing. Long-form coherence, humour, irony, literary voice, and
genuine novel insight remain hard targets.

## What would close the full gate

1. Recruit two humans who did not build CRMS; run blinded clarity/comprehension
   ratings and publish agreement.
2. Author or commission 300 independent prompts over two source-disjoint
   corpora, with a frozen holdout.
3. Run a measured 70B checkpoint with disclosed parameters, quantization,
   hardware, and generation settings.
4. Publish the full rule-scaling curve and per-mechanism ablations.
5. Connect bounded source-to-proposition extraction and a natural-language chat
   route.
