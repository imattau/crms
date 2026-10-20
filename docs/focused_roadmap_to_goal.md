# Focused roadmap from the current CRMS to its goal

**Reviewed:** 2026-10-20 (after real-corpus and dialogue review)
**Status:** aligned in direction; the overall capability goal remains unmet.

## Focus for the next development cycle

The next cycle should close three integration gaps before adding more surface
area. Dialogue safety is the reliability gate; evidence-backed rule discovery
and recombination are the main capability bet; verified reasoning and governed
derivation keep composed outputs correctable. The most recent corpus probe
changes the rule-learning tactic: direct exact-pair predicate matching found no
useful variants in sampled SimpleWiki windows, while structured-field/prose
alignment found one repeated candidate (`capital city of` → `capital of`) on
eight distinct entity pairs. A replay through the integrated proposal API
found the same candidate on eleven pairs. The exploratory probe also
reported `national museum of` as a `born in` variant because it treated
infobox caption lines as prose. After excluding structured key/value lines,
that candidate disappeared; the `capital city of` candidate remained on eight
pairs. The matched-scope replay (`v1_458`) copied 3,284 eligible documents and
found exact agreement on all eight capital pairs. The full probe now reports
four candidate groups, one novel predicate group, and no caption-derived
false proposal. The integrated path's other three matches come from its
broader document scan. This is a useful source boundary correction, not a
precision estimate: the field-to-relation mapping is hand-coded, evidence
comes from one corpus, and unproposed variants remain unmeasured. Keep the
path report-only and review-gated. The arXiv index has zero exact attestations
of `capital city of` among 1,697 papers, and only one `capital of` sentence;
the latter supports canonical wording but does not validate this variant.
Use a corpus with actual relation and wording overlap for cross-source
generalization, and do not count missing phrase occurrences as false claims.
Codex's unblinded review found all eight cited capital sentences directly
express the relation; this does not estimate proposal precision or recall. See
the [review record](../experiments/reports/structured_predicate_alignment_review.json).

| Order | Work packet | Immediate outcome | Do not claim yet |
|---|---|---|---|
| 1 | Validate dialogue transfer and safety | Preserve current clean-process regressions; test independently authored transcripts, varied layouts, visible-context carryover, topic switching, repairs, and history questions. Measure wrong referents, omissions, clarifications, and task completion separately. | Robust open-domain conversation from authored fixtures. |
| 2 | Turn source alignment into a useful discovery experiment | Generalize structured-field/prose alignment without hard-coded field→relation truth; emit cited, report-only candidates with entity-role checks, source-disjoint splits, and negative controls. Measure yield and precision on a larger, blinded corpus sample before building more extraction machinery. | Autonomous rule learning or reliable paraphrase discovery from one repeated field. |
| 3 | Recombine learned components through reasoning | Route accepted, source-backed rules through natural-language chat, held-out composition, proof/checking, and an independent output validator. Include correction and derived-case invalidation; distinguish negative, conflict, missing premise, and incomplete search. | General planning or safe self-improvement from synthetic fixtures. |

Run the contextual-intent/dialogue track alongside these packets, but let intent
route, clarify, or repair only; it cannot supply evidence. Expand math, coding,
translation, creative work, and the portable SQLite model after the shared
chat-level evaluation contract can measure them. Choose each next task from a
measured failure or a gate blocker, and stop expanding when a packet fails its
negative controls.

## Goal

CRMS aims to become a lightweight, distributable language system that can understand and complete a broad range of ordinary requests, continue across turns, recombine learned knowledge and procedures, and improve from evidence and use. Its answers and generated artifacts should be inspectable, correctable, and clear about uncertainty. It should support coding, math, translation, creative work, and other domains through its natural-language interface.

The 70B-class comparison is a reference for task range and interaction, not a claim of architectural similarity or parity. Compare against a versioned task scorecard and published capability descriptions; no live 70B run is required.

## Overall review

The project is still pointed at the right goal. The architecture has meaningful strengths: searchable source text, explicit facts and procedures, provenance, bounded inference with proof checks, cautious abstention, and several narrow end-to-end language and task paths.

The gap is integration and generalization. Most strong results are bounded experiments on authored or controlled examples. They do not yet demonstrate broad task coverage, robust dialogue, autonomous rule learning from source material, or a distributable model that can learn and operate without the original files. The report on commit `043093f` found a wrong Eiffel Tower referent after a Colosseum topic switch and source-only context loss. Current-checkout replays (`v1_413`, `v1_419`, `v1_426`, and `v1_427`) now keep the cited completion answer on the Colosseum, preserve the latest evidence for `why?`, retain named source-only follow-ups, and resolve France → “and Italy?” to Italy's capital. `v1_449` closes a further integration gap: a pronoun-led date passes the final chat evidence gate only when the exact cited paragraph names the current topic before the pronoun; a pronoun-only paragraph abstains. An added interruption sequence in `v1_442` reports 32/32 supported evidence steps, no wrong answers, and 8/8 abstentions after an unsupported question, with follow-up context preserved. These are regression fixtures, not independent evidence of general dialogue reliability; held-out variation remains untested. Procedure composition has useful source-document holdout slices, while instruction alignment and connective evidence still depend on teacher-authored labels. Verified graph reasoning is stronger than its natural-language routing and breadth of rule coverage.

A four-conversation Taskmaster-1 test slice, disjoint from the labeled dev
conversations and earlier twelve test conversations, now gives a transfer
warning: the current transcript-context intent replay matched both
Codex-primary labels on 12/46 turns (26.1%), versus 64/131 (48.9%) on dev.
All 46 source spans verified, but labels are single-annotator and do not
measure task completion. Treat the dialogue-transfer gate as unmet; keep this
slice frozen and develop against disjoint conversations.

This is **on track architecturally, not yet on track to claim the capability goal**. The priority is to turn the strongest components into one measured, reproducible chat-level capability, then widen coverage without hiding abstentions or errors.

The latest selected runtime replay on `edb2893` passed 10/10 diagnostics across
phrase transfer, recombination, graph reasoning, math/code, translation,
creative revision, and dialogue persistence. This is healthy regression
coverage, not a user-level success rate: the checks are controlled and do not
measure broad task completion. The current paraphrase layer answered 73/78
dev, 44/45 held, and 42/44 unseen items with no wrong outputs; five, one, and
two items respectively abstained. Its direct baseline shifted from the older
snapshot, so comparisons need a pinned, investigated baseline before they can
support trend claims. The main unmet risks remain independent dialogue
generalization and source-derived rule discovery; the project should spend its
next cycle measuring those instead of adding domain breadth.

## What counts as progress

Maintain one versioned end-to-end scorecard. For every task set, keep source documents or dialogue splits disjoint where relevant, freeze expected answers and negative controls, and report:

- useful coverage, correct answers, wrong answers, abstentions, and omissions;
- evidence or proof quality, completeness, provenance, and repair success;
- generalization to held-out wording, examples, and sources;
- teacher/labeler contribution and effort, separately from what CRMS learned;
- runtime and storage cost where they affect the user experience.

A retrieval hit, a passing component experiment, or a generated artifact that passes only its own examples is not an end-to-end success. Retain failures as regressions and identify the code snapshot and corpus behind every result.

## Execution path

Work in these packets. Dialogue and contextual intent are an active research track alongside packets 1–3; they are not deferred until reasoning is finished. Keep each packet small enough to produce a clean-process chat result before expanding scope.

### 1. Protect chat correctness and establish the evaluation contract

Freeze the current reliable dialogue cases and add a compact multi-turn set around topic switches, paragraph/entity grounding, source-only answers, unanswered turns, `why?`, clarification, corrections, history questions, ordinal selection, and save/reload. Include the Eiffel Tower/Colosseum competing-pronoun case and the source-only follow-up case. Specifically test sentences beginning with a pronoun or omitted subject: they may answer for an entity only when the source paragraph or another explicit relation binds that sentence to the entity. Retrieval support alone must not choose the referent.

Treat context as typed evidence with bounded lifetime, not a single all-or-nothing reset. Preserve the last visible source entities and active question across a source-only answer or a recoverable abstention; replace or expire them on explicit topic change, reset, or a turn that establishes incompatible context. `why?` must identify the exact answer or abstention being explained. For “and Italy?”, “what did I just ask?” and “the first one,” either resolve from visible, still-open context or ask a short clarification. Add the reported wording contrast (“built” vs “designed and built”) as a relation-coverage case, while keeping it separate from referent safety.

Use full chat transcripts and varied document layouts, not resolver-only checks. The focused tests now cover the Eiffel/Colosseum sequence, source-only topic changes, current-topic pronoun binding, explicit topic-switch clauses, save/reload, failed follow-ups, history, ordinals, and `why?`; a curated 30-turn transcript completes without a crash. `v1_438` adds transfer from neutral to gendered single-pronoun follow-ups and verifies that user-named context cannot create evidence. `v1_439` routes “Switch to X. [question]” through the standard answer path and verifies an unsupported target cannot borrow prior evidence. `v1_449` tests the reported cross-paragraph topic switch through fresh CLI processes and confirms that an exact cited paragraph can jointly ground a named antecedent and its pronoun-led date; a detached pronoun paragraph is still rejected. Keep these as regression controls, then add independently authored transcripts and varied layouts before claiming robust dialogue. Keep factual and language regressions in the same locked suite so dialogue changes cannot silently damage answer quality. Report wrong referents separately from abstentions and omissions; a more cautious system is not a regression if it prevents a confident wrong answer.

**Exit:** fresh-process replay passes the fixed regressions across varied entities and layouts; every pronoun-led source sentence has a justified entity/paragraph link; citations support what the user saw; unresolved references are repaired or declined honestly. Record corpus size and layout coverage. Do not proceed to learned dialogue moves as a product feature until this explicit baseline is stable.

### 2. Demonstrate source-disjoint procedure learning and recombination

Make recombination and self-learning rules the central capability experiment. Extend the `v1_433` stable-unique → sort → reverse slice with independent examples per component, complete-document holdout, unseen combinations, independently written request wording, varied values/order, and near misses. Keep source text, examples, instruction mapping, connective labels, induced rule, and validator result as distinct provenance-bearing records.

The current `v1_433` result is a useful vertical slice: a three-stage procedure passes four held-out lists and held-out NumPy source documents through chat and a fresh process, with an independent output oracle. However, component instruction mappings and connective supervision remain teacher-attributed; it does not yet prove autonomous rule learning from prose. Before additional labels, three wording probes yielded 1/3 generated and 2/3 abstained with no wrong outputs. After adding Codex-labeled phrase examples for the alternate operation wording and a two-step unique-plus-sort phrase, all three full requests generated and passed an independent check on four held-out lists and two complete held-out NumPy documents (3/3, no wrong or abstained). The full request compositions were held out, but component mappings were supervised; this establishes useful label-driven recombination, not autonomous synonym discovery. The expanded `v1_436` now tests two operation phrases: source prose and code from distinct publishers propose `sort values ascending` and `reverse the order of elements` for explicit review. Both candidates stay inert until review; accepted mappings preserve phrase/source citations, learn through chat, persist, generate validated code for three held-out lists each, and reject descending and directly negated near misses. The reverse mapping requires seven additional Codex-labeled examples beyond the cited pair, making teacher effort visible rather than hiding it. `v1_437` adds a publisher-held-out MDN “will + operation” construction and a sentence-form-held-out passive NumPy construction; only MDN is a new publisher, since NumPy appeared in `v1_436`. Each reviewed phrase rule passes three held-out lists, but both patterns are hand coded against selected snippets. Proposal extraction is not an integrated feature or autonomous language learner. The related source-learning/recombination regressions pass together (5/5).

**Exit:** at least one unseen composition passes ordinary chat, fresh-process reload, and an independent checker on source-disjoint examples. Unsupported, incomplete, or conflicting instructions abstain. Report teacher effort and labeler contribution. Do not describe teacher-assisted alignment as source-only learning.

### 3. Join recombination to verified reasoning and governed learning

Route the same natural-language task through chat, procedure/rule selection, and the reasoning or task checker. Cover a supported result, missing premise, conflict/negative evidence, cycle or integrity violation, and search-budget exhaustion. Keep `unknown`, explicit negative, conflict, missing premise, and incomplete search distinct.

Then test derivation as a governed proposal: retrieve → compose → independently verify → propose with full lineage. Keep derived cases review-only and lower trust than taught or source-backed knowledge until correction, dependency invalidation, duplicate control, and growth policies are exercised. Derived outputs must not validate the rules that produced them.

**Exit:** chat and engine agree; every positive is independently verified; incomplete search cannot become a positive answer; corrections identify and disable affected derived proposals until revalidated.

**Controlled integration progress (2026-10-20):** `v1_451_reasoned_procedure_composition.py` now learns and source-holdout-validates a typed three-premise relation rule, routes positive/negative/unknown record questions through chat, independently verifies the positive proofs, and feeds only proof-backed record IDs to a separately learned list procedure. The generated artifact passes an independent oracle; conflicted and unsupported IDs are excluded; and a practiced conclusion is invalidated after premise correction. This closes one synthetic integration seam, not the packet: the graph is authored, the procedure examples and phrase association are Codex-labeled, and stage selection is hard-coded in the experiment. Raw-source learning and ordinary-language planning remain unproven.

`v1_456_source_frames_to_reasoned_procedure.py` now supplies the graph facts by running source sentences through CRMS's corpus-frame proposal and explicit review path. Training and holdout documents are separated before frame acceptance; the induced parent-chain rule passes the document holdout; its runtime proofs feed the composed procedure; and correction invalidates a practiced conclusion. This removes hand-entered premises from one controlled integration path. The four source documents are still Codex-authored, origins are synthetic, frame acceptance is explicitly orchestrated, and procedure demonstrations are Codex-labeled. It establishes source-extraction-to-reasoning mechanics, not source-independent language learning or broad recombination.

**Current evidence (2026-10-20):** `v1_379` exercises one complete `parent + parent → ancestor` path through source-held-out rule validation, explicit acceptance, SQLite packaging, ordinary-language chat, and independent proof verification. `v1_192` now exercises a different, typed three-premise schema (`employs + owns + located in → reaches`) through held-out validation, ordinary-language chat, independent proof verification, separate derived-case practice, reload, and invalidation after source correction. The typed negative control confirms the engine reports a positive proof plus explicit negative as `ambiguous/contradiction`, while chat does not return a positive answer when the explicit negative is present. Both paths also check incomplete search and/or missing support, with derived write-back gated accordingly. The focused reasoning-governance suite passed 7/7 (`v1_191`, `v1_192`, `v1_193`, `v1_376`, `v1_379`, `v1_415`, `v1_82`). This is stronger integration evidence across two rule shapes; it still does not demonstrate broad natural-language reasoning, arbitrary learned-rule coverage, or cross-domain procedure planning.

### 4. Advance contextual intent and dialogue

Treat user intent as a revisable hypothesis from the current utterance and explicit discourse context. Use it to track task/subgoal, resolve follow-ups, choose a route, or ask for clarification; it must not create facts or authorize unsupported actions. Evaluate identical utterances in different contexts, topic changes, repairs, confirmations, open choices, and history questions. Keep three measures separate: intent classification, safe context resolution, and successful task completion. A classifier improvement is not useful if the answer uses the wrong entity.

Run the bounded dialogue-move induction pilot separately from the explicit baseline. Preserve utterance citations, corpus/domain policy, and Codex labeling provenance; compare coverage, task completion, inappropriate moves, abstention, and labeling effort. One labeler's agreement is a diagnostic, not accuracy.

**Exit:** contextual intent improves held-out task completion without more wrong referents, stale state, or inappropriate actions. Learned dialogue moves remain experimental unless they beat the explicit baseline on held-out outcomes.

### 5. Expand task range one validated domain slice at a time

Choose one useful bounded task in each of math, coding, translation, and creative work. Define ordinary-language requests, held-out wording, negative cases, independent validation, evidence policy, and repair flow before implementation. Compose across domains only after the components work alone. Creative work needs human ratings for coherence and requested constraints; template invariants alone do not establish quality.

**Exit:** each slice reports held-out coverage, correct/wrong/abstained, completeness, provenance, repair success, and cost through chat. New breadth must not increase wrong answers or conceal abstentions.

### 6. Complete the distributable SQLite model contract

After the records and learning lifecycle above are stable, complete migration and packaging so one SQLite model carries searchable source text, accepted knowledge, rules/procedures, and provenance. Build it, copy it to a clean location, remove access to original ingestion files, query it, learn through supported paths, export/reload it, and query it again. Preserve transactional updates and compatibility paths as needed.

**Exit:** a copied model supports the same fixed chat scorecard, evidence lookup, supported learning, and reload without original documents. Report model size, runtime, unsupported cases, and any remaining limits.

## Near-term order and scope control

### Immediate packets

1. **Dialogue transfer, not another resolver special case.** Keep the current
   topic-switch, paragraph-grounding, source-only, interruption, and `why?`
   regressions locked. Add independent transcripts and varied layouts with
   topic switches, competing entities, source-only answers, corrections, and
   history/ordinal references. Require either context-grounded resolution or
   a targeted clarification. Do not broaden learned intent routing until this
   evaluation shows no confident wrong referents and reports omission and
   completion rates.
2. **One decisive real-corpus discovery study.** Reproduce the structured
   alignment lead (`capital city of` / `capital of`, with matched agreement on
   eight pairs), then test whether candidate groups emerge from field labels
   plus aligned prose across disjoint documents and publishers. The algorithm may
   use field names to propose hypotheses, but must not treat them as semantic
   truth. Keep every candidate cited and inert pending review. Blindly label a
   sample containing candidate and non-candidate pairs from corpora with
   relation and wording overlap; report proposals, confirmed alignments, false
   proposals, coverage, and labeler time. Include
   role reversals, ambiguous fields, quotations, negation, contrast, and
   accidental title/value overlap. Stop or redesign if yield remains
   negligible or precision depends on hand-coded relation mappings.
3. **Promote only a proven path into recombination.** If packet 2 clears its
   precision and coverage gate, connect the reviewed alignments to source-held-
   out rule learning and a genuinely unseen multi-step task through ordinary
   chat and fresh-process reload. Verify proofs and outputs independently;
   test unsupported operations, missing steps, conflicts, cycles, incomplete
   search, source correction, and derived-case invalidation. Keep teacher and
   labeler input explicit. If packet 2 fails, spend this packet improving
   evidence extraction rather than adding dialogue or domain surface area.

These are sequential gates with parallel measurement, not three feature
projects. Contextual intent research may continue on frozen data, but may only
route, clarify, and repair; it cannot supply facts or evidence. Reasoning
improvements should be driven by failures in packet 3, not by engine depth in
isolation.

### Next-cycle deliverables and decision gates

1. **Dialogue transfer benchmark.** Create an independently authored, held-out
   set of multi-turn transcripts and document layouts that varies entity names,
   paragraph boundaries, topic switches, pronouns, source-only answers,
   unanswered turns, corrections, `why?`, history questions, and ordinal
   references. Record expected answer, acceptable clarification, evidence
   span, and failure type before running CRMS. Keep the existing Colosseum /
   Eiffel regressions as controls. Gate: no confident wrong referents on the
   locked set; report coverage, abstentions, clarifications, omissions, task
   completion, and layout/source diversity. If it fails, fix context lifetime
   and referent grounding before adding more intent or move machinery.
   The first small Taskmaster test replay underperforms dev (12/46 vs. 64/131
   joint label matches) and shows that the current context representation
   misses the assistant's last move and typed choice/confirmation state. Use
   disjoint dev conversations to test a bounded discourse state that explicitly
   records the assistant move, open question/choice, active goal, and subgoal;
   do not tune against the revealed test rows. Keep short confirmations
   ambiguous when that state is absent.
2. **Blinded source-rule discovery study.** Use corpora with actual overlap in
   relation and wording. Freeze the candidate generator before labeling; sample
   proposals and non-proposals, and label cited evidence for relation match,
   role direction, polarity, and sentence scope. Keep Codex labels identified
   as model-generated and audit a separate sample. Gate: report precision,
   yield/coverage, label effort, and source independence; retain review-only
   status unless negative controls and non-proposal checks support promotion.
   If yield or precision is inadequate, improve evidence extraction rather
   than hard-coding more aliases.
3. **One chat-level recombination/reasoning demonstration.** After packets 1
   and 2 clear their gates, use an unseen multi-step request whose components
   were learned separately. Run it through ordinary chat and a fresh process;
   independently verify its answer/proof; exercise missing premises,
   contradiction, unsupported operations, incomplete search, correction, and
   derived-case invalidation. Gate: no unsupported positive result, provenance
   survives reload, and teacher/labeler contributions are reported. Keep
   self-generated cases as review-gated proposals until these controls work.

For every deliverable, preserve the corpus and code snapshot, run the same
locked cross-domain regressions, and update
[`benchmark_baselines.md`](benchmark_baselines.md). A packet advances only on
held-out chat evidence, not because its component experiment passes. Once
these gates hold, select a single domain slice (math, coding, translation, or
creative work) by measured user-facing errors, then validate the copied SQLite
model without access to its original source files. This order keeps the core
goal visible: broad natural-language use, safe recombination, contextual
dialogue, and evidence-governed learning in a portable model.

### Next packets after those gates

4. **Broaden request language only when the source/rule gate is stable.** `v1_452` answers 8/11 positive forms with zero wrong outputs and abstains on three; all three negative-direction controls abstain. This is a bounded morphology and phrase-span result. Extend role learning only against held-out wording and conflicts, then choose the next domain slice (math, coding, translation, creative work) from the measured scorecard loss. Each slice needs natural-language holdouts and an independent checker before scope expands.
5. Continue contextual-intent evaluation in parallel. Defer learned dialogue-move induction until the explicit baseline generalizes across independent transcripts and the pilot beats it on held-out outcomes without raising wrong-referent or inappropriate-move rates.
6. Finish SQLite distribution after the record model and learning lifecycle stabilize, then verify a copied model with source files unavailable.

Choose work by reduction in wrong answers, increase in held-out useful coverage, or removal of a named integration blocker. Do not grow the corpus, add a domain, migrate storage, or add dialogue machinery solely to show activity. Keep recombination, self-learning rules, reasoning, dialogue, and contextual intent visible in each roadmap review. After every packet, update the scorecard and state plainly whether evidence moves CRMS closer to the overall goal. A packet is complete only when a clean-process chat replay and its negative controls pass; component scripts alone do not close it.

## Related design documents

- [Learning dynamics](design_learning_dynamics.md)
- [Evidence independence and transfer](design_evidence_independence_and_transfer.md)
- [Natural-language handling](design_natural_language_handling.md)
- [Natural-language replies](design_natural_language_replies.md)
- [Contextual user intent](design_user_intent_model.md)
- [Dialogue moves](design_dialogue_moves.md)
- [Conversation handling](design_conversation.md)
- [Domain expansion](design_domain_expansion.md)
- [SQLite memory](sqlite_memory_design.md)
- [Chat UX](design_chat_ux.md)
- [70B-class capability comparison](capability_comparison_70b.md)
