# Dialogue move annotation protocol

**Status:** protocol for the Taskmaster-1 restaurant-table pilot. It does not assert that move
learning is implemented. The corpus and preparation workflow are described in
[design_dialogue_moves.md](design_dialogue_moves.md).

## Unit and evidence

Annotate one assistant utterance at a time. Read the complete conversation when available; at
minimum, use the preceding context in the worksheet. Choose the move that best describes what the
utterance does in that context, not a word or phrase it happens to contain. Preserve the utterance
and its source citation exactly. Do not infer unstated intentions or whether the assistant's factual
content is true.

Each label must be grounded in the cited assistant turn and its conversational context. The
conversation is the split unit: all turns from one `conversation_id` belong to the same train, dev,
or test partition. The repeated-ID records in the release intentionally share a partition.

## Primary move labels

Use one primary label per assistant utterance. If a turn performs two actions, choose the action
that most changes what should happen next; note the secondary action in `annotator_note` if needed.

| Label | Apply when | Do not apply when |
|---|---|---|
| `greet` | Opens contact or returns a greeting. | A greeting is only quoted or discussed. |
| `acknowledge` | Signals receipt or understanding without adding a task constraint or completing an action. | It repeats a material detail to verify it (`confirm`) or closes the exchange (`close`). |
| `clarify-request` | Requests information needed to resolve missing or ambiguous task input. | It asks an optional follow-up after the task is already complete. |
| `repair` | Addresses a prior misunderstanding or error and corrects, retracts, or replaces the earlier contribution. | It simply asks for missing information (`clarify-request`) or confirms a detail. |
| `confirm` | Checks or restates a material user-provided detail for agreement before proceeding. | It merely says “okay” or acknowledges receipt. |
| `close` | Signals the interaction or task is complete and invites no further required input. | It says “thanks” while continuing the task. |
| `other-task` | Answers a content question, gives task information, performs a requested action, or advances the task without one of the moves above. | The turn is a clear social move in the table above. |
| `other-social` | Social or conversational content outside the target move classes. | The utterance is too unclear to classify; use `uncertain` instead. |
| `uncertain` | Context is insufficient, the turn is incomplete, or two labels remain equally plausible after applying these rules. | There is merely an unfamiliar phrase whose function is still clear. |

The initial target classes are `greet`, `acknowledge`, `clarify-request`, and `close`.
`repair` and `confirm` are kept as exploratory classes because they are central to conversational
competence and explicit feedback. The remaining labels are necessary controls: they prevent
ordinary task answers from being silently treated as negative examples of social moves.

## Context annotations

Fill the context fields independently from the primary label; do not infer a context condition from
the move label alone.

`context_license` uses one or more of:

- `opening`: first assistant turn in the conversation;
- `reply-to-greeting`: preceding user turn greets the assistant;
- `user-provided-detail`: preceding user turn supplies information or responds to a question;
- `missing-detail`: a required value has not been supplied;
- `ambiguous-detail`: multiple interpretations remain live;
- `prior-error-or-correction`: the user or assistant identifies a previous contribution as wrong;
- `task-complete`: no required task input or action remains;
- `none-obvious`: none of the above is supported by the local context;
- `uncertain`: context is unavailable or too unclear to decide.

Separate multiple values with `;`. `predecessor_label` records the immediately preceding speaker
and move when it can be determined: `user-question`, `user-answer`, `user-correction`,
`user-greeting`, `assistant-question`, `assistant-answer`, `assistant-other`, `conversation-start`,
or `uncertain`. These are observations, not claims that the move is appropriate.

## Annotation and review procedure

1. Use the CSV's `split` field; never move a conversation between partitions after seeing model
   results.
2. Annotators work independently and do not see CRMS predictions or one another's labels.
3. Double-label at least 20% of conversation IDs within each split. The preparation tool marks a
   deterministic sample in `double_label_required`; label every assistant turn from those
   conversations independently with a second annotator. Keep both original labels and the
   adjudicated value. This selects whole conversations, so no context is divided between the audit
   pool and single-rater pool.
4. Report raw agreement and a chance-adjusted measure (Krippendorff's alpha for nominal labels, or
   Cohen's kappa for exactly two raters), the confusion matrix, class counts, and the fraction marked
   `uncertain`. Do not merge classes solely to raise agreement; document any taxonomy change and
   relabel the affected material.
5. Keep label provenance: annotator identifier, timestamp, protocol version, original label,
   adjudicated label, and citation. Automated proposals may prioritize review but are never gold
   labels and must remain distinguishable from human judgments.

The prepared sheet has 7,312 assistant-turn rows, so labeling every row is a substantial effort.
Begin with a feasibility batch drawn from the existing train partition and its double-label audit.
Check class coverage, disagreement, and annotation time before expanding. Keep dev and test sealed
from frame induction and policy tuning. If a target class has too few independently supported
examples, report it as underpowered rather than borrowing turns across the split.

The worksheet stores the first label in `move_label`, `context_license`, `predecessor_label`, and
`reviewer`. For rows marked `double_label_required=true`, a second annotator fills the corresponding
`*_2` columns and `reviewer_2`. After independent labels are locked, an adjudicator fills
`adjudicated_label` and `adjudicator`; record explanations in `annotator_note`. Do not overwrite a
disagreement with the adjudicated result.

## Evaluation against dialogue comparators

Evaluate the current deterministic CRMS handlers first, then any induced move model, on the same
conversation-held-out examples. A strong instruction model may be run as a capability comparator
with a fixed prompt and the same visible context; its output is not a label source or factual oracle.
Annotators should be blind to system identity when judging outputs.

Report per-class precision and recall, macro-F1, abstention, inappropriate-move rate, task progress,
and evidence/provenance violations. For the latter, count unsupported claims separately from
conversational quality. Also report performance by context license and error type. Overall accuracy
alone is misleading because most turns may be ordinary task content.

A learned dialogue policy is a meaningful improvement only if it improves held-out appropriate
behavior over the current scripted baseline without increasing inappropriate moves or weakening
CRMS's evidence and abstention rules. Performance on Taskmaster supports a task-service claim only;
general dialogue claims require an independently collected second corpus.
