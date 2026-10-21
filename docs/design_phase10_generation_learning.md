# Phase 10 rule-complete generation and LLM-supervised rule development

**Status:** started 2026-10-21. First rule-only vertical slice implemented; the
full gate is open.
**Plan entry:** `docs/master_plan_to_final_state.md`, Phase 10.
**Core files:** `crms_generation.py`, `crms_generation_rules.py`,
`crms_generation_rules.json`, `experiments/v1_566_phase10_generation.py`.
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
- **Clean room:** no teacher, network, or originals; rules reload and roll back.

## First vertical slice

Implemented:

- generation contract and rule file;
- content planner over structured propositions;
- genre schemas for explanation, comparison, procedure, analysis, and summary;
- discourse/paragraph planning;
- clause and sentence planning with a small construction grammar;
- deterministic realizer;
- clarity checks;
- critic and candidate selection;
- frozen evaluation experiment.

This slice is intentionally narrow. It proves the stack and the output shape; it
does not yet prove broad rule sufficiency, teacher-driven induction, SQL
lifecycle, human calibration, or the full 300-prompt gate.

**First-slice result:** 7/7 frozen cases passed, mean copy ratio 0.00, mean 6.6
sentences. Five of the ten declared genres are tested: explanation, comparison,
procedure, analysis, and summary, plus abstention and clarification controls.
The report records the other five as untested and every full-gate item as open.
Copy ratio is a surface n-gram measure; the zero value reflects reworded source
documents and structured propositions, not a semantic-novelty proof.

## Known limits

- The first slice uses structured propositions; general source-to-proposition
  extraction is Phase 3/7 work that must be connected later.
- The construction inventory is small.
- The lexicon is hand-seeded and small.
- The critic uses heuristics; human/comprehension calibration is pending.
- The evaluation set is small and project-authored.
- No teacher loop or SQLite rule store is implemented yet.
- Long-form coherence, humour, irony, and literary voice remain hard targets.
- The 70B comparison is not yet run for this stack.

## Open decisions

1. Sign off the offline teacher amendment.
2. Store generation rules inside the learned model file or beside it.
3. Which model proposes and which model judges.
4. Transcript/teacher-data retention policy.
5. Whether future probabilistic rule weights are allowed; the first slice is
   deterministic and weight-free.
