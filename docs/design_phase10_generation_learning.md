# Phase 10 grounded generation and LLM-supervised learning

**Status:** planned 2026-10-21. Prototype evidence exists; the gate is open.
**Plan entry:** `docs/master_plan_to_final_state.md`, Phase 10.
**Committed so far:** `c8f8ef7` on branch `exam-fixes` (WHERE evidence gate and
a bare "Where is X?" exact-title route). Not merged.
**Prototype (not in the repository):** composer, frame learner, quality judge,
conversation miner, SQL store, and regression gate, kept in the working
session's scratchpad. Moving them in is Phase 10 work.

## What Phase 10 adds

Phase 9 showed two things: CRMS passes its own supported subset, and it fails
independently authored breadth. The prototype shows why part of that failure is
structural. A retrieved sentence cannot be a direct answer to "Is X in Y?", cannot
fuse an infobox fact with a lead sentence, and cannot shorten a nested place
chain. It also showed that an external LLM, used as an examiner, finds the
specific rule or code defects behind failures faster than reading fixtures.

Phase 10 does two linked things:

1. **Grounded generation.** Compose short answers from cited facts. Never
   produce a clause that is not recoverable from a source span.
2. **LLM-supervised learning.** Use an external LLM as an offline examiner,
   judge, and proposer. CRMS accepts or rejects every proposal with its own exact
   checks. The LLM is not part of the shipped model.

## Decision amendment

Master plan decision 2 allows small learned components to *propose*. This phase
extends it to an external offline LLM teacher with these limits:

- it never runs at answer time and the packaged model has no LLM or network
  dependency;
- it is never the source of a fact;
- it never accepts its own proposal, and the proposing model is not the only
  judge of that proposal;
- every interaction records model id, prompt digest, and the artifact produced;
- human review remains the final step for code.

This needs owner sign-off before implementation starts.

## 1. Grounded composer

Pipeline: collect facts, plan, realise, verify.

**Fact collection.** A `FactSource` interface returns facts with text, a source
span, and a tier:

| Tier | Source | Label in the answer |
|---|---|---|
| accepted | taught or review-accepted facts | stated as fact, with citation |
| reviewed candidate | reviewed but not accepted claims | "the source says", not an accepted fact |
| raw | source sentence or structured field (infobox, dates) | quoted evidence |

Conflicting facts are reported as a conflict, not resolved silently. A fact with
no resolvable span is not eligible.

**Planning.** Rules, not code, decide which facts answer the question, their
order, what to trim, and what to add. Prototype knobs: place-chain style
(`full`, `region_country`, `levels_comma`), whether to bail out on irregular
tails, which extras to append (population with date), clause-cut markers with a
minimum-removed-length and a generic-head guard for definitions, and date style.

**Realisation.** Learned templates plus deterministic fixups: verb agreement,
a/an, month-abbreviation expansion, digit grouping.

**Question classes, in order:** place; definition; person and birth/death;
active and passive relations ("who wrote", "made by"); polar; multi-fact list;
short explanation.

## 2. Answer verifier

For each clause, every capitalised word and number in the output must be in the
clause's cited source or the entity name. The template vocabulary is a closed
list. A failing clause removes the answer and the system falls back to the quote
or abstains. The prototype verifier caught several template bugs at learn time
and produced zero unfaithful answers in the measured sets.

## 3. Composition memory in SQL

Composition rules are data in SQLite, not JSON. Conventions follow the existing
CRMS stores (application id, `user_version`, `WITHOUT ROWID`, one transaction
per change).

| Table | Holds |
|---|---|
| `comp_rule_version` | Rule values by scope/name with version, origin (seed, llm, conversation, human), rationale, status, change reference. `comp_rule` view gives current accepted values. |
| `comp_pattern` | Question wordings by class, priority order, origin, and the example that taught them. |
| `comp_lexicon` | Verb forms. |
| `comp_triple` | Labelled training examples by round. |
| `comp_frame_stat` | Good/bad counts per learned frame, kept across runs. |
| `comp_judgment` | Quality scores and a separate human verdict. |
| `comp_change` | Audit trail across three tiers (data, rule, code), with before/after score, accepted flag, and a reference such as a commit. |

Composition rules also register in `crms_rule_registry.py` as a `composition`
family so they share lifecycle, utility counts, and contest/retire/rollback.

## 4. Examiner loop

```
generate questions from passages (gold from spans)
  → CRMS answers through the real chat
  → teacher scores correctness and quality, tags a cause
  → group failures by cause
  → propose the lowest-tier fix: data → rule → code
  → CRMS verifies; keep only if quality rises, faithfulness holds,
    and no control regresses
  → record in comp_change
```

**Rubric.** Faithful (hard gate), direct, grammatical, concise, informative.
Each judgment stores a one-line cause.

**Acceptance for a rule change.** Mean quality up on a fixed answer set;
faithfulness unchanged at 1.0; no item worse by more than one point; frozen
controls unchanged. The prototype accepted two rule rounds this way and caught a
bad region-and-country style on the blind set.

**Judge validity.** Teacher scores are compared with human grades on at least
100 answers and agreement is published. The proposing model and the judging
model differ, or a human-graded slice decides acceptance. A blind set is never
used for tuning; once used, it becomes tuning data and a new set is written.

## 5. Reinforcement signal

No gradient training, no neural policy. Rewards update per-rule utility:

| Signal | Source |
|---|---|
| positive | citation resolves and the evidence gate passes; user `/right`; user accepts without rephrasing |
| negative | `/wrong`; correction; answer verifier or round-trip replay fails |
| diagnostic | rephrase-after-failure (a new wording of the same question that worked) |

Selection among rule variants is bandit-style. A wrong answer costs more than an
unnecessary abstention, and abstention is counted so refusing is not a winning
policy. A frame or rule whose bad count outweighs its good count is disabled
automatically and the change is logged.

## 6. Conversation learning

Local, opt-in. Sources: the feedback ledger (`/right`, `/wrong`), dialogue
state, and transcripts.

- verdicts become rule utility;
- rephrase-after-failure sessions yield question-pattern proposals, applied only
  if the pattern recovers the entity and reproduces the confirmed answer;
- corrections become scoped negative examples and triples for teacher review;
- redaction, retention, and export rules are specified before any transcript is
  stored.

The prototype's five accepted patterns came from simulated sessions because the
ledger is empty.

## 7. Code-patch tier

The teacher may propose a code patch only when a failure is a code defect. The
patch lives on a branch in its own worktree and must pass:

1. the targeted experiments for the area;
2. the full suite, run in parallel shards on the candidate and on an unmodified
   baseline, with zero new failures (`run_regress.py`);
3. the examiner non-regression check;
4. human review.

No automatic merge. In the prototype this gate caught three regressions from the
first version of `c8f8ef7` (an over-strict fragment filter and a route that
blocked the fallback) before the fix was committed.

## Measurements and controls

- Report answered/correct/wrong/abstained and the quality rubric separately; do
  not collapse them.
- Report copy ratio (share of an answer covered by one verbatim source run) to
  show how much is composed.
- Keep every fixed failure as a permanent control.
- Keep a human-graded slice, a private rotating holdout, and authored/teacher/
  independent provenance labels (§8 of the master plan).
- Report teacher calls and human minutes per round.

## Prototype evidence (not a gate)

| Measure | Result |
|---|---|
| Held-out set, 54 answerable | 21 correct before fixes, 33 after the gate and where-route fixes, 48 with composer and learned frames; 6 abstained |
| Unanswerable controls | 0 hallucinations across 62 |
| Teacher-judged quality, 24 answers | concision 3.83→4.21, informativeness 3.38→3.79, faithfulness 1.0; one item slightly worse |
| Composed answers, blind place set | mean copy ratio 0.8; 29 of 60 not verbatim |
| First blind run | 17 answers less specific than required and 2 corrupted tails, fixed in rules; the set is now tuning data |
| Mined patterns | 5 accepted from simulated sessions; all resolved unseen entities |
| Regression | zero new failures across 549 experiments for `c8f8ef7`; 116 failures exist in both checkouts (mostly missing data in the worktree) |
| SQL rules | answers on 162 held-out questions identical to the JSON version |

## Known limits

- The teacher was also the editor, and was not calibrated against human grading.
- Conversation sessions were simulated.
- Grading used gold keywords plus reading; some correct answers are more or less
  specific than the keyword.
- The corpus is place-heavy; definitions, persons, and relations are thin.
- The prototype is outside the repository; `exam-fixes` is unmerged.
- A fresh blind set (v4) and a human-graded calibration slice are required before
  any capability claim.

## Open decisions

1. Sign off the teacher decision amendment.
2. Store composition memory inside the learned model file or beside it.
3. Which model is the judge and which is the proposer.
4. Transcript storage policy for conversation learning.
