# Focused roadmap from the current CRMS to its goal

**Reviewed:** 2026-10-20
**Status:** aligned in direction; the overall capability goal remains unmet.

## Goal

CRMS aims to become a lightweight, distributable language system that can understand and complete a broad range of ordinary requests, continue across turns, recombine learned knowledge and procedures, and improve from evidence and use. Its answers and generated artifacts should be inspectable, correctable, and clear about uncertainty. It should support coding, math, translation, creative work, and other domains through its natural-language interface.

The 70B-class comparison is a reference for task range and interaction, not a claim of architectural similarity or parity. Compare against a versioned task scorecard and published capability descriptions; no live 70B run is required.

## Overall review

The project is still pointed at the right goal. The architecture has meaningful strengths: searchable source text, explicit facts and procedures, provenance, bounded inference with proof checks, cautious abstention, and several narrow end-to-end language and task paths.

The gap is integration and generalization. Most strong results are bounded experiments on authored or controlled examples. They do not yet demonstrate broad task coverage, robust dialogue, autonomous rule learning from source material, or a distributable model that can learn and operate without the original files. Recent dialogue work improves specific topic-grounding and follow-up failures, but remains small-corpus evidence. Procedure composition has a useful source-document holdout slice, while instruction alignment and connective evidence still depend on teacher-authored labels. Verified graph reasoning is stronger than its natural-language routing and governance.

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

Freeze the current reliable dialogue cases and add a compact multi-turn set around topic switches, paragraph/entity grounding, source-only answers, unanswered turns, `why?`, clarification, corrections, and save/reload. Include the Eiffel Tower/Colosseum competing-pronoun case and the source-only follow-up case. A confident wrong referent, stale explanation, or discarded valid context fails the packet; ambiguous context should trigger clarification or abstention.

Use full chat transcripts and varied document layouts, not resolver-only checks. Keep the existing factual and language regressions in the same locked suite so dialogue changes cannot silently damage answer quality.

**Exit:** fresh-process replay passes the fixed regressions across varied entities and layouts; citations support what the user saw; unresolved references are repaired or declined honestly. Record the scope of the corpus.

### 2. Demonstrate source-disjoint procedure learning and recombination

Make recombination and self-learning rules the central capability experiment. Extend the `v1_433` stable-unique → sort → reverse slice with independent examples per component, complete-document holdout, unseen combinations, independently written request wording, varied values/order, and near misses. Keep source text, examples, instruction mapping, connective labels, induced rule, and validator result as distinct provenance-bearing records.

The current `v1_433` result is a useful vertical slice: a three-stage procedure passes four held-out lists and held-out NumPy source documents through chat and a fresh process, with an independent output oracle. However, component instruction mappings and connective supervision remain teacher-attributed; it does not yet prove autonomous rule learning from prose. Before additional labels, three wording probes yielded 1/3 generated and 2/3 abstained with no wrong outputs. After adding Codex-labeled phrase examples for the alternate operation wording and a two-step unique-plus-sort phrase, all three full requests generated and passed an independent check on four held-out lists and two complete held-out NumPy documents (3/3, no wrong or abstained). The full request compositions were held out, but component mappings were supervised; this establishes useful label-driven recombination, not autonomous synonym discovery. A new `v1_436` experiment demonstrates one source-derived phrase candidate: cited prose and a cited code example from two origins propose `sort values ascending` for review. The proposal remains inert until Codex accepts it; after acceptance, chat learns the rule, preserves both citations, passes three held-out lists, and rejects descending wording. Proposal extraction is still a hand-coded cue experiment, not an integrated feature or general language learner. The adjacent `v1_431`, `v1_433`, and `v1_434` regressions pass together (3/3).

**Exit:** at least one unseen composition passes ordinary chat, fresh-process reload, and an independent checker on source-disjoint examples. Unsupported, incomplete, or conflicting instructions abstain. Report teacher effort and labeler contribution. Do not describe teacher-assisted alignment as source-only learning.

### 3. Join recombination to verified reasoning and governed learning

Route the same natural-language task through chat, procedure/rule selection, and the reasoning or task checker. Cover a supported result, missing premise, conflict/negative evidence, cycle or integrity violation, and search-budget exhaustion. Keep `unknown`, explicit negative, conflict, missing premise, and incomplete search distinct.

Then test derivation as a governed proposal: retrieve → compose → independently verify → propose with full lineage. Keep derived cases review-only and lower trust than taught or source-backed knowledge until correction, dependency invalidation, duplicate control, and growth policies are exercised. Derived outputs must not validate the rules that produced them.

**Exit:** chat and engine agree; every positive is independently verified; incomplete search cannot become a positive answer; corrections identify and disable affected derived proposals until revalidated.

### 4. Advance contextual intent and dialogue

Treat user intent as a revisable hypothesis from the current utterance and explicit discourse context. Use it to track task/subgoal, resolve follow-ups, choose a route, or ask for clarification; it must not create facts or authorize unsupported actions. Evaluate identical utterances in different contexts, topic changes, repairs, confirmations, open choices, and history questions.

Run the bounded dialogue-move induction pilot separately from the explicit baseline. Preserve utterance citations, corpus/domain policy, and Codex labeling provenance; compare coverage, task completion, inappropriate moves, abstention, and labeling effort. One labeler's agreement is a diagnostic, not accuracy.

**Exit:** contextual intent improves held-out task completion without more wrong referents, stale state, or inappropriate actions. Learned dialogue moves remain experimental unless they beat the explicit baseline on held-out outcomes.

### 5. Expand task range one validated domain slice at a time

Choose one useful bounded task in each of math, coding, translation, and creative work. Define ordinary-language requests, held-out wording, negative cases, independent validation, evidence policy, and repair flow before implementation. Compose across domains only after the components work alone. Creative work needs human ratings for coherence and requested constraints; template invariants alone do not establish quality.

**Exit:** each slice reports held-out coverage, correct/wrong/abstained, completeness, provenance, repair success, and cost through chat. New breadth must not increase wrong answers or conceal abstentions.

### 6. Complete the distributable SQLite model contract

After the records and learning lifecycle above are stable, complete migration and packaging so one SQLite model carries searchable source text, accepted knowledge, rules/procedures, and provenance. Build it, copy it to a clean location, remove access to original ingestion files, query it, learn through supported paths, export/reload it, and query it again. Preserve transactional updates and compatibility paths as needed.

**Exit:** a copied model supports the same fixed chat scorecard, evidence lookup, supported learning, and reload without original documents. Report model size, runtime, unsupported cases, and any remaining limits.

## Near-term order and scope control

1. Freeze and replay the compact dialogue/chat evaluation slice.
2. Extend the source-disjoint procedure experiment beyond teacher-labeled aliases. Keep the 1/3 baseline and 3/3 explicitly supervised result side by side. Generalize the `v1_436` review-only proposal path across more operation phrases and near-miss source prose, then move it from the experiment into a reusable chat review flow only if held-out precision remains high and rejection remains safe.
3. Connect one successful composition to proof/task verification and governed derivation.
4. Use the scorecard's largest user-visible loss to select the next task: answer-bearing retrieval, paraphrase coverage, dialogue completion, or one bounded domain slice.
5. Continue intent/dialogue evaluation in parallel; defer production dialogue-move induction until it clears its held-out gate.
6. Finish SQLite distribution after the record model is stable, then evaluate the clean copy.

Choose work by reduction in wrong answers, increase in held-out useful coverage, or removal of a named integration blocker. Do not grow the corpus, add a domain, migrate storage, or add dialogue machinery solely to show activity. Keep recombination, self-learning rules, reasoning, dialogue, and contextual intent visible in each roadmap review. After every packet, update the scorecard and state plainly whether evidence moves CRMS closer to the overall goal.

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
