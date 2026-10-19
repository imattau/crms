# Design: a conversation layer (dialogue acts, discourse state, grounded moves, conversational teaching)

**Audience:** the developer (human or AI) implementing this.
**Status:** proposed, revised after a review against the code at commit `73e4599`. A first
conversation baseline is already implemented (section 0.1); the rest is not. The evidence comes from
scripted sessions (about 35 turns before the baseline landed, about 40 after), not from a
benchmark; treat the figures as motivation and a baseline to re-measure, not as results to cite.
**Relationship to other docs:** the ground rules in section 0 of
[design_learning_dynamics.md](design_learning_dynamics.md), the presentation rules in section 1 of
[design_chat_ux.md](design_chat_ux.md), and the output rule in section 0 of
[design_natural_language_replies.md](design_natural_language_replies.md) apply unchanged. Two
research notes already cover the *learned* side of dialogue and are not repeated here:
[design_dialogue_moves.md](design_dialogue_moves.md) (corpus-licensed moves, Taskmaster pilot) and
[design_user_intent_model.md](design_user_intent_model.md) (contextual user intent hypotheses). This
document covers what those do not: the discourse state the moves need, the turn types that are still
unhandled, and a confirmation-gated way for a user to teach CRMS in plain sentences.

## 0. Problem and evidence

CRMS began as a question router with a refusal path: a turn was a content question, one of a few
regex-matched phrases, or a `/command`, and anything else was a failed lookup. Three scripted
sessions were run (a copy of `crms_project_model_academic.sqlite`, and a six-sentence source about
Babbage, Lovelace and Hopper; the second source session repeated the follow-ups after accepting the
facts). They were run twice: before and after `crms_conversation.py` landed.

| Turn | Before | Now (commit `73e4599`) |
|---|---|---|
| "Hello?", "Good morning", "How are you?" | Canned out-of-scope line | Greeting with counts of facts, sources and pending claims |
| "hi there" | Quoted a Python code snippet | Greeting |
| "Goodbye" | Quoted a code snippet | Ends the session and saves |
| "Tell me more" | Quoted an unrelated paper | Asks which entity or source to look at; does not elaborate |
| "lol" | not run (quoted a video-game sentence when first tried) | Handled as a reaction; no retrieval (phase 0) |
| "what's your name?" | not run | Refusal ("multiple equally supported sentences") |
| "Who designed **it**?" after "Who created Python?" | Refusal | Refusal |
| "Who worked with **him**?" | Refusal | Named choice ("Which entity do you mean?") after phase 0; still not bound |
| "Where did **she** work?" | "No workplace statement for *she*" | "Could refer to the first compiler, Grace Hopper; name one" |
| "And Ada Lovelace?" | "Name an entity already in the knowledge base" | Same |
| "No, I meant …" | Same | Same |
| "What do you know about Python?" | Refusal | Refusal |
| "Why?" after two refused turns | "No previous grounded answer" | Same |
| "Is Babbage the designer of the Analytical Engine?" | Cannot answer yes or no | Same |

Already working and not to be regressed: "it" resolved to the last entity when it is unambiguous,
"Why?" after a direct answer, thanks, help, numbered clarification choices (`_select_candidate`),
contextual yes/no and corrections while a choice is open, a comma-separated greeting plus question
("Hello, who created Python?"), and bounded multi-question routing.

Findings from the review that change the design:

- **The junk-retrieval path was any content-free turn outside the seed phrases.** "lol" reached the
  retriever and quoted a sentence about a video game. Phase 0 closed it with seed reactions and a
  non-lexical class (`_ACTS` in [crms_conversation.py](../crms_conversation.py)). That is still an
  enumeration, and the general rule drafted here does not work as first written: "lol" **is** a word
  in the corpus, so a test of "no known word" cannot catch it (section 2, rule 1).
- **The pronoun failures had two causes, now traced.** (1) `CRMSDialogue.turn` calls `clear()` on any
  turn that is not an accepted-fact answer, and recorded source-quoted names only when the research
  status was `sources_found`. A quoted answer awaiting review (`needs_review`, which is what
  "Who designed the Analytical Engine?" returns) left no referent at all, so "Who worked with him?"
  got "Please name the entity this pronoun refers to." Phase 0 retains the quoted names for
  `needs_review` as well; the follow-up now gets a named choice. (2) Even then `him` is not bound:
  `_resolve_pronoun` accepts a substitution only when the knowledge answers it, and a quoted-source
  match does not count, because the research status cannot separate a real answer from a loosely
  related sentence ("Who worked with the Analytical Engine?" also returns a quote). Binding needs a
  role-checked match or entity kind (section 3), not a status check. When the object of the last
  answer is a candidate too, `she` is ambiguous between a thing and a person. The direct questions
  with explicit names answer. Two related questions still fail even with explicit names: "Who did
  Ada Lovelace work with?" (active/passive rewording) and "Who worked with Ada Lovelace?" (the source
  states it from Ada's side; no inverse reading).
- **A small defect in the new greeting, fixed in phase 0.** With one document and pending claims it
  printed "0 accepted facts and 1 source documents; 2 claims awaiting review loaded." It now reads
  "…1 source document loaded, with 2 claims awaiting review."

### 0.1 What exists, and where it falls short

- **A dialogue-act layer exists, but is anchored and small.** `crms_conversation.py` defines
  `classify_act` (greeting, farewell, thanks, acknowledgement, elaboration, help, unclassified),
  `classify_user_intent` and `respond`, called from the chat loop in place of a direct
  `dialogue.turn`. Each turn it handles carries an inspectable `UserIntentHypothesis` (dialogue act,
  task intent, decision, matched frame, context predicates, alternatives), shown by `/intent`.
  The baseline includes contextual pending-choice and explanation-follow-up handling, plus bounded
  lexical frames for direct wh/yes-no questions and modal requests. It remains a hand-checked
  rule set; nothing is learned. A typed elaboration-topic slot now recovers a bare entity reply
  when CRMS has asked which accepted entity to expand on; the general task-slot inventory remains
  unimplemented.
- **Elaboration and conversation memory were added in phase 1** (the baseline described here
  predates it). "Tell me more" lists unshown accepted facts about the focus; it used to return "I can
  look for more grounded information about X…" and show nothing. For a topic that exists only in a
  quoted source it still asks which entity to look at.
- **State was a bag of fields, with additions.** `CRMSDialogue` holds `last_entity`,
  `subject_entity`, `object_entity`, `last_question`, `last_selected_answer`, a pending
  clarification, writing and timeline fields, `source_mentions` (names quoted from sources, kept as
  candidate referents), `last_intent_hypothesis`, a bounded intent trace and active task-intent label,
  `pending_dialogue_slot`, `open_dialogue_question`, `history`, `last_answered` and `shown` (format
  version 16, with legacy state loading). A bounded assistant clarification is retained as an
  explicit question-under-discussion (QUD), including whether it expects detail or yes/no and a
  bounded expected-slot type exposed to licensed intent frames. Answers to six supported task-slot
  questions are retained in session state with their prompting question and can be recalled by a
  direct follow-up; missing values abstain instead of querying factual memory. Offers are transient.
  The active task label supplies only a
  `task_in_progress` context predicate to licensed frames.
- **Entity recognition is partly widened.** `_source_entity_mentions` retains capitalised names from
  quoted sentences as candidates; `_canonical_entity` and `_known_entity_surfaces` still look only at
  accepted facts and aliases. Pronoun resolution does not consult entity kind.
- **The chat loop still post-processes every turn** (count routes, source routes) in a file of about
  10,000 lines.
- **Chat learning is explicit.** Every `/teach-*` command teaches content. No command teaches a
  conversational behaviour and a plain statement is not treated as something to learn from.

## 1. What "conversational" means here, and what it does not

CRMS replies are never sampled or generated from a learned distribution (replies doc, section 0).
That rule stays. Conversational therefore means **good turn-taking over verified content**, not
fluent filler:

- recognise what the user is doing (ask, greet, thank, correct, ask for more, answer a question
  CRMS asked, tell CRMS something);
- keep track of what is being talked about and what has already been said;
- respond to every turn with an answer, a useful next step, or an honest statement of what is
  missing, never with an unrelated quotation;
- ask the user a short closed question when that is the cheapest way to proceed;
- let the user teach CRMS in plain sentences, with an explicit confirmation before anything is
  stored.

This adds a **fourth reply class** beside the three allowed today (quoted source sentence, templated
rendering of a stored or derived fact, checked proof explanation): an **act reply**. An act reply is
a fixed, versioned template whose slots are filled only from checked state: counts read from the
loaded model, the session history, entity names from the knowledge base or index, and the user's own
words. **An act reply never asserts a fact about the world.** The current greeting, farewell and
acknowledgement already satisfy this.

**Goal and its constraint.** CRMS is meant to be an LLM-class system built on a different
architecture, not a research assistant or a lookup tool. Conversation therefore has to grow toward
general use: open-ended chat, writing, explanation and reasoning, not only questions about loaded
sources. The README's "not a general-purpose chatbot" describes today's coverage, not the target. What
the architecture adds is a rule about *how* it grows: every claim stays traceable, and nothing is
produced by a learned distribution. So the items below are things this document does not yet design,
not things CRMS should never do: open-ended chit-chat, a consistent personality, opinions and humour,
and broader creative generation (the bounded story generator is separate). Each would need a
verified, auditable mechanism before it ships, and a reply whose wording is chosen only to sound good
has none.

## 2. Architecture

The pipeline is the one `crms_conversation.respond` already starts:

```
user text
  -> classify (act + UserIntentHypothesis)    existing, extend
  -> discourse state update                   section 3
  -> dispatch
       content act -> resolved question -> existing question path (unchanged)
       social / meta / repair / teach act -> act handler    section 5
  -> ReplyPlan (extended intents)             section 6
  -> existing realisation and evidence labels
  -> record in history
```

Rules that bind the whole pipeline:

1. **A content-free turn never reaches retrieval.** What is built is a closed set: seed phrases,
   a short list of reactions (laughter, exclamations) and turns with no letters, digits or
   arithmetic operators. A general test was drafted as "no word that is an entity, alias,
   source-mentioned name or relation word known to the knowledge base or index", and it fails on the
   evidence: "lol" appears in the corpus, so it counts as a known word. Open design problem: a
   single-token turn with no question shape ("lol", "Python") matches any sentence containing the
   token, and the answer gate has nothing to check because there is no asked relation or answer type.
   A candidate, untested, is to answer such bare topics with an entity card or "What would you like to
   know about X?" (5.8) instead of a quotation. That would change replies to bare topic words, so it
   needs the answer-regression test in section 7 first.
2. **An act handler may replace an abstention or answer a content-free turn. It may never replace an
   answer.** This mirrors the "scope message may replace an abstention, never an answer" rule in the
   chat UX doc, whose measurement showed rule lists are fragile on fresh wording (45% on 20 unseen
   utterances).
3. **Mixed turns are split.** Only a comma after the greeting is handled today ("Hello, who…?").
   Extend to "hi there who created Python?" (it currently passes straight to the question path and
   answers, so this is a consistency fix, not a bug fix) and to a trailing thanks.
4. **Deterministic.** Same state and input give the same reply.

Code placement: extend `crms_conversation.py`; keep `CRMSDialogue` for entity and pronoun machinery.
Do not add new routing to `crms_chat.py`.

## 3. Discourse state

Move from the flat fields to one structure, saved in the next dialogue-state format version (9 is
current). Keep reading older versions and the fallback that starts a fresh dialogue when a saved
state cannot be loaded.

| Component | Contents | Used by | Today |
|---|---|---|---|
| `history` | Bounded turn records: act, utterance, status (12 turns, 200 characters each) | "why?", correction, "are you sure?" | implemented in phase 1; no fact or citation ids yet |
| `last_answered` | Question and answer of the last grounded answer, kept across refused turns | "why?" after a refusal | implemented in phase 1 |
| `salience` | Ordered entities with kind (person, place, thing, event) and the turn that mentioned them | pronouns, ellipsis | partly (`last_entity`, `source_mentions`) |
| `qud` | Question under discussion: relation asked, bound entity, answer slot | "And Ada Lovelace?", "What about X?" | missing |
| `shown` | Keys of accepted facts already presented (500 at most) | elaboration without repeats | implemented in phase 1 |
| `offers` | Open proposals with a one-or-two-turn expiry | yes / no / "ok" | partly (open choice only) |
| `session_facts` | Statements the user made, with speaker and turn as provenance, not accepted | conversational teaching (5.9) | not built; confirmed statements become permanent facts with a "told by user" source instead |
| intent hypothesis | Current-turn decision record | routing, `/intent` | exists |

Design decisions:

- **Pronoun class comes from entity kind, not names.** Existing policy is that CRMS does not infer
  gender. Resolve `he`, `she`, `him`, `her` and `they` to the most salient entity of kind `person`,
  and `it` to the most salient non-person; when two persons are equally salient, ask (5.5). This
  needs kinds for source-derived names. The current candidate set mixes subjects and objects of the
  last answer, which is the observed cause of "could refer to the first compiler, Grace Hopper".
- **Entity inventory.** Accepted-fact entities, learned aliases, subjects and objects of pending
  candidates, and source-quoted names. The last of these exists; replies about a source-only entity
  keep the label "quoted evidence, not an accepted fact".
- **A refusal clears the live referents but not the conversation memory.** `clear()` still runs on
  every non-answered turn, deliberately so that an unrelated pronoun cannot reach a stale referent. It
  no longer touches `history`, `last_answered` or `shown`; only the explicit `/reset` wipes those
  (`reset_history`). "Why?" after a refusal now explains the earlier answer, recomputed from current
  evidence, and begins "Explaining my earlier answer to ‘…’." so the user can see which turn it means.
  Reading "Why?" as a request to explain the *refusal itself* is the other plausible meaning and is
  not implemented; the refusal text is unchanged.
- **User-supplied text is stored locally in the state file.** Say so in the help text, and clear it
  with the existing reset command.

## 4. Dialogue acts

### 4.1 Taxonomy and current status

Vocabulary follows `UserIntentHypothesis` (`dialogue_act`, `task_intent`) from the intent design.

| Act | Example | Handler | Slots | Status |
|---|---|---|---|---|
| greeting | "Hello?" | status greeting (5.7) | model counts, a tested suggestion | implemented |
| reaction | "lol", "wow", "🙂" | acknowledge, no retrieval | none | implemented in phase 0 |
| farewell | "Goodbye" | close and save | none | implemented |
| thanks | "thanks" | acknowledgement | none | implemented |
| acknowledgement | "ok" | asks what next, or defers to open choice | open offer | implemented |
| affirm / deny | "yes", "no" | resolves an open offer; else asks what it answers | `offers` | implemented in phase 3 for one offer (review pending claims); an open choice keeps its own yes/no handling |
| content question | "Who created Python?" | existing question path | n/a | implemented |
| elliptical follow-up | "And Ada Lovelace?" | carry the last question frame to the new entity (5.1) | last question | exists (`_resolve_entity_followup`) for fact-backed answers; quoted-source answers cannot verify it |
| elaboration | "Tell me more" | next unshown facts about the focus (5.3) | `shown`, focus entities | implemented in phase 1 for accepted facts; source-only topics still ask a question |
| justification | "Why?" | existing explanation | `last_answered` | implemented; after a refusal it explains the earlier answer and says which |
| challenge | "Are you sure?" | re-run with evidence | `history` | missing |
| correction / repair | "No, I meant …" | re-ask the last question about the named entity (5.4) | `last_question` | implemented in phase 3 for fact-backed questions; records no verdict |
| clarification choice | "the second one" | `_select_candidate` | pending result | implemented |
| entity overview | "What do you know about X?" | entity card (5.8) | facts about X | implemented in phase 2 for entities with accepted facts |
| capability / meta | "What can you do?" | help text | none | implemented; status slots missing |
| user statement | "Ada wrote the first algorithm." | confirm-and-learn (5.9) | the sentence | implemented in phase 4 (permanent, confirmed, labelled) |
| out of scope | "Write me a poem" | scope message | none | partly (stories, scope text) |

### 4.2 Classification

1. **Seed patterns**, anchored and ordered (today's `_ACTS`).
2. **General content check** (rule 1 in section 2).
3. **Learned frames.** This is the research track in
   [design_dialogue_moves.md](design_dialogue_moves.md): move and intent frames induced from a
   labelled corpus, with usage evidence, context licence and policy approval kept separate and
   conversation-level holdouts. This document does not duplicate it. One addition worth deciding:
   whether a user may also teach a frame directly (`/teach-reply`-style examples, held-out checked,
   shown in a review queue). The pilot corpus is task-service dialogue (restaurant booking), which
   covers greetings, repair and closing but not open-domain conversation, so it is a starting corpus
   and not the target; a second, open-domain corpus will be needed for the stated goal.
4. **Unclassified.** No act, no content: a closed question about what CRMS can do with the loaded
   model, never retrieval.

The classifier returns the act, the remainder of the text after the act phrase, and the stage that
matched, so a wrong classification can be diagnosed from the hypothesis shown by `/intent`.

## 5. Moves

### 5.1 Elliptical follow-up
This already exists, which the first draft of this document missed. `_resolve_entity_followup`
carries the last question frame to a named entity ("And Ada Lovelace?", "What about Babbage?") by
substituting the entity into the previous question and accepting the result only if the knowledge base
answers it. That is why it fails on quoted-source answers: a quoted answer cannot verify the
substitution (the research status does not separate a real answer from a loosely related sentence,
section 0), so the user sees "name an entity already present in the knowledge base", which is
misleading when the entity is in the sources. A separate `qud` record is therefore not needed. What
remains is the wording of that failure and, for quoted-source answers, offering the rewritten question
as a numbered choice in the way section 5.5 now does for pronouns.

### 5.2 Pronouns
Phase 2 did not change which entity a pronoun binds to; it changed what the user can do when it
cannot decide (5.5). Kind-based filtering is still the way to stop `she` offering "Harvard" or "the
first compiler" as candidates, and it needs entity kinds for source-derived names, which do not exist.
Question wording that fails with explicit names ("Who did Ada Lovelace work with?") belongs to the
inverse-relation work in the reasoning notes, not to this layer.

### 5.3 Elaboration
Implemented for accepted facts (`CRMSDialogue.elaborate`). The focus is the last answer's entity and
the subject and object of the last answer, in that order. Facts are read through the fact store's
subject and object indexes (a `lookup_subject` was added next to `lookup_object`), those not in
`shown` are listed three at a time as "subject — relation → object [source: …]", and the reply says
how many remain, then "That is everything I have accepted about X." The wording is deliberately a
cited fact line, not a sentence: no licensed sentence frame is required, so it works on a fresh
knowledge base. It never retrieves. Facts are ordered by relation name, not by what the user has asked
about. Still to do: source-only topics (quoted candidates), ordering by the relations the user asked
about, and licensed sentence wording where a frame exists.

### 5.4 Correction and repair
Implemented in phase 3, with one deliberate change from the first draft.

- **"No, I meant X" re-asks, and records nothing.** It carries the previous question to X through the
  existing entity follow-up and replies "Understood. Asking again as ‘…’." The first draft also
  recorded a `/wrong` signal against the earlier answer. That was a design error: a correction says
  CRMS misread the *question*, and the earlier answer may be right for what was asked. A `/wrong`
  signal can suspend a learned rule that supported it, so it must not be inferred from a correction.
  Corrections during an open choice keep their existing handling.
- **"That's wrong" / "that's right" map to `/wrong` and `/right`.** Only an explicit verdict about
  "that" or "it" counts ("that's incorrect", "it is not right", "that's correct"). A bare "correct",
  "right" or "wrong" is left alone, because the terminal's review prompts use those words as replies.
  With no recent evidence-backed answer the existing command explains that. `natural_feedback_verdict`
  is in `crms_conversation.py`; the rewrite to the command is in the chat loop.

### 5.5 Clarification as a question
Extend the numbered-choice mechanism from "multiple candidate answers" to the other ambiguities
already detected: two equally salient persons, two entities with the same surface name, and
"multiple equally supported source sentences" (currently a plain refusal). Options are always real
candidates from the evidence, shown with their sources, answerable by number, ordinal or name.

Implemented in phase 2 for pronouns (`pending_binding`). When a single pronoun could mean several
entities, the reply keeps its existing explanation and adds "Or reply with a number or a name: 1. …".
Picking one runs the corresponding rewritten question through the ordinary path, so its answer carries
its normal evidence label. A receipt ("ok", "yes", a reaction) repeats the choice; any other turn
discards it. The binding is transient and not saved, and only questions with exactly one pronoun get
options. Still to do: the same for two entities with one surface name and for "multiple equally
supported source sentences".

### 5.6 Offers and suggestions
After a reply CRMS may offer a next step stored in `offers` with a short expiry: "1 source claim is
awaiting review. Review it?", "Ask about: Charles Babbage, Grace Hopper." The UX-doc rule applies:
**only suggest what is known to work**, checked at suggestion time against an answered question or an
accepted fact. A yes or no resolves the offer; with no open offer "yes" gets "Yes to what? I asked
nothing." (the current hypothesis already marks this case ambiguous).

Implemented in phase 3 for one offer. Where the terminal tells the user claims are waiting ("…use
/pending-candidates to inspect.", and the greeting when claims are pending) it adds "Say ‘yes’ to
review them now." and opens a `review_pending` offer. A bare yes then replies "Okay, here they are."
and asks the terminal to run `/pending-candidates` (`DialogueTurn.action`, taken from a fixed
allowlist and never from user text); no declines it. An offer survives one intervening turn and is gone
after two, and it is not saved. An open answer choice or pronoun choice takes the yes/no first. The
"Ask about: …" suggestion needs a check that each suggested entity answers, and is not done.

### 5.7 Greeting and status
Implemented. Remaining work: fix the plural and clause-order defect, and add at most one tested
suggestion. Replies name CRMS in the third person ("CRMS has …"); keep that convention and make no
claim about feelings.

### 5.8 Entity overview
Implemented in phase 2 (`CRMSDialogue.overview`). "What do you know about X?", "What can you tell me
about X?" and two similar phrasings list up to five accepted facts about X, including facts where X is
the object, each as a cited line, then how many remain; "tell me more" continues with the rest. It
applies only when X names a single entity with accepted facts and no taught about-frame already
matches, so unknown and source-only entities keep their existing handling. Not done: grouping by
relation, a count of mentioning source passages, and an unreviewed-claims section for source-only
entities.

### 5.9 Conversational teaching
Implemented in phase 4, after the spike this section called for. The user states something in a plain
sentence; CRMS replies with what it understood and asks before storing anything:

```
I understood: Ada Lovelace — wrote → the first published algorithm. Shall I remember that as
something you told me? Say ‘yes’ or ‘no’.
```

**Spike results.** Both risks from the first draft were tested before building.

1. *Extraction.* `propose_facts` returns nothing for a fresh wording. A wording pattern is learned by
   `teach_fact_pattern`, which declines the first example (it needs at least two distinct subjects and
   objects) and accepts the second; after that an unseen sentence ("Jane Austen wrote Emma.") is
   proposed. So the first two statements of a new wording cannot be recognised automatically.
2. *Citation.* A fact whose source is a plain string, not an indexed document, works end to end:
   it answers questions, is explained by "why?", takes `/right` and `/wrong` feedback, and can be
   retracted. No transcript document is needed.

**The flow.**

- `parse_statement` (in `crms_conversation.py`) proposes (subject, relation, object) from a plain
  sentence: a leading named entity, one to three lowercase predicate words, the rest as the object. It
  is deliberately narrow. It refuses questions, commands, first-person sentences ("My name is Matt."),
  anything with punctuation inside, compound or subordinate sentences, and a list of imperative and
  greeting openers. It only ever proposes; this is not a parser.
- The proposal opens a `confirm_statement` offer (section 5.6). A bare yes stores it, a bare no
  discards it, and it lapses after two other turns. Nothing is stored before the yes, and a sentence
  already known is reported as known instead of proposed.
- On yes, the fact is added with the source `told by user#<hash of the sentence>`. The part before the
  `#` is the same for every statement, so source-independence counting sees all user statements as one
  origin and they cannot inflate rule validation. The reply is labelled "[told by user]", says whether
  the wording is now recognised or needs one more example, and prints the exact
  `/retract-fact POS|…` command that forgets it. The terminal saves the knowledge immediately.
- The told-by-user fact answers questions straight away (a stored-relation question frame needs no
  extra teaching).

This is a different evidence class from a cited source: it records that the user said it, not that it
is true. The label travels with the fact into answers ("Sources: told by user") and nothing in
this flow marks it as corroborated.

**Not done.**

- *Session scope.* The first draft offered "this session / permanently / ignore". Only a permanent
  confirmed fact exists, because session-only facts would need the terminal's many `knowledge.save`
  calls to skip them. Open question 2 stands, now with this as the default.
- *Conflicts.* A statement that contradicts an accepted fact or a source is not detected. A
  functional-relation conflict would show only at inference time.
- *First-person statements* and statements with several objects are refused, not handled.
- *Unconfirmed wording learning.* The wording pattern is taught from the same confirmation; a mistaken
  parse that the user confirmed teaches a mistaken pattern. Review of learned patterns is the existing
  `/retract-fact` and pattern tooling, not new here.

**A bug this exposed, fixed.** After a second confirmed statement for a verb, answering a question
raised `KeyError: 'canonical_form'`: `render` had no branch for the evidence kind
`fact_pattern_derived_question_frame` and its fallback assumed every other kind had a
`canonical_form`. It reproduces with `add_fact` and `teach_fact_pattern` alone, so it predates this
work and would have hit `/teach-fact` users. `render` now has a branch for that kind and a fallback
that cannot fail.

## 6. Reply plan and realisation

Extend `ReplyPlan` (replies doc, section 3.1) with intents `social`, `clarify`, `offer`,
`elaborate`, `entity_card` and `confirm_learn`. Claims inside `elaborate` and `entity_card` are
ordinary claims with origin and sources, so they pass through existing realisation and labelling
unchanged. Act-only replies carry no claims, which makes the "never asserts a fact about the world"
rule testable: a reply with intent `social`, `clarify` or `offer` must have an empty claim list.

Wording stays deterministic. Variation between replies is a setting that is off by default; when on,
selection is keyed to the turn number so the same conversation replays identically. Avoid internal
vocabulary in ordinary replies (UX doc, item 6).

## 7. Evaluation

Add a scripted conversation benchmark under `experiments/`, growing from the sessions in section 0
(`v1_365_contextual_clarification_intent.py` is the existing nearby regression). It should record
turns, expected act, expected reply kind and content assertions.

| Metric | Definition | Baseline |
|---|---|---|
| Junk-retrieval rate | Content-free turns that produced a quoted passage | before: 3 of 7 on the academic model; now: 0 of 3 non-seed content-free turns after phase 0 ("lol" is a reaction; "blah blah" and "what's your name?" are refused) |
| Act accuracy | Correct act on held-out phrasings | not measured; seed regexes only |
| Resolution accuracy | Correct binding for it, she, he, him, her, they and elliptical turns | 1 of 4 person and elliptical cases, before and now |
| Dead-end rate | Turns ending with no answer and no next step | not measured |
| Recovery rate | After a miss, the user can continue in one turn | not measured |
| Answer regression | Previous answers that become refusals or act replies | must be 0 on the 204-question set |
| Determinism | Same script gives byte-identical replies | not measured |

Two tests are mandatory: no act handler may replace an answer (run the existing question benchmark
through the dispatcher and require identical answers), and every `social`, `clarify` or `offer`
reply has an empty claim list.

## 8. Delivery order

The numbering is changed from the first draft because phase 0 is largely done.

0. **Finish the baseline.** Done on branch `conversation-phase0`: the greeting wording, seed
   reactions and non-lexical turns kept out of retrieval and out of an open choice, and quoted
   answers under review kept as candidate referents (checked by
   `experiments/v1_370_conversation_content_free_and_referents.py`). Not done: a general rule for bare
   single-token topics (section 2, rule 1), mixed-turn handling beyond the comma form, and binding
   `him` and `she` to the right referent.
1. **Discourse state.** Turn history, `last_answered`, `shown`, active task intent, a bounded
   turn-intent trace, session task-slot values, and the current assistant clarification QUD are
   saved in dialogue-state format version 16 with older versions still loading. A single typed
   `elaboration_topic` slot also
   persists and is validated; see `experiments/v1_375_contextual_elaboration_slot.py`,
   `experiments/v1_386_session_intent_context.py`, and
   `experiments/v1_388_open_dialogue_question_state.py`. The expected answer type is part of the
   QUD and can license contextual intent frames; the clarification response is recorded as a
   user-provided value in the intent trace and never becomes a fact. Elaboration moved here because
   `shown` needs it. Selected clarification values are retained as session-only task slots; CRMS
   does not yet use them to fill forms or execute actions. `session_facts` and entity kinds for
   source-derived names remain future work.
2. **Follow-ups.** Done on branch `conversation-phase2`: a numbered choice for an ambiguous pronoun
   and the entity overview (checked by
   `experiments/v1_373_conversation_binding_and_overview.py`). Elliptical turns already existed. Not
   done: kind-based pronoun filtering, elaboration for source-only topics, and the wording of the
   quoted-source follow-up failure.
3. **Mixed initiative.** Done on branch `conversation-phase3`: the review offer with affirm and deny,
   corrections that re-ask without a verdict, and natural verdicts routed to `/wrong` and `/right`
   (checked by `experiments/v1_374_conversation_offers_and_corrections.py`). Not done: clarification
   questions for two entities with one name and for "multiple equally supported source sentences",
   suggestion offers, and "Are you sure?".
4. **Conversational teaching.** Done on branch `conversation-phase4`: the spike, then confirm-and-learn
   with permanent scope only (checked by `experiments/v1_375_conversation_teaching.py`). Session scope,
   conflict display and first-person statements are not done (5.9).
5. **Learned frames.** Owned by the dialogue-moves and intent research notes. Decide separately
   whether to add a user-taught route.

Each phase ships with its own tests and may not lower any metric in section 7.

## 9. Out of scope

Not designed here yet, and needed for the stated goal of LLM-class conversation: open-ended
generation, a persona, emotion and opinion statements, and long-range discourse structure beyond the
bounded history. Out of scope for a different reason: speech and multi-user conversations.

## 10. Open questions for the owner

1. Is a user-taught conversational frame wanted in addition to corpus-induced frames, given that the
   pilot corpus is restaurant-booking dialogue and the goal is open-domain, LLM-class conversation?
   (A first draft of this document called CRMS a research assistant; that was wrong.)
2. Should user statements be allowed a session-only scope, and should confirmation be asked every time?
   Phase 4 asks every time and stores permanently; a session scope needs the terminal's saves to skip
   those facts.
3. Which corpus should the junk-retrieval baseline use as the standard? The academic model contains
   this project's own source files, which is where the code-snippet replies came from.
4. Does the intent design's `UserIntentHypothesis` stay the single decision record, so this layer
   only adds state and handlers and never a second classification output?
