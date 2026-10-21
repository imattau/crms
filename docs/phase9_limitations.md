# Phase 9 limitations and open gates

Phase 9 is an external-validation lane, not a claim that CRMS has reached the
full §2 capability contract. The published report separates what passed from
what did not.

## Human raters

The plan asks for two independent raters for evidence validity and answer
adequacy. This run used two independent hosted model instances:

- `opencode-go/claude-haiku-5-5`
- `opencode-go/glm-5.3-flash`

They rated blinded A/B responses, and their agreement is published. They are
not humans. The human-rater prerequisite therefore remains open, even though
the automated agreement panel is complete.

A human rater packet is available at
`experiments/reports/phase9_rater_packet.json`. To close the human gate, two
people who did not build CRMS should rate each of the 20 responses using the
packet's rubric, then record their ratings and agreement. Do not replace this
with another model run and call it human.

## 70B comparison

The qualitative baseline is `opencode-go/qwen3.8-max`, a hosted frontier-class
proxy. The provider does not disclose its parameter count. It is therefore
**not** a measured 70B model. The comparison is useful for gap direction and
product judgement, not for a parameter-matched benchmark claim.

A measured local 70B comparison would require a model checkpoint with a known
parameter count, a fixed quantization, a hardware profile, and published
generation settings. None of those is claimed here.

## Scorecard size and representativeness

The gated supported subset has 35 tasks. The independent breadth split has 12
literary probes. The plan's §2 target is roughly 300 ordinary tasks across ten
categories. Phase 9 does not meet that count.

The supported tasks are project-authored against a declared capability list.
They are not independent. The breadth probes are independently model-authored,
but 12 probes are not a representative sample of general requests.

The literary breadth result is 0/12. That is a real coverage result and must
not be hidden by quoting only the 35/35 supported subset.

## Corpus and licensing

The breadth corpus is four public-domain Project Gutenberg excerpts, not the
268k-document Phase 7 corpus. The supported subset uses six project-authored
fact sheets. Licence inventory is complete for these documents, but this is a
small validation corpus, not a broad web-scale distribution.

The Phase 8 release remains a compact fixture. Full Phase 7 corpus packaging is
still a follow-up.

## Performance and scale

The supported subset ran with median 0.26 s and p95 0.30 s per task. These are
short chat tasks with small indexes. The §2 target of p95 <2 s at 1M facts and
a 2 GB index is **not measured** by Phase 9.

## Metrics not collapsed

The report keeps supported completion, breadth completion, unsafe answers,
rater agreement, comparison means, and failure taxonomy separate. It does not
publish a single “CRMS score.” A single score would conceal the 0/12 breadth
result and the human-rater gap.

## What would close the full gate

1. Recruit two humans who did not build CRMS; run the frozen rater packet and
   publish agreement.
2. Expand the externally authored suite to roughly 300 ordinary tasks across
   ten categories, with a source-disjoint held-out split.
3. Run a measured 70B model with disclosed checkpoint, quantization, hardware,
   and generation settings.
4. Measure p95 at 1M facts and a 2 GB index.
5. Publish the resulting scorecard, failure taxonomy, licence inventory, and
   this limitations file together.
