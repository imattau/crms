# Design: chat experience (answer format, dead ends, scope messages, multi-part questions, starter questions)

**Audience:** the developer (human or AI) implementing this.
**Status:** partially implemented. The gate-conditioned closest-sentence behavior in 2.2 and the
bounded explicit multi-question routing in 2.4 are now in the runtime; the remaining delivery items are proposed. Five ideas were prototyped as *wrappers around the unmodified chat* in a scratch
folder and measured on small sets (section 2). Everything else in section 3 is observed but not
tested. The prototype scripts are not committed; the figures are reproducible only by re-writing the
wrappers, so treat them as evidence for a design, not as a benchmark to cite.
**Relationship to other docs:** the ground rules in section 0 of
[design_learning_dynamics.md](design_learning_dynamics.md) apply unchanged. This document is about
presentation and routing of replies; it must not change what CRMS accepts as evidence or when it
abstains. It complements [design_natural_language_handling.md](design_natural_language_handling.md)
(which decides *whether* a sentence answers a question) by deciding *how that decision is shown*.

## 0. Why this matters

People who use LLM assistants expect: an answer or a useful next step on every turn, one consistent
reply shape, continuity across turns, an honest statement of what the assistant cannot do, and
discoverability (what can I ask?). CRMS already beats LLM chat on speed on small corpora (about
0.15 s from startup to one answer in my runs), on citations, and on honesty about evidence. It falls
short of the LLM experience mostly on the *miss* path: most failures leave the user with nothing to
do next.

Observed in two short driving sessions (about 30 turns, small corpus, committed engine):

| # | Observation | Example |
|---|---|---|
| 1 | The same generic refusal covers different causes. | "Tell me more", "What's your name?" and "Explain relativity like I'm five" all got "I don't know… Add a source or teach the fact." |
| 2 | Unsupported requests are treated as failed lookups. | "Write me a poem about Python" got "I found relevant source text, but no accepted fact supports an answer yet." |
| 3 | Follow-ups are weak. | "And France?" asked for "an entity already present in the knowledge base"; "Are you sure?" and "How do you know?" said there was no previous answer after one had just been given. |
| 4 | Part of a multi-part question is dropped without a word. | "Who created Python? Also who developed Linux?" answered only the first part. |
| 5 | Several reply shapes. | A bare sentence, `Source text: … Source: …`, `The source identifies: …`, `Partial source evidence: …`. |
| 6 | Internal vocabulary in ordinary replies. | "supporting claim awaiting review; use /pending-candidates to inspect" under many answers; the review queue listed the same fact twice. |
| 7 | Citations print raw local paths with hashes. | `world.txt#sha256=…&chars=335:366` in `/pending-candidates`. |
| 8 | Help is a command reference. | `/help all` is about 80 lines of teach-command variants with pipe syntax; no example questions from the loaded sources. |
| 9 | No correction path. | There is no "that's wrong" or "that's right"; accepting a fact needed `/pending-candidates` then `/accept 1`. |
| 10 | No feedback during slow searches. | Earlier measurements: 1–12 s on a 2.1 GB index with no output. |

## 1. Ground rules

- **Presentation only.** None of these changes may turn an abstention into an answer or hide a
  label that says an answer is unreviewed. They may reword, reorder, split, or add suggestions.
- **Never invent confidence.** A highlighted answer, a progress line or a suggestion must be backed
  by a check that actually ran.
- **Suggest only what works.** Any example question shown to the user must have been answered
  correctly by the system on the same sources.
- **A scope message may replace an abstention message, never an answer.**
- **Deterministic.** Same input, same output.

## 2. Tested ideas

Method: the same 204 benchmark questions as in the NL design doc (three small corpora), plus
SQuAD for one check, run against a **frozen copy of the committed engine** (`git archive`, commit
`622fa99`), because another session edits the engine files while tests run and live-tree runs were
not comparable.

### 2.1 One reply shape with an answer line

Target shape:

```
**Guido van Rossum**
> **Guido van Rossum** created Python.
world.txt · quoted source (not yet accepted)
```

An answer line (bold) when a closed-class extractor finds the span the question asks for (year,
number with unit, number word, capitalised name or place); then the supporting sentence with that
span marked; then a short source name and a plain-language status. No paths or hashes in the default
view.

Result on 204 replies (106 carried a source sentence; 98 were abstentions, which are untouched):

- All 106 sourced replies, in four different engine shapes, parsed into (sentence, source, status)
  with the source name and the accepted/unreviewed status preserved: 106 of 106.
- On the 78 replies that contained the gold answer, the extracted span matched the gold answer in
  78 after two fixes. The first version got 4 wrong, both found by this test: it highlighted the
  *negated* city in "Canberra is the capital of Australia, **not Sydney**" (bold "Sydney"), and it
  took only "one hundred" from "one hundred thousand". The fixes: drop the clause after "not"; match
  a run of number words. A bold wrong answer is worse than no bold, so extraction must be tested on
  negation and multi-word numbers.
- Of the 11 sourced replies that did **not** contain the gold answer, 5 would have received a bold
  answer line if the extractor ran on any sentence. With the NL gate as a precondition (the sentence
  must pass the answer-type and relation checks) that falls to 0, and 77 of the 78 correct replies
  keep their bold line.

**Rule:** only show an answer line when the NL gate passes; otherwise show the sentence without
emphasis and say what it is ("closest sentence, may not answer your question").

### 2.2 Show the best sentence instead of "ask why?"

For the 25 dead-end replies ("I found relevant source text, but no accepted fact supports an
answer yet. Ask 'why?'") on questions whose answer is in the corpus, I compared what `why?` then
shows:

| Policy | Sentences shown | Contain the answer | Non-answers shown | Right answers withheld |
|---|---|---|---|---|
| Always show it | 25 | 18 (72%) | 7 | 0 |
| Show it only if it passes the NL gate | 17 | 15 (88%) | 2 | 3 |

Always showing it puts a non-answer in front of the user about a quarter of the time ("Name the
creator of Python" showed "Python was released in 1991"). Show it only when the gate passes; when
it fails, say that sources were found but the closest sentence does not answer the question, and
show that sentence labelled as such (the wording of that third path was not tested).

**Runtime update:** rejected, uniquely selected evidence now appears as a “Closest source sentence”
with its source title and an explicit “may not answer your question” label. It is removed from
`source_sentences` and passage evidence, so it cannot become a cited answer or feed a later
follow-up as accepted evidence. Ambiguous candidates remain omitted. The runtime regression in
`experiments/v1_329_runtime_nl_gate.py` checks that this near-match context is shown while the
existing mismatch abstention and subsequent-turn checks still pass. This is a narrow presentation
change; it does not establish better answer accuracy or implement the common reply shape in 2.1.

### 2.3 Scope and intent messages

Idea: recognise requests outside what CRMS does (creative writing, opinion or advice, questions
about the assistant, open-ended explanation or planning) and say so plainly instead of reporting a
failed lookup.

Findings:

- Rule lists are fragile. My first rule list caught 34 of 34 utterances from the set it was written
  with (a circular result, since I wrote both). On 20 fresh utterances written afterwards it caught
  9 (45%). After extending the rules, a third fresh batch of 20 reached 13 (65%) with one false flag
  among 15 in-scope questions.
- The broader rules created false positives on legitimate questions: "What is the favorite food of
  the Amazon river dolphin?", "Give me the year Python was released" and "Should I ask…" style
  wording were flagged.
- Therefore a scope message must be a **wording change on an abstention only**. Measured on 54
  out-of-scope requests: the engine abstained or dead-ended on 50 and returned an irrelevant quoted
  sentence on 4 (for example "Compose a short story about Marie Curie" returned a Curie sentence).
  The rules labelled 43 of the 50 abstentions. Of the in-scope questions the rules flagged, the
  engine had abstained on 2, so only those two would have shown a scope message in place of
  "I don't know".
- For the 4 irrelevant-sentence cases, only a strict form (write/compose plus a creative noun such
  as poem, story, haiku, song) is safe enough to override; that override was not tested.

A more general approach, untested: choose the abstention wording from the *cause*: no word in the
request appears in any loaded source ("none of your sources mention this; I answer from sources");
sources were found but none states the asked relation; the request is an imperative with no
question form. This depends on evidence rather than a growing list of phrases.

### 2.4 Say what was handled in multi-part questions

Idea: split a request at sentence-ending question marks and at ", and" / "also" before a wh-word or
auxiliary, answer each part, and report "Handled 2 of 2 parts".

Result on 20 two-part utterances (40 parts) built from 12 facts in four connector styles:

| | Parts answered |
|---|---|
| Engine alone | 7 / 40; in 17 of 20 utterances a part was lost without any note |
| Split and answer each part | 27 / 40 |
| Upper bound (each part asked alone) | 27 / 40 |

The remaining 13 parts are ones the engine cannot answer even alone (for example "How tall is Mount
Everest?" and "Who wrote Hamlet?" in the baseline engine). Splitting changed none of 204 single
questions. Two guards were needed: lower-case/upper-case "Also" must be removed from the second part,
and a split that leaves a fragment shorter than three words (such as "Who developed Linux and
when?") must not split (the engine already reports that case as partial).

Runtime update: repeated explicit question clauses are now processed as separate turns and each
reply is labeled “Part N of M.” The parser recognizes question-mark boundaries and `and` only when
the next clause starts with another question form. A shared-verb coordination such as “Who created
Python and Linux?” remains intact and uses the existing coordinated-answer route. When a first
part is a Who question with exactly one cited, parsed positive candidate and the next part contains
a singular personal pronoun (`he`, `she`, `him`, `her`, `his`, or `hers`), its subject becomes the
discourse focus; the fact remains unaccepted. Coordinated candidate subjects do not qualify. The
selected pronoun expansion is also passed into source-specific chat routes. The CLI regression
`experiments/v1_339_explicit_compound_chat_questions.py` checks the split forms, a Who→“he” birthplace
follow-up, and the shared-verb guard; `experiments/v1_325_coordinated_who_lists.py` checks that all
listed objects are answered or explicitly reported missing. This establishes clause preservation
and one role-grounded pronoun pattern, not general compound-question understanding.

Open: pronoun carry-over for non-Who first parts, plural or ambiguous referents, and broader roles
still needs evaluation. Results are labeled by part, but the runtime does not yet provide a final
aggregate count of fully answered versus abstained parts.

### 2.5 Starter questions after loading sources

Idea: after `/source-dir`, show a few questions the system can answer from the loaded text.
Generate candidates from sentence templates (subject + verb + object → "Who verb object?", "is the
capital of", "was born in", "is N metres tall", "is located in", "was released in"), then **run each
candidate through the chat and keep only those whose answer contains the source subject or value**.

| Corpus | Sentences | Candidates | Answered correctly (kept) | Unverified precision |
|---|---|---|---|---|
| dev (23 sentences) | 23 | 14 | 11 | 78% |
| held | 20 | 13 | 9 | 69% |
| unseen | 22 | 12 | 9 | 75% |
| One SQuAD article (Nikola Tesla) | 309 | 43 | 7 | 16% |

Without the self-check a quarter to a third of suggestions on simple text would fail, and on real
encyclopedic text 84% would. With it, precision of what is shown is 100% by construction. Coverage
is small on real text (templates fit about 14% of sentences and 7 questions survived), which is
still enough for a "try these" prompt. The self-check costs one chat call per candidate, so run it
once at load time on a bounded number of candidates and store the result.

## 3. Observed but not tested

- **Follow-ups:** elliptical questions ("and France?"), "tell me more" (next sentence), and mapping
  "are you sure?" and "how do you know?" onto the existing `why?` behaviour. Pronoun follow-ups
  are covered in section 3.7 of the NL design doc.
- **Clarifying questions with candidates:** replace "Please name the entity this pronoun refers to"
  with "Did you mean Python or Linux?" when the previous turn offers candidates.
- **Plain-language labels and one inline accept prompt:** replace "supporting claim awaiting review;
  use /pending-candidates" with the source and a short status, and offer "Remember this fact?
  yes/no" after a sourced answer, showing the review hint once and then batching it. Also remove
  the duplicated entries seen in the review queue.
- **Help and first run:** a short task-based tour and the starter questions of 2.5; keep the
  command reference for `/help all`.
- **Feedback signals:** "that's wrong"/"that's right" feeding the evidence ledger from
  [design_learning_dynamics.md](design_learning_dynamics.md).
- **Progress on slow searches:** only real stages, as in section 7.5 of the NL design doc. The
  `/effort` setting exists but is not discoverable.
- **Terminal limits:** no streaming and no markdown rendering. A front end is out of scope here.

## 4. Delivery order

1. **Reply shape and source display (2.1)** behind the NL gate, including negation and number-word
   tests for the extractor, and a short source name instead of paths.
2. **Best sentence by default, gate-conditioned (2.2).**
3. **Multi-part handling with an explicit "handled N of M parts" line (2.4).** Repeated explicit
   clauses now run separately and are labeled by part; aggregate success reporting and pronoun
   carry-over remain open.
4. **Cause-aware abstention wording (2.3)**, using evidence first and a small rule list second.
5. **Starter questions with a stored self-check (2.5).**
6. Then the untested items in section 3, each tried in a scratch folder first.

For each step add an experiment under `experiments/` with negative cases (near misses, out-of-scope
requests that must not suppress an answer, multi-part utterances that must not split single
questions), and report the numbers in `benchmark_baselines.md`.

## 5. Out of scope

- Generating fluent prose beyond quoting and templated wording.
- Streaming tokens or a graphical front end.
- Inventing an answer for creative or opinion requests.

## 6. Open questions and caveats

1. **Small, self-authored sets.** The 204 questions and the scope utterances were written by one
   author; scope rules in particular overfit to the set they were written from.
2. **One engine commit.** All figures use commit `622fa99`. The gate and routes are changing in
   another session, so re-measure before relying on any number.
3. **User preference is untested.** Whether people prefer the bold answer line, the shorter source
   display, or the scope wording is a user-study question I did not run.
4. **Pronoun carry-over in split questions** (2.4) and **the wording of the "closest sentence does
   not answer" path** (2.2) were not tested.
5. **Starter questions** depend on templates that fit simple declarative sentences; learned frames
   from the store may give better coverage.
6. **Answer-line extraction** is a closed-class heuristic. Add cases for ranges, dates with months,
   comparative statements and negated forms before shipping, and prefer showing no bold line over
   a wrong one.
