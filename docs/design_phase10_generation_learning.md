# Phase 10 rule-complete generation and LLM-supervised rule development

**Status:** bounded lane completed 2026-10-21. Rule-only generation, SQL
memory, teacher proposal loop, clean room, CLI, generalisation diagnostics, and
automated comparison are measured; the full external gate is open.
**Plan entry:** `docs/master_plan_to_final_state.md`, Phase 10.
**Core files:** `crms_generation.py`, `crms_generation_rules.py`,
`crms_generation_rules.json`, `crms_composition_memory.py`,
`crms_examiner.py`, `crms_generalisation.py`, `crms_generate.py`,
`run_phase10_eval.py`, `run_phase10_teacher.py`,
`run_phase10_comparison.py`, `run_phase10_external.py`.
**No distilled model:** generation is deterministic rules, grammar, and search.
An offline LLM may propose rules and exemplars; it never runs at answer time.

## Target

Generate clear, coherent, audience-adapted, multi-paragraph content in a
declared set of genres. Content is composed from cited propositions or
explicitly fictional premises, not selected as whole source sentences.

This is not a claim of arbitrary open-world omniscience. It is a claim about
**rule completeness over a declared distribution**. A finite grammar can
generate unbounded output; the open question is whether the rule library,
knowledge, and selection mechanism are sufficient for the target genres.

## Why this replaces the earlier composer framing

The earlier Phase 10 draft was a short-answer composer:

- compose short answers;
- closed template vocabulary;
- fixed question classes;
- fixed quality rubric;
- no discourse planner, general grammar, open lexicon, clarity rewriter, or
  candidate search.

That can improve grounded QA, but it cannot produce LLM-like content. The
revision keeps the evidence contract and replaces the template selector with a
generation stack.

The research evidence is consistent with this direction:

- **WritingBench** (1,239 queries, 6 domains, 100 subdomains) reports frontier
  writing scores around 8.2–8.6/10, with curated 7B models near 8.5. It also
  shows query-dependent criteria align with human judgment much better than
  static rubrics.
- **FACTS Grounding** (1,719 long-document tasks) shows even frontier models
  are not perfectly grounded; top public scores are around 87–89%, with a broad
  average near 70%.
- **Plain-language summary research** shows LLM text can have better
  readability and similar subjective ratings while producing worse reader
  comprehension than human text. Clarity must be tested by comprehension, not
  readability alone.
- **MT-Bench / LLM-as-judge** work shows position, verbosity, and
  self-enhancement biases. Teacher and judge must be separated and calibrated.
- **Longform writing benchmarks** show coherence degradation, repetition,
  “slop,” and forced metaphor over long outputs. Rule data must be filtered for
  restraint, not just fluency.

## Architecture

```
request contract
  -> content planner (propositions, evidence, gaps)
  -> discourse planner (genre schema, moves, sections)
  -> paragraph planner (topic sentence, support, example, transition)
  -> sentence planner (clauses, reference, aggregation, lexical choice)
  -> construction realizer (grammar, morphology, punctuation)
  -> clarity/style rewriter
  -> critic/search (coverage, faithfulness, coherence, clarity, copy)
  -> answer + plan + evidence + scores
```

### 1. Generation contract

Parse:

- genre;
- audience;
- length and format;
- clarity target;
- evidence policy: cited fact, explicit inference, or explicitly fictional.

Declared genres for the phase:

1. explanation;
2. comparison;
3. procedure;
4. analysis;
5. summary;
6. argument;
7. professional writing;
8. narrative;
9. technical note;
10. dialogue.

Unknown genres clarify or abstain. A genre is not a template; it is a schema
over moves and content points.

### 2. Content planner

The planner turns the request into **propositions**, not sentences:

- required content points;
- source facts with spans;
- proof-bearing inferences;
- missing information;
- what to omit;
- whether to clarify or abstain.

Every factual proposition carries a source id and span. A proposition with no
resolvable evidence is not eligible for a factual answer. Creative content is
explicitly marked fictional and cannot silently become a factual claim.

### 3. Discourse and paragraph planner

Genre schemas select rhetorical moves and order them. Example schemas:

| Genre | Moves |
|---|---|
| Explanation | direct answer → definition → mechanism → consequence → example → caveat → summary |
| Comparison | framing → criterion A → criterion B → contrast → recommendation |
| Procedure | goal → prerequisites → steps → pitfalls → verification |
| Analysis | claim → evidence → interpretation → counterpoint → conclusion |
| Summary | main point → supporting points → qualification |
| Argument | thesis → reasons → evidence → objection → response |
| Narrative | status quo → inciting incident → escalation → climax → resolution → change |

The paragraph planner allocates moves to paragraphs and chooses topic sentences,
support, examples, transitions, qualifications, and conclusions. This is where
multi-paragraph structure comes from. It is not produced by concatenating
source sentences.

### 4. Sentence planner and realizer

Facts become **clauses**:

- subject;
- predicate;
- object/complement;
- modifiers;
- source span.

The sentence planner chooses:

- referring expressions;
- voice;
- aggregation;
- coordination;
- subordination;
- lexical frames;
- information order.

The realizer uses a feature-based construction grammar, not a whole-sentence
template library. Supported constructions in the first slice include:

- definition: “X is Y.”
- cause: “Because X, Y.”
- result: “X, so Y.”
- contrast: “X, whereas Y.”
- example: “X. For example, Y.”
- sequence: “First, X. Then, Y.”
- elaboration: “X. Y.”
- qualification: “However, X.”

Later slices add relative clauses, conditionals, concession, purpose,
comparison, appositives, and richer noun phrases. Factual content tokens are
separated from function/style vocabulary: open-class function words do not need
closed-template membership, while names, numbers, relations, and polarity remain
evidence-checked.

### 5. Clarity, style, and revision

Clarity rules:

- define a term before relying on it;
- one main idea per sentence;
- split overlong sentences;
- prefer active voice unless passive is clearer;
- replace nominalizations with verbs;
- add necessary background and examples;
- use signposting;
- remove unexplained jargon;
- keep terminology consistent;
- put the main point first;
- avoid repetition and forced ornament;
- summarize when useful.

Style profiles: plain, professional, academic, friendly, persuasive, narrative.
Each profile selects lexical and syntactic rules; it is not a single prompt.

Clarity is a hard gate, not a soft rubric. Evaluation includes comprehension
questions and recall, not only readability scores. The plain-language evidence
shows this distinction matters.

### 6. Critic and candidate search

The generator produces several valid plans and realizations, then scores them:

- required-point coverage;
- clause faithfulness;
- relation, role, number, and polarity checks;
- coherence and entity continuity;
- clarity and comprehension heuristics;
- copy ratio;
- style/format/length adherence;
- repetition and “slop” penalties;
- audience fit.

The best candidate wins. If none passes, the system falls back to a quote, asks
a focused question, or abstains. Search is how a rule system avoids producing
the same stiff output every time.

### 7. LLM-supervised rule development

The teacher is offline and optional. It generates:

- annotated exemplars: prompt, content points, rhetorical moves, sentence
  functions, clarity edits;
- contrast pairs: clear vs unclear, structured vs rambling, concise vs verbose;
- critiques of CRMS outputs;
- proposed rules in the generation rule DSL.

CRMS induces and stores:

- genre schemas;
- move-order statistics;
- sentence constructions;
- lexical frames and collocations;
- connective preferences;
- clarity rewrite rules;
- critic weights.

Acceptance is deterministic: held-out quality rises, faithfulness holds, no
control regresses. The teacher never accepts its own proposal. This is rule
induction, not model distillation.

### 8. Rule store and lifecycle

The seed rule file is `crms_generation_rules.json`. It is visible and
reviewable. The production store moves to SQLite with:

- rule id, family, genre, scope, version;
- origin: seed, teacher, conversation, human;
- rationale and source examples;
- status: proposed, active, contested, retired;
- utility counts and before/after scores;
- rollback reference.

Composition rules join `crms_rule_registry.py` as a `composition` family.

### 9. Evaluation

The frozen evaluation must include:

- ≥300 blind, independently authored prompts;
- 10 genres;
- two source-disjoint corpora;
- required-point coverage checklists;
- comprehension quizzes and recall;
- expert clarity ratings;
- human/LLM judge calibration with kappa;
- copy ratio;
- 70B-class comparison;
- adversarial cases: missing evidence, conflicting sources, ambiguity,
  constrained length, audience shift, multi-turn repair;
- rule coverage matrix and unseen-combination tests.

### 10. Packaging

A copied release must generate identically with:

- no LLM;
- no network;
- no original source files;
- rules reloaded from SQL;
- one-operation rollback;
- provenance intact.

### 11. Generalisation mechanisms

What an LLM appears to generalise is largely what its training put in. Rules can
be made to cover more than they were taught, without gradient training and
without a model at answer time, through four deterministic mechanisms. All are
stored in SQL, reproducible, and bypassable.

| Mechanism | What it does | Prototype seed |
|---|---|---|
| Learned classes | Induce word and phrase classes from corpus co-occurrence and from the slots rules fill (agent-taking verbs, place nouns, months, genres). A rule over a class covers unseen members. Replaces the hand-written lexicon. | Verb-slot frames over a hand-written verb lexicon |
| Back-off hierarchy | General-to-specific rule inheritance. A request matches the most specific rule and falls back to a more general one; the fallback path is recorded. | Anchor merging turned "municipality in" and "comune in" into "* in" |
| Analogical matching | Nearest-example lookup over stored exemplars with a fixed similarity, used to propose a rule or construction for a novel input. Proposal only. | Rephrase-after-failure pattern mining |
| Evidence-count weights | Explicit hits, misses, scope, and source counts rank competing rules. No hidden state; numbers live in SQL. | Per-frame good/bad counts that disable a bad frame |

Safeguards (from master plan §5.7): a generalised rule starts `proposed`;
counterexample search runs before activation; validation is source-disjoint; the
class or back-off path is logged on every use; exact checks decide acceptance.
The prototype's region-and-country place shortening is the cautionary case: it
looked good on development questions and dropped required specificity on the
blind set.

**Rule-scaling curve.** On frozen task families, plot held-out coverage and
confident-error rate against (a) training examples seen and (b) active rule
count, from about 10^2 to 10^5. Run each mechanism on and off. Report coverage
per training example, cost, and the slope against the section 2 thresholds. A
plateau is diagnosed (missing rule, bad selection, missing knowledge, or
evaluator error), not hidden. An earlier unsupervised measurement on Simple
English Wikipedia found reusable relation frames growing about 5 to 6 points per
tripling of training sentences without flattening; it is evidence that the
curve is worth measuring, not evidence about this stack.

## Gate

Thresholds are provisional until the baseline is frozen, then locked.

- **Faithfulness:** 100% of factual clauses resolve to a cited span; relation,
  role, number, and polarity independently checked.
- **Trust:** ≤2% confidently wrong on ≥300 blind prompts over two corpora; zero
  on safety controls.
- **Content:** ≥90% required-point coverage; ≥60% answers synthesize two or
  more facts; ≥70% multi-sentence.
- **Clarity:** ≥85% comprehension; expert clarity ≥4/5; ≤5% unexplained jargon.
- **Composition:** mean copy ratio ≤0.4; no answer above 0.7.
- **Style/control:** ≥90% format, length, audience, and register adherence.
- **Comparison:** ≥80% of measured 70B baseline adequacy and ≥90% clarity, no
  genre below 70%.
- **Judge validity:** human/judge kappa ≥0.6; judge differs from proposer.
- **Rule sufficiency:** coverage matrix and unseen-combination tests; every
  failure attributed to missing rule, selection, knowledge, or evaluator.
- **Learning:** three teacher-assisted rounds give ≥15% relative held-out gain
  with no confident-error increase.
- **Generalisation:** rule-scaling curve with per-mechanism ablations; each
  mechanism's held-out gain and confident-error change reported; no generalised
  rule active without counterexample search and source-disjoint validation.
- **Clean room:** no teacher, network, or originals; rules reload and roll back.

## Bounded lane

Implemented:

- generation contract and rule file;
- content planner over structured propositions;
- genre schemas for all ten declared genres;
- discourse/paragraph planning;
- clause and sentence planning with a small construction grammar;
- deterministic realizer;
- clarity checks;
- critic and candidate selection;
- SQL snapshots, judgments, active selection, and rollback;
- offline teacher proposal loop with accepted and rejected controls;
- generalisation diagnostics: class hierarchy, back-off, report-only analogies,
  evidence weights, and a fact-coverage curve;
- clean-room copied rule/fixture run;
- JSON-request CLI and `/compose PATH` chat command;
- frozen evaluation experiment;
- blind automated comparison against a hosted 70B-class proxy.

This bounded lane proves the stack and the output shape. It does not yet prove
broad rule sufficiency, human clarity calibration, or the full independent
300-prompt gate.

**Bounded-lane result:** 12/12 frozen cases passed, covering all ten declared
genres plus abstention and clarification controls. Mean copy ratio is **0.157**
and mean length is **6.2** sentences. Copy ratio is a surface 5-gram measure;
it is not a semantic-novelty proof. The teacher proposal loop accepted a clarity
alignment with no regression and rejected a deliberately bad sentence cap. SQL
snapshots, judgments, active selection, rollback, and clean-room reload pass.
The automated 70B-class comparison scores CRMS adequacy **1.75/2**, clarity
**1.90/2**, coverage **1.85/2**, and evidence **1.85/2** against the proxy's
2.00, 2.00, 2.00, and 1.85; CRMS has three confident errors and the proxy six.
Human clarity calibration, an independently authored 300-prompt suite over two
source-disjoint corpora, and a measured 70B checkpoint remain open.

## Known limits

- The first slice uses structured propositions; general source-to-proposition
  extraction is Phase 3/7 work that must be connected later.
- The construction inventory is small.
- The lexicon is hand-seeded and small.
- The critic uses heuristics; human/comprehension calibration is pending.
- The evaluation set is small and project-authored.
- The generalisation diagnostics cover classes, back-off, analogies, evidence
  weights, and a small fact-coverage curve; the full 10^2–10^5 rule-scaling
  curve and per-mechanism ablations are not measured.
- Rater agreement is weak on clarity (kappa 0.0) and coverage (kappa -0.07);
  the automated panel is not a substitute for humans.
- Long-form coherence, humour, irony, and literary voice remain hard targets.
- The 70B comparison is a hosted proxy with undisclosed parameter count, not a
  measured 70B checkpoint.

## Open decisions

1. Sign off the offline teacher amendment.
2. Store generation rules inside the learned model file or beside it.
3. Which model proposes and which model judges.
4. Transcript/teacher-data retention policy.
5. Evidence-count rule weights are proposed as allowed (explicit numbers in SQL,
   reproducible, no hidden state); the first slice is weight-free. Probabilistic
   or learned-similarity weights beyond counts remain undecided.
