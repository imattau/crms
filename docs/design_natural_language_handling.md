# Design: improving natural language handling (answer-type gate, paraphrase tolerance, polar entailment, pronouns)

**Audience:** the developer (human or AI) implementing this.
**Status:** proposed; the quoted-evidence gate and FTS fallback are implemented. The benchmark
ideas below were prototyped as a *wrapper around the unmodified engine* in a scratch folder and
measured on three question sets (section 2). The live gate applies to quoted source evidence,
checks named mentions, answer type, lexical relation support and required superlatives, and can
select from top FTS hits. Exact-title polar evidence can resolve a surname used locally in one
unique article, and bounded birthplace questions can read an exact-title `birth_place` field.
The prototype and the three question sets are in
`experiments/v1_327_paraphrase_benchmark_nl_layer.py` (run it to reproduce section 2.3); the code
is a sketch of the logic, not a patch to apply. A later check on real SQuAD passages (section 2.5)
showed the "zero wrong" result does not generalise: about one question in eight still gets a wrong
answer, and the main remaining losses are indirect references inside sources and choosing among
several passing sentences (section 6, items 8 and 9).
**Relationship to other docs:** the ground rules in section 0 of
[design_learning_dynamics.md](design_learning_dynamics.md) apply unchanged (evidence over
assumption, abstain when unsure, propose then verify, deterministic, CPU-friendly). Section 4
(synonym proposals) reuses the review-before-store path and is a cousin of the equivalence work in
that document. Latency and reasoning-effort work should also follow the staged plan in section 7;
it complements recombination, self-learning rules, and proof-producing reasoning rather than
replacing them.

## 0. Problem and evidence

A hand-driven chat session (about 64 phrasings, small corpus) and then a scripted benchmark
(section 2) showed four failure classes, in order of seriousness:

1. **A sentence for the wrong relation is shown as the answer.** "How tall is Mount Everest?"
   returns the location sentence although the height sentence is indexed. "How many people work
   at Quarn Beacon?" returns the founding sentence. "Does the Amazon River flow through Peru?"
   returns the Brazil sentence with no yes, no, or unknown. This breaks "abstain when unsure".
2. **Reversed roles.** "Who is the parent of Dan?" returned "Dan is a parent of Eve" (the child
   direction) in the interactive run. Not covered by the benchmark; see section 6.
3. **Dead ends and misroutes.** "I found relevant source text, but no accepted fact supports an
   answer yet. Ask 'why?'" appears where other routes show the sentence directly. "Who wrote
   Hamlet?" was sent to the paper-title lookup although "Shakespeare wrote Hamlet" was indexed.
4. **Brittleness to wording.** "Who made Python?", "Name the creator of…", "Australia's
   capital city is which?", typos ("craeted"), short names ("Einstein" for "Albert Einstein"),
   definitions ("What is photosynthesis?"), and every pronoun follow-up fail.

### 0.1 Baseline (unmodified engine, `crms_chat.py` as of commit `a77f167` plus uncommitted work)

| Set | Answerable correct | Abstained | Wrong | Must-refuse ok |
|---|---|---|---|---|
| dev (89 items, written first, used while building) | 33 / 78 (42%) | 37 | 8 | 10 / 11 |
| held (57 items, written before building the layer; later used to tune two rules) | 26 / 45 | 16 | 3 | 9 / 12 |
| unseen (58 items, written after the layer was final; run once) | 25 / 44 | 15 | 4 | 13 / 14 |

Baseline runs repeat identically. Per-family baseline for dev: polite wrappers, case/punctuation,
superlatives, release years 100%; canonical 10/19; synonym verbs, typos, possessives, definitions,
property questions, inverse questions, birthplace 0%; count questions 0/4 and all four *wrong*.

## 1. Ground rules for this work

- **The layer may only turn an answer into an abstention or add an answer that passes the same
  checks.** It must not make a wrong answer more likely. Track `wrong` as the number to drive
  toward zero and `correct` as the number to grow. Zero was reached on small hand-written fixtures;
  on real passages it was not (section 2.5), so report the measured rate honestly.
- **No hidden semantics.** Anything the layer "knows" about language is either (a) closed-class
  grammar (wh-words, auxiliaries, units, number words) kept in one inspectable table, or (b) a
  reviewable, revocable record with provenance (section 4). Nothing silent.
- **Every added answer is labelled** as quoted evidence, as the engine already does.
- **Deterministic**: same input, same output (verified by repeat runs of the benchmark).

## 2. Method and results

### 2.1 Benchmark

Three question sets with expected answers, run each in a fresh chat process (no dialogue state)
against a small text corpus of simple factual sentences:

- `dev`: 15 facts, 89 items in 25 phrasing families (canonical, case/punctuation, polite wrapper,
  passive, synonym verb, nominal, possessive, cleft, wh-variant, alias, typo, count, height,
  definition, property, polar yes / no / wrong-object, unanswerable).
- `held`: new corpus, 57 items, same families. I wrote it before the layer, then used its results
  to fix two defects (an over-eager relation veto and missing place and unit checks). Treat it as
  partly tuned.
- `unseen`: another new corpus, 58 items. I wrote it after the layer was final and ran it once
  before any further change. I then made small fixes (ordinal and superlative handling, a
  definition-pattern bug) found through a separate larger-index test and re-ran all three sets to
  check for regressions (section 2.3). Treat unseen as lightly tuned too.

Grading is lenient: an answerable item is *correct* if the reply contains the expected string and
is not a refusal; *wrong* if it answers without it; *abstain* if it declines. A must-refuse item
is ok if the reply declines (or, for a wrong-object yes/no question, says no).

### 2.2 Ablation (dev set; each row adds nothing else)

| Configuration | Correct | Abstain | Wrong | Notes |
|---|---|---|---|---|
| baseline | 33 | 37 | 8 | |
| gate only | 33 | 45 | 0 | all 8 wrong become abstentions; one more correct |
| gate + fallback retriever | 57 | 21 | 0 | +25 correct, no regressions |
| rewrite only | 38 | 30 | 10 | +6 correct, but alias expansion exposes 2 more engine errors |
| typo only | 37 | 33 | 8 | +4 |
| polar only | 37 | 34 | 7 | +5 |
| all of the above | 69 | 9 | 0 | |
| + strict gate + seed pack | 73 | 5 | 0 | final |

The gate alone is the single most valuable piece for safety; the fallback retriever is the single
most valuable piece for coverage. Rewriting alone can *increase* visible wrong answers because it
routes more questions to engine paths that mis-answer; do not ship rewrites without the gate.

### 2.3 Final configuration across all sets

| Set | Baseline correct / wrong / refuse-ok | Final correct / wrong / refuse-ok | Final without seed pack |
|---|---|---|---|
| dev | 33 / 8 / 10 of 11 | 73 / 0 / 11 of 11 | 68 / 0 / 11 of 11 |
| held | 26 / 3 / 9 of 12 | 44 / 0 / 12 of 12 | 43 / 0 / 12 of 12 |
| unseen | 25 / 4 / 13 of 14 | 42 / 0 / 14 of 14 | 40 / 0 / 14 of 14 |

Zero wrong answers and all must-refuse items declined on all three sets. **This does not carry
over to real passages.** These sets are short, hand-written, partly tuned, and use simple sentences
with explicit subjects. On real encyclopedic paragraphs the same layer still gave a wrong answer to
about one question in eight (section 2.5). Read "zero wrong" as a property of these fixtures and a
target for the design, not as a measured property of the system.

### 2.4 Check on a real index (2.2 GB Simple English Wikipedia FTS index, copy, deleted afterwards)

24 factual questions through the real chat (hand graded). Of the 18 questions the engine answered
(not abstained), 12 were wrong or non-answers (WWII end date returned a memorial sentence; "How
tall is Everest" returned "a tall mountain range"; "boiling point of water" returned a solutes
sentence; "largest planet" returned a Mercury sentence; "How many moons does Mars have" returned
"both moons have many craters"; a citation fragment for the Great Wall; and so on). The gate
vetoed 8 of those 12 with 0 false vetoes in the final run. Four wrong replies still passed: the
"United States founded" rock-band sentence (ambiguous entity), "first president" returning a
sentence about the current president (ordinal modifier not checked), a percentage for "How many
people live in Tokyo", and a printing-press sentence. Six correct replies passed unchanged.
This is a small sample, and it was run before the last tweak removing `first` and `last` as
required modifiers; the numbers show direction, not a rate.

### 2.5 Check on real passages (SQuAD 1.1 dev set)

To test the layer outside my own sentences I used the SQuAD 1.1 dev set (question, source
paragraph, gold answer span; CC BY-SA 4.0; about 4.8 MB; downloaded to a scratch folder and not
added to the repository). I picked 10 of its 48 articles at random (fixed seed), indexed each
article's paragraphs as one corpus, and asked 200 of its questions (20 per article). As a safety
check I also asked 100 of those questions against a different article's corpus; every one should
be declined. A reply counts as correct if it contains any gold answer after lowercasing and
stripping articles and punctuation. This grading is lenient on span length and strict on wording
(see the caveats below).

All figures use a frozen copy of the committed engine (`git archive` of commit `622fa99`).
Another session was editing `crms_chat.py` and `crms_research.py` while I tested, and earlier
runs against the live working tree were not comparable: the engine-alone count moved between
runs (60, 65 and 90 correct) because the code changed underneath the test. Two runs against the
frozen copy gave identical numbers. Any future benchmark of this kind should pin the engine
version it measures.

| Configuration | Correct | Abstained | Wrong | Wrong-article answered | Precision |
|---|---|---|---|---|---|
| Engine alone | 90 | 77 | 33 | 5 / 100 | 73% |
| Prototype layer (section 2.3 final) | 99 | 74 | 27 | 5 / 100 | 79% |

Precision is correct divided by all answers given. The layer helps, but 27 of 200 questions
(13.5%) still get a wrong answer, against 0 of 78, 0 of 45 and 0 of 44 on the small sets. Do not
promise "no wrong answers" for real text.

**Stricter gate (tested, not recommended).** Three changes were tried on top of the layer:

| Variant | Correct | Abstained | Wrong | Wrong-article answered |
|---|---|---|---|---|
| Layer as before | 99 | 74 | 27 | 5 / 100 |
| + abbreviation-safe sentence splitting ("St.", "Mr.", initials) | 99 | 74 | 27 | 5 / 100 |
| + sentence-level gate (check each sentence of a long reply) | 96 | 74 | 30 | 5 / 100 |
| + require two shared content words | 87 | 88 | 25 | 2 / 100 |

Splitting made no measurable difference. The sentence-level gate returned only the first passing
sentence and so dropped some gold sentences that sat next to it in the reply. Requiring two shared
words removed two wrong answers at the cost of 12 correct ones; on the small sets it lost one dev
and one unseen answer. Making the gate stricter trades correct answers for a small safety gain and
does not address the real cause below.

**Why the remaining answers are wrong.** For the 25 wrong answers left in the last variant:
21 came from the engine's own reply passing the gate and only 4 from the fallback selector. In 12
cases the sentence that contains the gold answer *fails* the gate, mostly because it refers to its
subject indirectly ("it", "the former", "this process") or paraphrases the question. In the other
12 the gold sentence passes the gate but a different passing sentence was chosen; the median number
of corpus sentences passing the gate was 3. So the loss is (a) indirect reference and paraphrase
inside the source and (b) choosing among several plausible sentences. It is not a lack of strictness.

**Ranking among gate-passing sentences (small gain, margin required).** I ranked the sentences
that pass the gate by the summed inverse document frequency of the question's content stems and
mention tokens that they contain, then chose between the top sentence and the engine's reply:

| Variant | Correct | Abstained | Wrong | Wrong-article answered | Precision |
|---|---|---|---|---|---|
| No ranking (layer as before) | 99 | 74 | 27 | 5 / 100 | 79% |
| Always take the top-ranked sentence | 99 | 61 | 40 | 18 / 100 | 71% |
| Top-ranked, plus a bonus when the engine also returned it | 105 | 61 | 34 | 18 / 100 | 76% |
| Top-ranked only if it scores at least 1.2 times the runner-up, else previous behaviour | 103 | 72 | 25 | 6 / 100 | 80% |
| Same margin 1.2, else abstain | 85 | 99 | 16 | 6 / 100 | 84% |
| Margin 1.5, else abstain | 70 | 117 | 13 | 6 / 100 | 84% |

The small sets were unchanged in every variant. Ranking without a margin is worse than not ranking.
With a margin, the best balanced variant gained 4 correct answers and lost 2 wrong ones, which is
within the noise of a 200-question set. Abstaining when the top candidates are close gives cleaner
answers (about 84% precision) but declines roughly 40% of questions. Use ranking only to choose
between candidates that already pass the gate, always with a margin, and prefer abstaining over
guessing when candidates are close.

**Caveats for this section.**
- 200 questions from 10 articles is a small sample; differences of a few questions are noise.
- I fixed the margin values (1.2, 1.5) in advance but compared them on the same test set, so a
  fresh sample may differ.
- Grading by gold-string containment has known gaps: a few "wrong" answers are near misses (a
  rounded date, a truncated sentence), and one engine abstention ("I found topic matches, but no
  retrieved sentence states a cause") was graded as wrong because the grader does not recognise
  that phrasing.
- Learning wording from the dataset did not help (section 3.6): mining question-to-gold-sentence
  word pairs from 7,590 questions in the other 38 articles and adding them to the synonym list left
  correct answers unchanged and slightly increased wrong ones. Only 9% of the sampled questions
  share no content word with their gold sentence; 28% share all of theirs and 63% some, so missing
  paraphrase knowledge is not the dominant loss on this data.
- The test scripts are in a scratch folder and are not committed. Adding a SQuAD-style set to the
  repository needs the data to be fetched at run time (it cannot be bundled without checking the
  licence), so it would be an optional experiment.

## 3. The ideas, with what was tested

### 3.1 Answer-type and relation gate (highest priority)

**Rule.** Parse the question into: wh-type (WHO, WHEN, WHERE, MEASURE, COUNT, DEF, NAME, POLAR),
mentioned entities, content words, and modifiers. A candidate sentence is accepted only if it:

1. contains every mention token (so "Everest" matches "Mount Everest": token subset);
2. satisfies the type: WHEN needs a four-digit year; MEASURE needs a number followed by a unit
   (closed list: metres, km, miles, degrees, kg, years …), so a bare year does not answer
   "how tall"; COUNT needs a digit or number word; WHO / WHERE need a capitalised span that is not
   one of the question entities;
3. shares at least one content-word stem with the question, using the engine's own irregular
   verb paradigms (`_IRREGULAR_VERB_PARADIGMS`) plus suffix stripping and a 5-character prefix;
4. contains required superlative modifiers (`longest`, `largest`, `smallest`, …);
5. for DEF ("What is X", "What does X do"), has X in the first six tokens (subject position).

Otherwise reply "I found source text, but it does not state what you asked; I won't guess." and
show the sentence found.

**Tuning that mattered.** A *lenient* gate (veto the relation check only if the question's
relation word occurs somewhere in the corpus) left one wrong answer on unseen ("birthplace" never
occurs in the corpus, so the location-of-photography sentence passed). A *strict* gate (always
veto on no overlap) plus a seed pack of equivalences (section 3.5) removed it. Strict without the
seed pack costs correct answers on legitimate paraphrases (rows "without seed pack" above), which
is why section 4 matters.

**Edge cases found.** A "first" modifier must not be required verbatim ("What year was Python
first released?" regressed); superlative questions must not be classified DEF ("What is the
smallest planet…" regressed).

**Where to put it.** One function applied to every candidate reply before it is returned, in
`crms_chat.py` where routes currently build `turn.text`, and inside `ask` for direct answers.
Do not re-implement per route. It must run on top-k candidate sentences from the index, not on a
corpus scan.

**Acceptance.** On a held-out set of at least 40 questions: zero wrong answers among answerable
items and 100% of unanswerable items declined, with correct count not lower than baseline. That
bar was met on the hand-written sets but not on real passages (section 2.5: 27 wrong of 200).
For real text, report wrong answers, abstentions and wrong-article answers as separate numbers and
track the wrong-answer rate over time instead of asserting zero.

### 3.2 Fallback sentence selector

When the engine abstains (or the gate vetoes), score candidate sentences with the same checks and
return the unique best, labelled "fallback match: quoted evidence, not an accepted fact". If two
candidates tie, abstain. In the dev ablation this added 25 correct and no wrong answers.

**Scale caveat.** The prototype scanned all sentences of a 29-sentence corpus. In CRMS it must
take its candidates from the FTS retrieval (`source_fts`, `source_chunks`), not the whole corpus,
and sentences from the top chunks only. This was **not** tested at scale; measure latency and
accuracy on the real index before adopting.

### 3.3 Polar (yes/no) entailment

Parse "Is / Was / Did / Does A V B?" into agent, verb stem, patient (passive forms swap them).
Answer *yes* when one sentence contains all mention tokens and the verb stem and the agent comes
before the verb before the patient; answer *no* when a mention appears after "not" in the matching
sentence ("Canberra is the capital of Australia, **not Sydney**"); otherwise, if a sentence has the
same subject and relation but not the object, say "the source does not confirm this; it states: …".
Role order matters: "Did Penicillin discover Alexander Fleming?" must not answer yes.

Fixes: "Was Marie Curie born in Warsaw?", "Is Mount Everest in the Himalayas?", "Does the Thames
flow through London?". Added 5 correct on dev (polar only), 3 on held.

**Known weakness.** Mention detection joins consecutive capitalised words into one mention. "Is
Australia Sydney?" becomes one mention and answered *yes* from the "not Sydney" sentence. Mention
detection should split on the capitalised-run boundary and use known entities from the store
(section 6).

### 3.4 Light pre-processing (only with the gate)

Deterministic rewrites tested: possessive ("X's capital" → "the capital of X"), "In what year did"
→ "When did", "By whom was Z V-ed?" → "Z was V-ed by whom?", "Name the X of Y" / "Define X" → "What
is …", and alias expansion (short mention → the unique corpus entity containing its tokens;
ambiguous → leave). A rewrite "Which city is …" → "What is …" *hurt* ("Which range is Mount
Everest in?" regressed) and was removed. Typos: replace an out-of-vocabulary word of length ≥ 4
with the unique vocabulary word at edit distance 1 (including transposition) and **echo the
correction** to the user. Typo alone added 4 correct on dev and 4 on held.

### 3.5 Seed equivalence pack (closed, inspectable, revocable)

The gate removes wrong answers but also rejects legitimate paraphrases that share no word with the
sentence ("tall" ~ "height", "born" ~ "birthplace", "create" ~ "make"). The prototype used five small
groups. Effect: dev 68 → 73 correct, held 43 → 44, unseen 40 → 42, with wrong still 0.

This conflicts with the README principle of "no built-in synonym inventory". The compatible
design is a **starter pack stored as ordinary reviewable records** (same store as learned
equivalences, with a provenance of `seed`), listable and removable by the user, never hidden in
code. Learned groups (3.6) use the same store.

### 3.6 Corpus-evidence predicate alignment

The implemented report-only aligner proposes a relation wording when two positive, independently
parsed relation frames share at least two exact subject/object pairs. For each shared pair, it
requires the two wording variants to come from different documents; each side must also be
supported across distinct documents. The user chooses whether to accept the canonical relation.
Acceptance revalidates every cited sentence, stores both sources, and teaches the observed question
frames. It never auto-accepts a proposed alignment.

Frame mining now retains up to eight independent source documents for each exact relation/pair.
This matters when the first occurrence of both wordings appears in one article: that shared article
cannot count as independent evidence, but it must not hide later independent sources. The
alignment stage selects a cross-document pair and still counts distinct entity pairs, not repeated
mentions, toward the two-pair threshold. `experiments/v1_260_corpus_only_predicate_alignment.py`,
`v1_261_large_corpus_alignment.py`, `v1_296_large_corpus_predicate_learning.py`, and
`v1_334_independent_alignment_evidence_retention.py` exercise report-only discovery, explicit
acceptance, held-out transfer, and this source-retention rule.

Real-corpus yield remains the open problem. On the 285,478-document SimpleWiki index, a read-only
10,000-document/400,000-sentence sample produced 19 relation-frame proposals but zero predicate
alignments, even when the retained frames were checked for any cross-document shared pair. Do not
lower the evidence threshold to manufacture yield. The next research step is role-compatible
distributional evidence (such as independently grounded subject and object classes), with
review-only hypotheses and held-out tests that measure both paraphrase recall and false alignment.

### 3.7 Pronouns and follow-ups

Baseline: every pronoun follow-up in nine scripted two-turn dialogues returned "Please name the
entity this pronoun refers to." The prototype substituted the single named entity of the previous
question, and asked "Which one do you mean?" when the previous turn had more than one distinct
entity. Result: 7 of 9 dialogues acceptable vs 3 of 9 (the comparison counts "abstain on a trap"
as acceptable). It failed two ways worth designing against: (a) "Did Marie Curie win a Nobel
Prize? / How many did she win?" asked for clarification because "Nobel Prize" counts as a second
entity (needs animacy or role: prefer the grammatical subject); (b) "What is the capital of
Australia? / Is it Sydney?" bound "it" to the wrong entity (the capital, not the country) and the
polar module then answered yes (see 3.3 weakness). Also never search the pronoun itself: the
interactive run had "Where was he born?" looking for the birthplace of "he".

### 3.8 Exact-title context and structured biographical fields

A unique exact-title article can license a narrow local subject alias. For example, if the
`Alan Turing` page says “Turing worked at Bletchley Park,” that page title resolves `Turing` to
`Alan Turing` for this sentence. The alias must not transfer to another search result or become a
general surname rule. The polar route still requires the requested verb, argument order, and
complete object phrase in the same asserted sentence; a different workplace remains unknown. The
quoted sentence is reviewable evidence, not an accepted fact.

Some source pages express an answer in an infobox instead of prose. For the bounded `Where was X
born?` form, CRMS can read the exact-title page's explicit `birth_place` field when one unique
value exists. It cites that exact field and labels the result as quoted source evidence. It does
not turn the field into an accepted fact or infer a birthplace from nationality, an institution,
or nearby text. Conflicting values, missing fields, and non-unique title matches must abstain.

`experiments/v1_333_exact_page_alias_and_birthplace.py` checks the title-local alias, wrong-object
abstention, explicit negation, and exact field citation through a fresh CLI session. A read-only
replay on the 285,478-document SimpleWiki index returned the Bletchley Park sentence for the
yes/no question, abstained for Cambridge, returned the same Bletchley Park sentence for `Where
does Alan Turing work?`, and read Warsaw from Marie Curie's exact-title infobox. These cases validate the
targeted route, not broad coreference or polar-question coverage.

## 4. Delivery order

### 4.1 Initial runtime gate

`crms_nl_gate.py` is wired into the final quoted-evidence reply path in `crms_chat.py`. It checks
capitalized entity mentions, a closed answer-type table (year, measurement, count, named answer or
definition), lexical relation overlap, and requested superlatives. It first considers the engine's
source sentences, then adds exact asserted sentences from the top 12 FTS hits; it does not scan the
corpus. It also runs on supported question types when the ordinary answer path abstains. A unique
best match is quoted with its source. If candidates fail the checks or tie, CRMS abstains. Accepted
fact answers and proof-backed inferences do not pass through this quoted-source gate. For WHO
questions it checks basic active and `relation of X` word order, including passive `by` evidence.
When the current research result carries a `licensed_predicate` expansion, the gate uses the
source-backed relation family for overlap and FTS retrieval. An unlicensed synonym cannot activate
that family.

Runtime validation in `experiments/v1_329_runtime_nl_gate.py` covers the Curie/Einstein retrieval
collision, a wrong answer type, a correct height answer, a direct creator answer, and abstention
when a measurement is absent, plus licensed-versus-unlicensed relation forms. It also checks the
previously observed reversed-parent role, exact polar support, polar abstention on a wrong object,
short-name location retrieval, and a question-anchored review proposal for `Who made Python?` when
the source says `created`. This proposal does not treat the two verbs as equivalent: it presents
the source relation and asks for review before teaching a rule. The `v1_327` three-set benchmark passed its wrapped-layer
invariants (zero wrong, all must-refuse items declined). Two identical runs with the live gate and
fallback scored 41/78, 25/45 and 27/44 correct on dev, held and unseen, with zero wrong and
corresponding abstentions. The full experimental wrapper scored 73/78, 44/45 and 42/44 with zero
wrong. Production safety improved, but substantial paraphrase coverage remains unimplemented and
the abstention rate is still high. The gate remains incomplete: lexical relation
overlap can abstain on valid paraphrases, named-entity detection is capitalization-based, and these
sets are partly tuned rather than a fresh independent evaluation. Reviewed equivalences remain
future work; do not treat this as complete natural-language understanding.

1. **Gate** (3.1), implemented for quoted-evidence and supported abstention routes; broaden its
   answer-type and relation coverage using independent evaluation.
2. **Show the best sentence by default** for the "no accepted fact supports an answer yet" case,
   labelled as before (small, consistent).
3. **Fallback selector** (3.2), implemented over the top 12 FTS hits; measure latency and improve
   candidate ranking.
4. **Polar entailment** (3.3), implemented for the bounded parsed forms; broaden it with tested
   mention and passive-role handling.
5. **Rewrites and typo echo** (3.4), only after 1 is live.
6. **Seed pack as records** (3.5), then **evidence-based synonym proposals** (3.6).
7. **Pronoun handling** (3.7) last; it needs the subject/role information.
8. **Measure retrieval latency and reduce snippet construction work** before adding visible
   reasoning stages (section 7.1; bounded matched-chunk selection is implemented, large-index
   acceptance remains open).
9. **Keep proof verification keyed and effort budgets deterministic** (sections 7.2–7.3;
   implementation and synthetic runtime checks are in place; disk-backed scale remains open).
10. **Validate thorough checks on independent natural-language data** (section 7.4; the current
    50-question synthetic lexical-confound benchmark is a mechanism check, not a general quality
    result).
11. **Keep page-title aliases local and structured metadata cited** (section 3.8; exact-title
    surname grounding and birthplace-field reading are implemented, with the real-index sample
    recorded in `benchmark_baselines.md`).

Each step: add a benchmark family or reuse the sets above, record the numbers in
`benchmark_baselines.md`, and require wrong = 0.

## 5. Out of scope

- Generating fluent replies (templates for the labelled sentence are enough).
- General coreference resolution across paragraphs. A bounded form is *not* out of scope: resolving
  an indirect reference to the topic of the same paragraph or article ("it", "the former", "this
  process") so that a sentence that states the answer can pass the mention check (section 6,
  item 8).
- Embeddings or any learned similarity model.
- Relation extraction beyond the closed type table; open-ended relation discovery stays with the
  existing frame-learning machinery.

## 6. Open questions and untested items

1. The benchmark corpora are small and the questions were written by one author, partly during
   development. A fixed, committed paraphrase benchmark with a shared grader should replace the
   scratch scripts (the cross-surface transfer benchmark in
   [design_evidence_independence_and_transfer.md](design_evidence_independence_and_transfer.md)
   section 3 is the natural home; that section still needs four corrections: a k=0 baseline,
   separate corpus and store routes, passive teaching via paired frames, and an updated reply
   classification).
2. The reversed-role case ("Who is the parent of Dan?") was observed interactively but is not in
   the benchmark; add family-chain items and check the gate's role-order logic handles "parent of".
3. Latency of the gate and selector on the 2.2 GB index (candidates only) is not measured.
4. The strict gate's false-veto rate on varied real questions is unknown beyond the 24-question
   sample. Precision of ordinal/superlative handling ("first president", "largest") is partial.
5. The seed pack was composed after seeing the dev set; its groups should be reviewed and the
   effect re-measured on a fresh set before it ships.
6. Mention detection should use known entities in the store, not capitalisation, to avoid the
   merged-mention error in 3.3.
7. Cold-cache behaviour and multi-threading of the gate are not examined.
8. **The real next problem: indirect reference inside sources.** On SQuAD passages (section 2.5)
   half of the remaining wrong answers are cases where the sentence that states the answer does not
   name the entity the question asks about ("It was founded in 1946", "the former type", "this
   process"), so the mention check rejects it and a different sentence is chosen or CRMS abstains.
   Candidate approach, to be tested before adoption: for a sentence without a named subject, bind
   its pronoun or definite reference to the nearest preceding named subject in the same paragraph
   or to the exact-title article (section 3.8 already does this for a surname), record that binding
   as reviewable evidence, and let the mention and type checks run against the bound entity. The
   binding must abstain when more than one preceding entity could fit. Measure it on the SQuAD
   sample first, because it targets the largest remaining loss.
9. **Choosing between gate-passing sentences.** The other half of the remaining wrong answers are
   cases where several sentences pass the gate. Ranking by inverse-document-frequency overlap with a
   margin helps only slightly (section 2.5); try stronger evidence (proximity of the matched words,
   agreement between the two best candidates' answer spans, and the role-order checks from 3.3)
   and keep abstaining when candidates are close.
10. **Pin the engine version in benchmarks.** Results moved between runs when the working tree
   changed during testing. A benchmark script should record the commit it ran against, or run
   against an exported copy, and refuse to compare numbers from different commits.
11. **A real-text benchmark in the repository.** The SQuAD runs used scratch scripts. An optional
   experiment that fetches a QA dataset at run time, pins the engine, and reports correct,
   abstained, wrong and wrong-article counts would turn section 2.5 into a regression check.
   Check the dataset licence before bundling any data.

## 7. Latency, effort budgets, and visible verification

This section records the supplied reasoning-period measurements as design evidence and a
measurement plan. The original large-index profile was reported from scratch prototypes against
the real engine and a copy of the 2.1 GB Simple English Wikipedia index. Repository experiments
now validate several mechanisms on synthetic fixtures, but do not reproduce that full profile.
Do not present either set of timings as product guarantees.

### 7.1 Remove retrieval work that does not affect the answer

The reported profile attributes most slow large-index turns to snippet construction: repeated
document scans for each hit, rather than FTS lookup or inference. First build snippets from the
matched chunk or sentence and preserve its citation; then profile again. Keep the selected sentence
and answer unchanged in a before/after comparison.

**Current implementation:** SQLite retrieval now ranks documents using their best FTS chunk,
then examines at most four high-ranking chunks per selected document. It builds sentence snippets
from a bounded source window around each chunk (up to 1,200 characters of context on each side),
selects the best sentence by weighted term coverage, and translates snippet and match offsets back
to the original document. Citation resolution still checks the exact source slice; PDF page
numbers are mapped from the match offset. This avoids tokenizing every retrieved document in full
while retaining opportunities to find an answer sentence outside the single top chunk.

A local synthetic profile used eight documents totaling 1,238,696 bytes. Median search over five
warm runs was 40.1 ms with bounded chunks. The prior full-document tokenization and snippet scan,
run after the same current FTS retrieval, took 261.5 ms median. Citations resolved exactly in the
profile. These timings are directional only: they are not a before/after full-pipeline comparison,
and they do not validate the 2.1 GB acceptance target or cold-cache behavior. The four-chunk bound
can miss an answer sentence in a lower-ranked chunk; monitor this on long-document regressions and
raise or adapt the bound only when measured retrieval quality warrants it.

**Acceptance target from the report:** on the same 2.1 GB index and ten-question set, median
question latency below 200 ms and the slowest question below 1 s, with identical answers and
citations. Record warm and cold-cache results separately when available. Retrieval should remain
serial unless a measurement shows parallel lookup helps; the reported three-index trial found no
parallel gain.

### 7.2 Make proof verification proportional to the proof

The independent verifier can either build a fact signature set or receive a fact lookup callback.
CRMS inference and derived-proof reuse now use keyed lookups into the in-memory or SQLite fact
store, checking the triple, exact sources, and qualifiers for each proof leaf. Standalone callers
that provide only an iterable retain the full-snapshot fallback. This preserves the independent
verifier boundary and accept/reject semantics while making the integrated path proportional to
proof length. It directly supports trustworthy recombination and self-learning: derived cases and
learned rules should be stored only after their evidence chains pass the verifier.

`experiments/v1_330_keyed_proof_verification.py` compares both paths on a synthetic 300,000-fact
store and a three-edge transitive proof. A current runtime pass measured 2,188.73 ms median for
the full-snapshot path and 0.076 ms for the keyed callback. Both accepted the same proof, and the
keyed path rejected a proof with altered provenance. Timings vary between runs, but the result
confirms the lookup scaling mechanism on this workload, not on a 300,000-fact end-to-end chat or
SQLite disk-backed benchmark; memory use and real corpus latency remain to be measured.

**Acceptance target from the report:** verify a three-hop proof in under 5 ms at 300,000 facts,
with unchanged outcomes on existing proof checks. Benchmark memory use as well as time, and retain
proof-chain provenance for later invalidation when a premise changes.

### 7.3 Effort means deterministic work limits, not a delay

If users can select reasoning effort, define levels by explicit bounds: rule depth, expansion
count, candidate count, and proof listing cap. A wall-clock timeout may stop work for interface
safety, but must be reported as an interrupted search and must not define the meaning of an effort
level. Given the same store, query, and level, results should repeat exactly. More effort may find
additional supported answers, but must not retract or change an answer already proved at a lower
level; the engine should preserve the lower-level proof and report whether the search was complete.

Use names such as `quick`, `standard`, and `thorough` only once their budgets are documented and
tested. **Current implementation:** `crms_inference.py` defines deterministic budgets for all
three levels; `experiments/v1_321_reasoning_effort_budgets.py` checks repeatability, a stable
already-proved conclusion across levels, explicit incomplete-search reporting, and thorough checks.
That experiment passed in the current runtime. Show the selected level and completeness only when
useful to explain an abstention or bounded result; do not claim that a longer wait itself
constitutes reasoning.

### 7.4 Thorough checks must be able to change the result

The thorough path runs these checks after retrieval and ordinary inference:

1. Count independent source origins supporting the selected evidence.
2. Scan for contradicting, negative, or integrity-violating evidence.
3. Independently verify each proof step through the keyed verifier from 7.2.
4. Check that the selected sentence actually asserts the relation and roles asked about.
5. Follow an incomplete derivation to identify missing premises in the same turn, when bounded.

Each check should return a structured result that can strengthen, qualify, or retract the answer.
If it finds no additional evidence, report that plainly when the user has requested details. Do not
run a stage just to consume a visible number of seconds. Keep the existing core priorities:
recombination must preserve argument roles and provenance; learned rules remain reviewable and
revocable; reasoning remains proof-producing and abstains when support is incomplete.

**Initial evaluation:** `experiments/v1_323_thorough_retrieval_plausibility_benchmark.py` runs 50
known-answer questions through the chat in quick and thorough modes. The current runtime passed:
quick had 25 wrong and 0 abstentions; thorough had 0 wrong, 25 correct, and 25 abstentions. The
fixture deliberately pairs a matching entity and noun with a sentence whose verb does not support
the requested relation. This demonstrates that the plausibility stage can prevent these lexical
false matches; it does not establish broad answer-quality gains. The evaluation gate remains at
least 50 independently authored, varied questions, recording correctness and abstention by stage.
Measure each stage separately and omit any stage that does not improve the result or useful
explanation.

### 7.5 Show stages only when they ran

If the interface presents progress, emit a line only after its corresponding operation has
actually completed, with truthful stage status. Thorough inference currently returns explicit
check results after those checks run; it does not simulate elapsed time. The first answer may be
provisional only if later checks can explicitly strengthen or retract it. Log stage start/end and
result so the interface can be checked against real work. A short operation should appear short;
never insert artificial waiting or fabricate a progress line.

### 7.6 Suggested implementation sequence

1. Profile a reproducible question set and optimize snippet construction; compare answers and
   citations before and after. Bounded matched-chunk retrieval is implemented, but the 2.1 GB
   end-to-end acceptance target remains open.
2. Keep keyed proof-step lookups and deterministic effort budgets; add disk-backed scale and
   memory measurements for proof verification.
3. Evaluate the thorough checks individually on independently authored questions, reporting
   wrong answers and abstentions for each effort level. The current synthetic 50-question check
   validates one lexical-confound mechanism only.
4. Add stage-by-stage progress display only after operations and their logs are stable; current
   thorough check results are available in the reply, but live per-stage progress is not yet
   validated.

The supplied profile reports that proof expansion itself is inexpensive at current scales, while
verification and snippet construction dominate larger cases. Treat that as a hypothesis to verify
on the current code. Prioritize removing measured waste before adding parallelism or more
reasoning stages.
