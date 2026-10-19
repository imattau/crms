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
| "lol" | not run | **Quoted a sentence about a video game** |
| "what's your name?" | not run | Refusal ("multiple equally supported sentences") |
| "Who designed **it**?" after "Who created Python?" | Refusal | Refusal |
| "Who worked with **him**?" | Refusal | Refusal; cause not yet diagnosed |
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

- **The remaining junk-retrieval path is any content-free turn outside the seed phrases.** "lol"
  still reaches the retriever. The seed handlers are anchored regexes (`_ACTS` in
  [crms_conversation.py](../crms_conversation.py)), not a general check, so the rule in section 2
  stays necessary.
- **The `she` failure is partly explained.** Pronoun resolution treats the object of the last answer
  ("the first compiler") as a candidate referent alongside the subject, so `she` is ambiguous between
  a thing and a person. Resolving by entity kind (section 3) addresses this. `Who worked with him?`
  is a pronoun failure, not a relation failure: the direct "Who worked with Charles Babbage?" answers
  from the source. What the pronoun was bound to was not traced. Two related questions still fail
  even with explicit names: "Who did Ada Lovelace work with?" (active/passive rewording) and "Who
  worked with Ada Lovelace?" (the source states it from Ada's side; no inverse reading).
- **A small defect in the new greeting.** With one document and pending claims it prints
  "0 accepted facts and 1 source documents; 2 claims awaiting review loaded." The plural and the
  trailing "loaded" are wrong when the pending-claims clause is present.

### 0.1 What exists, and where it falls short

- **A dialogue-act layer exists, but is anchored and small.** `crms_conversation.py` defines
  `classify_act` (greeting, farewell, thanks, acknowledgement, elaboration, help, unclassified),
  `classify_user_intent` and `respond`, called from the chat loop in place of a direct
  `dialogue.turn`. Each turn it handles carries an inspectable `UserIntentHypothesis` (dialogue act,
  task intent, decision, matched frame, context predicates, alternatives), shown by `/intent`.
  Basis is `hand_checked_runtime_rule`; nothing is learned.
- **Elaboration is a stub.** "Tell me more" with a current topic returns "I can look for more
  grounded information about X. Ask a specific question…". It retrieves and shows nothing.
- **State is still a bag of fields, with two additions.** `CRMSDialogue` holds `last_entity`,
  `subject_entity`, `object_entity`, `last_question`, `last_selected_answer`, a pending
  clarification, writing and timeline fields, plus `source_mentions` (names quoted from sources,
  kept as candidate referents) and `last_intent_hypothesis`. Saved as format version 9. There is
  still no turn history, no record of what has been shown, no question under discussion and no open
  offer.
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

Non-goals: open-ended chit-chat, personality, opinions, humour, creative generation (the bounded
story generator is separate), and any reply whose wording is chosen to sound good.

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

1. **A content-free turn never reaches retrieval.** Replace "matches an anchored seed phrase" with a
   general test: after removing any act phrase, the turn contains no word that is an entity, alias,
   source-mentioned name or relation word known to the knowledge base or the loaded index. "lol"
   fails the test today. The test must be conservative: a short real question ("Python?") has a known
   entity and passes.
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
| `history` | Bounded turn records: act, utterance, resolved question, reply kind, status, ids of facts and citations shown | "why?", elaboration, correction, "are you sure?" | missing |
| `salience` | Ordered entities with kind (person, place, thing, event) and the turn that mentioned them | pronouns, ellipsis | partly (`last_entity`, `source_mentions`) |
| `qud` | Question under discussion: relation asked, bound entity, answer slot | "And Ada Lovelace?", "What about X?" | missing |
| `shown` | Claim identifiers already presented | elaboration without repeats | missing |
| `offers` | Open proposals with a one-or-two-turn expiry | yes / no / "ok" | partly (open choice only) |
| `session_facts` | Statements the user made, with speaker and turn as provenance, not accepted | conversational teaching (5.9) | missing |
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
- **A refusal should not erase the last grounded answer.** "Why?" after two refused turns returned
  "No previous grounded answer to explain yet." The mechanism was not traced; the requirement is that
  `history` keeps the last *answered* turn separately from the last turn.
- **User-supplied text is stored locally in the state file.** Say so in the help text, and clear it
  with the existing reset command.

## 4. Dialogue acts

### 4.1 Taxonomy and current status

Vocabulary follows `UserIntentHypothesis` (`dialogue_act`, `task_intent`) from the intent design.

| Act | Example | Handler | Slots | Status |
|---|---|---|---|---|
| greeting | "Hello?" | status greeting (5.7) | model counts, a tested suggestion | implemented; fix wording defect in section 0 |
| farewell | "Goodbye" | close and save | none | implemented |
| thanks | "thanks" | acknowledgement | none | implemented |
| acknowledgement | "ok" | asks what next, or defers to open choice | open offer | implemented |
| affirm / deny | "yes", "no" | resolves an open offer; else asks what it answers | `offers` | partly: only during an open choice; otherwise an ambiguous hypothesis |
| content question | "Who created Python?" | existing question path | n/a | implemented |
| elliptical follow-up | "And Ada Lovelace?" | rebind `qud` (5.1) | `qud` | missing |
| elaboration | "Tell me more" | next unshown facts about the focus (5.3) | `shown`, `salience` | stub that asks a question |
| justification | "Why?" | existing explanation | `history` | hypothesis exists; refusal erases context |
| challenge | "Are you sure?" | re-run with evidence | `history` | missing |
| correction / repair | "No, I meant …" | rebind the last reference (5.4) | `history`, `salience` | only while a choice is open |
| clarification choice | "the second one" | `_select_candidate` | pending result | implemented |
| entity overview | "What do you know about X?" | entity card (5.8) | facts about X | missing; refuses |
| capability / meta | "What can you do?" | help text | none | implemented; status slots missing |
| user statement | "Ada wrote the first algorithm." | confirm-and-learn (5.9) | `session_facts` | missing |
| out of scope | "Write me a poem" | scope message | none | partly (stories, scope text) |

### 4.2 Classification

1. **Seed patterns**, anchored and ordered (today's `_ACTS`).
2. **General content check** (rule 1 in section 2).
3. **Learned frames.** This is the research track in
   [design_dialogue_moves.md](design_dialogue_moves.md): move and intent frames induced from a
   labelled corpus, with usage evidence, context licence and policy approval kept separate and
   conversation-level holdouts. This document does not duplicate it. One addition worth deciding:
   whether a user may also teach a frame directly (`/teach-reply`-style examples, held-out checked,
   shown in a review queue). The pilot corpus is task-service dialogue (restaurant booking), so a
   user-taught route may fit a research tool better than corpus-induced greetings.
4. **Unclassified.** No act, no content: a closed question about what CRMS can do with the loaded
   model, never retrieval.

The classifier returns the act, the remainder of the text after the act phrase, and the stage that
matched, so a wrong classification can be diagnosed from the hypothesis shown by `/intent`.

## 5. Moves

### 5.1 Elliptical follow-up
Keep the question under discussion as `(relation, answer slot, bound entity)`. "And Ada Lovelace?"
and "What about Babbage?" re-ask the same relation with the new entity bound and run the ordinary
question path on the rewritten question. With no `qud`, or an unresolvable entity, say what is
missing ("I don't have a previous question to apply that to"), not "name an entity already in the
knowledge base".

### 5.2 Pronouns
As in section 3. Trace what `him` is bound to in "Who worked with him?" (the explicit-name form
answers, so the binding is the fault), and measure the effect of kind-based filtering on the current
candidate set. Add the section 0 pronoun cases as a regression table. Question wording that fails
with explicit names ("Who did Ada Lovelace work with?") belongs to the inverse-relation work in the
reasoning notes, not to this layer.

### 5.3 Elaboration
Select accepted facts and cited source sentences about the focus entity that are not in `shown`,
ordered by the relations the user has asked about, then by stable identifier. Show a small batch with
citations, add them to `shown`, and say how many remain. When none remain, say so. This replaces the
current stub; it never retrieves on the words "tell me more".

### 5.4 Correction and repair
"No, I meant X" rebinds the most recent resolved reference or ambiguity candidate and re-runs the
previous question. It also records a `/wrong` signal against the earlier answer through the existing
feedback path, so a learned rule used in that proof is suspended exactly as today. "That's wrong" and
"that's right" map to `/wrong` and `/right`. Contextual corrections during an open choice already
exist; this extends them to the last answered turn.

### 5.5 Clarification as a question
Extend the numbered-choice mechanism from "multiple candidate answers" to the other ambiguities
already detected: two equally salient persons, two entities with the same surface name, and
"multiple equally supported source sentences" (currently a plain refusal). Options are always real
candidates from the evidence, shown with their sources, answerable by number, ordinal or name. The
current pronoun message ("please name one and restate the question") is the form to improve.

### 5.6 Offers and suggestions
After a reply CRMS may offer a next step stored in `offers` with a short expiry: "1 source claim is
awaiting review. Review it?", "Ask about: Charles Babbage, Grace Hopper." The UX-doc rule applies:
**only suggest what is known to work**, checked at suggestion time against an answered question or an
accepted fact. A yes or no resolves the offer; with no open offer "yes" gets "Yes to what? I asked
nothing." (the current hypothesis already marks this case ambiguous).

### 5.7 Greeting and status
Implemented. Remaining work: fix the plural and clause-order defect, and add at most one tested
suggestion. Replies name CRMS in the third person ("CRMS has …"); keep that convention and make no
claim about feelings.

### 5.8 Entity overview
"What do you know about X?" renders an entity card: accepted facts about X grouped by relation, each
with its citation, then the number of source passages that mention X and an offer to elaborate. It is
a deterministic template over stored facts, the kind of rendering `write_fact` already does for single
facts. With no accepted facts, list candidate claims labelled as unreviewed, or say there is nothing,
with the usual next step.

### 5.9 Conversational teaching
The user states something in a plain sentence; CRMS replies with what it understood and asks before
storing anything:

```
I understood: Ada Lovelace — wrote — the first published algorithm.
Remember it for this session, remember it permanently, or ignore it?
```

- Nothing is stored before an explicit answer, and nothing becomes an accepted fact without the
  existing acceptance gate. The exact gates stay in charge. This agrees with the intent design: a user
  claim is not a world fact by default.
- A session statement lives in `session_facts` with speaker `user`, is labelled as told by the user,
  and does not feed rule discovery until promoted.
- On conflict with an accepted fact or a cited source, show both with provenance and ask which to
  keep. Never overwrite silently.

**Feasibility risk found in review.** Two things in the first draft were not checked and are false as
stated:

1. `propose_facts` only returns candidates from *licensed* fact patterns. In a fresh knowledge base it
   returned no candidates for "Ada Lovelace wrote the first published algorithm.", "My name is Matt."
   or "Charles Babbage designed the Analytical Engine." (the same last sentence does produce a claim
   through the `/source` path, which realises questions from source sentences instead). A user
   statement therefore needs either a learned pattern for its wording or a different extraction path.
2. Facts need a citation that resolves. A user's turn is not a document in the research index. A
   workable route, not tried: append the statement to a session transcript source indexed with a
   content hash and character offsets, as the Taskmaster pilot does for its transcripts, so the
   citation resolves like any other.

Until a spike shows both work, treat 5.9 as unproven. If no licensed pattern matches, say so and
offer `/teach-fact`; never guess a relation.

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
| Junk-retrieval rate | Content-free turns that produced a quoted passage | before: 3 of 7 on the academic model; now: 1 of 3 non-seed content-free turns ("lol"; "blah blah" and "what's your name?" refused) |
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

0. **Finish the baseline.** The general content-free rule (replaces seed-only matching), the greeting
   wording defect, mixed-turn handling beyond the comma form, and the trace of what `him` binds to.
1. **Discourse state.** Turn history, `shown`, `qud`, last answered turn kept separate from the last
   turn, saved in the next format version with tolerant loading kept. Entity kind for source-derived
   names.
2. **Follow-ups.** Kind-based pronoun binding, elliptical turns, "why?" surviving a refusal, real
   elaboration, entity card.
3. **Mixed initiative.** Clarification questions beyond numbered candidates, offers, affirm and deny,
   correction of the last answer wired to `/wrong` and `/right`.
4. **Conversational teaching.** First a spike on the two risks in 5.9; only then the confirm-and-learn
   flow with session and permanent scope.
5. **Learned frames.** Owned by the dialogue-moves and intent research notes. Decide separately
   whether to add a user-taught route.

Each phase ships with its own tests and may not lower any metric in section 7.

## 9. Out of scope

Free-form generation, an open-ended persona, emotion or opinion statements, long-range discourse
structure beyond the bounded history here, speech, and multi-user conversations.

## 10. Open questions for the owner

1. Is a user-taught conversational frame wanted in addition to corpus-induced frames, given that the
   pilot corpus is restaurant-booking dialogue and CRMS is a research assistant?
2. Should user statements default to session scope or always ask? The design asks every time at
   first, then allows a setting.
3. Which corpus should the junk-retrieval baseline use as the standard? The academic model contains
   this project's own source files, which is where the code-snippet replies came from.
4. Does the intent design's `UserIntentHypothesis` stay the single decision record, so this layer
   only adds state and handlers and never a second classification output?
