# Language and recombination benchmark baselines

## Proof-guided procedure composition (2026-10-20)

Command: `python3 run_experiments.py --match v1_451 --timeout 300`.

The experiment discovers a typed three-premise rule (`employs + owns +
located in → reaches`) from two training examples and validates it against two
held-out examples. Ordinary-language chat asks which runtime record IDs are
reachable. Every positive used in the next stage has a proof accepted by the
independent proof verifier. Two distinct proofs for record 4 intentionally
produce a duplicate in the intermediate list: `[12, 4, 4, 9]`.

A separately learned procedure, “remove duplicate values then reverse the
list,” transforms those proof-derived IDs into `[9, 4, 12]`. The generated
Python artifact passes its recorded parity checks and an independent output
oracle. Explicit negative record 7, conflicting record 6, and unsupported
record 8 are excluded. A fresh chat process answers positive, negative, and
unknown questions, explains the positive proof, and generates the artifact. A
practiced conclusion is stored separately and becomes unavailable when its
supporting source premise is corrected.

This closes one controlled integration gap among reasoning, procedure
recombination, chat, and correction. The graph examples are synthetic; the
list-operation mapping and demonstrations are Codex-labeled; and the final
composition is orchestrated by the experiment rather than planned from a broad
request. It does not show autonomous rule learning from source documents or
general task planning.

## Role-compatible predicate candidate probe (2026-10-20)

Command: `python3 experiments/v1_450_role_compatible_predicate_candidates.py`.

The runtime probe extracts the inflected source relations “created” and
“made”, then uses accepted, source-cited entity types to surface relation pairs
whose subject and object roles match. It reports the plausible created/made
pair, but also surfaces created/praised despite their different meanings. The
person-to-city “visited” relation is filtered by its mismatched object type.
Every proposal is explicitly `investigate_only`, carries citations for the
relation examples and role types, and cannot be accepted through this path.
The fresh chat command preserves that warning and does not alter facts or
frames. The follow-up trust-boundary check confirms that a role type with an
explicit negative conflict or contextual qualifier does not participate in
candidate generation.

This synthetic fixture confirms a useful, higher-recall investigation signal,
not synonym discovery: type compatibility alone is too weak to license an
alignment. It gives no estimate of real-corpus precision. Continue only with
held-out examples and direct semantic validation; do not turn these candidates
into learned rules automatically.

## Current cross-domain regression replay (2026-10-20)

Code snapshot: commit `69158a4` (`Exclude conflicted types from candidate
discovery`), including the role-type trust-boundary fix. The checkout also
contained user-owned dialogue artifacts and an edited corpus-audit report; the
runner gave each experiment an isolated temporary working directory, and none
of those files was used as a fixture.

Command:

```sh
python3 run_experiments.py --match 327 --match v1_242 --match v1_376 \
  --match v1_357 --match v1_207 --match v1_389 --match v1_413_source \
  --match v1_414_persisted_source --match v1_427 --match v1_449 \
  --match v1_436_source_derived --match v1_437_heldout_publisher \
  --match v1_448 --match v1_250 --match v1_192 --match v1_379 --timeout 300
```

All 17 selected diagnostics passed in 13.93 seconds:

| Capability slice | Diagnostics | Result |
| --- | --- | ---: |
| Paraphrase transfer and retrieval | `v1_327`, `v1_242` (2 diagnostics) | 2/2 passed |
| Source-derived rules and procedure recombination | `v1_250`, `v1_436`, `v1_437`, `v1_448` | 4/4 passed |
| Verified reasoning and governed learning | `v1_192`, `v1_376`, `v1_379` | 3/3 passed |
| Math/code and translation | `v1_357`, `v1_207` | 2/2 passed |
| Creative revision | `v1_389` | 1/1 passed |
| Dialogue continuity and evidence grounding | `v1_413`, `v1_414`, `v1_427`, `v1_449` | 4/4 passed |
| **Total** | **17 diagnostics** | **17/17 passed** |

This is a regression sweep across separately designed experiments. Their
fixtures, difficulty, and scoring differ, so the pass count is not a shared
accuracy score, a representative user-task distribution, or a comparison with
a 70B-class model. It confirms that these specific paths still satisfy their
assertions on the current code snapshot. Broad conversation quality, independent
human assessment of creative work, and reliable autonomous rule discovery from
raw source documents remain unmeasured. The separate `v1_450` role-compatibility
probe also shows a false created/praised candidate; it must not be folded into
the passing source-learning evidence as if candidate recall proved rule
learning.

## Cross-paragraph source pronoun grounding (2026-10-20)

Command: `python3 experiments/v1_449_cross_paragraph_pronoun_grounding.py`.

The fresh-process chat path switches from an Eiffel Tower paragraph to a
Colosseum paragraph, then answers “When was it completed?” with the Colosseum's
1980 date instead of reusing the Eiffel Tower's 1889 date. The exact cited
paragraph supplies both the named antecedent and pronoun-led date. A pronoun-
only paragraph without a local named antecedent remains an abstention. Both
cases pass in separate CLI processes. This is one targeted regression, not a
broad dialogue evaluation.

## Grounded language recombination grid

Command: `python3 experiments/v1_242_grounded_recombination_benchmark.py`

Runtime rerun on 2026-10-19. Each k is the number of demonstrations used to
learn the phrase grid. The held-out count is the number of phrase combinations;
each is checked on two input lists.

| k | Held-out phrases | Correct predictions | Wrong | Abstained | Coverage | Controlled-negative abstention |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 15 | 0/30 | 0 | 30 | 0% | 100% |
| 2 | 14 | 0/28 | 0 | 28 | 0% | 100% |
| 4 | 12 | 0/24 | 0 | 24 | 0% | 100% |
| 8 | 8 | 16/16 | 0 | 0 | 100% | 100% |
| 12 | 4 | 8/8 | 0 | 0 | 100% | 100% |

The ten hand-authored unseen wordings all returned `need_examples`. Article and
casing variants scored 2/3 with the exact-frame baseline and 3/3 after
normalization, with the same trace. These are bounded fixture results: at k=12
the held-out set has only four phrases, and the hand-authored wording set is
not representative of open-domain paraphrase. This does not establish broad
language coverage or creative-writing ability.

## Bounded fictional story composition

Command: `python3 run_experiments.py --match v1_353_creative_request_scope`

The chat composes a deterministic five-beat short story around a supplied
topic, with an optional funny tone selecting a comic template. A missing topic
prompts for clarification; an unsupported story constraint (source grounding)
is declined, and a question asked during clarification returns to the factual
route. The regression also checks that generated details are labelled as
invented fiction, invalid topics are rejected, poems and jokes remain
unsupported, and factual questions keep their previous routes. Runtime result:
3 generated stories, including a topic clarification and funny variant; all
scope and factual-routing controls passed. This checks request routing and
story-grammar invariants, not human-rated coherence, originality, or parity
with a large instruction model.

## In-session story tone revision

Command: `python3 experiments/v1_389_story_revision_dialogue.py`

The terminal generates a story, revises the latest story to the other supported
tone on request, handles a repeated tone request without rerendering, and then
answers a factual question through the normal source route. This verifies
session context and route separation for one narrow creative revision. It does
not measure human-rated quality, originality, or parity with a large model.

## Mystery story request and revision

Command: `python3 experiments/v1_421_story_mystery_revision.py`.

The CLI recognizes an explicit mystery-story request, selects one of two
five-beat mystery grammars, and revises the latest story from mystery to funny
and back to mystery. It preserves the requested topic and invented-fiction
label, then answers a factual question through the normal source route. This
adds one bounded creative mode; it is not evidence of human-rated story quality,
open-ended writing, or broad creative competence.

## Capability-comparison status (2026-10-19)

CRMS has focused, reproducible checks for natural-language transfer,
recombination, retrieval, math, coding, translation, and proof-backed
reasoning, but these results are not a shared cross-domain score and do not
establish equivalence to a large language model. A qualitative capability and
interaction comparison, based on published model reports and the CRMS
component results, is in
[`capability_comparison_70b.md`](capability_comparison_70b.md). It compares
what a strong large instruction model can typically attempt, how it presents
answers, and how it handles follow-ups against CRMS's measured behavior. No
live large-model run is required. Report CRMS component results and
unsupported cases separately; make no parity claim.

## Cross-domain working-tree scorecard (2026-10-20)

The selected runtime checks below were run through `run_experiments.py` from
the working tree based on `d597615` (not a clean checkout). The tree contained
uncommitted dialogue/chat changes and an updated large-corpus audit report, so
these results describe that local snapshot. They are component diagnostics,
not a single capability score and not a large-model comparison.

Command:

```sh
python3 run_experiments.py --match 327 --match 242 --match 376 \
  --match 357 --match 207 --match 389 --match 413 --match 414 --timeout 300
```

All 9 selected scripts passed: `v1_207_grounded_translation`, both
`v1_242` recombination/retrieval diagnostics, `v1_327` natural-language
transfer, `v1_357` list-to-math/code composition, `v1_376` reasoning graph
benchmark, `v1_389` story revision, and `v1_413`/`v1_414` source-topic
dialogue and persistence. Passing means each script's own assertions passed;
it does not mean the system performs those tasks broadly.

The direct `v1_327` run reported:

| Set | Baseline correct | Layer correct | Layer wrong | Layer abstained | Must-refuse accepted |
|---|---:|---:|---:|---:|---:|
| Dev | 50/78 | 73/78 | 0 | 5 | 11/11 |
| Held | 31/45 | 44/45 | 0 | 1 | 12/12 |
| Unseen | 29/44 | 42/44 | 0 | 2 | 14/14 |

These figures are for the benchmark wrapper and its small, partly tuned
question sets. They do not contradict the weaker real-text audit below: the
wrapper and the large-corpus probe test different distributions and scoring
rules.

The same run of `v1_376` independently verified every positive proof and
replayed semantic results deterministically. The 35-hop chain and depth-9
binary tree completed; the diamond query answered with 64 listed proofs and
`complete=False` due to the explicit proof cap; the positive/negative conflict
was ambiguous; the negative-only and complete-miss cases remained unknown; an
expansion-limited query remained incomplete; the cycle-backed self-relation
was ambiguous; and the declared irreflexive constraint denied its self-link.
Observed runtime was 0.8–311 ms across those cases on this machine; these
values are not portable performance guarantees.

The current 1,200-document, 7,200-sentence audit in
[`large_corpus_chat_audit.json`](../experiments/reports/large_corpus_chat_audit.json)
reports that all 30 expected sentences for its canonical queries were seen by
retrieval and that all three negative relation controls abstained. This is
retrieval coverage on a generated corpus, not answer accuracy. For 11 positive
paraphrase probes, the report records 7 expected-sentence hits; a hit can still
be labelled as related evidence rather than an answer to the requested
relation. Several paraphrases remain unsupported, including `Which stream
passes through Nacre City 0133?` and `Where does the Serein River 0133 run?`.
This gap is language/relation coverage, not missing source text.

The scorecard points to the next work: retain the strong bounded recombination
and verified-proof behavior while improving answer-bearing sentence selection
and relation paraphrase transfer on source-disjoint language tests. Continue
to evaluate multi-turn dialogue across topic switches and restarts, and measure
creative quality separately from scripted route and template correctness.
No overall capability or parity claim follows from this run.

## Recent-paper topic follow-up (2026-10-20)

The older academic-model chat audit found that “What topics do these papers
cover?” could retrieve an unrelated project-source sentence after a recent
paper list. A fresh CLI replay reproduced that failure. CRMS now routes this
plural follow-up to the immediately visible list and returns each listed
paper's opening abstract sentence with a citation verified against the indexed
source. It retains the list for the next ordinal follow-up and asks which papers
the user means when no list is open. The response is explicitly extractive; it
does not claim to synthesize a shared taxonomy or explain the result in simpler
terms. The current runtime replay against a temporary copy of
`data/crms_project_model_academic.sqlite` returned the three listed abstracts
instead of the unrelated project-source sentence, while leaving the original
model untouched.

`v1_453_recent_papers_topic_followup.py` passes fresh-process checks for all
three paper entries, exact citation resolution, follow-up persistence to an
ordinal summary, and clarification when the list context is absent. The broader
cross-domain replay including `v1_453` passed 19/19 in 14.46 seconds. This is a
specific contextual-retrieval repair, not evidence of general multi-document
reasoning or broad dialogue reliability.

## Pending-review interruption control (2026-10-20)

`v1_454_pending_review_does_not_interrupt_answer.py` creates two cited,
review-only claims, then asks an unrelated question with an already accepted
answer. The accepted answer is returned without a candidate reminder; both
claims remain available through `/pending-candidates` in the same session and
after restart. The adjacent rule-pending usability diagnostic also passes.
These controls verify queue isolation for this sequence, not every possible
pending-state interaction during long conversations.

The combined cross-domain regression replay, including `v1_453`, `v1_454`, and
the pending-rule usability control, passed 21/21 in 15.35 seconds. The
diagnostics have different fixtures and scores; their aggregate is a regression
count, not an overall capability rate.

## Plain-language result follow-up (2026-10-20)

When a user asks for a simpler explanation and no rewrite frame is learned,
CRMS now says that it cannot yet provide a verified rewrite, quotes the cited
source statement, and describes the two aligned examples needed to teach one.
The existing `v1_265_grounded_plain_rewrite.py` confirms that a learned
same-language rewrite still answers with the source attached;
`v1_455_plain_explanation_without_frame.py` covers both the unlicensed and
learned cases. The 23-diagnostic replay, including these checks, passed in
17.07 seconds. The test rewrite is Codex-authored and demonstrates supervised
frame use, not autonomous simplification or semantic validation of arbitrary
rewrites.

## Post-grounding cross-domain rerun (2026-10-20)

Code snapshot: commit `57c7892` (`Bind pronoun evidence to the nearest topic`).
The tree also contained the pre-existing modified large-corpus report and
untracked dialogue artifacts; those were not used by these selected scripts.

Command:

```sh
python3 run_experiments.py --match 327 --match 242 --match 376 --match 357 \
  --match 207 --match 389 --match 413 --match 414 --timeout 300
```

All 10 selected diagnostics passed in 11.27 seconds. This reruns language
transfer, the phrase-grid recombination benchmark, sentence-focused retrieval,
cross-domain list/math/code composition, grounded translation, proof-backed
reasoning, creative story revision, source-topic follow-ups, and citation-backed
topic persistence. The results show no regression in these probes after the
dialogue grounding changes; they are not a broad task-suite accuracy estimate.

Direct metric outputs on this snapshot:

| Probe | Current result | Limit |
| --- | --- | --- |
| `v1_327` paraphrase layer | Dev 73/78, held 44/45, unseen 42/44 correct; zero wrong; 8 abstentions across held/unseen; controlled negatives refused 37/37 | Small authored sets; phrase coverage is not open-domain language understanding |
| `v1_242` phrase-grid learning | 0/30, 0/28, 0/24 correct at 1, 2, 4 examples; 16/16 at 8 and 8/8 at 12; zero wrong; all 10 authored unseen wordings abstained | Synthetic phrase grid; a supervision/coverage threshold, not broad recombination |
| `v1_376` reasoning graph | 35-hop chain and depth-9 binary tree answered with verified proofs; diamond answer marked incomplete at the 64-proof cap; conflict ambiguous; open-world misses unknown; cycle-backed self-relation ambiguous; irreflexive self-link denied | Engine-level graph benchmark; natural-language routing and real-corpus premise coverage remain separate gaps |

This snapshot supports continuing the shared benchmark and the source-disjoint
learning work. It does not establish parity with a 70B-class assistant. The
next high-value experiment remains natural-source procedure learning with
independently written requests, an unseen composition, and an independent
validator; keep source attribution, labeler decisions, and generalization
results separate.

## Active/passive exact-predicate morphology

Commands: `python3 experiments/v1_416_regular_es_gate_morphology.py` and
`python3 experiments/v1_417_ied_relation_gate.py`, followed by
`python3 experiments/v1_329_runtime_nl_gate.py` and
`python3 experiments/v1_347_grounded_passive_question_recombination.py`.

The large-corpus audit had a clear sentence but the evidence gate rejected it:
the question used `crosses`, while the source used passive `is crossed by`.
`_stem` had stripped only the final `s`, producing `crosse` versus `cross`.
The narrow `-es` normalization now makes these forms agree. The exact-predicate
positive is accepted; the wrong numbered entity and an unrelated `flows through`
question remain rejected. Both focused experiments pass. This demonstrates a
specific inflection/voice transfer, not semantic synonym coverage; questions
using `run` still need a licensed relation or must abstain.

The same gate also normalizes regular consonant-y past forms (`studied`→`study`),
which lets a question and a sentence share the predicate without relying on
other overlapping content words. It preserves `died`→`die` and rejects a
same-entity question with the unrelated verb `investigate`. These targeted
controls and the broader quoted-evidence and passive-question regressions pass;
they do not measure broad paraphrase recall.

## Reported natural-language chat failures

Command: `python3 experiments/v1_418_reported_chat_language_regressions.py`.

This scratch-chat regression checks source-only answers for the previously
reported Everest location, Alan Turing workplace, Eiffel Tower builder, and
active-question/passive-evidence cases. It also checks a source-backed yes/no
answer. The `Who built the Eiffel Tower?` case uncovered a route-order bug: a
review-only candidate for the compound source predicate `designed and built`
preempted the already-supported `built` question. Chat now applies the exact
question-evidence gate to that candidate sentence first, quotes it when the
predicate and roles are directly supported, and keeps extracted facts
unaccepted. The same corpus still sends `Who made the Eiffel Tower?` to review,
and abstains on the unlicensed `Where does the Serein River 0133 run?` and a
mismatched city identifier. The end-to-end experiment passes. This is a fix for
direct predicate containment and route order, not a synonym or open-domain
semantic parser.

## Citation-local topic grounding with competing antecedents

Command: `python3 experiments/v1_435_dialogue_visible_evidence_anchor.py`.

A varied corpus probe put the Eiffel Tower and Colosseum, and both
"It was completed" sentences, in the same paragraph. Initially the Colosseum
switch displayed the Eiffel Tower's 1889 sentence. Two changes address this:
the evidence gate checks only citations shown in the reply, and retrieval now
binds a sentence-initial pronoun to the nearest preceding explicit sentence
subject rather than any entity mentioned somewhere in the paragraph. The
same-paragraph transcript now selects 80 CE for the Colosseum, switches back to
1889 for the Eiffel Tower, and keeps both follow-ups on the current topic. A
constructed negative confirms an unseen 80 CE citation cannot license a
visible 1889 citation. The same work exposed a related plausibility failure:
"How many people could Italy hold?" quoted "Rome is the capital of Italy."
CRMS now abstains when a `how many` reply contains no quantity. The separate-
paragraph control and focused dialogue regressions `v1_412`, `v1_413`,
`v1_414`, `v1_423`, `v1_426`, `v1_427`, and `v1_418` pass on this working tree.
These are small authored fixtures; they test topic grounding and one answer
type, not broad coreference or semantic answerability.

## Current-topic binding for gendered and neutral follow-up pronouns

Command: `python3 experiments/v1_438_dialogue_topic_pronoun_context.py`.

The prior topic anchor handled neutral `it` follow-ups but still let a gendered
pronoun such as “he” probe older entities and source mentions. On a source-only
switch from the Eiffel Tower to Alan Turing, “Where did he work?” could ask the
user to choose among Turing, Bletchley Park, and the Second World War. A single
pronoun now binds to the explicitly current topic before checking which entity
happens to have answerable evidence. An explicit user-named topic also remains
available as dialogue context after the carried question fails, but that name
does not enter factual memory or establish evidence. The experiment verifies
the next pronoun resolves to the named target and that an unsupported question
still abstains without reusing the Eiffel Tower's date. A later switch to the
Sydney Opera House also stays anchored despite the earlier answerable topic.

This is a deterministic single-pronoun context rule, not general coreference.
Plural or multiple-pronoun turns still need candidate resolution or
clarification, and the source sentence must independently support the answer.
`v1_438` plus the established topic, persistence, citation, and transcript
regressions passed 10/10 in the focused runtime suite.

## Explicit topic-switch clause followed by a question

Command: `python3 experiments/v1_439_explicit_topic_clause.py`.

The natural multi-clause turn “Switch to the Sydney Opera House. Who designed
it?” previously reached retrieval as one malformed question. A bounded
directive parser now separates an explicit `Switch to <name>. <question>`
prefix, sets the named topic in dialogue state, and sends the question suffix
through the usual evidence path. The test confirms a cited designer sentence,
a later pronoun follow-up to the same topic, and refusal to reuse Eiffel Tower
evidence when the new name (Atlantis) is unsupported. The explicit topic is
context only; the parser neither accepts a fact nor generates a source.

The test uses explicit entity-bearing source sentences. It does not show that
retrieval can resolve arbitrary aliases or pronoun-only source sentences, and
the directive grammar covers only one bounded prefix form. The current
dialogue suite, including this experiment, passed 11/11.

## Failed entity follow-up must not leave a stale explanation target

Command: `python3 experiments/v1_419_failed_entity_followup_state.py`.

The source-only dialogue sequence moves from Eiffel Tower to Colosseum, then
tries the unsupported elliptical switch “And Italy?”. The turn remains
unanswered, but the prior Colosseum question had remained available to the
`why?` handler, which replayed evidence for the wrong conversational move.
When a named entity substitution has no grounded answer, dialogue now clears
the explainable-question pointer while retaining the last cited topic as a
candidate for repair. A source-backed named switch becomes the current topic
and asks what the user wants to know; a following “it” binds to that topic, and
“why?” cites only the latest source-only turn. The regression checks both
`CRMSDialogue.turn` and the interactive CLI in an isolated directory. It does
not claim that all elliptical topic changes are understood; unsupported
switches still need clarification or abstention.

The same sequence exposed a source-role error: “The Colosseum is … in Rome,
Italy” was accepted as an answer to “Where is Italy?” because the target name
and a locative phrase appeared somewhere in the sentence. The evidence gate
now requires the named WHERE anchor to precede the locative relation in the
sentence. It accepts the same evidence for “Where is the Colosseum?” and
rejects it for Italy, while the reported Everest and Turing location questions
remain supported.

Command: `python3 experiments/v1_420_where_role_variants.py`.

The WHERE role check also recognizes the bounded inversion “In the Himalayas
lies Mount Everest” and the correlative clause “Bletchley Park is where Alan
Turing worked”. It still rejects both a destination-only mention and a
same-entity sentence with no location relation, including “Italy is discussed
in The History of Europe”. A location preposition alone is not enough; the
sentence also needs a bounded location-bearing predicate. Typed “at which
institute” questions retain their narrower venue construction, and the prior
numbered-institute control still passes in `v1_329`. These are explicit
surface patterns, not general syntactic parsing; untested clause forms remain
outside the claim.

## Thirty-turn multi-topic dialogue transcript

Command: `python3 experiments/v1_427_dialogue_multiturn_transcript.py`.

Runtime replay on 2026-10-20 for `a00f863`,
using a fresh temporary source index and dialogue state. All 30 turns completed
without a crash. The Eiffel Tower → Colosseum switch kept the Colosseum's
`80 CE` and `50,000 spectators` evidence local; `why?` followed the capacity
answer; history recall updated after an unanswered turn; and the final `why?` did not reuse stale
evidence. Nearby regressions `v1_426` and `v1_419` also passed.

The transcript is a two-paragraph diagnostic, not a representative dialogue
benchmark. It exposed a mismatch between the active topic and a newly named
entity: an active-topic veto rejected a cited sentence whose preceding text in
the exact same paragraph named that entity. Paragraph-local anchoring now
allows the explicit “Who built the Eiffel Tower?” query to use “The tower was
designed and built by Gustave Eiffel.” The resulting topic remains Eiffel
Tower, so “Who designed it?” resolves to “Who designed Eiffel Tower?” instead
of drifting to Gustave Eiffel. A source-only “And Italy?” follow-up also sets
Italy as the current topic; “What is its capital?” now reuses that topic and
returns the exact “Rome is the capital of Italy” source sentence as review-
pending evidence, not an accepted fact. When “When was it built?” follows an
unsupported Analytical Engine query, CRMS asks which entity “it” refers to.
That open entity slot now survives save/reload; “What about the Eiffel Tower?”
supplies the referent and resumes the pending question through ordinary
retrieval, including when the user's entity name is lowercase. The source only
says that the tower was designed and built by
Gustave Eiffel, so CRMS shows that exact related sentence and does not turn the
completion date into a construction date. “When was it completed?” then returns
the cited 1889 sentence. An unrelated turn closes the open entity slot, and a
bare “and yes” is not treated as an entity. This remains a two-paragraph
diagnostic, not a representative dialogue benchmark;
it measures safe recovery, not broad conversational competence.

## Grounded math-to-list-code composition

Command: `python3 experiments/v1_356_grounded_math_list_composition.py`

The experiment learns exact `times` and `plus` operators from two examples
each. A natural-language code request maps `x times x plus 3` over integer-list
values. The generated standalone artifact returns `[19, 19, 7]` for
`[4, 4, 2]`; its exact scalar expression artifact, operator examples, list
contract, and four elementwise parity probes are retained in provenance. A
separate `x / 2` map preserves exact `Fraction` results. Unsupported operators,
extra variables, units, scalar-only formulas, booleans, and oversized lists
produce no usable map artifact or are rejected by its input contract. The
terminal path supports code generation, explanation, and evidence follow-up.
This is a bounded elementwise math→code composition, not general coding.

## Cross-domain list→math composition

Command: `python3 experiments/v1_357_cross_domain_list_math_composition.py`

This diagnostic learns two oppositely ordered sequence patterns using a
contrastive duplicate-only input, then applies the transferred sort→reverse
sequence before an exact learned `x*x+3` map. The request route also accepts
“and then” and “After [list stage], map … over each value” formulations; these
wording variants keep the same typed operations and evidence. The generated artifact returns
`[19, 19, 7, 4]` for `[4, 1, 4, 2]`, records list-stage, math-stage, and outer
composition provenance, checks both component artifacts and four composed
probes, and answers a polite function request followed by explanation and
evidence questions. The same learned sequence also composes with `x divided by 2`,
preserving exact `Fraction` outputs and the second formula's provenance.
It also transfers the learned connective to the unseen `remove duplicate
values then sort` pair before applying exact division. Missing list or math
support abstains. This checks a small cross-product of learned sequence and
math stages, not arbitrary task planning or broader coding parity.
The 2026-10-20 extension adds two unseen three-operation list sequences before
the math stage. On the untrained input `[4, 1, 4, 2]`,
`remove duplicates → sort → reverse → x*x+3` returns `[19, 7, 4]`; a different
ordering followed by exact division returns `[1/2, 1, 2]`. The regression
checks the three-operation order, composed validation probes, exact rational
results, and the same three-stage request through chat. This demonstrates a
bounded longer composition over already learned primitives, not open-ended
program synthesis or broad coding competence.
The chat response now identifies whether the unsupported component is the
list procedure or math expression, suggests a matching teaching/rephrasing
step, and clears stale generated-code context so an explanation follow-up
cannot describe the previous artifact. The diagnostic now checks each
conjunctive list operation independently when a composed request fails: an
unsupported middle operation is named as step 2 instead of being mislabeled as
an unsupported first step. If each individual operation is learned but the
exact sequence is not, it reports that the combination itself needs examples.
The chat transcript now exercises sort → rotate → reverse → math, confirms
that step 2 is named, and asserts that no generated artifact appears after
that diagnostic. This improves failure localization and integration coverage;
it does not change which procedures are licensed or generated.

The existing v1_355, v1_357, and v1_424 cases together provide bounded
evidence for unseen rule recombination, source/evidence lineage, contrastive
teaching, and chat recovery. They use small synthetic list and math fixtures,
so they do not satisfy the roadmap's source-disjoint generalization gate or
establish broad natural-language transfer.

## Elliptical entity-switch follow-up

Command: `python3 experiments/v1_161_dialogue_demonstratives.py`

After “What is the capital of France?”, the terminal accepts “And Italy?” and
answers “Rome” using Italy's stored fact and the previously licensed question
frame. The diagnostic also checks the resolved question and evidence in the
dialogue API and confirms that an unsupported entity prompts for a known
entity. Other parts of this diagnostic cover ambiguous demonstratives. This is
bounded entity substitution, not general conversational context handling.

## Natural follow-ups to quoted evidence

Command: `python3 experiments/v1_352_quoted_evidence_followup.py`

In a fresh terminal session, the same source-backed question is asked before
each of three follow-ups: “Why?”, “How do you know?”, and “Are you sure?”. All
three follow-ups return the previously cited sentence, identify it as quoted
evidence, and say it has not been accepted as a fact. This validates three
surface forms for one narrow source-explanation route; it does not establish
general conversational memory or confidence calibration.

## Portable dialogue-intent memory

Command: `python3 experiments/v1_383_dialogue_model_memory_packaging.py`

Portable model v5 can carry an optional, versioned dialogue-intent payload with separate
built-in-policy and learned-frame collections. The validator enforces a closed context-predicate
vocabulary, source citations for learned frames, held-out validation metadata, and disjoint train
and holdout conversation IDs. The experiment checks export, installation into the model sidecar,
chat startup, repacking, malformed-frame rejection, and legacy packaging without dialogue memory.
`experiments/v1_384_contextual_dialogue_frame_resolution.py` verifies that a held-out-validated
literal frame routes only when its context and predecessor match, its citation survives state
persistence, and train-only frames remain inert. Candidate induction is now available through
`experiments/v1_392_induce_dialogue_intent_candidates.py`; on the 563-turn single-Codex-label batch
it produced 13 exact-surface candidates, all inert, with citations and active-task context. An
offline check with `experiments/v1_393_evaluate_dialogue_intent_candidates.py` initially matched 2
of 48 classifiable turns (4.2%) in four disjoint Codex-labeled dev conversations. After expanding
the development sample to ten disjoint conversations and 124 classifiable turns, the same frozen
40-conversation training candidates matched 7/124 turns (5.6%); all seven agreed with the same
primary annotator, while 117 had no candidate. Typed active-task context prevented a
search-constraint candidate from matching a reservation answer. `experiments/v1_394_task_specific_intent_context.py`
checks that identical wording can select a search constraint or reservation intent according to the
active goal. Exact-surface candidate coverage remains too low for broad dialogue understanding.
These are single-annotator label-agreement diagnostics, not accuracy estimates, independent review,
or evidence of paraphrase transfer. No independently reviewed intent model is available.

### Broad-goal labels

The user-intent pilot now carries a separate `goal_intent` label. Codex supplied a provisional,
contextual primary-label pass for the 563 training turns and 200 dev/test turns across 16 disjoint
conversations. The labels track the active task across information requests and constraints; blanks
mean there is no task goal, while `uncertain` means the broader goal could not be established. No
second annotator reviewed this pass.

With the 40 training conversations frozen, goal-aware exact-surface induction still produced 13
inert candidates. On 192 classifiable dev/test turns, 12 matched (6.25% coverage). Act agreement
was 12/12; immediate-intent and broad-goal agreement were each 11/12 (91.7%). This is agreement
with the same Codex labeler, not independent accuracy. Low coverage remains the main result; broader
contextual generalization needs more work.

### Context-gated nearest-example dialogue baseline

`experiments/v1_406_contextual_intent_nearest_neighbor.py` compares labeled training turns by
content-word Jaccard similarity over both the current user wording and the most recent assistant
utterance. It requires exact dialogue-state, predecessor, and active-goal matches whenever those
fields are available; tied conflicting labels abstain and selected examples keep their citations.
This is an offline comparator only.

On the ten-conversation dev set, the development-only selection rule was to maximize coverage among
configurations with at least 80% joint act/task-intent agreement. It selected a 0.25 weight for the
assistant prompt and a 0.4 similarity threshold. That configuration selected 15/124 turns (12.1%),
with 13/15 (86.7%) joint act/task-intent agreement and 14/15 (93.3%) broad-goal agreement. The
exact-surface baseline selected 8/124 (6.5%) with 7/8 (87.5%) joint agreement. These remain
development results against the same single Codex annotator, with prior turn labels supplied as
oracle context. They suggest the preceding assistant wording adds useful context, but do not
establish held-out transfer or runtime quality.

A fresh conversation-held-out evaluation selected six previously unused test conversations before
transcript inspection (86 turns; 83 classifiable). The method and settings were frozen at threshold
0.4 and assistant-context weight 0.25. Codex labeled dialogue act, task intent, broad goal, context
state, and predecessor from the complete transcripts under the project protocol; the results are
therefore agreement with one named annotator, with prior context supplied as oracle input. The
nearest-example matcher selected 1/83 turns (1.2% coverage), and that prediction matched neither
act, task intent, nor broad goal. The exact-surface candidate baseline selected 0/83. This small
negative result means the development-selected lexical matcher did not transfer to this fresh
sample; it should not be routed at runtime. It does not establish that contextual intent modeling
is unhelpful: it indicates that content-word similarity plus simple hard gates is insufficient and
that context-sensitive dialogue needs broader, more discriminating representations and evaluation.
The labeled sheet, selection manifest, and machine-readable reports are in
`/tmp/crms_dialogue_feasibility_v1/`.

### Multi-turn history intent retrieval

`experiments/v1_407_context_history_intent_retrieval.py` adds similarity over cited prior speaker
turns to the v1_406 lexical baseline. It validates each character-offset citation against the
source turn, uses the latest assistant turn plus up to four prior turns, and keeps the same typed
context/predecessor/active-goal gates. The dev-selected setting (0.45 current-user, 0.15 latest
assistant, 0.40 broader history; threshold 0.4) covered 17/124 turns (13.7%) with 14/17 (82.4%)
joint act/task agreement. This improved dev coverage by two turns over v1_406 but lowered agreement
from 86.7% to 82.4%.

Before inspecting a second new test sample, the setting was frozen and six previously unused test
conversations were selected (69 turns; 66 classifiable). The history model selected 0/66. On the
same sample v1_406 selected 1/66 with agreement on that one turn; exact-surface candidates selected
0/66. Together with the earlier fresh sample, v1_406 selected 2/149 classifiable turns and matched
1; exact candidates selected 0/149. This is evidence that longer lexical context did not solve
generalization at these thresholds, not evidence against explicit contextual modeling as a whole.
The next experiment should represent discourse state directly (for example, open options,
referents, expected slot, task phase, and goal transitions) and evaluate it on a new frozen sample.
All results are agreement with one Codex primary annotator; no independent reliability estimate is
available.

### Runtime intent routing with supplied context

`python3 experiments/v1_395_runtime_intent_oracle_context.py USER_TURNS.csv` replays labeled turns
through the hand-checked router, supplying the annotated context state, preceding assistant question,
and prior labeled active-task intent. On the ten-conversation development set (124 classifiable
turns; seven uncertain), the prompt/slot rules produced 63 hypotheses (50.8% coverage), with
48/63 (76.2%) joint act-and-intent agreement. Adding explicit assessment acknowledgements found
in the development labels raised this to 67 hypotheses (54.0% coverage) and 52/67 (77.6%) joint
agreement; 65 were selected, 2 ambiguous, and 57 abstained. Selected-turn joint agreement was
52/65 (80.0%). A later dev-v4 pass added handling for affirmative answers that include preference
details, preference-oriented prompts, and short detail answers during an information-seeking task.
Coverage stayed at 67/124; joint agreement rose to 56/67 (83.6%), and selected-turn agreement to
56/65 (86.2%). Four previous mismatches became matches, with no new mismatches on this same dev
sample. The context-free ablation hypothesized 37/124 (29.8%) and matched 26/37 labels (70.3%).
These are **development-set fit**: the prompts and labels from these
conversations guided the rules, so this is not held-out generalization. The labels and context come
from one Codex annotator, with no independent review. The changes remain hand-checked phrase rules,
not learned generalization; frozen exact-phrase candidates still cover only 5.6%. Longer-term work
should induce dialogue-act and task-intent frames conditioned on typed question/slot and active task,
while preserving ambiguity and abstention.

The original replay inferred yes/no versus detail answer type from the coarse annotated context
state. `python3 experiments/v1_401_transcript_question_type_replay.py USER_TURNS.csv` instead uses
the latest assistant utterance to infer question type and slot, matching the runtime's prompt-based
typing. It still takes open-question presence, predecessor act, and prior active-task intent from the
annotations, so this remains a partial-oracle replay. On dev-v4 it hypothesized 68/124 turns (54.8%),
selected 63, and matched both labels on 52/68 (76.5%); 5 were ambiguous. The different method
changes coverage and abstention, so its scores are not directly comparable with v1_395.

After further dev-only changes to question typing and preference/reservation answers, the same
transcript-derived replay at commit `ea523b1` hypothesized 66/124 classifiable turns, selected all
66, and matched both labels on 58/66 (87.9%); it abstained on 58. The preceding transcript-typed
replay at `144f8c9` matched 52/68 (76.5%). These are in-sample results: the same development labels
guided the new rules. The replay still receives annotated open-question presence, predecessor act,
and prior task intent, so it is not end-to-end performance or independent accuracy. Remaining
disagreements suggest that active task intent does not yet distinguish a user's broad goal from a
current subgoal, such as selecting a restaurant during a reservation flow.

### Frozen contextual-intent test pilot

After commit `5afd9f5`, six complete conversations were labeled from the source corpus `test` split
and replayed without further code changes. The pilot selection was the first six test conversations
by source order with 8–18 user turns (not a random sample); it contains 66 classifiable turns and
two uncertain turns. With annotated context supplied, the frozen router produced 31 hypotheses
(47.0% coverage): 29 selected, 2 ambiguous, and 35 abstentions. Joint agreement with the same
Codex labeler was 21/31 (67.7%) among hypotheses and 21/29 (72.4%) among selected turns. A
context-free comparison produced 16 hypotheses (24.2%) and 10/16 exact label matches. Frozen
train-only exact-phrase candidates matched 1/66 classifiable turns (1.5%). These are provisional
single-labeler agreement results on a small, domain-specific, non-random pilot—not accuracy, a
large-scale dialogue benchmark, or evidence of parity with a 70B-class assistant.

The mismatches identify useful next research questions: preference answers such as “Low-price drinks
if anything” still fall through to generic clarification; “Sure” without an open assistant question
is marked uncertain rather than acknowledged; a reservation goal can start inside a search task;
and “Can you tell me how late ...?” is classified as a request-action rather than a question. Keep
this test set frozen. Any changes motivated by these cases must be developed on train/dev data and
checked on a later untouched test sample. The test labels were supplied by Codex under user
authorization and have no independent human review. Subsequent phrase-rule changes were developed
against dev labels; the pilot metrics above apply to commit `5afd9f5`, not the current code. No
post-change result is claimed by this first pilot.

### Second frozen contextual-intent test pilot

A second disjoint set of six complete conversations was selected in source order from the remaining
Taskmaster-1 test split after the first pilot, using the same 8–18 user-turn window. The 69 turns
include one uncertain label; all 69 cited record hashes and exact utterance spans verified, and IDs
were checked against train, dev, and the first test pilot. Before the later dev-only preference-
intent change, the replay at `8bd3b69` hypothesized 31/68 classifiable turns (45.6%), selected
all 31, and matched both labels on 23/31 (74.2%). The context-free comparison hypothesized 13/68
(19.1%) and matched 12/13. The inert train-only candidate memory matched four turns (5.9% coverage),
all four agreeing with the provisional labels; it remains inactive at runtime.

A follow-up replay used the transcript-derived question typing and the later dev-only code at
`144f8c9`. It hypothesized 35/68 turns (51.5%), selected all 35, and matched both labels on 25/35
(71.4%). The context-free comparison again hypothesized 13/68 and matched 12. This replaces neither
the original v1_395 result nor the labels: it is a second analysis of the same small sample using a
more realistic question-type source, while open-question presence, predecessor act, and preceding
active-task intent remain supplied by the provisional annotations. The updated result still does not
measure a fully autonomous transcript replay or independent accuracy. It yields four more hypotheses
and two more label matches than the earlier replay, but a lower match rate among hypotheses; this
shows that higher coverage alone does not resolve contextual intent. No code was tuned from this
replay; keep the sample frozen for future development.

These results are provisional agreement with one Codex annotator, not accuracy or independent
validation. The sample is small and non-random, and the runtime replay was given annotated context
state and predecessor acts, so it is not end-to-end performance. The higher context-free agreement
rate is based on only 13 predictions. Keep this sample frozen; the later preference-intent change
was developed and measured on dev data only. Label and output files are in
`/tmp/crms_dialogue_test_v2`.

### Contextual task goal and subgoal state

`python3 experiments/v1_402_task_goal_subgoal.py` checks the current task hierarchy in both direct
dialogue and the actual CLI. It covers explicit reservation requests, distinguishes an information
question about making reservations, and replays a Taskmaster-1 development turn asking for a
restaurant's phone number while a reservation is active. The phone-number request remains the
immediate `seek-information` intent; the broad `make-reservation` goal remains active and the
information request becomes a subgoal. Without an active parent, the same utterance establishes
`seek-information` as the goal. The experiment also checks search constraints, save/reload, invalid
state rejection, `/intent` display, and reset behavior. A mixed turn that commits to a reservation
while requesting the address records `make-reservation` as `goal_intent` and `seek-information` as
the immediate `task_intent`. All checks pass. These are controlled mechanism checks using
Codex-authored labels, not held-out dialogue accuracy or a general task hierarchy result. The current
vocabulary covers only constraint, information-seeking, and availability subgoals; the system has no
arbitrary goal stack or learned task decomposition.

## Contextual intent: active task and expected slot

Command: `python3 experiments/v1_390_contextual_intent_task_slot_diagnostic.py USER_TURNS.csv`

On the 563-turn, 40-conversation single-Codex-label feasibility batch, there were eight repeated
normalized user surfaces with multiple annotated act/intent pairs. A coarse partition by
`context_state + predecessor_act` put six surfaces into internally consistent context buckets;
the exploratory `active task + expected slot` signature also put six there and reduced rows in
conflicted buckets from 10 to 9. The remaining ambiguous surfaces included “yes” and “San
Francisco, California.” The features are small lexical cues from the latest assistant turn and
recent user statements. This is descriptive label-consistency evidence only; it does not establish
label correctness, held-out generalization, or improved runtime intent recognition.

The follow-up implementation stores a typed expected slot on each open assistant question and
exposes predicates such as `awaiting_slot_location` to the portable dialogue-frame matcher.
`experiments/v1_388_open_dialogue_question_state.py` checks slot inference, persistence, migration
from state format 14, context-conditioned frame selection, and retention of six supported
user-provided task-slot values in session state. It verifies those values stay separate from facts,
survive reload, and clear on full reset; direct “What time did I give you?”-style questions return
the saved value and its original clarification prompt. Missing values abstain without falling
through to factual retrieval. Explicit slot-named corrections update the saved value and retain the
correction utterance; if no value exists, CRMS asks for the named detail. Arbitrary turns are not yet
parsed into slots.

## Balanced phrase recombination from three demonstrations

Command: `python3 experiments/v1_354_balanced_phrase_recombination.py`

Two balanced 2×2 phrase grids tested whether a single held-out combination can
be recombined from three same-operation examples:

| Trained phrases | Held-out phrase | Teaching orders | Held-out inputs correct | Wrong | Abstained |
|---|---|---:|---:|---:|---:|
| reverse list, reverse values, invert values | invert list | 6 | 18/18 | 0 | 0 |
| reverse list, invert list, invert values | reverse values | 6 | 18/18 | 0 | 0 |

The held-out inputs include an empty list, negative values, and repeated values.
Every prediction cites all three teaching phrases. Across all orders, the model
abstained on 48/48 controls containing an unseen operator, an unseen object,
reordered words, or an unsupported inserted modifier. This is evidence of
position-based verb/object recombination with familiar terms after only three
demonstrations, and it is invariant to order for these two specific crossings.
It does not establish transfer to synonyms, unseen vocabulary, or open-ended
requests. In particular, the broader 4×4 grid in `v1_242` intentionally has
unbalanced early examples: its first four phrases contain four distinct verbs
and four distinct nouns, so those examples do not independently repeat the
word roles. Read the two learning curves together; the example arrangement is
part of the measured condition. The experiment also creates overlapping
reverse/sort language grids where an unseen phrase fits both behaviors; CRMS
returns `need_examples` with conflicting token and bigram evidence instead of
choosing one operation. The 12 unambiguous held-out phrases also pass through
the standalone Python renderer: all artifacts execute, pass parity checks,
preserve all three training phrases in provenance, and use the retrieved
procedure. Generated artifact IDs are stable across all teaching orders for
each crossing. The unsupported `flip` operator and the ambiguous reverse/sort
cross do not produce code. This is a bounded end-to-end composition check, not
open-ended software generation.

## Learned sequence connective to natural-language code generation

Command: `python3 experiments/v1_355_learned_sequence_connective_codegen.py`

Five base phrases teach sorting and reversal for two object phrases and
duplicate removal for a third. Two separate compound instruction patterns
then establish order-sensitive uses of `then`. For both compound rules, six
all-distinct inputs initially leave two procedures consistent; CRMS requests
`[0, 0]`, and the teacher's output resolves the ambiguity. A control with
only one grounded compound still abstains on new sequence crossings, including
the new operation pair. With two compound contexts, the held-out instruction
`sort the list then reverse the list` produces `[4, 4, 2, 1]` for the input
`[4, 1, 4, 2]` through the learned `then` connective.

The standalone code artifact executes and passes its parity cases. Its
provenance retains the two component phrases and both compound examples. The
actual chat CLI accepts `Write Python code to sort the list then reverse the
list`, then answers `Explain that code` and `Show the examples for that code`
from the generated artifact. With no example of the unique→sort pair, the same
learned connective also composes “remove duplicate values then sort the list”
and generates executable code returning `[1, 2, 4]` for `[4, 1, 4, 2]`; the
artifact cites both component procedures and both connective examples.
At the default composition depth, the same grounded procedures also answer
“remove duplicate values then sort the list then reverse the values” with
`[4, 2, 1]`. This phrase was not taught directly; its generated code passes
the artifact's examples and retains all three component phrases plus both
connective examples. Exact sort/reverse normal forms merge equivalent
segmentations, while magnitude sorting remains distinct. This advances
bounded three-clause recombination, not arbitrary task planning.
Unsupported connective, operation, and modifier variants abstain and produce
no code. This is reusable composition over known list procedures, not zero-shot
programming or broad natural-language understanding. The control flow and
evidence counts are local CRMS results; no external 70B model was run on this
fixture.

## Cross-surface question transfer v1

Command: `python3 experiments/v1_315_cross_surface_question_transfer.py`

This deterministic diagnostic uses six synthetic relations, 12 invented entity pairs per
relation, two entities to license question frames, and 10 held-out entity pairs. Correctness
requires the expected answer and its held-out source fact. Transfer additionally requires either
that the matched template corresponds to a licensed explicit question frame or that the answer
contains a language-derivation trace. Direct or built-in answers are counted separately. The
second full run must reproduce the same rows.

| Regime (`k`) | Canonical B/T held-out accuracy | Additional taught G frames | Correct untaught S/P/L answers | S/P/L with frame/derivation trace | Untaught S/P/L cases | Transfer ratio | Wrong near-misses |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 (no question-frame teaching) | 20/60 | 0/0 | 30 | 30 | 300 | 0.300 | 0 |
| 1 | 60/60 | 0/0 | 120 | 120 | 300 | 0.400 | 0 |
| 2 | 60/60 | 60/60 | 120 | 120 | 300 | 0.400 | 0 |
| 3 | 60/60 | 120/120 | 120 | 120 | 300 | 0.400 | 0 |

At k=0, 20/60 canonical cases and 30/300 untaught S/P/L cases answer through existing derived
language routes without question-frame examples; this is the untrained baseline, not learned-frame
transfer. At k=1, explicit teaching yields 60/60 canonical T and 120/300 untaught S/P/L cases. The
G results make entity-slot transfer from each additional taught frame visible: all 60
held-out examples at k=2 and all 120 at k=3 answer with the correct source and a licensed-frame
trace. The separately worded, untaught S/P/L results remain at 120/300; all 120 successes have a
frame or derivation trace and none are direct/built-in answers. The ratio stays at 0.400 as more
explicit frames are taught, showing that the added frames have not generalized to the independent
paraphrase and synonym sets. A grounded `has + regular -ed` perfect-aspect transformation now
answers the tested `Who has discovered ...?` surface form. The other tested paraphrases and lexical
synonyms still abstain. Near-miss questions produced no wrong answers in this fixed set. These
results measure this benchmark only; they are not a general language score. Preserve the detailed
per-relation route rows by running the command when comparing a change.

A separate grounded rule-transfer check passed: two fact-backed examples of `Who is the creator
of {object}?` licensed the regular nominal-to-verb frame `Who created {object}?`. The held-out
answer cited its own accepted fact, while the unlicensed synonym `Who crafted ...?` abstained. The
answer now includes a `language_evidence` record naming the stem rule and the two licensing source
facts. This narrow transfer is deliberately reported separately from broad paraphrase coverage.

A second grounded transfer check passed for a predicate phrase explicitly aligned by examples:
two accepted sentence frames using `made` as the surface form of canonical relation `created`
licensed `Who made {object}?` for a held-out entity. One example alone did not license the transfer;
after the second, CRMS cited the held-out entity's fact and reported both licensing sources in
`language_evidence`. The unrelated `Who crafted ...?` form still abstained. This is the supported
route for learning a lexical relation form, not zero-shot synonym guessing.

The benchmark also checks regular perfect aspect independently: two examples of `Who discovered
{object}?` license `Who has discovered {object}?` for a held-out entity. Its trace names the
licensed and derived frames and the example facts. `Who has destroyed ...?` remains unanswered.

The same source-backed `made` alignment now transfers through do-support into the infinitive in
`What did {subject} make?`, starting from two examples of `What did {subject} create?`. The
held-out answer cites its own fact and carries an `irregular_do_support_question_transfer` trace
back to both licensing sources. One example does not license the transfer; `craft` and a
subject/object role swap remain unanswered. This exercises recombination across argument roles
and grammatical form while keeping the relation mapping evidence-bound.

Two licensed examples of the active sentence pattern `<subject> made <object>` derive both
`Who made {object}?` and `What did {subject} make?`, without teaching either question frame. Two
examples of the passive pattern `<object> was made by <subject>` likewise derive `Who was {object}
made by?` and `What was made by {subject}?`. Held-out questions cite their accepted facts and
trace the derived frame to the source-backed training pairs. One pattern example is insufficient;
unsupported synonyms and role swaps abstain.
The active pattern also licenses passive questions (`Who was {object} made by?`, `What was made
by {subject}?`) when the observed predicate has a bounded past-participle form. These forms trace
to the active pattern examples; passive sentence examples are not required for this narrowly
mechanical voice transformation. The converse is also supported: two passive examples derive
active questions, including the irregular `seen` -> `saw` and `What did {subject} see?` forms.
Passive frames are generated only for regular `-ed` participles or listed participles, so an
active past form such as `saw` is not accepted as the participle in `was saw`.
The generated frames are rebuilt from active source evidence, survive a save/load round trip, and
disappear when their training facts are retracted. The persistence check uses a SQLite-backed
knowledge store containing 2,000 unrelated facts, so indexed fact retrieval is exercised alongside
the derived language frame.

The benchmark also drives the actual CLI in a fresh temporary directory: three cited `/teach-fact`
inputs, then the held-out `Who made ...?` and `What did ... make?` questions, without question-frame
teaching. CRMS realizes both as `Rila Sen made Tavor Engine.` and cites the accepted held-out fact.
This guards the chat path in addition to the direct `ask()` checks above.

### Exact-title writer routing on the large index

`Who wrote Hamlet?` exposed a route collision in the full SimpleWiki index. The academic-paper
author lookup treated an ordinary book title as a paper, and the generic quoted-evidence gate
later preferred a lexical match about Saxo Grammaticus writing the story that inspired Hamlet.
The paper-only route now requires an academic-source cue or an explicit authors request, and a
successful exact-title writer route is preserved after its source and roles have been checked.
The cited Hamlet page now answers `Shakespeare wrote Hamlet.`; the Saxo sentence no longer
overrides it. `experiments/v1_290_irregular_who_passive_source.py` covers the CLI route with
Frankenstein, Hamlet, and Mona Lisa, while the 285,478-document index replay confirms the real
page result. This is a bounded exact-title and listed-irregular-verb realization, not a general
author synonym rule; the answer remains quoted source evidence awaiting review as a fact.

A second CLI session learns only passive patterns and asks four active/passive subject/object
questions. All four realize the answer as `Tavor Engine was made by Rila Sen.` and cite the
held-out accepted fact; no question frames are taught.

### Explicit compound question clauses

`experiments/v1_339_explicit_compound_chat_questions.py` reproduces a chat miss where
“Who created Python? Also who developed Linux?” returned only the second clause. The runtime now
queues repeated, explicit question clauses independently and labels their replies “Part 1 of 2” and
“Part 2 of 2.” The fixture answers both from the correct source sentences. A second clause joined
with `and` is also split only when it starts with another question form. A second fixture asks
“Who developed Linux? Also where was he born?”; its unique cited source parse binds `he` to Linus
Torvalds and the birthplace route returns exact-title Helsinki evidence. Shared-verb coordination
(“Who created Python and Linux?”) is not split and remains covered by
`experiments/v1_325_coordinated_who_lists.py`, which passes its answer-or-disclose-missing checks.
The explicit-clause test also checks a supported first clause followed by an
unsupported “Who developed Minix?” clause: CRMS answers the first, labels and
processes the second, and reports that the request was only partially
supported.
That fixture also pairs an exact title containing a conjunction (“Research and Development”)
with a shorter title (“Research”); exact-title lookup keeps the longer entity intact and prevents
a misleading partial list answer.
This is a bounded clause-preservation and one role-grounded pronoun-transfer result; it does not
cover ambiguous or non-Who antecedents or report an aggregate count of successfully answered parts.

The first run exposed an `IndexError` for a question-frame candidate with an empty prefix in
`crms_knowledge.py`. The candidate generator now guards that access; the no-entity near-miss
`Who is a parent?` remains in this benchmark.

An explicitly supplied, fact-backed passive question example can now extend an already licensed
relation and answer role. `experiments/v1_317_additional_passive_question_frame.py` teaches one
passive form from a third accepted `created` fact after two active examples licensed that relation;
the new passive frame answers for a separate fourth entity and survives save/load. The test does
not license a new relation from one example: the relation and answer role must already have an
independently licensed question frame.

`experiments/v1_319_additional_synonym_question_frame.py` exercises the corresponding lexical
learning path. One additional, explicitly labeled example maps `Who made {object}?` onto the
already licensed `created` relation. CRMS answers the same wording for a separate entity after
save/load, while `Who crafted ...?` still abstains. This demonstrates user-directed transfer from
one grounded example under an existing relation license; it does not demonstrate automatic
synonym discovery or broad lexical-semantic coverage.

## Zero-frame corpus relation learning

Command: `python3 experiments/v1_245_zero_frame_corpus_learning.py`

The diagnostic starts with no taught relation frame, finds repeated claims in indexed source
sentences, and checks report-only proposals before explicit acceptance. It verifies separate
documents, distinct subjects and objects, citation revalidation, and that acceptance adds usable
facts only after review. A narrow named-subject + lowercase-object pattern now discovers claims
such as `Marie Curie discovered radium` and `Ernest Rutherford discovered polonium`; the two
examples yield a review proposal and accepted facts answer their corresponding questions.

The corpus learner may also group passive evidence with an already supported inflectional
relation only when the by-phrase parser provides agent/patient roles and an independent
morphology rule maps the surface verb to that canonical relation. Unsupported passive parses
remain excluded. In the same runtime diagnostic, inflected positive/negative claims, typed versus
untyped questions, conflicts, in-memory/SQLite parity, pagination, provenance, and CLI review all
pass. The proposal stage never writes facts; `accept_corpus_relation_frame` rechecks the citations
and unique parses before transactional acceptance. Run the command to reproduce the current
result; it reports `PASS`.

These safeguards make lowercase-object extraction a proposal path, not a semantic license. The
remaining risk is that a repeated but malformed sentence pattern can still produce a plausible
candidate, so review is mandatory and negative/near-miss source fixtures should continue to grow.

A read-only pilot on the local 2.05 GB SimpleWiki FTS index scanned eight 125-document windows
(1,000 of 285,478 documents) in 1.22 s and found four recurring frame shapes: `is-a`, `born in`,
`married to`, and `plays`. A malformed clipped candidate (`Thompson was born in St.`) exposed a
sentence-boundary error at the abbreviation `St.`. The sentence splitter now keeps `St.
Petersburg` and similar title/place abbreviations intact; rerunning the same sample produced no
lowercase object equal to the truncated token `St`. The sample remains systematic rather than
random and is not a precision estimate. Some sources can themselves contain bad claims (for
example, a biographical source said someone was born in a political party), which reinforces why
corpus proposals remain review-only.

The installed SimpleWiki index contains 285,478 documents and 591,889,415 characters of source
text in a 2.05 GB SQLite file. As an end-to-end learning check, a 125-document window at offset
150,000 produced a `plays` frame with 15 distinct subject/object examples from independent
documents. After accepting that proposal in a temporary in-memory knowledge base, `Who plays Tina?`
answered `Cameron Diaz` and `What does Cameron Diaz play?` answered `Tina`; both cited the source
fact from the original index. The SQLite file's size and modification time were unchanged. This
demonstrates source-backed question/recombination behavior on a real corpus, not equivalent
coverage to a 70B-parameter model; knowledge volume and task coverage need their own targets and
benchmarks.

## Source-backed rule discovery at SQLite scale

Command: `python3 experiments/v1_307_sqlite_rule_discovery_scale.py`

The diagnostic seeds two independent examples of a `parent + parent -> ancestor` rule among
unrelated facts, then compares deterministic candidate discovery in memory and in the SQLite
knowledge database. Candidate structure, evidence, source independence, expansion count, and
negative/cross-scope pruning are checked for parity.

| Facts | Candidate-search expansions | In-memory median | SQLite median |
|---:|---:|---:|---:|
| 20,006 | 2 | 215.58 ms | 29.58 ms |
| 100,006 | 2 | 1,316.82 ms | 152.78 ms |
| 300,006 | 2 | 3,550.20 ms | 497.64 ms |

After discovery, the diagnostic also validates the rule against two independent held-out source
documents, explicitly accepts it, and uses it to derive a new entity chain. That full learning,
validation, acceptance, and recombination path passes for both in-memory and SQLite stores at each
size. Candidate structure, evidence, source independence, proof status, expansion count, and
negative/cross-scope pruning are checked for parity.

The 300,006-fact run exposed a separate inference issue: a global lexical candidate cap let
unrelated entities displace a query's actual intermediate. The cap now applies to narrowed
query-relevant candidate sets; direct endpoint indexes can prove a complete absence without
enumerating unrelated entities. `experiments/v1_321_reasoning_effort_budgets.py` checks that a
genuinely broad recursive search still reports the candidate cap. These timings are from one local
run and are a scale diagnostic, not a throughput guarantee. They do not establish full inference,
language learning, or retrieval performance at 70B-model-comparable knowledge scale; those need
separate corpus and workload benchmarks.

## Composed polar questions over large SQLite fact stores

Command: `python3 experiments/v1_305_compound_question_scaling.py`

The benchmark stores two supported claims among unrelated SQLite facts and asks the composed
question `Did Ada design Engine and build Loom?`. It checks the exact answer, truth value, source
provenance, and deterministic repeatability. The measured warm-run medians were:

| Total SQLite facts | Before indexed evidence lookup | After indexed evidence lookup |
|---:|---:|---:|
| 1,002 | 17.51 ms | 0.47 ms |
| 100,002 | 1,769.04 ms | 12.04 ms |
| 1,000,002 | 17,808.65 ms | 127.40 ms |

The profile identified full-table decoding and tokenization while checking stored polar evidence
and closed-world relation metadata. SQLite-backed exact-triple lookups now retrieve only the
matching evidence rows; closed-world declarations use the relation/object index. A 100,000-fact
profile dropped from 26.1 million calls and 5.24 seconds under profiling to 4,250 calls and 16 ms,
with the same `Yes` result. These are single-machine, warm-cache synthetic results, not a guarantee
for cold storage or source-text retrieval. They show the composed-question path stays below 200 ms
at one million facts for this sparse workload.

## Thorough retrieval relation check

Command: `python3 experiments/v1_323_thorough_retrieval_plausibility_benchmark.py`

The 50-question synthetic set asks for an award count for 50 distinct numbered people. Half of
the source sentences state that the person won awards; the other half state that they received
awards, which does not establish that they won them. Before the entity-boundary fix, the numeric
suffix was dropped from names such as `Person 0`, making the questions ambiguous or ungrounded.
The gate now keeps numeric suffixes as part of the named mention.

| Mode | Correct | Wrong | Abstained |
|---|---:|---:|---:|
| Quick | 25 | 25 | 0 |
| Thorough | 25 | 0 | 25 |

This confirms that the thorough relation check can suppress lexical-confound errors while
preserving supported answers on this controlled set. It is not a general retrieval accuracy rate;
the set is synthetic and restricted to one entity/relation pattern.

## Rule-candidate support coverage

Command: `python3 experiments/v1_316_rule_coverage_ranking.py`

The fixture creates 20 distinct endpoint pairs supported by the same two premise relations.
One candidate conclusion is present on 2 pairs and another on 18. Both remain labeled
`uncontradicted` because status describes contradiction and independent-source checks, while the
reported coverage distinguishes their observed support and ranks the broader candidate first.
The incomplete-search case reports coverage as unavailable instead of treating a partial search
as a complete denominator.

| Candidate conclusion | Positive support | Eligible premise pairs | Coverage | Rank |
|---|---:|---:|---:|---:|
| trusts | 18 | 20 | 90% | 1 |
| admires | 2 | 20 | 10% | 2 |

Coverage is a descriptive ranking signal, not a rule acceptance criterion. Rule review still
requires independent evidence and held-out validation.

## Structured source-field evidence

Command: `python3 experiments/v1_318_infobox_field_evidence.py`

The deterministic fixture checks that exact-title `designer = ...` and `capital = ...` fields can
answer bounded agent and capital questions. Replies cite the exact field and label the answer as
structured evidence rather than an accepted fact. The fixture interleaves unlabelled continuation
lines, checks that `manufacturer` does not answer `Who created ...?`, and verifies that conflicting
exact-title records abstain. Read-only spot checks using the actual SimpleWiki Python and Germany
pages answered `Who designed the Python programming language?` and `What is the capital of
Germany?` from their `designer` and `capital` fields; only those pages were copied into temporary
test indexes, so this does not measure full-corpus retrieval quality.

## Title definitions, count phrases, and category superlatives

Command: `python3 experiments/v1_332_title_count_superlative_grounding.py`

The exact-title definition route now selects the first assertion that defines the exact topic in
the page lead, rather than rejecting a page because the same topic has several compatible
definitions later. The count parser looks for the quantity within the final few tokens before the
asked item, so modifiers such as `little` in `two little moons` do not hide the number. Count
evidence runs at standard and thorough effort; standard replies stay concise, while thorough can
show the plausibility result. A bounded superlative route handles direct forms such as
`Which planet is largest?` only when one exact-title page says `TITLE is the largest CATEGORY`.
Ordinal and qualified near-misses such as `third largest chain` and `largest celestial body to be
so` do not match.

The temporary SQLite fixture checks answer selection, citation validity, near-miss rejection, and
the CLI at standard effort. A read-only chat replay against the installed 285,478-document
SimpleWiki index returned the Photosynthesis lead definition, a cited sentence stating Mars has
two moons, and Jupiter's sentence naming it the largest planet. The superlative search uses a
bounded 250-hit query, so it is not a general ranking or comparison engine. These paths quote
source evidence and do not promote it to accepted facts.

## Corpus frame-quality gates

Command: `python3 experiments/v1_326_corpus_frame_quality.py`

Corpus-only frame discovery now rejects extraction shapes too weak to license reusable rules:
pronoun subjects or objects, coordinated clauses flattened into one object, dangling `example`
complements, relative-clause material absorbed into a class phrase, clipped copular postmodifiers,
discourse openings and temporal phrases parsed as subjects, capitalized common nouns after
determiners (`an EP called X`, `the TV series X`), and two-endpoint `connect ... with ...` clauses
collapsed to one object. These sentences remain searchable evidence; the gates apply only to
induced rule proposals. The synthetic fixture retains valid repeated `is-a` and active-verb frames.

A read-only spot check over 1,000 documents and up to 20,000 sentences in the local SimpleWiki
index completed in 0.54 seconds and returned three reviewable frame proposals. Before the
additional gates, the same sample returned six, including pronoun-led, coordinated, and clipped
frames. The 21 retained `is-a` examples were individually inspected; some still contain source
grammar or semantic oddities, so proposals remain review-only and are not accepted facts. This
bounded sample is a quality diagnostic, not a precision estimate for the complete corpus.

After widening the gates to exclude quoted titles, timeline-prefixed claims, passive-agent role
reversal, preposition-only predicates, numeric fragments, and overlong predicate spans, a
read-only 10,000-document / 200,000-sentence sample completed in 4.51 seconds. It yielded 19
review proposals containing 422 evidence rows. The sample included useful candidates such as
`born in`, `based in`, `acquired`, and `is-a`, while excluding the observed `across`, `armies`,
passive `adopted`, `versus`, and `years` boundary errors. This still leaves 368 `is-a` evidence
rows that require review; the 19 proposals are not an acceptance rate or a corpus-wide precision
estimate.

## Controlled `is-a` article agreement

Command: `python3 experiments/v1_328_article_agreement_realization.py`

The writer now adjusts `a`/`an` in an already licensed `is-a` sentence frame using a small
deterministic English onset rule and explicit exception prefixes (`hour`, `honest`, `university`,
`European`, etc.). It changes only the surface article; it does not create a fact, change a
relation, or license a sentence frame. The fixture checks both directions of transfer, the
two-varied-example licensing threshold, and persistence. This is a bounded English rule, not a
pronunciation dictionary; ambiguous initialisms and non-English agreement remain unsupported.

## Bounded real-corpus predicate discovery sample

Command: `python3 experiments/v1_331_real_corpus_alignment_sample.py`

The read-only diagnostic sampled four 1,000-document windows (offsets 0, 25,000, 75,000,
and 150,000) from the local 285,478-document SimpleWiki index, processing at most 12,000
sentences per window. After rejecting candidates whose grammatical subject was resolved only
from the article title, the current checkout found 1, 3, 1, and 5 repeated relation frames
respectively, and no cross-predicate alignment proposals in any window. It accepted no rules
and made no index writes. The 2026-10-20 rerun after sentence-boundary changes passed the
read-only sampler in 4.86 seconds.

This is evidence that the strict shared-subject/object alignment path has low yield in these
bounded samples, not evidence that the corpus contains no useful paraphrase pairs. Windows are
not exhaustive, and the frame counts are not precision estimates. The `born in` examples also
show sentence-level extraction relying on article context (`He was born in Swansea`), so proposed
rules must retain exact source citations and remain reviewable. Corpus frame mining now excludes
such page-title substitutions because they do not establish the pronoun antecedent strongly
enough for reusable language rules. A read-only inspection of the Ban Ki-moon source also found
that “U.S.” and the following middle initial in “John F. Kennedy” had been treated as sentence
punctuation, yielding a truncated meeting candidate. Sentence splitting now keeps dotted
initialisms with their continuation and middle initials with surnames; on rerun, the complete
sentence is preserved and that under-specified “met → U.S.” frame is no longer proposed.
`v1_457_dotted_initialism_sentence_boundaries.py` checks those boundaries and exact source spans.
Treat this as a motivation to improve corpus candidate recall and context validation together;
do not lower the independent-pair or human-review requirements based on this sample.

## Structured-field supervision probe for predicate learning

Command: `python3 experiments/v1_337_structured_prose_alignment_probe.py`

The read-only probe paired five explicit infobox fields (`birth_place`, `capital`, `designer`,
`creator`, `author`) with complete sentences that mention both the page title (or its final title
token) and field value. It scanned all 285,478 pages in three sequential windows and found 40,979
field rows, 4,047 joint mentions, 68 role-compatible parses, and 50 exact canonical-relation
matches. The strict probe found one repeated novel predicate group: `capital city of` aligned with
`capital of` on eight distinct entity pairs. Other repeated groups used the canonical wording.

The production API path, with a 40,000-sentence budget, found a 12-pair `capital city of` group
and one unsupported conjunctive candidate (`capital and largest city of`). The latter is excluded
because CRMS does not preserve that coordination in the generated question form. Explicit
acceptance learned from nine training pages and passed three held-out pages: Sicily → Palermo,
Papua New Guinea → Port Moresby, and Iceland → Reykjavík. Each answer matched the learned question
frame `what city is the capital city of {object}` and retained evidence from its held-out page.
The chat CLI uses its default 20,000-sentence budget and found 11 pairs (eight training, three
held-out); an end-to-end CLI run explicitly reviewed and accepted that proposal, then answered
“What city is the capital city of Iceland?” with “Reykjavík is the capital city of Iceland.” The
learned question form answered from the knowledge DB without the source index lookup. The CLI
requires explicit review and can scan larger windows with `/suggest-corpus-alignments OFFSET|MAX_DOCS`.

This demonstrates one useful structured-field supervision route, not broad synonym learning. The
field map is a small explicit schema, and the real-corpus result covers one relation family. Other
field types need separate precision and held-out evidence before they are added. `v1_338` checks
report-only discovery, six-page training, two held-out questions, stale-proposal rejection, SQLite
persistence, and the chat review/write-back path; `v1_337` remains the full-corpus yield probe.

### Independent-source retention for predicate alignment

Command: `python3 experiments/v1_334_independent_alignment_evidence_retention.py`

Frame mining previously retained only the first source for each exact subject/object pair. If the
first examples for two predicates were both in one document, the aligner discarded the pair even
when separate documents later supported each wording. It now retains up to eight distinct source
documents per pair and chooses a cross-document pair for alignment; the minimum of two distinct
entity pairs remains unchanged. The regression passed, including a same-document co-mention,
independent corroborating documents, no writes before review, explicit acceptance, and a
source-backed held-out wording answer.

A read-only 10,000-document/400,000-sentence SimpleWiki sample yielded 19 relation-frame proposals
and zero predicate alignments. An offline overlap check on those retained frames also found no
single shared entity pair between differing predicates. The evidence-retention bug is fixed, but
the real-corpus recall gap remains. Wider role-class evidence needs its own precision and held-out
evaluation before it can license a rule.

## Source-grounded role-type alignment probe

Command: `python3 experiments/v1_335_role_type_alignment_probe.py --window-count 3 --sentences-per-window 200000`

The probe reads exact-title lead sentences (including leads after infobox blocks and a bounded
parenthetical after the title) plus explicit `type`, `class`, and `kind` infobox fields. On the
285,478-document index it found 148,162 pages with one unambiguous coarse type head. Three disjoint
10,000-document windows produced 58 frame proposals and 215 positive non-`is-a` support rows; 49
subjects and 55 objects matched a unique type, and 14 rows had both endpoints typed. It found no
predicate hypotheses even when one distinct entity pair per wording was enough, provided the
examples were independently sourced and did not reuse the exact same pair. The diagnostic accepted
no rules and changed no index data. This role-type signal has no yield in these windows; better
entity linking or separately sourced category fields need coverage and held-out precision evidence
before they can support language rules.

The current five-window replay uses leading-article normalization for exact-title endpoint matches,
checks `settlement_type` values, and excludes several newly inspected false subjects. Compound or
conflicting class values are withheld. It retained 84 frames and 355 positive non-`is-a` supports;
60 subjects and 108 objects matched one unique type, with 22 supports typed at both endpoints. The
revised replay still found zero role-type alignment hypotheses. The low yield does not justify
weakening the review or evidence thresholds.

### Page-local identity control for role-type candidates (2026-10-20)

Command:

```sh
python3 experiments/v1_335_role_type_alignment_probe.py \
  data/crms_simplewiki_research.sqlite --type-documents 300000 \
  --window-documents 10000 --window-count 5 --sentences-per-window 200000
```

The report-only diagnostic now qualifies a shortened endpoint with its local
page title when that title ends in the extracted name. This prevented “Jones”
on the Felicity Jones and Owen Jones pages from being counted as one entity,
and added exact cited sentences and offsets for every candidate example. On the
285,478-document index, the rerun scanned 190 frames and 1,378 positive
non-`is-a` support rows; 368 rows had both endpoints typed. It found one weak
candidate (`district of` / `province of`) at one distinct pair per wording, and
zero candidates at the existing two-pair threshold. The cited examples,
“Maseru is a district of Lesotho” and “Stara Zagora is a province of Bulgaria,”
are not equivalent relations. Codex's manual review of the previous run also
found the stronger `electoral district of` / `region of` candidate and
`born in` / `lives in` candidate were false alignments. These are provisional
single-reviewer judgments, not an independent precision estimate. Keep the
method report-only: page-local identity removes observed collisions, but the
current real-corpus sample still provides no supported alignment at the
two-pair threshold.

### Wider role-type sample and corpus-miner crash regression (2026-10-20)

The same read-only command was rerun with `--window-count 20`, sampling 20
disjoint 10,000-document windows across the 285,478-document index. The first
pass completed 813 relation frames and examined 4,499 positive non-`is-a`
supports; 590 had both endpoints typed. It reported 11 weak candidates and one
meeting the two-pair threshold. The strongest was `capital city of` /
`province of` with the shared coarse type `city → country`; the cited example
pair was “Accra is the capital city of Ghana” and “Benguela is a province of
Angola.” These do not express the same relation, so role-type compatibility
alone is not safe for alignment.

A later page-title check qualified a shortened endpoint only when the exact
page-title descriptor matched the nominal head of an `X of` relation, avoiding
the `Benguela` city/province collision while leaving unrelated endpoints such
as `Mumbai` on the `Maharashtra` page unqualified. The corrected 20-window scan
reported 610 typed-both supports, seven one-pair candidates, and zero at the
two-pair threshold. This removes the observed strong false candidate, but the
weak set has not been independently adjudicated and the result does not
establish candidate precision. The probe reports the number of supports after
page-title disambiguation; it does not apply a separate predicate-head/type
compatibility filter. Keep role-type discovery report-only and require
source-disjoint precision evidence before licensing an alignment.

The first 20-window run crashed on “An-26 is a modernized variant” because
tokenization split the hyphenated model name into `an` and `26`, then article
stripping emptied the subject. Article removal now requires a standalone
surface article, and the probe has a direct regression for `An-26`. The full
20-window read-only scan completes after this fix, with no index writes. Keep
role-type alignments report-only until a stronger semantic discriminator and
source-disjoint precision evaluation are available.

## Exact-title structured type answers

Command: `python3 experiments/v1_336_structured_type_field_chat.py`

The CLI now recognizes bounded `What type/kind of [category] is X?` and `What is the type/kind of
X?` forms, then reads a unique `type`, `class`, `kind`, `entity type`, or `settlement_type` value
from one exact-title infobox. It cites the exact field, rejects conflicting title records and
non-infobox key/value text, and labels the result as quoted structured evidence. The fixture also
checks a `settlement_type = City` field. The same exact field enters the
review queue as a `subject — is-a → value` candidate, but it is stored only after explicit
acceptance. The fixture confirms that acceptance enables a later yes/no answer from the fact store.
A read-only query to the 285,478-document SimpleWiki index answered `What type of place is Albury?`
from `type = city`; a second read-only chat query answered the same form for Chicago from its exact
`settlement_type = City` field. Both values were cited as structured evidence, and Chicago remained
unaccepted in the store.

## Exact-title subject alias and birthplace retrieval

Command: `python3 experiments/v1_333_exact_page_alias_and_birthplace.py`

The fixture passed its checks: a unique `Alan Turing` page licenses `Turing` as the subject of
“During World War II, Turing worked at Bletchley Park”; an unsupported workplace abstains; an
explicit negative sentence yields no; and `Where was Marie Curie born?` reads and cites the page's
exact `birth_place` field. The structured value remains quoted evidence, not an accepted fact.

A read-only four-question replay on `data/crms_simplewiki_research.sqlite` (285,478 documents)
completed in 4.54 seconds. It answered yes with the cited Bletchley Park sentence, abstained for
Cambridge, returned the exact-title location sentence for `Where does Alan Turing work?`, and
returned Warsaw, Congress Poland, Russian Empire from Marie Curie's exact-title infobox. This
confirms the targeted regressions on the real corpus; it does not measure broad polar accuracy,
structured-field coverage, or cold-cache latency.

### Additional corpus-frame boundary filters

After the bounded windows, the 10,000-document / 200,000-sentence SimpleWiki sample was
re-run with guards for numeric subjects, determiners swallowed into predicates, objects beginning
with auxiliaries or prepositions, and subjects embedded after a preposition. Those guards reduced
the frame proposals from 20 to 12. A narrow `of ...` noun-complement rule then retained complete
objects such as `Supreme Commander of NATO Europe` rather than dropping the complement. The
current sample yields 5 frames with 422 support rows, 404 of them `is-a`; the regression fixture
checks complete objects. This is a candidate-count change, not a precision estimate. The observed
`species`, `flows` with a prepositional object, `called` from an embedded place phrase, and
`becomes the first` boundary frames are no longer proposed. The cross-predicate alignment count
remains zero. Residual broad frames such as `becomes` and `like` still need independent review
before any automatic use; all proposals remain review-only.

## Possessive variable path questions

Command: `python3 experiments/v1_59_path_question_paraphrase_transfer.py`

Two fact-backed examples of `Who are {person}'s grandchildren?` license the learned path
`parent, parent`. On a held-out person, both ASCII and curly possessives return the unique
grandchild with a two-edge proof. The CLI now preserves the composed answer rather than realizing
the first leaf fact as if it answered the question; the runtime regression checks both possessive
forms and the CLI output. The query remains unknown until the path wording is licensed; CRMS does
not assume that the word `grandchildren` means two `parent` edges.


## Indexed variable inference over large stores

Command: `python3 experiments/v1_340_indexed_variable_inference.py`

A learned variable question for a two-premise `grandparent` rule now finds answers in either
endpoint direction when the knowledge base has more than 256 entities. Candidate enumeration joins
indexed premise facts from the bound endpoint, then verifies each candidate through the normal
proof-producing inference engine. The diagnostic checks exact proof leaves against the live fact
store, a complete miss, irrelevant-entity resistance, and the same answers after SQLite persistence.
A query whose rule depends on a derived/recursive premise still uses the bounded fallback and reports
incomplete search rather than asserting that the candidate set is exhaustive.


## Indexed recursive variable queries

Command: `python3 experiments/v1_340_indexed_variable_inference.py`

The indexed variable-answer path handles the common linear rule pair `parent + parent -> ancestor`
and `parent + ancestor -> ancestor`. On a 2,047-node binary tree it returns all nine rule-supported
ancestors for the deepest leaf with proof trees retained. The diagnostic also checks inverse
endpoint answering, independent proof verification, in-memory and SQLite-backed facts, complete
misses, and honest abstention after the 10,000-row fact-scan budget is reached. Other recursive
shapes remain on the bounded fallback.

## Large-corpus chat and unknown-answer classification

Command: `python3 experiments/v1_251_large_corpus_chat_stress.py`

The current runtime pass indexed 1,200 synthetic source documents (7,200 sentences) and surfaced
the exact expected sentence for all 30 baseline queries. All three relation-conflict controls
abstained. Two unsupported questions were both classified as abstentions: one plain abstention and
one abstention that included a closest sentence explicitly labeled as not answering the question.
The portable model also retained and retrieved its embedded source corpus after the original
source directory and research index were made unavailable.

The replay corrected a scorer defect: `I won't guess` with a `Closest source sentence` was
previously counted as an unclassified response. The experiment now distinguishes plain
abstention, abstention with related evidence, clarification, and other replies, and requires both
unsupported prompts to abstain. It also checks numbered-record disambiguation at full corpus scale:
`At which institute did researchers study quartz field 0266?` now selects the matching record
instead of tying against records 0000–0009. The gate treats explicit numeric identifiers in a
question as identity constraints. Four other positive paraphrase probes remain unresolved, including
the stream/waterway relation variants and a location/relation wording case. Nearby quoted text is
not counted as a correct answer unless it is presented as answer-bearing support.

## Reviewed corpus predicate transfer

Command: `python3 experiments/v1_296_large_corpus_predicate_learning.py`

On the controlled 1,200-document corpus, repeated pairs in independent documents propose
`flows through` ↔ `passes through` and `flows through` ↔ `runs through`. The system changes no facts
until explicit acceptance. After acceptance, chat composes both alternate predicates with separate
source sentences explicitly classifying held-out entities as a `stream` or `waterway`. It cites the
relation sentence and presents resulting claims for review; the class is not inferred from the
entity name. This is demonstrated transfer from repeated evidence, not broad language parity. A
read-only sample of four 1,000-document windows in SimpleWiki produced zero predicate alignments,
and the expanded 5,000-document/60,000-sentence scan also produced zero, so corpus-derived transfer
remains sparse in the sampled real corpus.

## Project-document question answering and procedural retrieval

Command: `python3 experiments/v1_252_project_document_chat_eval.py`

The terminal indexed the current 318,997-byte `CRMS_README.md` as one source and
answered all five questions with answer-bearing source text (5/5). The fixed
set covers a procedural “How can I …?” request, a question about the meaning
of an absent proposition, a qualitative “How much of …?” question, and two
questions about model-size claims and induced-frame limits. The procedural
route retrieved the complete sentence about embedding searchable text without
the original files; it no longer quotes a mid-sentence fragment before a
colon. The missing-proposition query now quotes the sentence defining absence
as unknown, and the qualitative amount query can use the source's explicit
“substantially” wording without inventing a numeric estimate.

This is a five-question check over one project document, not broad reading
comprehension. Replies remain quotations marked as evidence rather than
accepted facts. The evaluator rejects replies that merely append the expected
sentence as “closest source” while saying it may not answer the question.

## Gate-preserving sentence ranker on FTS candidates (two disjoint samples)

Command: `python3 experiments/v1_346_fts_sentence_ranker_evaluation.py --docs-per-window 100 --train-examples 40 --test-examples 40 --json-out /tmp/crms-ranker-fts-eval-v2.json`

Read-only run on the 285,478-document SimpleWiki SQLite index. Training and test questions were
generated from disjoint 100-document windows (offsets 20,000 and 220,000); test-window documents
were excluded from the training candidate pool. Training produced 70 candidate rows (15 positive)
from 40 generated questions. On 40 held-out generated questions, both the unchanged gate and the
ranker answered 39 correctly, abstained once, and answered none incorrectly. Of 16 questions with
at least two gate-passing candidates, both answered 15 correctly and abstained on one (100%
precision among answers, 93.75% coverage). The ranker therefore showed no measured selection gain
over the gate in this sample. Removing the target article left 15 questions with other-source
candidates: 14 abstained and one selected a sentence that did not contain the generated gold
answer. Median selector time was 0.41 ms for the ranker and 0.24 ms for the gate; the whole
question-generation and FTS evaluation took 150.7 seconds, which is not chat latency.

An independent second draw used `--train-offset 50000 --test-offset 200000` with the same window
and question limits. It generated 40 training and 40 test questions, with 82 training candidate
rows (25 positive). On the 40 test questions, the gate answered 36 correctly, one incorrectly,
and abstained on three; the ranker answered 37 correctly, two incorrectly, and abstained once. On
the 15 multi-candidate questions, the gate answered 12 (11 correct, one wrong) and abstained on
three, while the ranker answered 14 (12 correct, two wrong) and abstained on one. The ranker thus
increased multi-candidate coverage from 80% to 93.3%, but lowered precision from 91.7% to 85.7%.
Median selector time was 0.64 ms for the ranker and 0.45 ms for the gate; evaluation took 119.4
seconds.

Across these two small draws, the ranker has not shown a safe quality gain: it ties the gate on the
first and trades more coverage for more errors on the second, at a modest added selector cost. It
remains disabled in chat. This is still a narrow check: questions are self-generated WHO clozes
from leading-subject sentences, and labels are weakly derived from those sentences. Broader
generated question types, larger independent samples, human-written questions, and non-Wikipedia
domains remain unmeasured.

### Typed self-cloze extension: WHERE (initial sample)

Command: `python3 experiments/v1_346_fts_sentence_ranker_evaluation.py --question-type WHERE --train-offset 200000 --test-offset 220000 --docs-per-window 600 --train-examples 40 --test-examples 40 --threshold 0.3`

Threshold comparison: rerun the same command with `--threshold 0.4`; the source windows and
training examples remain unchanged.

The evaluator now supports narrow `WHEN`, `WHERE`, `MEASURE`, `COUNT`, and `DEF` templates in
addition to the original `WHO` mode. `experiments/v1_347_sentence_ranker_cloze_types.py` checks
the generated forms and pronoun/negation near misses. In this first WHERE run, 600-document
training and test windows yielded 33 training questions (59 candidate rows, 16 positive) and 29
held-out test questions. The unchanged gate answered 14 correctly and abstained on all 15
multi-candidate questions. At threshold 0.3, the ranker answered 18 correctly and two incorrectly,
abstaining on nine; among the 15 multi-candidate questions it selected four correct and two wrong
(66.7% precision). Both wrong selections confused people sharing a surname (Lipscomb and Rhodes)
with other people in the corpus. At threshold 0.4 it answered the same 14 single-candidate cases as
the gate and abstained on all 15 multi-candidate cases. Median selector time was 0.23 ms at 0.3
and 0.24 ms at 0.4, versus 0.10 ms for the gate; full evaluations took 52.6 and 55.5 seconds.

This demonstrates a recall/precision tradeoff, not safe ranker improvement. The higher threshold
removes the wrong selections by declining every ambiguous case, while the lower threshold adds
four correct multi-candidate selections alongside two wrong ones. The question templates and
answer labels are generated from a few exact sentence patterns, and the test set is small; these
results do not measure human-written query coverage or the efficacy of the additional `WHEN`,
`MEASURE`, `COUNT`, and `DEF` types. The ranker remains disabled in chat.

## Source-only entity candidates in dialogue follow-ups

Command: `python3 experiments/v1_362_source_entity_followup.py`

On a one-sentence indexed source, asking “Who worked with Charles Babbage?” retains Ada Lovelace
and Charles Babbage as candidate referents, with the source title and citation attached to dialogue
evidence. The actual terminal saves this state and a second process asks “Where did she work?”; it
restores the referents only when the loaded index still resolves the citation, then asks which named
entity the user means rather than guessing. An empty index causes the saved candidates to be
discarded. The check confirms that no facts are added from those quoted names. On a separate
accepted-fact fixture, licensed frames still resolve supported “she” and “him” follow-ups to the
corresponding subject and object and return the expected fact-backed answers. Existing
entity-repair, pronoun, and seed-conversation experiments also pass on the same checkout.

This is a bounded, citation-revalidated discourse-memory improvement. Capitalized names are only
referent candidates; they are not a general named-entity recognizer, accepted knowledge, or evidence that a substituted
question has an answer. Multi-turn salience, coreference across paragraphs, and learned dialogue
moves remain unmeasured. The corpus-induced move research direction and its policy/labeling limits
are described in [`design_dialogue_moves.md`](design_dialogue_moves.md).

## Relation-schema registry and proof contract

Command: `python3 experiments/v1_374_relation_schema_registry.py`

The shared registry covers six schema types, distinguishes derivation from
integrity constraints, and records built-in proof IDs, premise counts,
validation metadata, and the allowed transitive flat-chain proof form. Teaching,
explicit source parsing, and relation-name discovery recognize the same six
types. Transitive and symmetric conclusions still pass the independent proof
checker; tampering with the proof form is rejected. Unregistered schema names
and proof forms are refused. The existing `v1_349`, `v1_350`, and `v1_351`
schema-proposal, inference, explanation, and scope tests also pass. This is a
consistency and proof-contract regression, not automatic schema learning.

## Report-only symmetric-schema candidates

Command: `python3 experiments/v1_380_reciprocal_schema_candidates.py`

The diagnostic finds a symmetry candidate only from explicit reciprocal positive facts. It shows
explicit negative reverse facts as counterexamples, keeps missing reverse statements unknown, and
requires multiple independent source origins before describing support as uncontradicted. A
contradictory pair retains both its positive and negative evidence. Search bounds are reported, and
the interactive command is verified to leave the knowledge store unchanged. This is a proposal
generator, not an automatic schema learner. `experiments/v1_381_heldout_schema_review.py` checks
source-separated validation, explicit held-out counterexamples, missing reverse evidence, and the
interactive report-only path. Passing the configured holdout threshold is evidence for these
controlled cases, not proof of a universal relation property.

## Cross-shape reasoning graph baseline

Command: `python3 experiments/v1_376_reasoning_graph_benchmark.py`

Runtime rerun on 2026-10-19. The experiment checks nine cases: 35-hop recursion, a depth-9 path in a 2,047-node binary tree,
a ten-layer diamond, direct positive/negative conflict, negative-only evidence, a complete miss,
an expansion-limited search, a cycle-backed self-relation, and a declared irreflexive denial.
Positive proofs and constraint denials are checked independently; each semantic result is replayed
to check deterministic status, bounds, shortest proof depth, proof count, reason and proof content. All nine matched their
expected status and completeness in the current run. Negative-only evidence remained `unknown`;
the budget-limited case remained incomplete with `expansion_limit`; the diamond returned 64 proofs
with `proof_limit`; and the cycle returned an ambiguity rather than an unqualified self-relation.

Before the inference normalization cache, a local run with `tracemalloc` enabled measured 35 ms for
the 35-hop chain (211 KiB peak), 636 ms for the tree (6,617 KiB), and 267 ms for the proof-capped
diamond (556 KiB). The bounded 65,536-entry token-normalization cache reduced the tree to 321 ms
(6,257 KiB). A second, narrowly recognized target-pruning path for the exact rule pair
`edge + edge -> closure` and `edge + closure -> closure` reduced it further to 105 ms (2,850 KiB)
and reduced proof-search expansions from 2,055 to 27. This optimization uses backward reachability
over the same scope-filtered direct-edge index, preserves direct and verified closure-edge anchors,
and leaves other rule sets on the general search path. The 35-hop chain took 29 ms and 105
expansions after pruning (versus 28 ms and 70 expansions after normalization caching alone): the
reachability scan adds work when there are few irrelevant branches. A `cProfile` replay of the tree
measured 0.077 s / 0.41 million calls after both changes, compared with 0.390 s / 1.82 million calls
before them. These are machine- and instrumentation-specific observations, not performance
thresholds. The current profile is dominated by repeated fact-triple verification; any further
optimization should be separately measured and must preserve the fallback for broader rule sets.
The initial graph matrix improves coverage over the focused regressions, but does not yet include
larger adversarial branching graphs, nonlinear recursive joins, or a broad query distribution.

## Nonlinear recursive self-composition

Command: `python3 experiments/v1_377_nonlinear_recursive_closure.py`

For `ancestor := parent,parent` plus `ancestor := ancestor,ancestor`, the indexed seed closure
answered 4-, 8-, and 12-edge chains in 6, 26, and 207 expansions. Before this implementation, the
bounded candidate scan exhausted 10,000 expansions even on a four-edge chain. All returned nested
proofs passed the independent verifier, including a typed variant with middle-kind witnesses. A
disconnected query remained a complete unknown, explicit depth and expansion limits remained
incomplete, a cycle-backed self-relation remained ambiguous, and the behavior survived a SQLite
round trip. This covers the exact self-composition shape with directly joinable two-premise seed
rules; other nonlinear recursion still uses the bounded fallback.

## Source-validated rule learning through portable-model distribution

Command: `python3 experiments/v1_379_portable_validated_rule_learning.py`

This integration diagnostic learns a `parent + parent -> ancestor` candidate from two training
documents, validates it on two source-held-out documents, and explicitly accepts it. The rule is
then applied to a new unlabeled chain, and the verified derivation is retained as a separate case.
Packaging the learned knowledge and source text into one SQLite model preserves the rule's
validation examples, the derived case's rule lineage, and searchable citations. After installation,
the API and `/infer-relation` CLI command derive the practiced conclusion. The experiment now also
adds a separate, never-practiced chain and asks about it through ordinary natural-language chat. Its
proof passes the independent verifier, while a one-edge near-miss abstains. This closes a bounded
rule-to-chat integration gap; it remains one controlled rule shape and does not establish
open-domain rule induction quality or natural-language intent learning.

The current runtime extension also checks failure governance through the same
installed rule: a one-expansion search stays `unknown/incomplete` and writes no
derived case; an explicit negative against a positively derived chat answer
returns `ambiguous/contradiction`; and a cycle-backed `Ann ancestor Ann` chat
query returns `ambiguous/cyclic_support`. Retracting a required premise after
installation makes the previously practiced `Nia ancestor Pia` case unavailable
and marks it stale or conflicted. These checks connect proof status, chat
routing, and derived-case lineage for this rule shape, but do not test general
dialogue or arbitrary rule compositions.

On 2026-10-20 the focused reasoning-governance suite
(`v1_191`, `v1_193`, `v1_376`, `v1_379`, `v1_415`, `v1_82`) passed 6/6 on the
working tree. Together these cover bounded abduction without write-back,
schema conflicts and scope, graph-search limits and cycles, portable validated
rule use, redundant-fact detection, and derived-lineage invalidation. This is a
selected diagnostic suite, not a broad reasoning accuracy estimate.

## Derived-case correction after source retraction

Command: `python3 experiments/v1_72_proof_backed_derived_cases.py`

Explicit practice stores a verified inference separately from source facts and deduplicates
repeated practice. The experiment now tests correction propagation at the evidence level: retracting
one citation from a premise with an independent remaining source refreshes the stored proof and
lineage; retracting the final required premise makes the case unavailable and marks it stale. The
existing conflict, persistence, and no-fact-promotion checks still pass. This verifies one bounded
revalidation path; it does not establish general derivation governance, automatic practice, or
storage-compression safety.

## Held-out typed three-premise rule transfer through chat

Command: `python3 experiments/v1_192_typed_three_premise_discovery.py`

The learner discovers a typed `employs + owns + located in → reaches` rule, validates it on
source-held-out positive examples, rejects a balanced negative holdout, and requires both middle
kind witnesses. The added natural-language probe asks “Does Nia reach Sydney?” and independently
verifies the proof; removing the runtime person-kind witness makes the chat path abstain. This
demonstrates one held-out ternary schema through ordinary language, not general three-premise
understanding or broad learned-rule coverage. The 2026-10-20 extension also practices that
conclusion into a separate verified derived-case store without adding a fact, checks persistence
and invalidation after retracting a required source premise, and tests the same schema against
explicit negative evidence. The inference engine returns `ambiguous/contradiction` for a positive
rule proof plus explicit negative; ordinary chat does not return a positive answer in that case.
The focused reasoning-governance suite passed 7/7 (`v1_191`, `v1_192`, `v1_193`, `v1_376`,
`v1_379`, `v1_415`, `v1_82`). This extends evidence to a second rule shape; it is not broad rule
learning or open-domain reasoning.

## Large-corpus language-to-rule transfer through chat

Command: `python3 experiments/v1_297_large_scale_rule_learning.py`

In this generated 1,162-fact corpus, two cited examples teach each sentence-to-relation frame;
later source claims enter through reviewed extraction. The binary parent-to-ancestor candidate is
validated on 12 source-held-out examples, while a linked-location decoy is blocked by a held-out
negative. The 12 unlabeled chains all derive with independently verified proofs. A new natural-
language chat probe reaches one of those conclusions through the learned rule, and a one-edge
near-miss does not receive a positive inference. This exercises the full pipeline on a controlled
corpus, not broad natural-language or open-domain learning quality.

## Contrastive procedure learning through chat and cross-domain composition (2026-10-20)

Command: `python3 experiments/v1_424_contrastive_rule_learning_composition.py`.

The previously unlicensed instruction “sort the numbers” now has an end-to-end
learning-path regression. A fresh chat first abstains on the code request. The
user supplies five input/output examples; the learner asks for a contrastive
output on `[0, 0]`, which distinguishes sorting from deduplication. That reply
licenses the procedure, after which the same natural-language request composes
it with a separately learned exact math map. The chat exposes both provenance
stages, validates the generated artifact, and the learned rule still works
after reload on an unseen integer list. A request to rotate the numbers remains
unsupported and abstains. The same deterministic composed artifact is
recreated after a fresh chat process starts.

This exposed and fixed a chat integration defect: `/teach-rule` displayed the
requested contrastive probe but did not save it as pending lesson state, so the
teacher's output was routed as an unrelated question. The command now persists
that pending probe and consumes a plain list reply. The focused experiment and
the existing CLI teaching, cross-domain composition, and portable validated
rule-transfer experiments pass. This is evidence for one teacher-guided rule
shape and one exact-math composition, not autonomous language acquisition or
broad coding competence.

## Sentence-ranker fresh-index diagnostic (2026-10-20)

Command:

```sh
python3 experiments/v1_346_fts_sentence_ranker_evaluation.py \
  --index data/crms_simplewiki_research.sqlite \
  --docs-per-window 60 --train-examples 20 --test-examples 20
```

On the current 1.3 GB SimpleWiki research index, the disjoint 60-document
windows produced 20 training questions (34 candidate rows, of which only 4
were positive) and 20 test questions. The existing quoted-evidence gate
answered 20/20 with 20/20 correct. The opt-in ranker answered 17/20 with 17/17
correct and abstained on 3; both methods answered all eight test cases with
multiple gate-passing candidates correctly. Median ranking time was 0.48 ms
versus 0.30 ms for the gate on this run; total evaluation time was 91.8 s.

This is a small, self-cloze WHO diagnostic with weak labels, not a representative
quality evaluation. It shows no accuracy gain over the gate on this sample and
lower overall coverage, so it does not justify enabling the ranker in chat.
Expand and diversify the source-disjoint evaluation before reconsidering
deployment; report wrong-answer rate and abstention as well as precision.

## Answer-bearing pronoun sentence in source retrieval (2026-10-20)

Commands: `python3 experiments/v1_423_pronoun_sentence_answer_selection.py` and
`python3 experiments/v1_426_dialogue_paragraph_grounding.py`.

The runtime now retains three candidate sentences per document for factual
questions, permits a leading “It” sentence only when the named entity occurs
in the same paragraph, and ranks date-bearing sentences above entity-only
lead sentences for `When` questions when the requested predicate also matches.
When the chosen sentence uses a pronoun, its answer text is shown with the
nearest named antecedent in one exact, source-cited excerpt. When retrieval
returns only the pronoun sentence, it now searches the cited paragraph for the
nearest preceding sentence that names the queried entity, then verifies and
cites the combined source slice. The Eiffel Tower / Colosseum sequence selects
1889 and 80 CE respectively, preserves the Colosseum topic through a
capacity follow-up, `why?`, and save/reload, and refuses an unanchored sentence
from a separate paragraph. Measurement questions such as “How tall is it?”
stay on answer-sentence ranking rather than entering the broader
explanation-paragraph path. Follow-up checks also confirm that “What did I just
ask?” can use the recorded last user question after a failed turn, and that an
ordinal without an open numbered list asks for clarification. Evidence remains
quoted source text, not an accepted fact. The focused and nearby topic-anchor,
source-follow-up, persistence, quoted-evidence, and sentence-retrieval checks
pass. An incompatible “And Italy?” after the Colosseum capacity question does
not reuse the capacity answer; its abstention names the quoted sentence as
missing the target, rather than claiming the whole source lacks it. This
remains bounded coverage, not a general answerability classifier, dialogue
model, or broad semantic ranker.

## Named-entity grounding for source-only chat answers (2026-10-20)

Command: `python3 experiments/v1_425_named_entity_evidence_guard.py`.

The chat path now refuses to present source-only text for a named entity unless
the visible cited excerpt names that entity or an explicitly stored alias. A
fresh replay of “When was the Eiffel Tower completed?” followed by “And
Italy?” had previously produced the Colosseum date, 80 CE, as if it answered
the Italy follow-up. It now abstains and clears the old answer as a target for
`why?`; the named “And the Colosseum?” switch still returns its cited date.
The experiment also confirms current retrieval selects Marie Curie's own
Nobel sentence and forces the former Einstein-for-Curie sentence through the
negative guard.

The focused experiment, topic-anchor, answer-bearing-pronoun, and persistent
feedback-context regressions pass. This is a chat-layer attribution check, not
a semantic relation verifier: it may abstain when a source uses an unlicensed
alias or paraphrase, and it does not establish that a sentence entails the
requested relation. Retrieval and relation-answerability evaluation remain
necessary.

## Relation-aligned source answers for named actions (2026-10-20)

Command: `python3 run_experiments.py --match v1_423_pronoun_sentence_answer_selection --match v1_425_named_entity_evidence_guard --match v1_426_dialogue_paragraph_grounding --match v1_438_dialogue_topic_pronoun_context --match v1_439_explicit_topic_clause --match v1_440_who_action_sentence_alignment --timeout 300`.

The baseline failure was reproduced: `Who designed the Sydney Opera House?`
selected “The Sydney Opera House opened in 1973.” although “Jorn Utzon designed
it.” was present. For a named `Who [action] [entity]` question, retrieval now
searches for the asked predicate and admits an object-pronoun sentence only
when the nearest preceding explicit subject in the same paragraph matches the
named entity. The resulting cited excerpt includes that local entity sentence.
The selected sentence must also state the requested predicate or an active,
licensed predicate wording. A named-entity sentence without the asked action,
a pronoun sentence across a paragraph break, and a sentence whose nearest
explicit subject is another entity all abstain. Direct entity-bearing wording
and “designed and built” for a `Who built ...?` request remain supported.

For `When` questions, the final selected citation must contain an explicit
temporal expression. The exact selected citation is used for the source
passage, even when the initial lexical hit was a truncated or neighboring
sentence. This keeps answers such as 1889 and 80 CE while preventing a sentence
such as “Rome is the capital of Italy” from filling an unrelated date slot.
An unsupported question about the current source-backed topic now retains that
topic for a later follow-up while clearing the old answer as a `why?` target.

The six focused retrieval and dialogue experiments pass (6/6); `v1_440` covers
the original failure plus direct, missing-action, wrong-paragraph, and wrong-
antecedent cases. This is a narrow alignment gate, not a general entailment or
temporal-expression model. It requires the requested action to be exact or
licensed, uses a bounded temporal vocabulary, and may abstain on valid but
unrecognized wording. The separate sentence-ranker evaluation was not
completed in this run; no broad retrieval-quality claim follows from these
fixtures.

## Transformation-rule example provenance (2026-10-20)

Command: `python3 experiments/v1_428_procedure_example_provenance.py`.

`CRMSModel.teach` now accepts optional per-example `source_ids`. The chat
command also accepts a fourth field, `/teach-rule INSTRUCTION|INPUT CSV|OUTPUT
CSV|SOURCE CITATION`; the exact citation must resolve against the active index.
The cited span must also contain the exact numeric input/output pair. The reply
states that this does not verify that the source wording licenses the
instruction. The IDs remain parallel to demonstrations through
JSON and SQLite persistence, are available through `example_records()` and
the document-level `example_documents()` view, and are embedded in
generated-code evidence. Multiple citations in one document count as one
document; the method does not assert independent publishing origins. Old rule memories load with missing
provenance left unknown. `v1_428` checks held-out composition, artifact parity,
JSON/SQLite round trips, legacy loading, and source-list validation.
`v1_429_chat_rule_source_attribution.py` drives the actual command, verifies
persistence of a valid citation, confirms an unlabelled example stays
unlabelled, and rejects stale citations and citations that state a different
output.

Runtime result: all checks passed. The source identifiers in this experiment
are fixture labels authored for the test; the task is still a plumbing and
lineage check, not a source-disjoint transfer result. Chat captures citations
only when explicitly supplied; conversational and contrastive teaching
examples remain unlabelled unless taught separately with a citation. The
cited numeric pair is checked, but the instruction-to-operation alignment is
not verified, and the existing recombination scores remain bounded synthetic
results. The next gate must
exercise lineage from independently sourced examples through ordinary chat on
genuinely held-out documents and independently written requests.

## Source-document-held-out procedure transfer through chat (2026-10-20)

Command: `python3 experiments/v1_430_source_disjoint_chat_rule_transfer.py`.

The actual chat teaches `sort the numbers` from exact input/output pairs cited
to two training documents, then generates standalone Python. A third indexed
document contains a held-out list/output pair; its citation is excluded from
the rule memory and artifact. The generated procedure returns the exact held-
out output and passes its embedded parity checks. The experiment also probes
an unseen paraphrase and an unsupported operation; both abstain in this run.

Runtime result: all safety and parity checks passed. These are three
programmatically authored fixture documents using the same wording pattern,
not independent publishers or a natural corpus. The result demonstrates
document separation and provenance through one exact procedure, not unseen
multi-step composition, broad language transfer, or independent source
reliability. The next recombination benchmark should teach connective patterns
from cited examples in separate source documents and test a held-out combination
through the same chat and artifact path.

## Cited connective transfer to an unseen composition (2026-10-20)

Command: `python3 experiments/v1_431_cited_sequence_rule_recombination.py`.

The chat learns five list operations and two examples of the `then` connective,
with each numeric demonstration cited to one of seven training documents. It
then writes code for a three-stage `unique → sort → reverse` composition, a
combination not directly taught. The held-out input/output pairs are in an
eighth indexed document whose citations are never given to rule teaching. The
generated artifact retains the rule and component citations and excludes all
held-out citations. It returns the correct output on four held-out inputs,
passes code checks, and survives a fresh chat process with a deterministic
artifact ID. A chat request with an unsupported middle operation emits no
artifact.

Runtime result: all checks passed. The documents are authored fixtures, the
examples share a narrow wording family, and source IDs establish document
separation only. This is stronger than a single-procedure transfer check, but
it does not show independence across publishers, robust paraphrase handling, or
general rule induction over naturally occurring text. The next evaluation must
use naturally occurring, independently sourced instructions and independently
written requests while retaining these controls.

## Cited doctest span retrieval across research indexes (2026-10-20)

Command: `python3 experiments/v1_432_cited_doctest_rule_learning.py`.

Research search now returns a complete short doctest paragraph when a matched
sentence belongs to one, preserving the prompt and result in the citation.
The experiment searches and resolves exact citations through both the
in-memory and SQLite-backed indexes. It also covers CRLF documents and
whitespace-only blank separators. Both official documentation examples remain
positive-only; after two separately identified, unattributed teacher contrasts,
the learned sort rule passes three held-out lists, its generated Python passes
independent checks, and unsupported rotation remains unlicensed.

Runtime result: all focused checks passed; `v1_430` and `v1_431` also passed
when rerun alongside it. This validates citation spans and one bounded
teacher-guided rule path. It does not demonstrate induction from source text
alone, broad coding skill, or natural-language transfer across diverse
instructions.

## Document-sourced component recombination through chat (2026-10-20)

Command: `python3 experiments/v1_433_document_sourced_procedure_composition.py`.

The chat learns numeric sort, sorted-unique, and reverse procedures using one
exact numeric code example cited to each official documentation source, plus
Codex-authored contrast examples. It also learns the `then` sequence connective
from separate Codex-authored examples. The initial held-out composition was
`unique → sort → reverse`. An ablation check found that NumPy's sorted-unique
operation made the sort stage redundant: removing `sort` left all held-out
outputs unchanged. That original result was therefore not strong evidence that
all three stages had recombined.

The experiment now composes `stable unique → sort → reverse`. Stable-unique
examples are explicitly Codex-labeled and linked to Python's documented
insertion-order semantics; the docs do not themselves state the natural-language
instruction mapping. Sort and reverse retain exact cited code pairs. Each of
the three non-empty held-out lists changes when any one stage is removed; the
empty list remains an unchanged control.
Chat-generated Python passes those lists, preserves the citations and labeler
attribution, reproduces after a fresh chat restart, and refuses an unsupported
`encrypt` middle step. Held-out inputs and expected outputs remain in the
experiment evaluator and are not written to the source index loaded by chat.
Two complete NumPy reference documents (`numpy.unique` and
`numpy.unique_values`) also supply held-out arrays. They live in a separate
evaluation index, remain absent from the training/search index, and their
outputs are checked against an independent `sorted(set(values))` oracle before
the generated artifact is run on those arrays.

Runtime result: all checks passed. This remains a source-cited,
teacher-guided composition result, not source-only induction or broad coding
competence. The held-out arrays test behavior transfer across complete
documents and a separate publisher; they do not test whether the language
instruction mapping or sequence connective can be induced from source text.
Those remain teacher-attributed, so the broader source-driven learning gate is
still open.

Before additional labels, three chat wording probes generated one procedure
and abstained on two; none were wrong. After adding explicit Codex-labeled
examples for the alternate phrases `remove repeated values`, `sort them
ascending`, `reverse the result`, `reverse them`, and the composite phrase
`find the unique elements in ascending order`, all three full requests
generated and passed an independent oracle on four held-out lists and arrays
from two complete held-out NumPy documents (3/3, 0 wrong, 0 abstained). The
full requests were held out as compositions, while their component phrase
mappings were supervised. The underlying operation examples retain
source/labeler provenance; the composite phrase is a Codex label combining
stable-unique and sort. The result demonstrates that explicit phrase teaching
increases coverage for these requests and that the resulting components
recombine. It does not demonstrate autonomous synonym discovery, source-only
instruction alignment, or general paraphrase transfer.

## Source-derived procedure phrase proposal (2026-10-20)

Command: `python3 experiments/v1_436_source_derived_rule_phrase_review.py`.

The experiment now proposes two narrow mappings. It retrieves prose stating
“A simple ascending sort” and an independently hosted pandas sentence stating
“Sort values ascending order,” paired with a Python `sorted()` doctest. It also
retrieves NumPy prose stating “Reverse the order of elements” and a Python
`reversed()` doctest. The exact citations are retained. Sources:
[Python Sorting HOWTO](https://docs.python.org/3/howto/sorting.html),
[pandas Series.sort_values](https://pandas.pydata.org/docs/reference/api/pandas.Series.sort_values.html),
[Python Data Structures](https://docs.python.org/3/tutorial/datastructures.html),
and [NumPy `flip`](https://numpy.org/doc/stable/reference/generated/numpy.flip.html).

Both candidates are inert and marked `needs_review`. Codex explicitly reviews
and teaches the mappings through chat. The sort mapping uses one cited pair and
two Codex-labeled contrast examples; the reverse mapping needs one cited pair
and seven Codex-labeled examples before the procedure learner finds a unique
fit. Accepted rules persist the code citation, phrase citation, and reviewer
label. Each passes three held-out numeric lists. Direction controls keep
descending wording unsupported by the ascending rule and reject descending
prose as support for that candidate. A sentence-initial operation cue rejects
metalinguistic phrase mentions, while descending, directly negated, and
unrelated source-text controls produce 0 false proposals in 7 cases. A
tampered code/output pair and two documents assigned to the same source origin
do not produce a valid sort proposal.

Runtime result: `v1_436` passed; the adjacent `v1_431`, `v1_433`, and `v1_434`
also passed in the same run (4/4). These seven controls are synthetic and
hand-selected, so 0/7 is a regression result, not an estimate of field
precision. The lead-cue and negation checks do not cover broader scope,
contrastive wording, or paraphrased negation. This is still a cue-based
experiment with explicit human review and substantial labeler effort for
reverse. It does not establish autonomous phrase induction, general language
learning, or a production review feature.

## Publisher- and sentence-form source phrase transfer (2026-10-20)

Command: `python3 experiments/v1_437_heldout_publisher_phrase_review.py`.

An isolated probe uses the [MDN Array.prototype.sort
reference](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort)
as an unseen publisher for the phrase “The following function will sort the
array in ascending order,” paired with a cited `sorted()` doctest from the
[Python Sorting HOWTO](https://docs.python.org/3/howto/sorting.html). The
bounded `will <verb phrase>` cue proposes `sort the array in ascending order`.
The same experiment adds the passive, conditional phrase “the returned array
will be sorted in ascending order” from the [NumPy `sort`
reference](https://numpy.org/doc/stable/reference/generated/numpy.sort.html),
proposing `sort in ascending order`. This is a new NumPy document and sentence
form, but not a held-out publisher: NumPy was already used for reverse in
`v1_436`.

Both candidates stay review-only until taught through chat. Their exact prose
and Python code citations and the Codex reviewer attribution survive reload;
each generated rule passes three independent held-out lists. Opposite-direction
wording remains unlicensed. Negation, metalinguistic, quoted-positive, and
direction-only controls produce no false proposals in four cases in `v1_437`.
The quoted-positive case exposed that the original cue also matched an
instruction embedded as a quotation; the extractor now rejects a phrase inside
balanced quotation marks. This small control set is still not a proposal
precision estimate. The five-script source-learning/recombination run passed
5/5, including `v1_437`.

This is publisher holdout for one MDN excerpt and source-document/sentence-form
holdout for one NumPy excerpt. Both depend on hand-coded extraction patterns
and one operation, and both use selected snippets rather than complete held-out
documents. The controls are too small to estimate proposal precision or broad
source-language recall. The next gate is more publishers and sentence forms,
complete document splits, and independently authored negatives held out from
cue design.

## Natural request syntax transfer after phrase-role learning (2026-10-20)

Command: `python3 experiments/v1_452_natural_request_frame_transfer.py`.

After learning six labeled action/object/direction combinations, two
additional inflection pairs, and two multiword direction examples, a fresh chat
process receives eleven positive requests in syntactic forms not represented
by the training phrases: “put items in increasing order,” “sort numbers from
minimum to maximum,” “arrange values in ascending order,” “order the numbers
ascendingly,” “make the values go from smallest to largest,” “sort the values
in ascending order,” “sort numbers in ascending order,” “order the numbers in
ascending order,” “arrange numbers upwardly,” “sort values increasingly,” and
“order items from low to high.”
The original positional frame abstained on the first five. The learned-role
route first answered four of eight, transferring licensed
action/object/direction values through articles and “in ... order”. With two
Codex-labeled inflection pairs (`ascending`/`ascendingly` and
`increasing`/`increasingly`), same-behavior evidence licenses the `-ly` edit
and transfers it to an unseen third root (`upwardly`). Two additionally labeled
examples ground the multiword direction span “from low to high”; CRMS recombines
it with a held-out action/object pair. Current coverage is 8/11; three positive
requests still abstain. “Sort items descending,” “arrange numbers downwardly,”
and “order items from high to low” receive clear abstentions (0 false
positives).
This establishes a concrete residual coverage gap in natural request
transfer; the existing 27-phrase positional grid does not show broad language
understanding. Expected interpretations and labels were written by Codex, and
the procedure examples use Codex labels, so this is a controlled diagnostic
rather than an independent language benchmark.

The learned-role routes require each single-token role value and each direction
span to be supported by at least two distinct successful phrases, preserve the
learned action/object/direction order, and retain supporting phrase and labeler
provenance. They transfer four tested grammatical variants, learn `-ly` from
two roots in one behavior group before applying it to an unseen third root, and
compose the multiword direction with a held-out action/object pair. Generated
code passes independent list oracles. They do not license the unsupported
directions or shuffled-role negative. The next model change should learn
additional request structures and ordering patterns with explicit training
evidence; it must improve positive held-out coverage without licensing
conflicting meanings.

After adding the role path, the 18-diagnostic cross-domain replay initially
found a false positive: treating “please” as a removable function word made
“reverse please the list” inherit a learned reversal rule. Removing “please”
from the allowed grammatical tokens restored abstention. The full replay then
passed 18/18 in 13.89 seconds before adding the morphology extension, including
language transfer, source-derived rules, procedure recombination, reasoning,
dialogue, code/math, translation, and creative revision. After morphology
integration, the same 18 diagnostics passed in 14.06 seconds; after the
multiword role extension and single-evidence abstention control, they passed
in 14.02 seconds. After the role-evidence index was cached and a teach-then-query
invalidation control was added, the same 18 diagnostics passed in 14.26
seconds. The focused experiment confirms that adding a second distinct
multiword-direction example clears the cached index and permits the newly
supported held-out request, while the one-example case still abstains. No
latency improvement is claimed from this run; it verifies index reuse and
correct invalidation. This protects adjacent tested paths; it is not a
representative task-distribution score.

## Source-grounded procedure phrase recombination (2026-10-20)

Command: `python3 experiments/v1_441_source_grounded_rule_recombination.py`;
adjacent regression run: `v1_355`, `v1_431`, `v1_433`, `v1_436`, `v1_437`, and
`v1_441` (6/6 passed).

This joins the isolated source-phrase proposal and sequence-recombination
paths. A reviewed MDN sentence and a separately sourced Python `sorted()`
example ground “sort the array in ascending order”; a reviewed NumPy sentence
and Python `reversed()` example ground “reverse the order of elements.” A
Python `dict.fromkeys` doctest cites a duplicate-removal example. Codex labels
the surface-to-operation associations and supplies independent input/output
contrasts. Two separately labeled compound examples teach the `then`
connective. CRMS then handles the held-out composition “remove duplicate
values then sort the array in ascending order” through fresh-process chat,
creates code with component/sequence evidence, and passes four held-out list
inputs against an independent `sorted(set(values))` oracle. Citation and
reviewer provenance survive rule-store reload; a descending-order near miss
abstains without producing code.

This is an end-to-end teacher-attributed recombination result, not autonomous
prose learning: two extraction patterns are hand coded, the phrase alignments
and connective examples are Codex-labeled, and the unique-operation wording is
also labeler-supplied. It shows these labeled/source-cited components can cross
in a new chat composition while preserving checks and lineage. It does not
establish general language induction, broad coding capability, or source-only
learning.

## Source-rule assertion and scope controls (2026-10-20)

Command: `python3 experiments/v1_443_source_rule_scope_controls.py`;
adjacent source-rule and recombination regressions: seven scripts, 7/7 passed
(`v1_355`, `v1_431`, `v1_433`, `v1_436_source_derived_rule_phrase_review`,
`v1_437_heldout_publisher_phrase_review`, `v1_441`, `v1_443`).

An initial probe found that a positive-looking `will sort` clause was proposed
inside claims such as “There is no guarantee that the function will sort” and
“It is unclear whether the function will sort.” The review-only extractor now
rejects denial, uncertainty, unverified-claim, quotation, metalinguistic, and
opposite-direction controls. It retains explicit applicability clauses on
conditional candidates as review notes; these candidates remain inert until
review. The probe passed five asserted or scope-qualified proposal cases and
rejected ten negative or non-instructional cases. Exact cited source text is
preserved.

These 15 authored snippets are regression controls, not a proposal-precision
estimate. The extraction patterns remain hand coded for two sorting forms and
are still isolated under `experiments/`, not a general source-rule review
feature. Full-document, cross-publisher data and genuinely held-out negatives
are still required before discussing production use or autonomous learning.

## Single-step phrase-role recombination (2026-10-20)

Command: `python3 experiments/v1_447_single_step_phrase_role_recombination.py`.

Twenty-six Codex-authored phrases cover all but one combination in a
3-action × 3-object × 3-direction grid. Three input/output demonstrations
teach each phrase as ascending sort. Leave-one-combination-out evaluation
composes all 27 held-out requests. For “arrange numbers upward,” CRMS produces
the correct transform for four lists and generates Python in a fresh chat
process. Four controls with an unseen role, unseen direction, wrong order, or
unrelated action abstain. Labeler provenance survives reload.

This establishes a useful one-step role-recombination path in addition to the
multi-step parameterized examples. The phrases and labels are all authored by
one Codex labeler; there is no raw-source extraction or source-disjoint
validation here. The grid uses three-token phrases and does not establish
general paraphrase understanding, novel syntax, or representative user
coverage. Keep the result separate from source-derived learning and measure
wording, order, and role transfer on independently sourced and held-out
language before widening the runtime behavior.

## Minimal support for single-step phrase-role transfer (2026-10-20)

Command: `python3 experiments/v1_448_minimal_phrase_role_recombination.py`.

The same 3×3×3 role grid can be covered by six carefully chosen phrase seeds,
each with three input/output demonstrations. All six seed phrases work exactly,
and the other 21 combinations are composed through a positional analogy frame:
27/27 correct. Four unsupported role/order controls abstain. The selected
held-out phrase generates code that passes four independently computed sort
outputs through a fresh chat process; all labeler records survive reload.

This reduces the controlled support requirement from 26 phrase mappings to 6,
but the inputs remain synthetic and all labels come from one Codex annotator.
It does not estimate a human review burden or source-text learning. Natural
syntax variation, independent wording labels, and proposition/source citations
remain necessary before this can be treated as broad natural-language transfer.

## Procedure evidence and labeler provenance (2026-10-20)

Commands:

```sh
python3 experiments/v1_434_rule_labeler_provenance.py
python3 run_experiments.py --match 301 --match 428 --match 429 --match 430 \
  --match 431 --match 432 --match 433 --match 434 --timeout 300
python3 run_experiments.py --match 177 --match 208 --match 223 --timeout 300
```

Each procedure example can retain a code-pair `source_id`, an optional prose
`instruction_source_id`, and a declared `labeler_id`. `/teach-rule` accepts the
instruction citation as a sixth field; earlier command forms remain compatible
and default the labeler to `user`. The three fields survive retry, JSON and
SQLite round trips, generated-code provenance, and the readable artifact view.
Forget removes them with the associated examples. The loader rejects malformed
or misaligned metadata and leaves old memories unlabelled.

`v1_433` carries exact citations for an executable pair and for source prose
selected to support the instruction. It tests a paraphrase with no matching
wording citation and confirms the citation is not inherited from a different
phrase. `v1_434` checks mixed metadata, JSON/SQLite persistence, legacy memory,
and malformed-input controls. The complete focused regression set passed:
8/8 provenance/citation/recombination diagnostics and 3/3 primitive-learning
diagnostics (11/11 total). `py_compile` and `git diff --check` also passed.

These fields improve auditability; they do not independently validate the
meaning link. The labeler declaration is not authenticated, neither labeler nor
wording citation changes rule selection, and none of these records count as
independent-source evidence. The natural-language mapping is still a reviewed
teacher judgment, not autonomous induction.

## Dialogue grounding and follow-up retest (2026-10-20)

Code snapshot: `2a41b96` (`Focus roadmap on dialogue and learning gates`). The
tracked dialogue implementation was unchanged during this retest. The working
tree contained unrelated edits to the large-corpus report and the source-rule
phrase experiment, plus local dialogue/research artifacts; those were not
inputs to these isolated dialogue scripts.

Runtime commands:

```sh
python3 experiments/v1_408_visible_source_referents.py
python3 experiments/v1_409_numbered_source_results.py
python3 experiments/v1_413_source_topic_followups.py
python3 experiments/v1_414_persisted_source_topic.py
python3 experiments/v1_419_failed_entity_followup_state.py
python3 experiments/v1_422_direct_search_request_results.py
python3 experiments/v1_426_dialogue_paragraph_grounding.py
python3 experiments/v1_427_dialogue_multiturn_transcript.py
python3 experiments/v1_435_dialogue_visible_evidence_anchor.py
python3 experiments/v1_438_dialogue_topic_pronoun_context.py
python3 experiments/v1_439_explicit_topic_clause.py
```

All eleven scripts passed. Together they exercise visible-only source referents,
numbered source selection and citation revalidation, named topic switches,
pronoun follow-ups, paragraph-local antecedent grounding, save/reload, failed
follow-up cleanup, and `why?` behavior. The CLI subprocess in `v1_419` checks a
source-only Eiffel Tower → Colosseum → unsupported Italy sequence and confirms
that a later `why?` does not replay the earlier entity's answer. `v1_435`
checks same-paragraph topic switches in both directions, rejects a wrong date
even when a matching citation exists but was not displayed, and checks a
separate-paragraph control. The `v1_413` history check and `v1_409` ordinal
selection check also pass. The 30-turn diagnostic in `v1_427` completed
without a crash and passed topic-switch, history, stale-explanation,
clarification, and save/reload checks.

These checks cover the previously reported classes of narrow topic-switch and
context failures, but they do not establish robust open-domain dialogue. The
30-turn `v1_427` script is a curated diagnostic, not an independently authored
representative benchmark or a verbatim replay of the earlier user scratch
session. Add varied document layouts and fresh paraphrased turns before
treating the dialogue packet as complete.

Current-checkout retest on 2026-10-20 ran `v1_413`, `v1_419`, `v1_426`, and
`v1_427`; all four passed. This includes the source-only Eiffel Tower →
Colosseum → “When was it completed?” sequence, the Colosseum's `80 CE` answer,
France → “and Italy?”, `why?`, and save/reload checks. The `v1_427` clarification
case was corrected to ask “When was it completed?” and require the cited 1889
sentence: its previous check asked when the tower was built but required a
builder sentence while rejecting the date, which did not measure the stated
dialogue behavior. The `v1_413` negative control now requires explicit
abstention and “may not answer” wording; it permits a closest sentence only
when clearly identified as non-answer evidence. These changes correct the
fixtures, not CRMS's answer behavior. The retest confirms these narrow cases on
the current checkout; held-out dialogue generalization remains unmeasured.

## New-entity dialogue transfer probe (2026-10-20)

Command: `python3 experiments/v1_442_heldout_dialogue_transfer.py`.

Four Codex-authored fixtures vary entity names and source layout: adjacent
entities in one paragraph, separate paragraphs with a third intervening
entity and a plural antecedent, line-wrapped source, and reversed entity order.
Each conversation checks a named answer, named topic switch, pronoun follow-up,
`why?`, exact source citation, state reload, and an unsupported closing-action
question. The run selected target evidence on 20/20 supported steps, returned
0 wrong answers, and abstained on all 4/4 negative controls. The conversational
labels and sources were constructed together by Codex; this is a frozen
regression/transfer probe, not an independent or representative dialogue
benchmark.

The probe exposed that `When did X open?` worked when the answer sentence
named X but failed when the source used a locally anchored pronoun and regular
past tense (`It opened ...`). The do-support retrieval morphology now runs for
WH questions beyond `where`, and exact licensed morphology can contribute to
sentence coverage. Pronoun-led sentences are considered when the nearest
explicit subject in the cited paragraph matches the query, including plural
and gendered forms. The existing 12 focused retrieval/dialogue regressions
(`v1_413`, `v1_414`, `v1_419`, `v1_420`, `v1_423`, `v1_425`, `v1_426`,
`v1_427`, `v1_435`, `v1_438`, `v1_439`, `v1_440`) also passed after the change.
This does not demonstrate open-domain language transfer or human-label
accuracy.

An added interruption sequence now tests each fixture after the initial
`why?`: an unsupported closing-date question must abstain, the next pronoun
follow-up must still resolve to the current named topic, and a subsequent
`why?` must explain that follow-up rather than the abstention. Current runtime
result: 32/32 supported evidence steps, 0 wrong answers, and 8/8 abstentions
across the existing four fixtures. Each fixture's pronoun check after the
interruption also remains correct after state reload. These are still
Codex-authored, fixed regression fixtures, not an independent dialogue
benchmark.

## New requests interrupt open dialogue slots (2026-10-20)

The 30-turn transcript uncovered a contextual routing error outside its
assertions: after CRMS asked which entity “it” referred to, “Tell me a joke”
was accepted as the missing entity. The same short-answer heuristic could
consume a new task as a response to an open clarification.

`experiments/v1_444_dialogue_request_interruptions.py` now checks three direct
requests (“Tell me a joke”, “Write a poem”, “Translate hello into French”) while
an entity slot is open, plus a valid short entity reply. Explicit imperative
requests are classified before the generic short-answer rule, clearing the old
slot; typed corrections such as “Set the location to San Jose” retain their
existing correction route. Clear embedded WH requests such as “Tell me who
created Python” and “Could you tell me who created Python?” enter the same
fact-question path as “Who created Python?”; the answer retains the original
utterance in its conversation history.

Runtime commands: `v1_444`, `v1_388`, `v1_427`, `v1_442`, `v1_353`, `v1_391`,
`v1_404`, `v1_419`, and `v1_438`; all nine passed. `git diff --check` passed.
The request classifier only recognizes the current explicit command vocabulary
and a narrow embedded-WH form; this does not establish broad intent recognition,
nor does it add joke-writing capability. The embedded question test uses an
accepted fact, not a source-only retrieval case. The new fixture and existing
dialogue scripts are Codex-authored.

## Grounded descriptive anaphora in source follow-ups (2026-10-20)

`experiments/v1_445_grounded_definite_description_followup.py` covers a source
paragraph that states “Python is a programming language” and later says “The
language was first released in 1991.” After the user names Python, CRMS now
normalizes “Tell me when it was first released” to direct-question word order,
resolves *it* to Python, and returns a citation spanning both the explicit type
link and the release-date sentence. The companion negative places Java as the
nearest explicit subject before “The language”; CRMS does not attribute 1991 to
Python.

The local anaphora check also now treats a copular phrase such as “It was
created” as a pronoun subject, not as a multiword entity name. The seven focused
scripts (`v1_445`, `v1_442`, `v1_426`, `v1_427`, `v1_423`, `v1_425`, `v1_438`)
passed, including cross-topic, source-only, exact-citation, and save/reload
controls. Compilation and `git diff --check` passed.

This is a narrow, source-explicit type-to-description link, not general noun
phrase coreference. The positive and negative fixtures were authored together;
they do not estimate accuracy on natural corpora. Unstated aliases and
description chains still require abstention or clarification.

## Source frames through reasoning and procedure composition (2026-10-20)

Command:

```sh
python3 run_experiments.py \
  --match v1_456_source_frames_to_reasoned_procedure --timeout 300
```

One diagnostic passed in 0.32 seconds. The experiment begins with four
Codex-authored documents. CRMS proposes parent and ancestor frames from two
training documents and two separately indexed holdout documents; the test
explicitly accepts these source frames, induces the parent-chain rule, validates
it on the held-out documents, then applies it to new runtime premises. Every
positive proof is checked by the independent proof verifier. Only the
proof-backed IDs `[12, 4, 4, 9]` feed a separately learned stable-unique then
reverse procedure; its `[9, 4, 12]` output is checked by an independent oracle.
The probe also verifies ambiguous proof-plus-negative evidence, an unknown
without a complete premise chain, correction invalidation, a proof explanation,
and code generation in a fresh chat process.

This closes a small but real integration seam between citation-backed sentence
frames, source-held-out rule induction, reasoning, and recombination. It does
not show autonomous frame acceptance: the experiment reviews every source
frame. The sentences are authored fixtures, source origins are synthetic, and
the procedure examples and instruction-to-operation mapping are Codex-labeled.
It does not establish broad corpus precision, publisher transfer, or open-ended
task planning.

During this work, the existing `v1_245` suite revealed a false parse after an
active “created” frame had been taught: “Archive was created by Cal” could be
read as “Archive was → create → by Cal.” `crms_knowledge.py` now rejects that
passive construction from active-frame matching. When the exact source is
queried, the separate review path still proposes `Cal — create → Archive`
with cited passive-role evidence. Corpus mining does not generalize from a
passive-only pattern without licensed morphology support. The focused
`v1_243`, `v1_245`, and `v1_456` diagnostics all pass after the guard.

## Current dialogue regression replay (2026-10-20)

On checkout `c229e3d`, the following targeted dialogue suite passed 5/5:

```sh
python3 run_experiments.py \
  --match v1_412_dialogue_topic_anchor_grounding \
  --match v1_426_dialogue_paragraph_grounding \
  --match v1_427_dialogue_multiturn_transcript \
  --match v1_442_heldout_dialogue_transfer \
  --match v1_449_cross_paragraph_pronoun_grounding --timeout 300
```

The suite covers the reported Eiffel Tower/Colosseum switch, paragraph-local
pronoun grounding, source-only follow-ups, unrelated interruption and `why?`,
fresh-process/reload persistence, and abstention when a pronoun lacks a valid
source anchor. Total runner time was 0.88 seconds. These five passing
diagnostics confirm the named regression controls on this checkout; most
transcripts and labels are Codex-authored, so the result does not show broad
dialogue reliability or independent generalization. Keep the dialogue packet
open for varied, independently authored conversations and measure wrong
referents, omissions, clarifications, and task completion separately.

## Structured-field predicate alignment on SimpleWiki (2026-10-20)

The exploratory read-only scan
`python3 experiments/v1_337_structured_prose_alignment_probe.py` processed all
285,478 documents in the local SimpleWiki index. Its explicit field/relation
map found a repeated `capital city of` candidate for `capital of` across eight
distinct entity pairs. The initial probe also produced a false
`national museum of` / `born in` candidate on two pairs: both mentions came
from `caption = ...` infobox lines, not article prose. The probe now excludes
sentence spans that overlap structured key/value lines, with a direct
caption-versus-prose regression. After that change, the scan counted 4,223
joint field/prose mentions, 45 role-compatible parses, and 30 canonical
relation matches. It reported four groups total, of which only
`capital city of` → `capital of` was a novel predicate group; the museum
caption proposal disappeared. This remains a narrow candidate-yield measure,
not proposal precision or recall.

A separate full-corpus call to the integrated
`CRMSKnowledgeBase._propose_structured_predicate_alignments` path found the
same capital wording on eleven pairs and did not return the museum alignment.
After that filter, the paths were compared on an identical probe-eligible set with
`python3 experiments/v1_458_matched_structured_alignment.py`. The script
copied 3,284 matching documents into a temporary SQLite index; both paths
found exactly the same eight `capital city of` pairs (8 overlap, zero
path-specific pairs). The original eleven-pair integrated result includes
three pages excluded by the probe's `text.startswith("Infobox")` scope. After
the caption filter, the exploratory scan reports four groups total, only one
novel predicate group, and no museum-caption false proposal. This is a useful
boundary correction, not a real-corpus precision estimate: both paths still
use hand-coded field-to-relation maps, and field and prose citations come from
the same page. The eight repeated pairs are not independent publisher
evidence, and unproposed variants remain unmeasured.

The matched-scope runtime diagnostic passed under the isolated experiment
runner (`v1_458`, 1/1 in 18.74 seconds); the structured learning/review fixture
also passed (`v1_338`, 1/1 in 0.34 seconds). The `v1_458` result checks exact
agreement between the two implementations for the capital candidate on the
matched documents. It does not evaluate general rule learning.

Codex manually reviewed the eight cited capital examples: all eight directly
express the capital relation, including the inverted “capital city of England
is London” frame. It also reviewed both metadata artifacts and labeled them
non-prose evidence. The citation-backed labels and explicit limitations are in
[`structured_predicate_alignment_review.json`](../experiments/reports/structured_predicate_alignment_review.json).
This was an unblinded review of generator-selected candidates by the same
system that built the probe; it is not independent precision evidence. No
random non-proposal sample was labeled, so recall is unknown.

## Academic-corpus phrase attestation (2026-10-20)

`python3 experiments/v1_459_academic_phrase_attestation.py` scanned all 1,697
documents in the local arXiv CC0/CC-BY research index, read-only. It found zero
sentences with the exact phrase `capital city of`; it found one sentence with
`capital of`, describing Stockholm as the largest city and a capital of
Sweden. The example citation resolved to the exact sentence. This gives one
independent-source attestation of canonical wording but no evidence for
cross-source transfer of the candidate variant. The arXiv sample is small and
domain-mismatched for country-capital wording, so zero hits are not a negative
semantic judgment and provide no estimate of general phrase coverage.

The script is a lexical attestation check, not a synonym test. A useful next
test needs a second source corpus with overlap in the candidate relation and
surface wording, or a broader independently sourced corpus where such overlap
can be measured. Do not count same-page field/prose repetitions as independent
publisher support.

## Cross-domain runtime replay on current checkout (2026-10-20)

At `edb2893`, the selected runtime set was rerun with isolated working
directories:

```sh
python3 run_experiments.py --match 327 --match 242 --match 376 \
  --match 357 --match 207 --match 389 --match 413 --match 414 --timeout 300
```

All 10 selected diagnostics passed in 11.34 seconds. The selected domains
cover phrase transfer, list recombination/retrieval, graph reasoning,
list→math/code composition, grounded translation, story revision, and
source-topic dialogue/persistence. These pass results mean only that the
selected assertions held; they do not provide a broad task success rate.

The current `v1_327` scores are:

| Set | Baseline correct | Layer correct | Layer wrong | Layer abstained | Must-refuse accepted |
|---|---:|---:|---:|---:|---:|
| Dev | 46/78 | 73/78 | 0 | 5 | 11/11 |
| Held | 34/45 | 44/45 | 0 | 1 | 12/12 |
| Unseen | 31/44 | 42/44 | 0 | 2 | 14/14 |

The paraphrase layer retained the earlier correct/wrong/abstain counts, while
the direct baseline changed from the prior recorded snapshot (`d597615`):
dev 50→46, held 31→34, unseen 29→31. A repeat run on this checkout produced
the same new figures. The datasets are small and partly tuned; the shift is
not evidence of a general regression or improvement. Preserve both snapshots
and investigate the baseline change before using that baseline for trend
claims.

The direct `v1_376` run independently verified positive proofs and reproduced
the expected distinctions: the depth-35 chain and depth-9 tree answered; the
diamond result was incomplete at the 64-proof cap; explicit positive plus
negative was ambiguous; a negative-only open-world case and a complete miss
were unknown; exhausted expansion remained incomplete; the cycle-backed
self-relation was ambiguous; and an irreflexive constraint denied its self
link. These are controlled engine checks, not evidence of broad natural-
language reasoning.

The current worktree also contained the user's uncommitted corpus audit report
and local dialogue scratch files. The scorecard did not edit or depend on
those artifacts. The older `d597615` result above remains a historical
snapshot rather than a substitute for this rerun.

`python3 experiments/v1_338_structured_field_predicate_learning.py` passed all
checks: the proposal remained inert before review, six training pages licensed
two held-out question forms, cited evidence survived SQLite reload, stale
proposals were rejected, and the coordinated “capital and largest city”
negative was not simplified into an alias. This validates the review/writeback
mechanics on fixtures, not the correctness or generality of the real-corpus
alignment. Next, evaluate a blinded sample of proposals and non-proposals
before widening the allowlist or promoting this to a language-learning claim.
