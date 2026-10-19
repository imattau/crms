# Language and recombination benchmark baselines

## Capability-comparison status (2026-10-19)

CRMS has focused, reproducible checks for natural-language transfer,
recombination, retrieval, math, coding, translation, and proof-backed
reasoning, but these results are not a shared cross-domain score and do not
establish equivalence to a large language model. The current container exposes
an `ollama` executable but no reachable Ollama service (`ollama list` failed to
connect to `127.0.0.1:11434` under the available runtime permissions), and no
direct 70B-class comparator outputs are recorded here. A qualitative
capability and interaction comparison, based on published model reports and
the CRMS component results, is in
[`capability_comparison_70b.md`](capability_comparison_70b.md). A direct
head-to-head score still requires a pinned model/runtime on the same held-out
tasks and context. Report component results and unsupported cases separately;
make no parity claim.

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
Unsupported connective, operation, and modifier variants abstain and produce
no code. This is reusable composition over known list procedures, not zero-shot
programming or broad natural-language understanding. The control flow and
source count are local CRMS results; no external 70B model was run on this
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
from the article title, it found 1, 1, 1, and 4 repeated relation frames respectively, and no
cross-predicate alignment proposals in any window. It accepted no rules and made no index writes.

This is evidence that the strict shared-subject/object alignment path has low yield in these
bounded samples, not evidence that the corpus contains no useful paraphrase pairs. Windows are
not exhaustive, and the frame counts are not precision estimates. The `born in` examples also
show sentence-level extraction relying on article context (`He was born in Swansea`), so proposed
rules must retain exact source citations and remain reviewable. Corpus frame mining now excludes
such page-title substitutions because they do not establish the pronoun antecedent strongly
enough for reusable language rules. Treat this as a motivation to improve corpus candidate recall
and context validation together; do not lower the independent-pair or human-review requirements
based on this sample.

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
