# Focused roadmap from the current CRMS to its goal

**Reviewed:** 2026-10-20
**Status:** aligned in direction; the overall capability goal remains unmet.

## Goal

CRMS aims to become a lightweight, distributable language system that can understand and complete a broad range of ordinary requests, continue across turns, recombine learned knowledge and procedures, and improve from evidence and use. Its answers and generated artifacts should be inspectable, correctable, and clear about uncertainty. It should support coding, math, translation, creative work, and other domains through its natural-language interface.

The 70B-class comparison is a reference for task range and interaction, not a claim of architectural similarity or parity. Compare against a versioned task scorecard and published capability descriptions; no live 70B run is required.

## Overall review

The project is still pointed at the right goal. The architecture has meaningful strengths: searchable source text, explicit facts and procedures, provenance, bounded inference with proof checks, cautious abstention, and several narrow end-to-end language and task paths.

The gap is integration and generalization. Most strong results are bounded experiments on authored or controlled examples. They do not yet demonstrate broad task coverage, robust dialogue, autonomous rule learning from source material, or a distributable model that can learn and operate without the original files. Recent dialogue work improves specific topic-grounding and follow-up failures, but remains small-corpus evidence. A new ~30-turn Rome/Paris replay confirms useful follow-ups and explicit topic switches, but also exposes a confident wrong answer when an anaphoric sentence is bound to the previous topic, context loss after source-only answers, stale `why?` context, and unsupported history/ordinal questions. Procedure composition has a useful source-document holdout slice, while instruction alignment and connective evidence still depend on teacher-authored labels. Verified graph reasoning is stronger than its natural-language routing and governance.

This is **on track architecturally, not yet on track to claim the capability goal**. The priority is to turn the strongest components into one measured, reproducible chat-level capability, then widen coverage without hiding abstentions or errors.

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

Use full chat transcripts and varied document layouts, not resolver-only checks. Replay the reported 30-turn Rome/Paris sequence, the Eiffel/Colosseum sequence, and a fresh-process save/reload variant. Keep the existing factual and language regressions in the same locked suite so dialogue changes cannot silently damage answer quality. Report wrong referents separately from abstentions and omissions; a more cautious system is not a regression if it prevents a confident wrong answer.

**Exit:** fresh-process replay passes the fixed regressions across varied entities and layouts; every pronoun-led source sentence has a justified entity/paragraph link; citations support what the user saw; unresolved references are repaired or declined honestly. Record corpus size and layout coverage. Do not proceed to learned dialogue moves as a product feature until this explicit baseline is stable.

### 2. Demonstrate source-disjoint procedure learning and recombination

Make recombination and self-learning rules the central capability experiment. Extend the `v1_433` stable-unique → sort → reverse slice with independent examples per component, complete-document holdout, unseen combinations, independently written request wording, varied values/order, and near misses. Keep source text, examples, instruction mapping, connective labels, induced rule, and validator result as distinct provenance-bearing records.

The current `v1_433` result is a useful vertical slice: a three-stage procedure passes four held-out lists and held-out NumPy source documents through chat and a fresh process, with an independent output oracle. However, component instruction mappings and connective supervision remain teacher-attributed; it does not yet prove autonomous rule learning from prose. Before additional labels, three wording probes yielded 1/3 generated and 2/3 abstained with no wrong outputs. After adding Codex-labeled phrase examples for the alternate operation wording and a two-step unique-plus-sort phrase, all three full requests generated and passed an independent check on four held-out lists and two complete held-out NumPy documents (3/3, no wrong or abstained). The full request compositions were held out, but component mappings were supervised; this establishes useful label-driven recombination, not autonomous synonym discovery. The expanded `v1_436` now tests two operation phrases: source prose and code from distinct publishers propose `sort values ascending` and `reverse the order of elements` for explicit review. Both candidates stay inert until review; accepted mappings preserve phrase/source citations, learn through chat, persist, generate validated code for three held-out lists each, and reject descending and directly negated near misses. The reverse mapping requires seven additional Codex-labeled examples beyond the cited pair, making teacher effort visible rather than hiding it. `v1_437` adds a publisher-held-out MDN “will + operation” construction and a sentence-form-held-out passive NumPy construction; only MDN is a new publisher, since NumPy appeared in `v1_436`. Each reviewed phrase rule passes three held-out lists, but both patterns are hand coded against selected snippets. Proposal extraction is not an integrated feature or autonomous language learner. The related source-learning/recombination regressions pass together (5/5).

**Exit:** at least one unseen composition passes ordinary chat, fresh-process reload, and an independent checker on source-disjoint examples. Unsupported, incomplete, or conflicting instructions abstain. Report teacher effort and labeler contribution. Do not describe teacher-assisted alignment as source-only learning.

### 3. Join recombination to verified reasoning and governed learning

Route the same natural-language task through chat, procedure/rule selection, and the reasoning or task checker. Cover a supported result, missing premise, conflict/negative evidence, cycle or integrity violation, and search-budget exhaustion. Keep `unknown`, explicit negative, conflict, missing premise, and incomplete search distinct.

Then test derivation as a governed proposal: retrieve → compose → independently verify → propose with full lineage. Keep derived cases review-only and lower trust than taught or source-backed knowledge until correction, dependency invalidation, duplicate control, and growth policies are exercised. Derived outputs must not validate the rules that produced them.

**Exit:** chat and engine agree; every positive is independently verified; incomplete search cannot become a positive answer; corrections identify and disable affected derived proposals until revalidated.

**Current evidence (2026-10-20):** `v1_379` now exercises one complete `parent + parent → ancestor` path through source-held-out rule validation, explicit acceptance, SQLite packaging, ordinary-language chat, and independent proof verification. It also checks an unsupported one-edge query, an expansion-limited result with no derived write-back, positive/negative conflict, cycle-backed self-relation, and invalidation after retracting a required premise. The focused reasoning-governance suite passed 6/6 (`v1_191`, `v1_193`, `v1_376`, `v1_379`, `v1_415`, `v1_82`). This closes the integration gate for one controlled rule family and its derived-case lifecycle. It does not demonstrate broad natural-language reasoning, arbitrary learned-rule coverage, or cross-domain procedure planning; those remain open.

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

1. **Dialogue safety baseline:** encode and replay the latest Rome/Paris errors plus Eiffel/Colosseum, including source-only follow-ups and restart. Fix the paragraph/entity binding before widening pronoun resolution. Preserve relevant context across non-final outcomes, but make expiry/replacement rules explicit and tested. Make `why?` point to the most recent relevant result. Add history and visible-list ordinal turns only where there is concrete state to resolve them; otherwise clarify.
2. **One source-disjoint rule-learning experiment:** expand beyond the two hand-coded MDN/NumPy sentence forms in `v1_437` to more publishers, complete source documents, and independently authored unrelated, metalinguistic, contrastive, and negated passages. The current 0/7 (`v1_436`) and 0/5 (`v1_437`) controlled false-proposal results are regression checks, not estimates of real-corpus precision. Keep proposal, source evidence, teacher/labeler decision, accepted rule, and validation as separate records. Promote it to a reusable chat review path only if held-out precision remains high, rejection controls stay safe, and labeler effort is reported. Do not call cue matching autonomous learning.
3. **Reasoning and recombination integration:** send a successful unseen composition through the normal chat route, proof/task checker, and independent verifier; then test missing premises, negative/conflicting evidence, cycles/integrity constraints, and incomplete search. Derived knowledge remains a review-gated proposal with lineage.

### Next packets after those gates

4. Use the shared scorecard's largest user-visible loss to choose between answer-bearing retrieval, relation/paraphrase transfer, or a bounded math/coding/translation/creative task. Each domain gets held-out natural-language requests and an independent checker before scope expands.
5. Continue contextual-intent evaluation in parallel. Defer learned dialogue-move induction until the safe explicit baseline is stable and the pilot beats it on held-out outcomes without raising wrong-referent or inappropriate-move rates.
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
