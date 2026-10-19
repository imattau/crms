# Design: improving natural language handling (answer-type gate, paraphrase tolerance, polar entailment, pronouns)

**Audience:** the developer (human or AI) implementing this.
**Status:** proposed. Every idea below was prototyped as a *wrapper around the unmodified engine*
in a scratch folder and measured on three question sets (section 2). No engine code was changed.
The prototype and the three question sets are in
`experiments/v1_327_paraphrase_benchmark_nl_layer.py` (run it to reproduce section 2.3); the code
is a sketch of the logic, not a patch to apply.
**Relationship to other docs:** the ground rules in section 0 of
[design_learning_dynamics.md](design_learning_dynamics.md) apply unchanged (evidence over
assumption, abstain when unsure, propose then verify, deterministic, CPU-friendly). Section 4
(synonym proposals) reuses the review-before-store path and is a cousin of the equivalence work in
that document.

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
  checks.** It must not make a wrong answer more likely. Track `wrong` as a hard zero target and
  `correct` as the number to grow.
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

Zero wrong answers and all must-refuse items declined on all three sets.

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

**Acceptance.** On a held-out set at least 40 questions: zero wrong answers among answerable
items and 100% of unanswerable items declined, with correct count not lower than baseline.

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

### 3.6 Corpus-evidence synonym proposals (tested synthetically only)

Propose "verb a ~ verb b" when they share at least 3 (subject, object) pairs across the corpus,
and **block** the proposal when both verbs are used for the same pair in the *same document* for
at least half of the shared pairs (antonyms like built/destroyed co-occur on the same pair). In a
synthetic corpus (created/made true synonyms; built/destroyed antonyms sharing the same pairs):
created~made was proposed, built~destroyed was blocked, and built~constructed (one shared pair) was
correctly *not* proposed. Proposals go through the existing review-before-store path with held-out
checking; never auto-accept.

**Not tested on real text.** Real corpora are far noisier; measure precision before enabling.
It cannot help small corpora (the benchmark's "made/invented/designed" items have no evidence for
the equivalence, so they stay abstained, correctly).

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

## 4. Delivery order

1. **Gate** (3.1), report-level first: log what it *would* veto without changing replies, to
   check false vetoes on the real index. Then enable.
2. **Show the best sentence by default** for the "no accepted fact supports an answer yet" case,
   labelled as before (small, consistent).
3. **Fallback selector** (3.2) over FTS candidates; measure latency.
4. **Polar entailment** (3.3) with the mention fix.
5. **Rewrites and typo echo** (3.4), only after 1 is live.
6. **Seed pack as records** (3.5), then **evidence-based synonym proposals** (3.6).
7. **Pronoun handling** (3.7) last; it needs the subject/role information.

Each step: add a benchmark family or reuse the sets above, record the numbers in
`benchmark_baselines.md`, and require wrong = 0.

## 5. Out of scope

- Generating fluent replies (templates for the labelled sentence are enough).
- Multi-sentence coreference ("it" across paragraphs in a source).
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
