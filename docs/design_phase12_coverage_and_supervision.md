# Phase 12 coverage and supervised learning at scale, generation first

**Status:** planned 2026-10-22; not started.
**Plan entry:** `docs/master_plan_to_final_state.md`, Phase 12.
**Builds on:** Phase 10 (generation stack, teacher loop skeleton), Phase 11 Stage A
(pattern layer, spec verifier, SQL pattern memory, infobox oracle).

## Decision recorded

The question was whether to retrofit the older regex code with the pattern layer,
or to solidify generation and the supervised-learning regime. Phase 12 chooses the
second, with a narrow, gated retrofit lane inside it.

| | Wholesale retrofit | Coverage + supervision first (chosen) |
|---|---|---|
| Capability gained | None directly; maintainability | Answers more questions, composes more |
| Evidence | Combined system beat relation-only by 128 correct (388 vs 260), so the old routes are a working fallback | About 74% of oracle questions return no candidate; supervision was manual |
| Risk | About 850 regex sites; 249 of 562 experiments touch chat or gate; many sites are tokenising or literal commands | Spec explosion, reward hacking, judge self-preference |
| Unblocks the contract | No | Independent evaluation, learning efficacy, generation breadth |

The decision changes if regex families start failing on real user paraphrases at a
rate the pattern layer would fix, or if regex maintenance becomes the main cost of
every change.

## Principles

1. Independent evaluation comes first; no capability claim without it.
2. A teacher proposes, deterministic checks accept.
3. Reward rule: +1 correct, −3 wrong, 0 abstain. Coverage may not be bought with a
   higher wrong share of answers.
4. A regex family retires only on parity, one family per change.
5. No new matching regexes in migrated modules; a ratchet test enforces it.
6. A blind set that influenced a change becomes tuning data and is retired.

## 1. Independent evaluation (first, blocking)

- An externally authored set of at least 300 prompts over two source-disjoint
  corpora. The author sees no code, specs, or prior outputs.
- A human-graded slice of at least 100 answers rated by two people on correctness,
  faithfulness, and clarity; agreement and kappa reported.
- The judge model differs from the proposing model; judge/human agreement is part
  of the gate.
- Report correct, wrong, abstain, and coverage separately.
- Resources outside the project are needed. If they are unavailable the gate stays
  open and the independent-evaluation claim is withheld; the other workstreams
  continue.

## 2. Automated teacher loop

Extend `crms_examiner.py`.

```
passage -> question + gold span (teacher)
        -> CRMS answers through the real chat
        -> failure grouped by cause: no candidate | boundary | wrong entity |
                                      conflict | retrieval | wording
        -> proposal at the lowest fixing tier: data | spec | code
        -> verifier (replay, held-out, contrast, verb-swap, fire-rate, bank)
        -> accept / reject, logged with model, prompt digest, metrics
```

- The infobox oracle supplies scale and an independent label source (gold errors
  reported). Teacher-generated questions cover relations the oracle cannot.
- Acceptance needs: verifier passes; oracle wrong share does not rise; the
  parity bank does not regress.
- Budget and report teacher calls and human minutes per round.

### Coverage program

- A per-relation gap table from the oracle (candidates, correct, wrong) ranks
  families to add.
- The rule-scaling curve: coverage and wrong share against specs and against
  training examples, with each mechanism (classes, back-off, transformations,
  veto) switched off in turn.
- Improve class induction (the induced place-noun class is noisy) and add
  transformations that derive new surface forms from one base pattern.
- Keep ranking parameters hand-set until a learned ranker beats them under
  leave-one-set-out validation; use the larger labelled error set from the loop to
  retry.

## 3. Generation upgrades

- **Intake over the active index.** `/compose` accepts a topic or question and
  builds propositions from a bounded retrieved sentence pool, not only from the
  request's own documents.
- **Multi-fact composition.** Join facts about one entity across documents;
  aggregate shared subjects; keep a span for every clause.
- **Qualifiers and conflicts.** Distinguish current from former and dated facts;
  when sources disagree, say so with both citations instead of choosing. Phase 11
  only abstains on equal-cost conflicts.
- **Neighbour retrieval.** Reach a fact stated on a related page (a sentence about
  an airport on the capital's page) through links or redirects, with the extra
  hop recorded in the citation.
- **Restatement.** When the source sentence is already simple, composition is a
  copy (copy ratio 1.0 in the intake suite). Add variation rules and report the
  copy ratio per genre.
- **Critic.** Relation and role order exist; add tense and quantifier checks.

## 4. Gated retrofit lane

- Candidate families chosen by measured failure: the gate's locative and
  answer-type predicates (27 of 61 abstentions in one exam), bare arithmetic, and
  any family the loop shows failing on paraphrases.
- Each family is one change: characterise first (record its experiments as
  controls), add or tune specs, switch the route, run the sharded full-suite diff
  against an unmodified baseline, then delete the old code.
- Footprint ratchet: `experiments/v1_580_regex_footprint.py` records regex call
  sites per module and fails if a migrated module gains any. The footprint per
  module is published in the report.

## 5. Conversation learning

- Opt-in collection of feedback (`/right`, `/wrong`, rephrasings) with redaction
  and a retention limit, stored locally.
- Run rephrase-after-failure mining on real sessions; verified patterns enter the
  store like any other proposal.
- If no real data exists by the gate, report the signal as unmeasured instead of
  simulating it.

## 6. Packaging

Put the pattern tables (verbs, classes, specs, parameters, rewrites, audit) in the
Phase 8 model schema with a migration; keep the visible seed file as the reviewed
source. The clean-room run covers index-based intake.

## Measurements and controls

- Per-relation correct / wrong / abstain, coverage, and utility (+1, −3, 0).
- Fixed failures become permanent controls; consumed blind sets are retired.
- Authored, teacher-generated, oracle-labelled, and independent results are
  reported separately.

## Gate (thresholds provisional until the baseline is frozen)

- Independent set: wrong share of answered ≤5% over two corpora; coverage on
  in-scope relations against the 26% baseline with a frozen target; zero unsafe
  answers on safety controls.
- Judge validity: human/judge kappa ≥0.6 on ≥100 answers; judge ≠ proposer.
- Learning efficacy: three automated rounds give ≥15% relative held-out gain with
  no confident-error increase; the scaling curve and ablations published.
- Generation: index-based outputs of at least three facts, 100% of clauses
  resolving to a cited span; conflicts and dated facts reported, never silently
  chosen; copy ratio no worse than Phase 10.
- Retrofit: at least three families retired on parity; footprint ratchet passes.
- Clean room: no LLM, network, or originals; patterns reload from SQL and roll back.

## Risks

| Risk | Response |
|---|---|
| Judge self-preference | Separate judge and proposer; human-graded slice decides |
| Reward hacking by abstention or by easy questions | Report answered, abstained, wrong separately; oracle plus teacher questions |
| Spec explosion and shadowing | Bank non-regression, consolidation, matching budget, utility accounting |
| Oracle label noise | Report gold-error examples; normalise template residue; use hand slices |
| Independent author or raters unavailable | Withhold the claim; continue other workstreams |
| Retrieval misses (facts on other pages) | Neighbour retrieval workstream; report separately from pattern misses |
| Teacher cost | Budget per round; prioritise by oracle gap |

## Open decisions

1. Who authors the independent set and who rates the graded slice.
2. Which model proposes and which judges (Phase 10 decision).
3. Whether pattern tables live in the model file or beside it.
4. Retention and redaction policy for conversation data.
5. The frozen coverage target for in-scope relations.
