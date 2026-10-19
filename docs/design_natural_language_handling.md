# Design: improving natural language handling (answer-type gate, paraphrase tolerance, polar entailment, pronouns)

**Audience:** the developer (human or AI) implementing this.
**Status:** proposed; the quoted-evidence gate and FTS fallback are implemented. The benchmark
ideas below were prototyped as a *wrapper around the unmodified engine* in a scratch folder and
measured on three question sets (section 2). The live gate applies to quoted source evidence,
checks named mentions, answer type, lexical relation support and required superlatives, and can
select from top FTS hits. Exact-title polar evidence can resolve a surname used locally in one
unique article, and bounded metadata questions can read exact-title `birth_place`, `type`, `class`,
or `kind` fields.
The prototype and the three question sets are in
`experiments/v1_327_paraphrase_benchmark_nl_layer.py` (run it to reproduce section 2.3); the code
is a sketch of the logic, not a patch to apply. A later check on real SQuAD passages (section 2.5)
showed the "zero wrong" result does not generalise: about one question in eight still gets a wrong
answer. Follow-up tests on tuned and fresh samples (section 2.6) found that only the gate layer's
gain replicates; cheap wrapper additions (reference binding, proximity ranking, learned word pairs)
do not generalise, so the next work is structural (section 6, items 8 and 9). The one exception is
a small learned ranker over gate-passing sentences, which did generalise (section 2.7). The
project owner has decided that a bounded learned component of this kind is allowed (decision
recorded in section 2.7); embeddings and neural similarity are not yet allowed.
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
cases the sentence that contains the gold answer *fails* the gate. In the other 12 the gold
sentence passes the gate but a different passing sentence was chosen; the median number of corpus
sentences passing the gate was 3. So the loss is (a) gold sentences rejected by the mention or
relation check and (b) choosing among several plausible sentences. It is not a lack of strictness.
(My first reading of group (a) was that most were indirect references such as "it" or "the
former". That was a guess; the measurement in section 2.6 does not support it.)

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

### 2.6 Generalisation tests: what replicates on fresh articles

I tried four additions on top of the gate layer, one at a time, on the 10 articles used so far
("tuned sample") and then on 10 *different* articles never used for tuning ("fresh sample", same
sizes: 200 questions and 100 wrong-article questions). Both samples use the frozen engine at
commit `622fa99`. The ideas were chosen after looking at failures on the tuned sample, so its
numbers are optimistic; the fresh sample is the honest one.

| Configuration | Tuned: correct / wrong / abstained | Fresh: correct / wrong / abstained | Fresh precision | Fresh wrong-article answered |
|---|---|---|---|---|
| Engine alone | 90 / 33 / 77 | 75 / 43 / 82 | 63% | 11 / 100 |
| NL-gate layer (section 2.3 final) | 99 / 27 / 74 | 84 / 34 / 82 | 71% | 8 / 100 |
| + possessive and plural mention matching | 106 / 27 / 67 | 88 / 38 / 74 | 69% | 7 / 100 |
| + proximity-weighted ranking, margin 1.2 | 112 / 26 / 62 | 89 / 42 / 69 | 67% | 8 / 100 |
| + proximity ranking, margin 1.2, else abstain | 92 / 14 / 94 | 81 / 32 / 87 | 71% | 7 / 100 |

Findings:

1. **The gate layer replicates.** Against the engine alone it gives 9 more correct and 9 fewer wrong
   answers on the fresh sample (and 9 and 6 on the tuned one). This is the one robust result.
2. **Possessive and plural mention matching is mixed.** Of the question mentions that failed the
   check against the gold sentence on the tuned sample, 30 were inflected or possessive forms
   ("Oedogonium's", "Soviets") and 31 were entities the gold sentence does not name at all. Matching
   the first group added 7 correct answers on the tuned sample but only 4 correct and 4 more wrong
   on the fresh one. It is not clearly beneficial without a way to offset the extra wrong answers.
3. **Reference binding did not help.** Only 21 of 200 gold sentences begin with a pronoun or
   "this/the former/the latter" reference, and 9 of those were already answered correctly. Binding
   such a sentence to the article title (or to the previous sentence's subject) raised the number of
   non-correct questions whose gold sentence passes the gate from 27 to 29 of 101, and left the
   answer counts essentially unchanged (100 correct, 30 wrong). The earlier diagnosis that indirect
   reference is the largest remaining loss was wrong. The larger share are entities that the answer
   sentence does not mention, which only information from neighbouring sentences or the question's
   context could supply.
4. **Stronger ranking did not generalise.** Adding proximity of the matched words gained correct
   answers on the tuned sample but lowered precision on the fresh one (71% to 67%); with an
   abstain-if-close rule precision only returned to the layer's 71% at the cost of 3 correct
   answers. The overlap and proximity signals are too weak to choose between plausible sentences.
5. **Learned wording pairs did not help.** Requiring a word pair from questions and gold sentences
   to appear in at least 3 separate articles gave 103 correct and 38 wrong (worse than none); at
   least 5 articles changed nothing. The surviving pairs were generic words ("type" with "other",
   "also", "such"). Independent-article support alone does not select real paraphrases.
6. **Wider entity context raises coverage, not precision.** I let the mention check also accept
   entity tokens from the answer sentence's paragraph and the article title, together with the
   possessive and plural handling from item 2. With that, on the tuned sample the gold sentence
   passes the gate for 136 of 200 questions (68%), and on the fresh sample for 132 of 200 (66%);
   54 and 42 questions have no candidate sentence at all. Correct answers rise (tuned 99 to 111,
   fresh 84 to 97), but wrong answers rise with them (tuned 27 to 30, fresh 34 to 42) and
   precision stays flat to lower (tuned 78%, fresh 69%). The mention check remains the largest
   single blocker: of the 64 (tuned) and 68 (fresh) gold sentences still rejected, relaxing it
   alone would admit 42 in each, against 4 and 9 for the answer-type check and 10 and 16 for
   relation-word overlap. Remaining mention failures are possessive forms, name variants
   ("Bill Aiken" against "Aken"), a partial name for a multi-word title ("Doctor" for "Doctor
   Who") and pronoun-initial sentences.
7. **The selection gap is large.** When the gold sentence does pass the gate, plain overlap ranking
   puts it first in 100 of 200 questions (tuned) and 94 of 200 (fresh), and in the top three in 119
   and 113; the median number of sentences passing the gate was 5 and 6.
8. **Answer-span agreement did not replicate.** Preferring the top-ranked sentence when its typed
   answer span also appears in another top-five sentence, and abstaining when neither that nor a
   score margin holds, looked good on the tuned sample (99 correct, 16 wrong, 86% precision) but gave
   90 correct and 39 wrong (69%) on the fresh sample. A span-vote variant was worse on both.

Caveats: 200 questions per sample, so a few questions is noise; the same grader limits as in 2.5;
scripts are in a scratch folder and are not committed.

### 2.7 A small learned ranker generalises (decision recorded)

Everything above chooses between candidate sentences with hand-set scores, and none of it
generalised. The one thing that did is a small logistic-regression ranker over the sentences that
pass the gate.

**Setup.** Training data: 1,520 questions (40 from each of the 38 articles never used for
testing), 11,323 candidate rows (the top 15 gate-passing sentences per question), 1,749 positive
(the sentence contains a gold answer). Inputs are computed from the question and sentence only, not
from gold: idf-weighted share of the question's terms matched, fraction of terms matched, word
proximity, whether a typed answer span exists, mention coverage, sentence length, whether it is the
paragraph's first sentence, summed matched idf, the log of the number of candidates, and the wh-type
of the question (16 inputs in all). The ranker picks the highest-probability candidate and answers
only if its probability reaches a threshold; otherwise CRMS abstains. The mention fixes and
paragraph/title context from item 6 are used.

**Learned weights (largest).** idf-weighted term coverage +1.48, fraction of terms matched +1.27,
log candidate count -0.55 (fewer plausible candidates means more confidence), word proximity
+0.32, summed matched idf +0.23. The answer-span, first-sentence and wh-type inputs are all
within about 0.2 of zero.

**Results, first training draw.** All rows use the frozen engine at commit `622fa99`. **Read the
correction under the table before relying on these numbers.**

| Configuration | Sample | Correct | Abstained | Wrong | Wrong-article answered | Precision |
|---|---|---|---|---|---|---|
| Engine alone | fresh | 75 | 82 | 43 | 11 / 100 | 63% |
| NL-gate layer | fresh | 84 | 82 | 34 | 8 / 100 | 71% |
| Mention fixes and context, no ranking | fresh | 97 | 61 | 42 | 8 / 100 | 69% |
| Learned ranker, answer if p ≥ 0.3 | fresh | 99 | 76 | 25 | 2 / 100 | 79% |
| Learned ranker, answer if p ≥ 0.4 | fresh | 94 | 85 | 21 | 0 / 100 | 81% |
| Learned ranker, answer if p ≥ 0.5 | fresh | 83 | 100 | 17 | 0 / 100 | 83% |
| Learned ranker, answer if p ≥ 0.6 | fresh | 76 | 109 | 15 | 0 / 100 | 83% |
| NL-gate layer | tuned | 99 | 74 | 27 | 5 / 100 | 78% |
| Learned ranker, answer if p ≥ 0.3 | tuned | 107 | 66 | 27 | 2 / 100 | 79% |
| Learned ranker, answer if p ≥ 0.4 | tuned | 101 | 81 | 18 | 2 / 100 | 84% |
| Learned ranker, answer if p ≥ 0.5 | tuned | 91 | 98 | 11 | 2 / 100 | 89% |

At p ≥ 0.3 on the fresh sample this draw gave 15 more correct answers than the gate layer, 9 fewer
wrong ones and 6 fewer wrong-article answers, and raising the threshold traded coverage for
precision in a predictable way, which none of the hand-set rankers did.

**Correction: the first draw was favourable.** A second, independent random draw of 1,520 SQuAD
training questions (a different seed, the same procedure and the same test samples) gave a
weaker result:

| Training draw | Sample | p ≥ | Correct / wrong | Precision | Wrong-article answered |
|---|---|---|---|---|---|
| First | fresh | 0.3 | 99 / 25 | 80% | 2 |
| Second | fresh | 0.3 | 105 / 36 | 74% | 2 |
| First | fresh | 0.5 | 83 / 17 | 83% | 0 |
| Second | fresh | 0.5 | 98 / 30 | 77% | 1 |
| Second | tuned | 0.4 | 111 / 33 | 77% | 3 |

Precision therefore varies by several points with the training sample (74 to 80% at p ≥ 0.3), so
the gain over the gate layer's 71% is real but modest: about 3 to 9 points of precision with 20
more correct answers. Any claim of "79 to 83%" should be read as the upper end of a range. The
ranker still beats every hand-set variant, but the evidence is two training draws, not a
distribution.

**Training size (SQuAD-labelled questions, fresh sample).** Correct / wrong at p ≥ 0.3 and p ≥ 0.5:

| Training questions | p ≥ 0.3 | p ≥ 0.5 |
|---|---|---|
| 100 | 104 / 43 | 96 / 36 |
| 300 | 105 / 39 | 97 / 34 |
| 600 | 104 / 35 | 97 / 27 |
| 1,520 | 105 / 36 | 98 / 30 |

The ranker is data-efficient: 100 labelled questions already give nearly the coverage of 1,520, and
more data helps precision only slightly. The smaller subsets were taken from the first few training
articles (not shuffled), so this curve is article-biased and indicative only.

**Self-made training questions (the route that uses only CRMS's own sources).** The decision in
this section prefers training on data CRMS already holds. I tested that with no human labels and
no external dataset. For the 38 training articles I made cloze-style questions from their own
sentences: mask a four-digit year (question starts "When…") or the leading capitalised name
("Who…"), keep the remaining words with about 40% of the non-capitalised words dropped (so overlap
with the source is partial, as with real questions), and label only the original sentence as
correct. 1,500 questions gave 12,040 candidate rows with 1,457 positives. A first attempt with
template questions (the starter-question templates from the chat UX doc, plus a few more) produced
only 162 well-formed questions from 7,718 sentences, so cloze generation was used instead. Result
on the fresh sample, with the SQuAD-labelled ranker from the second draw for comparison; each cell
is correct / wrong (precision), then wrong-article answers:

| p ≥ | SQuAD-labelled (1,520) | Self-made cloze (1,500) |
|---|---|---|
| 0.05 | 109 / 56 (66%), 24 | 90 / 23 (79%), 0 |
| 0.1 | 109 / 53 (67%), 13 | 80 / 17 (82%), 0 |
| 0.2 | 108 / 41 (72%), 4 | 74 / 14 (84%), 0 |
| 0.3 | 105 / 36 (74%), 2 | 69 / 10 (87%), 0 |
| 0.4 | 102 / 31 (76%), 1 | 66 / 9 (88%), 0 |
| 0.5 | 98 / 30 (76%), 1 | 64 / 7 (90%), 0 |

On the tuned sample the cloze ranker reached 80% precision at 92 correct (p ≥ 0.3) against 76% at
114 correct for the SQuAD-labelled one. Training on cloze questions plus 300 SQuAD questions gave
99 / 31 at p ≥ 0.3, between the two. Findings: (1) a ranker trained purely on CRMS's own source
text, with no labels from outside, reaches the same precision frontier as the human-labelled one
(about 79 to 90%, against 71% for the layer) and answers no wrong-article questions at any
threshold; (2) it is much more cautious, topping out near 90 correct answers instead of 109,
probably because its training questions are only WHEN and WHO forms and so cover few other
question types; (3) it removes the dependence on SQuAD and its licence for this component. Broader
self-made question types (the "What is…", "Where…", measurement and count forms) are the obvious
next step and were not tested.

**Small hand-written sets (ranker alone).** Applied to the 150 answerable items and 37
must-refuse items from the three small sets (yes/no items excluded, no typo repair, no engine
abstention), the SQuAD-trained ranker gave 131 correct, 16 abstained and 3 wrong at p ≥ 0.3, but
declined only 25 of the 37 must-refuse items; at p ≥ 0.5 it gave 126 correct and 0 wrong and
declined 33 of 37. The cloze-trained ranker gave 131 correct, 3 wrong and 25 of 37 declined at both
thresholds. So the ranker transfers to short simple sentences, but **it does not preserve the
layer's refusals**: it answers some unanswerable questions because a candidate passes the gate.
It must run *inside* the layer, with the engine's abstention and the gate as preconditions, and
must not replace them. (These figures are not comparable with the earlier full-layer results on the
same sets, which include the engine's own abstentions, typo repair and yes/no handling.)

**Caveats.**
- Same kind of text for training and testing (Wikipedia-style paragraphs). I did not test other
  domains or languages.
- Self-made data covers only WHEN and WHO forms so far.
- It scanned every sentence of an article for candidates. At scale, candidates must come from the
  FTS retrieval and the 15-per-question cap, which I did not test, along with latency.
- Where candidates exist it answers with the chosen sentence directly and does not use the
  engine's own reply; the engine reply is the fallback only when no candidate passes the gate.
- 200 questions per sample, so a few questions is noise. The scripts are in a scratch folder and
  are not committed.

**Decision (project owner, recorded 2026-10-19).** The earlier rule "no learned similarity model"
is relaxed for a *bounded* learned component. This was option (B) in the analysis below, adopted
on the strength of the first fresh-sample result (later checks narrowed the gain to a range, see
above); it is a licence to pilot, not a finding that the
ranker is proven. The ranker is 16 numbers, deterministic to retrain, CPU-cheap, and restricted to
choosing among sentences the gate has already accepted.

*Allowed*
- A learned component that **proposes or ranks** candidates. It may never be the source of a fact
  and never the final judge of acceptance: the evidence gate, the proof checks and the abstention
  threshold still decide what is returned, so every answer still traces to a cited source.
- Small, readable models whose inputs are named features (the 16-weight form tested here), stored
  as a **reviewable, versioned record** that records its training data, training procedure and
  date, and that can be listed, replaced or removed like other learned items. The `why?` view
  should be able to show the feature values behind a choice.
- Deterministic training (fixed procedure, fixed order, fixed seed) and CPU-only inference.

*Not allowed yet*
- Embeddings or neural similarity, any learned component that decides what to accept as a fact,
  and any component that requires a model download. Reconsider only if the staged route below
  plateaus, and only as a proposer with exact verification.

*Conditions before it ships*
- Keep the "fresh articles only" bar: a gain counts only if it holds on text it was not trained or
  tuned on, with wrong answers and wrong-article answers reported alongside correct ones.
- Test the cases not yet covered: less training data (a learning curve), the hand-written sets,
  other kinds of text, and candidates supplied by FTS retrieval instead of a whole-article scan,
  with latency.
- Check that shipping weights trained on SQuAD (CC BY-SA 4.0) is acceptable, or train instead on
  data CRMS already holds under its own rules: reviewed answers, accepted facts, and feedback
  recorded in the evidence ledger. This is the preferred direction because it keeps the training
  loop inside the project's provenance rules. Training on self-made cloze questions from CRMS's own
  source text was tested and works (high precision, lower coverage, see above); training on
  reviewed answers and ledger feedback is still untested.
- Update the README so it states plainly that a small learned ranker exists (it currently says no
  AI model is needed or downloaded; a shipped weights record is not a download, but the wording
  must not imply there are no learned weights).

*Staged route.* (1) The feature-based ranker tested here. (2) A learned table of wording
equivalences that is only ever a proposal for human review (section 3.6). (3) Embeddings as a
proposer with exact verification, only if steps 1 and 2 plateau. Each step needs its own
fresh-sample evidence before the next is considered.

*Analysis behind the decision.* Arguments for: it fits "propose, then verify"; the weights are
reviewable; the choice can be explained. Arguments against: the training labels come from an
external dataset; it adds a model that must be retrained and versioned; it moves the project
across the "no learned weights" line that distinguishes it from an LLM. Options considered: (A) do
not adopt and accept about 70% precision on this kind of text; (B) adopt as a reviewable, versioned
record (chosen, within the limits above); (C) use the learned weights only as a guide for hand-set
scores (untested).

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
An initial title-lead-only probe found poor endpoint coverage. The expanded probe reads explicit
`type`/`class`/`kind` infobox fields and title-led leads after infobox blocks, including a bounded
parenthetical after the title. A fresh five-window replay across all 285,478 documents found
148,162 pages with one unambiguous coarse type head and 96 relation-frame proposals. Their 409
positive non-`is-a` support rows had 78 subjects and 144 objects with a matching unique type, with
27 rows typed at both endpoints. Even at a report-only threshold of one distinct independently
sourced pair per wording, no two predicates shared an ordered type signature. The distributional
path therefore still has no real-corpus yield in these windows; the sample improves endpoint
coverage but does not change the transfer result. Better entity linking or additional
source-grounded category fields remain possible, but need held-out precision evidence before they
support language rules. `experiments/v1_335_role_type_alignment_probe.py` reproduces this read-only
measurement.

The probe now normalizes a leading `the`, `a`, or `an` when matching a relation endpoint to an
exact-title type key, and checks the `settlement_type` field used by SimpleWiki settlement pages.
Compound and conflicting class values are withheld. The current five-window replay found 121,006
unambiguous type candidates and 84 relation-frame proposals. The 355 positive non-`is-a` support
rows had 60 typed subjects and 108 typed objects, with 22 rows typed at both endpoints. It still
produced zero ordered-type alignment hypotheses.
The audit also traced recurring false endpoints such as `Then`, `Sometimes`, `In 1969`, `TV`, and
`EP` to discourse openings, temporal phrases, and capitalized common nouns after determiners.
Corpus frame discovery now rejects those bounded cases. Compared with the earlier 96-frame
five-window run, the repeated-pair and role-type aligners still propose no real-corpus transfer.
This improves frame precision but does not solve entity linking or paraphrase coverage.

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

### 3.8 Exact-title context and structured source fields

A unique exact-title article can license a narrow local subject alias. For example, if the
`Alan Turing` page says “Turing worked at Bletchley Park,” that page title resolves `Turing` to
`Alan Turing` for this sentence. The alias must not transfer to another search result or become a
general surname rule. The polar route still requires the requested verb, argument order, and
complete object phrase in the same asserted sentence; a different workplace remains unknown. The
quoted sentence is reviewable evidence, not an accepted fact.

Some source pages express an answer in an infobox instead of prose. For the bounded `Where was X
born?` form, CRMS can read the exact-title page's explicit `birth_place` field when one unique
value exists. For bounded `What type/kind of [category] is X?` forms, it can read the exact-title
page's `type`, `class`, `kind`, `entity type`, or `settlement_type` field when one unique, short
value exists. Both
routes cite the exact field and label the result as quoted source evidence. A type field also
creates a review-only `subject — is-a → value` candidate using that exact field as its cited text.
Only explicit acceptance stores the type claim, after which ordinary reasoning can use it. The
birthplace route remains evidence-only. Neither route infers a birthplace from nationality, an
institution, or nearby text.
Conflicting values, missing fields, and non-unique title matches abstain.

`experiments/v1_333_exact_page_alias_and_birthplace.py` checks the title-local alias, wrong-object
abstention, explicit negation, and birthplace field citation through a fresh CLI session.
`experiments/v1_336_structured_type_field_chat.py` checks exact type-field citations, abstention
on conflicting or non-infobox values, review without automatic promotion, explicit acceptance,
and a later yes/no query over the accepted `is-a` fact. A read-only
replay on the 285,478-document SimpleWiki index returned the Bletchley Park sentence for the
yes/no question, abstained for Cambridge, returned the same Bletchley Park sentence for `Where
does Alan Turing work?`, and read Warsaw from Marie Curie's exact-title infobox. These cases validate the
targeted route, not broad coreference or polar-question coverage.

The same index answered `What type of place is Albury?` from the exact `type = city` infobox field
and `What type of place is Chicago?` from `settlement_type = City`. The latter required switching
the structured lookup from ranked body search to the exact-title index; the previous top-100 body
search did not find Chicago's title because the large corpus contained many body matches. Both
fields can enter the cited candidate-review queue and become reasoning facts only after explicit
acceptance. They do not automatically add class facts to predicate-alignment discovery.

Exact-title grounding now has a dedicated title-field lookup, avoiding a full ranked body search
when a route only needs to locate one page. The Who fallback also abstains when a predicate has no
object, cites the complete sentence, and filters new review proposals against the question's named
object. Regression checks in `v1_295`, `v1_318`, `v1_333`, and `v1_336` pass. This filtering is
limited to direct Who questions; it does not solve broad paraphrase or entity-linking coverage.

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
    surname grounding, birthplace-field reading, and bounded type-field answers are implemented,
    with the real-index sample
    recorded in `benchmark_baselines.md`).

Each step: add a benchmark family or reuse the sets above, record the numbers in
`benchmark_baselines.md`, and require wrong = 0.

## 5. Out of scope

- Generating fluent replies (templates for the labelled sentence are enough).
- General coreference resolution across paragraphs. Binding a pronoun to the article title was
  tested and did not improve answers (section 2.6); only revisit it with evidence from a larger
  sample.
- Embeddings or neural similarity models, and any learned component that decides whether
  something is accepted as a fact. A small, readable, versioned ranker that only orders
  gate-passing candidates is allowed under the decision in section 2.7.
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
8. **Structural fixes are the next work, not more wrapper rules.** The tests in section 2.6 show
   that adding rules around the retrieved sentence mostly trades correct answers for wrong ones.
   What is needed, in the order I would try:
   a. *Facts extracted from sentences at higher yield.* Answers that come from a stored fact
      generalise across wording because they go through the relation, not the sentence's words.
      The measured yield on real text is low (section 3.6), so improve extraction first and
      measure how many SQuAD-style questions become answerable from facts.
   b. *Evidence from neighbouring sentences.* About half of the gold sentences rejected by the
      mention check do not name the entity the question asks about. Letting the check use the
      paragraph's and title's entities (2.6, item 6) raised coverage by about 13 correct answers
      per 200 questions but also added wrong answers, so it needs a better selector (2.7) to be
      worth shipping. Name variants and partial names of multi-word titles remain open.
   c. *Answers built from the structured result* (the answer line from the chat UX doc, and
      realisation from the relation), so the response does not depend on quoting one sentence.
   d. *Role-aware wording evidence.* Plain word co-occurrence gave noise (2.6, item 5); the next
      step is evidence that also requires compatible subject and object classes, with review.
   Each needs a fresh-sample measurement before adoption; tuned-sample gains do not count.
9. **Choosing between gate-passing sentences.** Hand-set ranking (idf overlap with a margin, word
   proximity, answer-span agreement) did not generalise (section 2.6). A 16-weight learned ranker
   did (section 2.7: 74 to 83% precision on fresh articles depending on the training draw, against
   71% for the gate layer; a ranker trained only on CRMS's own cloze questions reached 79 to 90%
   at lower coverage). The
   project owner has allowed a bounded learned ranker (section 2.7). Next: test it with less
   training data (a learning curve), on the hand-written sets, on other text, and on FTS-supplied
   candidates with latency; try training it on CRMS's own reviewed answers and ledger feedback
   instead of an external dataset; and update the README wording. Until it ships, prefer abstaining
   when several sentences pass, with role-order checks from 3.3 or corroboration by an independent
   second source as non-learned alternatives.
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

A later read-only replay drove ten questions through one fresh CLI process on the local
285,478-document, 2.1 GB SimpleWiki index. It took 12.22 seconds overall (about 1.22 seconds per
turn including the initial process setup). Replies were broadly similar to the preceding replay,
but this was not a strict before/after comparison and citation identifiers were not captured. A
profile of `What is the Pacific Ocean?` showed 0.71 seconds in
`CRMSSQLiteResearchIndex.search`, including 49 SQLite `execute` calls, while five `_snippet` calls
took about 21 ms total. This means matched-chunk
snippet construction is no longer the dominant measured cost; wide FTS searches and their SQL work
now need attention. Exact-title lookup used to call full ranked retrieval and then discard every
non-exact title, so it now uses a dedicated FTS title phrase lookup instead. That narrow change
preserves the exact-title equality check, but did not bring the end-to-end replay near the 200 ms
target. An experiment removing corpus rarity weights from sentence selection failed the
entity-less-Who regression and was reverted; keep the grounding behavior while optimizing retrieval.

An interactive replay measured from query submission to first answer for each turn on the same
ten-question set: median 0.80 seconds, slowest 3.14 seconds. The run was not cold-cache controlled.
It still misses the supplied median-under-200-ms and slowest-under-1-second targets. Some
natural-language misses remained in the same run (`Who created Python?` did not select the
indexed creator sentence; `Where is Mount Everest?` abstained despite indexed location evidence),
so future latency changes must preserve answer quality and report those cases alongside timings.

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
