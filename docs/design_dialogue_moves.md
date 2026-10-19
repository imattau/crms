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

## Initial corpus choice

Use **Taskmaster-1's two-person Wizard-of-Oz conversations** for the first pilot, limited to the
released task-service domains. The dataset release says it contains 13,215 conversations, including
5,507 two-person spoken dialogues, and is available under CC BY 4.0. Its documentation says the
provided annotations describe API arguments and transaction status, rather than conventional
dialogue-act labels. See the [Taskmaster-1 release documentation](https://github.com/google-research-datasets/Taskmaster/blob/master/TM-1-2019/README.md)
and [Taskmaster-1 paper](https://aclanthology.org/D19-1459/).

This is a practical corpus for testing greetings, acknowledgements, clarification, repair, and
closing in task-oriented exchanges, but it is not a direct sample of research-assistant or open-domain
conversation. The two-person assistant turns were produced by trained human operators, so this
measures task-service conventions rather than an existing automated assistant. Label assistant
turns for the initial move inventory and label user turns separately for dialogue act and contextual
task intent. Keep the two label types distinct. Split by complete conversation ID so no adjacent
turn leaks across train and holdout. Treat distinct dialogue IDs as independent conversations
**within this one collection**, not as independent publisher origins. Any claim that a move or intent
generalizes beyond this corpus needs replication in a second, separately collected dialogue corpus.
Preserve the dataset citation and CC BY attribution with every derived evaluation artifact.

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

Preparation command:

```text
python3 experiments/v1_363_prepare_taskmaster_dialogue_pilot.py \
  /path/to/woz-dialogs.json /path/to/new-output-directory
```

The tool writes one indexed text source per complete conversation,
`assistant_turns_to_label.csv`, and `user_turns_to_label.csv`. Both sheets include preceding turns,
blank human-label fields, separate second-rater and adjudication columns, SHA-256/character-offset
citations, and the original file digest, conversation ID, and utterance index. By default, it
indexes the complete corpus but samples 500 distinct conversations from the
`restaurant-table` domain for human annotation (`--annotation-domain` and
`--annotation-dialogues` can change this). It creates deterministic 80/10/10 splits by conversation
ID and refuses to overwrite an existing output directory. CRMS currently uses absolute paths as
file-ingestion document IDs, so moving a prepared directory means reindexing it and regenerating
citations.

The released Taskmaster-1 file has now been processed in a scratch directory outside the repository.
Of 5,507 records, 5,503 contained turns; four empty records were skipped, five extra records with
reused conversation IDs were retained under distinct transcript filenames, and 55 blank speaker
labels were preserved as `UNKNOWN`. The indexed set has 73,195 assistant utterances. The
restaurant-table annotation sample contains 500 distinct conversation IDs and 7,312 assistant
utterances plus 6,227 user utterances, split across 397 train, 49 dev, and 54 test conversations.
The deterministic 20% second-rater sample covers 101 complete conversations and 1,476 assistant
turns plus 1,234 user turns. Every user and assistant citation resolved through CRMS's normal
research-index API to the exact utterance. Labels remain blank: this is prepared evidence, not an
induced or evaluated dialogue model. The corpus has six domains; the other five are indexed for
future transfer work, not mixed into this first annotation study.

The proposed 500-transcript scale and 80% held-out target are hypotheses, not acceptance criteria
until corpus size, class balance, label agreement, and a scripted baseline are measured. In
particular, a high greeting match rate is not useful if the system greets during a factual answer or
uses the wrong domain convention.

Use [dialogue_move_annotation_protocol.md](dialogue_move_annotation_protocol.md) for the label
definitions, context coding, independent review, agreement reporting, and comparator evaluation.
The worksheet flags a deterministic 20% conversation-level reliability sample within each split
and leaves the second-rater and adjudication fields empty until an independent rater and adjudicator
complete them. An explicitly authorized AI pass has filled the primary fields of the 40-conversation
feasibility batch, but it is provisional and does not count as independent review; see the protocol
for its provenance and limits.
The separate [contextual user-intent design](design_user_intent_model.md) makes intent a first-class
research target distinct from assistant move realization. The pilot now includes user-turn
annotations because assistant-only labels cannot teach CRMS what users are trying to accomplish.

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
