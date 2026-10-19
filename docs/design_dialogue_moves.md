# Research direction: explicit dialogue moves

**Status:** research proposal; no dialogue-move induction or move store is implemented.
**Relationship to** [design_conversation.md](design_conversation.md): that document describes the
conversation layer and its current baseline. Dialogue is an active research priority alongside
recombination, self-learning rules, and reasoning; this note records the auditable move-learning
track, which remains unimplemented.

## Claim

CRMS could model scoped conversational behavior as licensed moves rather than adding a growing set
of hand-written social scripts. A move is not a fact about the world. It is a proposed action whose
use is licensed by explicit, inspectable dialogue context.

A move record needs at least:

| Field | Example |
|---|---|
| Move class | `greet`, `acknowledge`, `clarify-request`, `repair`, `confirm`, `close` |
| Context conditions | Opening turn; unresolved ambiguity exists |
| Predecessor condition | A prior inform; a question awaiting an answer |
| Realization frame | `Sorry, did you mean {option1} or {option2}?` |
| Evidence and label provenance | Utterance citation, source document, labeler, review state |

Context and predecessor checks should be deterministic predicates over a bounded discourse-state
record. The existing `CRMSDialogue` state is oriented around question repair and referents; it is not
yet a general discourse-state model. Keep the first state small and typed (turn position, open
question or clarification, last move, current intent, and named referents). Add fields only when an
experiment shows a specific move cannot be expressed.

## What corpus evidence can establish

Dialogue corpora can support claims about observed forms and transitions, with utterance-level
citations and source independence. They do **not**, by themselves, establish that a move is
appropriate for CRMS's users or product. A greeting in a support transcript may be inappropriate in
a research tool; a movie subtitle is especially poor evidence for a service tone. Corpus/domain
selection is therefore an explicit product policy, and labels need review because “acknowledge” vs
“confirm” is not reliably settled by source text alone.

Keep these distinct:

1. **Usage evidence:** this wording or move occurred in the cited context.
2. **Context license:** the explicit state and predecessor conditions hold now.
3. **Policy approval:** the selected domain, corpus, tone, and move are acceptable for this product.

Holdout and cross-source gates can test generalization and reduce memorization. They cannot validate
the labeler's interpretation or choose the right corpus. Record label provenance and require human
review of a sample before treating induced frames as licensed. A model may propose labels, but its
proposals are not independent validation of those labels.

## Sequence modeling

Moves occur in exchanges, not isolation. For an initial experiment, prefer explicit sequence
templates over learned transition probabilities: for example,
`clarify-request -> user-restatement -> acknowledge`. This reuses CRMS's symbolic sequence-learning
direction and avoids assigning meaning to a probability threshold before its calibration is known.
Keep context predicates separate from learned surface frames. A frame can be well supported in a
corpus and still be wrong to use in the current state.

## Bounded experiment

The current baseline is sufficient to begin a dialogue pilot: content-free turns avoid retrieval,
source-only names can be retained as referents across a restart after citation revalidation, and
ambiguous follow-ups request a named choice. The pilot should build on that measured baseline rather
than wait for a complete conversation architecture. Keep it scoped so it can reveal whether learned
moves add value over the current explicit handlers.

- Choose one bounded domain and a licensed, documented corpus; do not mix subtitles, forums, and
  support transcripts as if they represented one policy.
- Start with four move classes: greet, acknowledge, clarify-request, and close.
- Have a human label examples and retain exact source/utterance citations. If automated labeling is
  used to scale proposals, audit a sample against independently labeled examples.
- Split train and holdout by source document, not utterance, to avoid leakage between adjacent turns.
- Learn realization frames and, separately, a small set of move-sequence templates. Context
  conditions remain explicit and reviewed.
- Compare with a scripted baseline on the same held-out conversations. Measure appropriate-move
  accuracy, unsupported/inappropriate move rate, abstention, frame coverage, source diversity, and
  teacher/reviewer time. Do not score surface similarity as conversational correctness.

The proposed 500-transcript scale and 80% held-out target are hypotheses, not acceptance criteria
until corpus size, class balance, label agreement, and a scripted baseline are measured. In
particular, a high greeting match rate is not useful if the system greets during a factual answer or
uses the wrong domain convention.

**Stop or narrow the work** if induced frames do not outperform or materially simplify the scripted
baseline, if acceptable coverage requires prohibitive annotation, if labels have poor agreement, or
if the context rules cannot reliably prevent inappropriate moves. A scoped dialogue assistant could
still be valuable without claiming to support open conversation.

## Relationship to an LLM surface

This path optimizes auditability and bounded behavior; it will have lower open-ended fluency and
coverage than a large language model. An LLM-rendered conversational surface is a separate product
option, not a hidden dependency of this research. A hybrid could use a model for low-stakes social
phrasing while CRMS controls claims, evidence, and licensed actions. If explored, the boundary must
be explicit: generated wording cannot upgrade a claim's evidence status or override CRMS's
abstention.

## Current implementation boundary

CRMS has a small set of explicit conversation handlers and typed evidence/referent behavior; these
are useful baselines, not examples of corpus-induced dialogue moves. Source-quoted names retained by
the dialogue layer are candidate referents only and are not accepted facts. They persist only when
their citation resolves against the currently loaded index. A follow-up must still be supported by
the existing answer path or lead to a clarification request. The immediate research step is to
compare this baseline with human-labeled, source-disjoint move frames in one explicitly selected
domain, then decide from coverage, appropriateness, abstention, and annotation cost whether Path B
deserves further implementation.
