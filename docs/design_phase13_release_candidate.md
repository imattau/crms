# Phase 13 release candidate: a pre-trained CRMS a user can run at once

**Status:** planned 2026-10-22; not started.
**Plan entry:** `docs/master_plan_to_final_state.md`, Phase 13.
**Builds on:** Phase 11 (pattern layer, SQL pattern memory, spec verifier) and Phase 12
(independent evaluation, teacher loop, abstention gate, route-first wiring).

## Decision recorded

The project owner's direction (2026-10-22): the pattern, teacher, and generation work
exists to produce a **pre-trained CRMS**, a packaged model an end user installs and uses
immediately, the way an LLM is pre-trained before use. Offline LLM sessions do the
supervision; the user's own conversations may refine it afterwards. A change that helps
only an evaluation harness does not count.

## Where Phase 12 left it (model-validated)

| Measure | Result |
|---|---|
| Independent set (320 questions), unchanged chat | 55 correct, 44 wrong, 221 abstain; 14 of 48 unanswerable questions answered |
| Same set, gated chat | 51 / 29 / 240; 6 unanswerable answered; 4 correct lost net (target ≤5% missed by 2 points) |
| Fresh blind set C (240), unchanged chat | 19 correct, 37 wrong, 184 abstain |
| Fresh blind set C, gated chat (one run) | 19 / 18 / 203; wrong share of answered 49%; unanswerable answered 2; no correct answer lost |
| Teacher loop, four rounds | 23 distinct proposals, 6 accepted, 2 kept; dev split 1 to 3 correct; about one spec per round |
| Why / how / list / yes-no | Span patterns cannot produce these answers (teacher reports) |

Two facts set the order of work. Half the answers a first-run user would see are still
wrong, and the system answers only about 8% of answerable questions. Safety and coverage
both have to move, and refusal alone cannot do it.

## Principles

1. Safe by default before broad. The reward rule (+1, −3, 0) applies; coverage does not
   buy a higher wrong share.
2. Only what the shipped chat route calls counts.
3. A blind set is single use. Every gate step gets a fresh LLM-authored set from unseen
   passages. Development uses the training set, the oracle samples, and loop data.
4. The deterministic verifier decides. Hand-written, induced, and teacher-proposed rules
   all pass the same gate.
5. Everything ships as data in the packaged model, with versions and one-step rollback.

## A. First-run answer quality

Characterise first, on development data only: bucket the wrong answers that pass the
gate (the 18 on set C are spent, so use the training set and oracle samples) into
selection errors (a sentence about another page, a pronoun-led sentence about something
else), responsiveness errors (related but not answering), span errors (truncated or
extended answer), and conflicts.

Changes, each a data or rule change with a measured effect:
- **Answer-bearing selection.** Rank retrieved sentences by coverage of the question's
  content terms, answer-type fit, entity-on-own-page, and the Phase 11 ranker features;
  keep the weights as SQL parameters.
- **Answerability test.** A typed check that the sentence states what was asked
  (relation predicated, slot filled, count next to the counted noun), extending the
  Phase 12 deviation dimensions. New dimensions are declared with a rationale and a
  witness, and policy rows say which are invariant.
- **Near-miss tier.** Where a sentence fails only a non-invariant dimension, answer with
  the sentence and the typed caveat instead of refusing, and measure whether that helps
  utility.

Gate: on a fresh blind set, wrong share of answered ≤10% (stretch ≤5%), unanswerable
answered ≤5%, ≤5% of currently correct answers lost.

## B. Spec induction from labelled examples

Teacher rounds yield about one spec each. Induction aims at throughput:
- Input: (question, sentence, answer) triples. Sources: the infobox oracle (large,
  automatic, with a noted circularity), and fresh LLM-authored sets with supporting
  sentences.
- Method: align the answer span, the entity, and the question words in each sentence;
  group triples by question shape; generalise the shared structure into a candidate
  pattern (anti-unification over chunk and token features: shared words stay literal,
  varying noun phrases become NP slots, verbs bind to the question verb).
- Every candidate passes `verify_spec` with the full oracle bank and the measured
  precision gate on labelled questions. The LLM teacher handles shapes induction cannot
  cover and repairs rejected candidates using the verifier's reasons.
- Lexicon growth (`crms_lexicon_growth.py`) continues, adopted in groups that leave the
  oracle bank unchanged.

Gate: ≥20 specs accepted per round with the dev wrong share not rising; the scaling curve
(accepted specs against dev coverage and wrong share, with mechanisms ablated in turn)
is published.

## C. Composed answers for why, how, list, and define

A separate route, used only when the gate says the evidence supports it:
1. Retrieve a bounded sentence pool for the question's entity and terms.
2. Select the few sentences that state something responsive (reuse A).
3. Compress each to its answering clause (drop leading adjuncts, trailing relative
   clauses, parentheticals) with pattern-based rules stored in SQL.
4. Compose with the Phase 10 generation layer: one cited clause per fact, conflicts
   stated with both sources (Phase 12), the critic's checks on numbers, polarity, names,
   and role order, and abstention with a typed reason when evidence is thin.

Gate: for these question types on a fresh set, correct ≥30% with wrong share ≤10%, and
every clause resolving to a cited source span.

## D. Packaging and first run

- Put the pattern tables (verbs, classes, specs, intents, gate policy, parameters,
  rewrites, audit trail) in the Phase 8 model schema with a migration; keep the visible
  seed file as the reviewed source.
- Add a clean-room install check: the release artifact, with no LLM, network, or
  original files, loads and answers.
- Add a first-run smoke test: install, ask ten fixed questions (answerable, unanswerable,
  and out-of-scope), check answers and refusals.
- Rollback to the previous model version is one operation, tested.

## E. Evaluation discipline

- Budget fresh blind sets (authored by a fresh LLM session that sees only passages) per
  gate step: one for A, one for C, one release-candidate set at the end.
- Separate proposer, author, and judge sessions; judges differ from the proposer; report
  judge agreement and agreement with the deterministic label; label every result
  model-validated. A human-rated slice remains an optional upgrade.
- Report correct, wrong, abstain, coverage, and unanswerable-answered separately.

## F. Housekeeping

Resolve the `exam-fixes` branch (merge or drop), remove finished worktrees, prune
superseded docs, keep the regex ratchet green.

## Order and parallelism

A and D can start now and are independent. B runs alongside as its own session because it
touches only the loop and the verifier. C starts after A has fixed sentence selection,
because it reuses that selection. E is continuous.

## Risks

| Risk | Response |
|---|---|
| The gate hides a low ceiling by refusing more | Coverage floor in the gate; improvement must come from selection and induction |
| Induced specs overfit or shadow each other | Verifier, full oracle bank, precision gate, fresh blind set per step |
| Composed answers state something the sources do not | Per-clause cited span, critic checks, abstain on thin evidence |
| Blind sets run out | Author fresh sets per step; keep a budget and retire spent sets |
| Judges and author share a model family with the builder | Separate sessions and fresh contexts; oracle cross-check; model-validated labels |
| Merge conflicts between parallel branches | One family or file area per branch; merge through a trial worktree and the sharded regression |

## Open decisions

1. The frozen coverage target, set after the Phase 12 baseline is re-measured on a fresh
   set.
2. Whether the release artifact bundles the Simple English Wikipedia index or fetches it
   on first run.
3. Whether to add a human-rated slice before calling the release candidate done.
4. Whether `exam-fixes` merges or is dropped.
