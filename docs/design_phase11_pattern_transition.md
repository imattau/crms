# Phase 11 pattern-matching transition, generation layer first

**Status:** Stage A implemented and merged 2026-10-22; Stages B–E not started; gate open.
**Plan entry:** `docs/master_plan_to_final_state.md`, Phase 11.
**Code:** `crms_patterns.py`, `crms_pattern_transforms.py`, `crms_relation_specs.py`,
`crms_spec_verifier.py`, `crms_spec_registry.py`, `crms_pattern_memory.py` (+ `crms_pattern_seed.json`),
`crms_pattern_sources.py`, `crms_source_intake.py`, `crms_pattern_rewrite.py`,
`crms_generation_checks.py`, `crms_oracle_eval.py`, `run_phase11_eval.py`.

## What the transition is

CRMS currently recognises requests, selects evidence sentences, and extracts
knowledge with 851 regex call sites spread across 71 modules. Regexes see text,
not structure. They fail on reversed word order, intervening phrases, verb-form
variants, and wording they were not written for.

Phase 11 replaces that matching, in stages, with one pattern layer:

```
text -> tokens with features -> shallow chunks (NP, PP, verb group, appositive, parenthetical)
     -> pattern language (gaps, alternation, optional groups, verb forms, classes, typed values)
     -> backtracking matcher -> captures + trace -> verified answer / proposition
```

Patterns are data: stored in SQL, versioned, verified by a deterministic gate,
registered as rules, and rolled back in one operation. The generation layer goes
first because it has almost no regex today (4 sites in `crms_generation.py`),
because Phase 10 left its source-to-proposition intake open, and because it is
the cheapest place to prove the layer before touching the 562-experiment
surface.

## Regex footprint (2026-10-22)

| Area | Modules | Regex sites | Stage |
|---|---|---|---|
| Generation | `crms_generation.py`, `crms_generation_rules.py` | about 4 | A |
| Evidence selection | `crms_nl_gate.py` 28, `crms_research.py` 37 | 65 | B |
| Request understanding | `crms_chat.py` 250, `crms_conversation.py` 88, `crms_dialogue.py` 32, `crms_task_composition.py` 27, `crms_math.py` 19, `crms_request_frames.py` 6 | about 420 | C |
| Knowledge extraction | `crms_knowledge.py` 143, `crms_document_learning.py` 15, `crms_procedure_discovery.py` 42 | about 200 | D |
| Domain engines, cleaning | `crms_domains.py` 32, `crms_codegen.py` 13, `crms_corpus_program.py` 38 | about 85 | not planned |

Regex call sites approximate, they do not measure, the amount of matching logic.
Many sites are tokenising, cleanup, or literal command syntax and stay as they
are. Each stage begins with an audit of its own sites.

## Evidence from the prototype

All numbers are prototype results on project-authored or infobox-labelled data.
They are not gate results.

| Measure | Result |
|---|---|
| Teacher-proposed relation specs accepted by the verifier | 8 of 8 after three rounds; round 1 rejected all (three real defects, five from a verifier bug) |
| Dev set, 35 answerable | 25 → 32 correct |
| Fresh hand-written blind set B2 (34 answerable) | 20 → 25 correct, 4 → 1 wrong, with the relation layer |
| Fresh infobox-oracle sample, 1,029 questions | 219 correct, 30 wrong, 780 no candidate; 217/25 with a truncated-name veto |
| Learned ranker vs hand-set ranking (leave-one-set-out) | learned 73–86 correct / 3–7 wrong vs hand-set 89 / 5; not adopted |
| Synthetic probe check for derived variants | caught a real chunker defect (a verb absorbed into a noun phrase) |

## Principles

1. **New layer first, old route as fallback.** A spec answers only if it matches
   and verifies; otherwise the request passes through unchanged.
2. **Retire on parity.** A regex family is removed only after: the full
   experiment suite shows no new failure against an unmodified baseline; frozen
   exam sets do not regress; the independent oracle shows no higher wrong-answer
   rate.
3. **Reward rule.** +1 correct, −3 wrong, 0 abstain. A migration that raises the
   wrong rate fails even if coverage rises.
4. **One family per change.** Each change is small, reversible by registry
   status, and logged in the audit trail.
5. **Parameters are data and tuned honestly.** Ranking weights, gap bounds, and
   thresholds are SQL parameters. A learned replacement is adopted only if
   cross-validation beats the current values.
6. **Commands stay literal.** `/commands`, file paths, and CLI syntax are not
   natural language and are not migrated.
7. **No leakage.** A blind set that influenced a change is retired. The infobox
   oracle gives fresh, independent samples without hand authoring.

## Stage A: generation layer

### A1. Engine port

Move the prototype into the repository with tests.

| Prototype | Proposed module |
|---|---|
| tokenizer, chunker, pattern language, matcher | `crms_patterns.py` |
| derived-variant transformations and probes | `crms_pattern_transforms.py` |
| relation specs, sentence pools, selection | `crms_relation_specs.py` |
| deterministic spec verifier | `crms_spec_verifier.py` |
| candidate features and ranking | `crms_pattern_ranker.py` |
| corpus class induction | `crms_class_induction.py` |
| infobox-oracle question generator | `crms_oracle_eval.py` |
| sharded regression gate | `run_regress.py` |

Required behaviour: deterministic output; no network; bounded matching time (a
cap on gap lengths and alternatives per sentence); a trace for every match
("why did this match").

### A2. SQL store and registry

Extend `crms_composition_memory.py` with: word classes with support counts and
origin, agentive nouns, match specs (question patterns, sentence patterns,
answer template, status, rationale, change reference), parameters, and the audit
trail. Register specs as a rule family in `crms_rule_registry.py` so they share
lifecycle, utility counts, contest, retire, and rollback. Include the tables in
the packaged model and the Phase 8 migration path.

### A3. Source-to-proposition intake

Patterns turn retrieved sentences into propositions
`(subject, relation, object, source span)` for the Phase 10 content planner. The
`/compose` path accepts a topic or question, retrieves a bounded sentence pool,
applies relation specs, and passes verified propositions to the planner. Without
a match it falls back to the existing quote or abstains. This closes the open
Phase 10 gap that ordinary research chat returns whole retrieved sentences.

### A4. Pattern-based generation rules

Clarity rewrite rules and critic checks (relation, role, number, polarity) are
expressed as patterns over chunks and stored in SQL, replacing the regex and
word-list matching in `crms_generation.py`. Tokenising and string cleanup may
remain regex.

### A5. Verification and faithfulness

- Each accepted spec passed the verifier: replay, held-out, contrast, verb-swap,
  corpus fire-rate, bank non-regression, and a passing probe for every derived
  variant.
- Every composed clause resolves to a source span; the closed-template check
  stays.
- Candidate selection uses the SQL parameters. A veto abstains when an answer
  span is followed by a capitalised word (a likely truncated name).

### A6. Evaluation (`run_phase11_eval.py`)

- Phase 10 frozen suite, 12 cases, for parity.
- A source-intake suite: a fresh infobox-oracle sample of at least 1,000
  questions plus hand-authored questions and unanswerable controls.
- Report correct, wrong, abstain, and coverage separately; never collapse them.
- Full experiment suite diffed against an unmodified baseline.

### Stage A gate (thresholds provisional until the baseline is frozen)

- Phase 10 suite 12/12 unchanged; mean copy ratio and clarity no worse.
- Full experiment suite: zero new failures against the baseline.
- Wrong-answer rate on the oracle sample no higher than the quote baseline.
- 100% of composed clauses resolve to a cited span.
- Matching regexes in `crms_generation*.py`: zero, with any remainder listed
  and justified.
- Clean room: no LLM, network, or originals; patterns, classes, and parameters
  reload from SQL and roll back in one operation.

## Later stages

### Stage B: evidence extraction
`crms_nl_gate.py` and `crms_research.py` sentence selection. Relation specs run
ahead of the gate. Regex families in the gate retire on parity. The gate's
answer-type checks (WHERE, WHEN, WHO) are the first candidates because their
failures were measured: 27 of 61 abstentions in one exam came from the location
predicate check.

### Stage C: request understanding
`crms_chat.py`, `crms_conversation.py`, `crms_dialogue.py`,
`crms_task_composition.py`, `crms_math.py`. The largest surface. One intent
family per change, each with its experiments as controls. Bare arithmetic
(`17 * 23`), "Where is X?" wording variants, and slot-reply handling are
examples already seen.

### Stage D: knowledge extraction
`crms_knowledge.py`, `crms_document_learning.py`, `crms_procedure_discovery.py`.
Extraction patterns become specs with the same verifier and review gate.

### Stage E: retirement and audit
Remove dead regex, publish the footprint per module with reasons for remaining
sites, and re-run the full gate.

## Teacher and learning

An offline teacher may propose specs; CRMS verifies and owns them (Phase 10
amendment applies). Pattern transformations reduce authoring: one base pattern
plus named transformations (passive, agentive noun, participle) derives variants
and tests each against a synthetic probe. Parameters stay hand-set until more
labelled error data exists. The infobox oracle and teacher-generated questions
are the planned sources.

## Risks

| Risk | Response |
|---|---|
| Regression across 562 experiments (249 touch chat or gate) | New layer first, per-family retirement, sharded full-suite diff |
| Hidden knowledge in old regex | Characterise first: record each family's experiments as controls before retiring |
| Spec overfitting | Verifier checks, independent oracle, retire consumed blind sets |
| Rule shadowing | Bank non-regression in the verifier |
| Coverage stays low (about 24% of oracle questions had a candidate) | Use the oracle to rank relation families by gap; teacher loop proposes per family |
| Retrieval and stale/conflicting facts | Not solved by patterns; tracked separately (neighbour retrieval, qualifier handling) |
| English-only rule chunker | Declare the language scope; defer other languages |
| Induced classes are noisy | Keep support counts and a review step; classes are proposals |

## Open decisions

1. Which stage-A modules ship in the first commit and what the module names are.
2. Store pattern tables in the learned model file or beside it.
3. Language scope for the chunker (English only for Phase 11).
4. Which model proposes specs and which model judges them (Phase 10 decision).
5. Whether and when a learned ranker replaces the hand-set weights; the current
   bar is beating leave-one-set-out cross-validation.

## Stage A result (2026-10-22)

Built: engine, SQL memory and seed, spec verifier, registry family, source intake,
pattern-based clarity rewriting and critic checks, oracle evaluation, clean-room
test, project-authored intake suite (10 cases). Measured on the frozen oracle
sample (`corpus/phase11_eval/oracle_sample.json`): quote baseline 182 correct / 55
wrong; relation layer alone 260 / 21; relation first with chat fallback 388 / 47
(utility 247 vs 17). One correct baseline answer was lost (Citibank).

Decisions recorded:
- The extended-title veto (abstain when the source page's title extends the
  entity) removed 5 wrong answers and lost 40 correct ones across all sets
  (utility 287→262); it ships off (`veto_extended_title = 0`).
- A learned ranker lost to the hand-set ranking under leave-one-set-out validation;
  parameters stay hand-set until more labelled error data exists.
- The generation path now depends on the pattern modules and seed; the Phase 10
  clean-room test carries them.

Open: independent intake suite; intake over the active research index; packaged
model tables; Stages B–E.

## Stages B–E result (pilot scope)

Implemented in `crms_intent_rules.py` with the SQL table `pat_intent` and seed
rules in `crms_pattern_seed.json`: gate answer type and location predicate,
arithmetic question wrappers, and claim-status cues. Each family was retired only
after a parity run against a frozen reference (see the master plan table). The
regex footprint ratchet is `experiments/v1_581_regex_footprint.py`; the record is
`corpus/phase11_eval/regex_footprint.json`. Total sites 914 to 889. Remaining
families are inventoried for the Phase 12 retrofit lane.
