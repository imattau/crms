# Design: natural-language replies built from stored content, not quoted sentences

**Audience:** the developer (human or AI) implementing this.
**Status:** proposed. A first-step prototype (question plus answer span to a short declarative
sentence, with a round-trip check) was tested in a scratch folder and **works only on simple
sentences**; it fails on real questions, and its cheap round-trip check cannot tell right from wrong
(section 2). The design in section 3 is therefore built around structured content and a *parsed*
round trip, not around rearranging question words. Nothing here is implemented.
**Relationship to other docs:** the output rule below governs everything.
[design_natural_language_handling.md](design_natural_language_handling.md) decides *whether* a
sentence answers a question; [design_chat_ux.md](design_chat_ux.md) decides how a reply is shown;
this document decides how a reply is *worded* when it is not a quotation.

## 0. The rule this design must satisfy

CRMS replies are never sampled or generated from a learned distribution. Every reply is one of: a
quoted source sentence; a templated rendering of a stored or derived fact; or a checked proof
explanation. Learned or statistical scores may rank or filter candidates, but never decide what is a
fact and never produce text. Same input, same reply. Each claim in a reply traces to a cited source.

Consequences: no free paraphrase, no fluent filler, no wording chosen to sound good. A reply is
"natural" only to the extent that CRMS has *verified wording rules* for the facts it is stating.

## 1. What exists, and what is missing

| Need | Exists today | Missing |
|---|---|---|
| Something to say that is smaller than a sentence (a fact, a typed span) | Stored facts with provenance; proofs; question frames | Facts extracted from real text at useful yield (measured low, see the NL doc section 3.6); a reliable answer-span extractor |
| Licensed wording for a fact | `write_fact` realises a stored fact as active or passive text, only when the wording has independent supporting examples; "I don't have a verified language rule to paraphrase this result yet" when it has none | Coverage across relations; tense, agreement, plurals, determiners, negation, quantities; question-shaped answer templates |
| Combining several facts | none | Aggregation, referring expressions, ordering, connectives |
| Checking its own output | none | A round trip: parse the reply back with CRMS's own rules and compare |
| Controlled variation | none | A deterministic choice rule or a user setting |

## 2. A first-step prototype, and what it showed

**Idea.** For a question plus a typed answer span taken from the cited sentence, build a short
answer-first sentence ("When was Python released?" with span 1991 gives "Python was released in
1991."), taking verb forms and determiners from the cited sentence so morphology is grounded in the
source. Then run a round-trip check before showing it; if the check fails, fall back to quoting.

**Prototype.** Question normalisation (strip "Can you tell me", "Tell me", "In what year" to
"When", "X was V by whom" to "Who V X", "Which city is the capital of Y" to "What is the capital of
Y"), then about ten patterns: When was/did, Who V, Who is, Where was/is, How tall/long, How many,
What is the A of X. A lexical round trip accepted a sentence only if its content words were all in
the cited sentence or the question, the answer span was in the cited sentence, and the NL gate's
answer-type check accepted it. All runs used the frozen engine at commit `622fa99`.

**Results.**

- *Small hand-written sets (simple declarative sentences).* Of 78 correct sourced answers, 32
  matched a pattern on the raw question and 52 after normalisation (67%). All 52 passed the round
  trip, and the sentences read correctly ("Guido van Rossum created Python.", "Python was released
  in 1991.", "Everest is 8849 metres tall.", "Canberra is the capital of Australia."). One defect
  was found and fixed: the span "Himalayas" dropped its determiner ("is in Himalayas"); the fix is
  to take the determiner from the cited sentence ("is in the Himalayas").
- *Real questions (fresh SQuAD articles, 200 questions, gold sentence given).* A typed answer span
  was found in the gold sentence for 153 (77%), but a question pattern applied to only 34 (17%).
  Of those 34, the output was wrong or ungrammatical in a large share, because the span
  extractor picked a capitalised sentence-initial word that is not an answer ("Falling ended the
  series in 1989.", "Accountants studies…", "White was the percentage of whit people…", "It decides
  the fate…", "Another was the name given to…"), the question was mis-parsed ("Luther mostly
  concentrating his efforts on reform was in Saxon.", "In Against did Luther call on…"), or the
  relation was wrong ("Los Angeles is the population of the second largest city…").
- *The lexical round trip cannot discriminate.* It accepted all 34 realisations, including every bad
  one above, and it also accepted 33 of 33 realisations built from a question and a deliberately
  wrong sentence. Rearranging question words plus a span trivially satisfies "no new words".
- *A stricter order check is too blunt.* Requiring the realised sentence to match the cited
  sentence's word order (longest common subsequence of at least 0.8) rejected 33 of 34 realisations
  and 33 of 33 wrong ones: precise, but it also rejects correct rearrangements ("Russell T Davies
  produced the Doctor Who revival series." against a source written in the passive).

**Conclusions.**

1. Answer-first templating from a question works on simple declarative text and not yet on real
   questions; coverage (17%) and span quality are both far from sufficient.
2. A check built from word overlap cannot validate a rewording. Validation needs the *roles*: who
   did what to whom, and what the span is the answer to. That means parsing the sentence into a fact
   (subject, relation, object, qualifiers) and comparing facts, which is what the existing
   fact-pattern machinery does.
3. The answer-span extractor used here and in the chat UX doc is a closed-class heuristic. The UX
   doc's claim that it matched the gold answer for 78 of 78 correct replies holds for simple
   sentences only. On real text a span must be checked (section 3.4) before it is shown in bold
   or used to build a sentence.

## 3. Design

### 3.1 Reply plan

Every reply starts from a *content plan*, not a sentence:

```
ReplyPlan(
  intent: answer | yes_no | list | summary | explanation | abstention,
  claims: [Claim(subject, relation, object, qualifiers, polarity, sources[], origin)],
  proof:  optional ordered steps linking claims,
  focus:  the claim or span the user asked about,
)
```

`origin` is one of `stored_fact`, `derived_fact`, `source_sentence_parse`, `quoted_only`. A claim
from `quoted_only` has no parsed structure and can only be quoted.

### 3.2 Realisation, in order of preference

1. **Realise from licensed wording.** If a claim's relation has a verified surface pattern (active
   and passive realisations with independent support, as `write_fact` already requires), render it
   with that pattern. Morphology comes from verified paradigms (the engine's irregular-verb table,
   regular rules checked against corpus forms), and determiners come from the cited sentence.
2. **Quote the clause.** If the claim came from a parsed source sentence but no verified wording
   exists, show the cited clause, trimmed to the smallest span that carries the claim, with the
   answer marked. Trimming is by constituents from the parse, not by arbitrary cuts.
3. **Quote the sentence** with the existing status labels. This is today's behaviour and is always
   a safe fallback.

A reply never mixes sampled wording into any of these.

### 3.3 Combining claims

Deterministic rules, applied only to claims that share a subject or a proof:

- **Aggregation:** claims with the same subject and relation are joined by a coordination pattern
  ("won two Nobel Prizes, in 1903 and 1911"); different relations share the subject with "and".
- **Referring expressions:** after a full name, use a pronoun or short name only if the entity has a
  single candidate in the plan; otherwise repeat the full name.
- **Ordering:** by time qualifier if present, otherwise by source order; proofs follow proof order.
- **Connectives:** "because" and "therefore" only between proof steps, taken from the proof graph.
- **Length bound:** a plan has a fixed maximum number of claims per reply; further claims are
  offered ("show more") so long answers stay inspectable.

### 3.4 The round-trip contract

Before showing any realised sentence the reply layer parses it with CRMS's own fact-pattern rules
and requires:

1. It parses into exactly the claims in the plan, with the same roles (not just the same words).
2. Every claim's cited sentence still supports the claim (the existing citation check).
3. The focus span is the object, subject or qualifier the question asked about, in the role the
   question's frame requires.
4. Span sanity: a span that is a single sentence-initial word is accepted as a name only if the
   parse marks it as one.

If any requirement fails, fall back to the next realisation option in 3.2. Prototype data show why
requirement 1 must use roles: a word-overlap check accepted 33 of 33 wrong realisations.

### 3.5 Variation

Wording choices (for example "was founded in" or "was established in") are made by a fixed rule
(first verified pattern by a stable order) or by a user setting. There is no random choice and no
learned selection of text.

### 3.6 Display

The realised sentence is shown with its sources and status, as in the chat UX doc. `why?` shows
the plan: each claim, the wording rule used, and the round-trip result.

## 4. Delivery order

1. **Span extractor with checks.** Replace the heuristic with a parse-backed span (section 3.4,
   requirement 4) and measure it on real questions; this also fixes the UX doc's bold answer line.
2. **Question-to-statement templates for stored facts first.** Answers backed by an accepted fact
   already have roles; add the ten-pattern set from section 2 on top of the verified wording, and
   measure the round trip on facts (not on question rearrangement).
3. **Round trip through the real parser** (3.4), with a benchmark of correct and deliberately wrong
   (question, sentence) pairs.
4. **Aggregation and ordering** for multi-claim replies (3.3), starting with same-subject claims.
5. **Proof explanations** with connectives (3.3).
6. **Wording coverage** for more relations and forms, driven by what the round-trip benchmark shows
   is missing.

## 5. Acceptance and tests

- On a benchmark of at least 100 (question, sentence) pairs that includes wrong sentences:
  zero realised sentences that state something the cited sentence does not support; report how
  many correct pairs are realised versus quoted.
- Reproducibility: identical output on repeated runs.
- No realised sentence without a successful round trip; otherwise the reply is a quotation.
- Include near misses: passives, negation ("not Sydney"), multi-word names, sentence-initial common
  words, and questions whose pattern does not match.
- Measure on fresh text, not only on the small hand-written sets, because the prototype looked
  good on those and failed elsewhere.

## 6. Out of scope

- Free paraphrase, summarisation by rewriting, or any learned text generation.
- Creative writing as such. If it is ever added, it must follow the same rule (templates and
  quoted material only) and will be much more limited than LLM output.
- Replies in languages other than the ones for which wording rules are verified.

## 7. Open questions and caveats

1. **Yield.** Realisation needs facts. If few real-text claims are parsed into facts, most replies
   stay quotations. Fact extraction yield (the NL doc, section 3.6) bounds the benefit.
2. **Which wording rules count as verified.** Reuse the `write_fact` standard (independent
   supporting examples per surface form), or adopt a lighter standard for closed-class templates
   such as "X was released in Y"? A decision is needed.
3. **Pronoun rules.** When is a pronoun safe? The prototype pronoun resolution got 4 of 6
   resolvable follow-ups in a small test and bound one wrongly.
4. **Grammar checking.** Round trip checks meaning, not fluency. Some realisations may parse
   correctly yet read awkwardly. A hand review of a sample per release is needed.
5. **Tested on narrow data.** The prototype used about ten question patterns, two small corpora and
   200 SQuAD questions; its coverage figures (67% on simple sentences, 17% on real questions) are
   indicative only. The scripts are in a scratch folder and are not committed.
