# Focused plan from current CRMS to its goal

**Reviewed:** 2026-10-20 (HEAD `578f3b0`)  
**Status:** active; the capability goal is not yet demonstrated.

## Goal

Build a lightweight, distributable language system that completes a broad
range of ordinary tasks through natural language, carries context across
turns, combines knowledge and procedures, reasons over evidence, and improves
from use. Outputs should be useful, inspectable, correctable, and clear about
what is supported, inferred, uncertain, or missing. Coding, math, translation,
and creative work should use the same interface. Strong 70B-class models are
a qualitative reference for breadth and interaction, not a parity claim or a
required live comparator.

## Current position

CRMS has meaningful foundations: searchable source text, provenance-bearing
knowledge and procedures, review-gated learning, proof-checked inference,
recombination, contextual dialogue state, and portable SQLite models. Recent
runtime work improved direct search intent, constraint handling, and
source-only follow-ups.

The main gap is reliable transfer across the full path from an ordinary
request to a correct, checked result. Successful examples remain narrow and
often use authored fixtures, explicit mappings, or Codex labels. Dialogue
regressions have targeted controls but not broad independent transfer;
source-derived rule learning has not established useful precision on a new
publisher; recombination and reasoning have not yet cleared a held-out,
ordinary-chat task gate; and safe self-learning at scale remains unproven.
The system is architecturally aligned, but not yet on track to claim broad
capability. Progress means held-out task completion with controlled errors,
not more features, data volume, or isolated passing scripts.

## Execution order

Dialogue safety is a release gate for every chat-facing change. Source-rule
research can run alongside recombination, but cannot block tests using
reviewed components. Derived-case promotion depends on recombination and
independent verification. Broader domains and full distribution follow those
gates.

### 1. Lock a shared end-to-end scorecard and dialogue baseline

Run the known multi-turn cases in a clean process: Eiffel Tower/Colosseum
topic switch, source-only follow-up, pronoun grounding, failed turns, `why?`,
history, ordinal selection, clarification, and save/reload. Add a small set of
independently authored conversations with competing entities, varied
paragraph layouts, and the same utterance under different contexts. Treat
contextual intent as a revisable hypothesis over utterance and explicit
discourse state; it may route, clarify, or repair, but cannot supply facts.
Keep dialogue-move induction as a research comparison against the explicit
baseline.

**Gate:** fixed regressions pass; held-out transcripts have no confident
wrong referent or stale explanation; ambiguity triggers focused clarification
or abstention; every factual answer is supported by shown evidence or a
verified proof. Report task success separately from intent-label agreement.

### 2. Make reasoning and recombination transfer through ordinary chat

This is the main capability gate. Freeze a task set that combines separately
reviewed facts, rules, and procedures. Vary entities, wording, evidence order
and layout, and operation order. Include multi-step inference consumed by a
procedure, proof-based selection followed by an operation, and partial or
compound requests. Include missing premises, explicit negatives,
contradictions, cycles/integrity violations, unsupported operations, and
resource limits. Run tasks through chat and a fresh process; use a copied
model where its serialization path is involved. Check results independently.

**Gate:** held-out ordinary-chat tasks complete more often than the explicit
baseline without confident invalid results. The independent checker accepts
valid outputs and rejects tampered ones. Missing, conflicting, incomplete, or
cyclic evidence produces a specific clarification, abstention, or limit
message. Report completion, omissions, errors, abstention, proof validity,
repair, and runtime separately. Authored controls alone do not pass.

### 3. Learn source rules as a bounded, review-gated research lane

Use complete source units that contain the target construction. Freeze the
candidate method before evaluation; split by document and publisher; review
both proposals and sampled non-proposals. Preserve roles, conditions,
qualifiers, polarity, contrast, and separate citations for claim and context.
Codex may label proposals, with labeler and limitations recorded; those labels
are supervision, not independent validation. Candidates remain inert until
accepted through existing review and holdout gates.

**Gate:** a new publisher and untouched documents yield useful, reviewable
rules with measured false proposals, missed claims, abstentions, and review
burden. Candidate count alone is not progress. If role or scope loss persists,
redesign the representation before scaling ingestion.

### 4. Close the governed self-learning loop

After recombination transfers, let independently verified outputs create
lineage-bearing proposals. Keep derived knowledge distinct and lower-trust
until independently revalidated. Test source/rule correction, dependency
invalidation, conflicts, duplicate suppression, retrieval weighting,
restart, and storage growth. Inject an incorrect derivation and show it cannot
validate itself or amplify through reuse.

**Gate:** every corrected dependency disables or revalidates all affected
derived cases; invalid lineage cannot support a confident answer; provenance
survives save/reload; growth follows an explicit policy. Keep write-back
review-gated until this passes.

### 5. Validate dialogue research and broaden task coverage

Compare contextual intent and any induced dialogue moves with the locked
dialogue baseline on unseen complete conversations. Keep a move only when it
improves task outcomes without increasing wrong referents or unsupported
claims. Then choose one bounded coding, math, translation, or creative task
from observed gaps. Reuse the natural-language interface, recombination, and
the same held-out, independent-check, abstention, and repair gates. Expand one
task slice at a time.

**Gate:** the dialogue approach improves held-out task completion or remains
an explicitly scoped research result. Each domain slice completes held-out
requests with independently checked outputs and honest limits before another
domain is added.

### 6. Verify SQLite as the complete distributable model

Copy the model to a clean location where original source files are absent.
From the copy alone, query, learn, review, recombine, reason, explain, correct,
save/reload, and rerun the shared scorecard. Confirm searchable source text,
accepted knowledge, procedures, licensing, provenance, and correction lineage
survive. Measure size, runtime, compatibility, and migration behavior.

**Gate:** tested behavior depends only on the copied model and runtime, and
evidence and corrections remain inspectable after reload.

## Working loop

For each change: reproduce a user-visible failure or name a gate; freeze the
case before tuning; change one responsible seam; run the targeted runtime case
and relevant cross-capability controls; record passes and failures; update the
scorecard and plan; commit only the intended files. Preserve counterexamples
and user-owned workspace state. At checkpoints, compare qualitatively with a
strong instruction model on task breadth, paraphrase and compound requests,
completeness, dialogue continuity, and repair. Use the comparison to locate
gaps, not to claim parity.

## Immediate next action

The clean-process dialogue and reasoning regressions pass, and the current
recombination packet again transfers across its three synthetic routes. Build
the next frozen packet from independently authored ordinary-chat tasks over
source-backed material. Vary request structure, evidence layout, and entity
disambiguation; include partial, unsupported, conflicting, and multi-source
comparison cases, with an independent answer checker. Start with composed
reasoning/procedure tasks through the CLI and copied model. Keep the current
dialogue, cycle, and integrity controls as release gates. Continue source-rule
quality work in parallel, and keep derived write-back review-gated until
recombination and correction pass on held-out tasks.

For detailed implementation history and experiment evidence, see
[`focused_roadmap_to_goal.md`](focused_roadmap_to_goal.md) and
[`current_development_plan.md`](current_development_plan.md).
