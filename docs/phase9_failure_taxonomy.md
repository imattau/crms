# Phase 9 failure taxonomy

Source: `experiments/reports/phase9_external.json`.
The supported subset passed 35/35. The 12 independent literary breadth probes
failed 0/12. One breadth failure was unsafe because an out-of-excerpt question
received a confident but unrelated answer.

## A. Literary entity and relation grounding

**Count:** 8 of 12 breadth probes.

The system can retrieve a related sentence but cannot establish the asked
relation. Examples:

- “What does Alice see the White Rabbit take out of its waistcoat-pocket?” —
  CRMS finds the rabbit sentence but does not bind the watch to the requested
  event.
- “Where did Sherlock Holmes live?” — CRMS finds “Baker Street” but rejects the
  sentence because the location is not the located subject.
- “How does Elizabeth Lavenza come to live with Victor's family?” — the answer
  needs the Milanese nobleman, the foster family, the priest, and the mother's
  permission; CRMS will not assemble that chain from loose evidence.

Cause: the research route is a sentence-selection and exact-grounding path, not
a general multi-sentence reader. It prefers abstention to an unsupported
paraphrase.

## B. Exact citation or required-content mismatch

**Count:** 10 of 12 breadth probes (overlapping with A).

The independent author wrote exact quote checks. CRMS often abstains or returns
a different sentence, so the quote and required phrase are absent. This is not
a false citation; it is a coverage failure surfaced by a strict oracle.

Cause: the author asked questions that require a specific passage, while the
current route selects one sentence and requires a direct predicate match.

## C. Confident answer where abstention required

**Count:** 1 of 12.

`frankenstein-creature-account` asks how the creature describes his first days.
The excerpt does not contain that account. CRMS answered with an unrelated
quoted sentence about Elizabeth instead of abstaining.

Cause: a topical word match passed the retrieval threshold without an
entity/relation check. This is the most serious breadth failure and is kept as a
permanent control.

## D. Compound and continuation decomposition

**Count:** 2 of 12.

The compound route correctly emits `Part 1 of 2` and `Part 2 of 2`, but the
parts can fail independently. `who-fell-down-where` processed three parts and
then missed the literary referents. `daisy-chain-followup` found the right
paragraph but could not bind “what Alice is doing” to the daisy-chain clause.

Cause: decomposition is working; the downstream grounded answer is not.

## E. Open-ended breadth (comparison probe)

**Count:** 1 of 10 comparison probes.

“Explain in three sentences why the sky appears blue.” CRMS abstains because it
has no source and no learned explanation. The 70B-class proxy answers with
Rayleigh scattering.

Cause: CRMS is evidence-first and does not generate general world knowledge.
This is a deliberate contract, but it is a user-experience gap against a
general assistant.

## F. Repair not applied (comparison probe)

**Count:** 1 of 10.

Conversation: “Who created Python?” → “I meant Linux.” CRMS answers the first
question again and adds quoted evidence; the proxy answers Linux.

Cause: the dialogue repair path handles selected entity substitutions, but this
probe's replacement changes the subject/object roles and the route falls back
to the previous evidence instead of asking a focused clarification.

## G. Literary research vs. proxy (comparison probe)

**Count:** 1 of 10.

“Where did Sherlock Holmes live?” CRMS abstains; the proxy answers Baker
Street. This is a real retrieval/interpretation gap, not a safety failure.

## H. Coding presentation

The supported coding task passes, but the comparison transcript includes
clarification lines before the generated artifact. The code is correct and
inspectable; the presentation is noisier than the proxy's direct function.

Cause: the procedure learner asks for disambiguating examples when several
list transformations fit. The final artifact is gated by parity checks; the
intermediate dialogue is not suppressed.

## I. Rater disagreement

Raters agreed on answer adequacy (0.90 exact, kappa 0.75) and confident-error
classification (0.95 exact, kappa 0.77), and had moderate evidence-validity
agreement (0.85 exact, kappa 0.51). The disputed cases were mostly abstentions with a “closest
source sentence” shown: one rater treated the shown evidence as valid
transparency, the other treated it as irrelevant to the requested answer.

This is why Phase 9 reports agreement instead of collapsing to a single score,
and why the human-rater gate stays open.
