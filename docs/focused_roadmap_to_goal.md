# Focused roadmap from the current CRMS to its goal

**Reviewed:** 2026-10-20
**Status:** execution plan; the capability goal remains unmet.

## Destination

CRMS aims to be a lightweight, distributable language system that can handle
broad ordinary requests, continue across turns, combine learned knowledge and
procedures, reason over evidence, and improve from use. Its answers and
artifacts must remain inspectable and correctable, with clear limits on what is
known, inferred, uncertain, or unsupported. Coding, math, translation,
creative work, and other domains should use the same natural-language
interface. Strong 70B-class models are a reference for task breadth and
interaction quality, not a parity claim or a required live comparator.

## Where the project is now

CRMS has substantial foundations: searchable source text, provenance-bearing
knowledge and procedures, review-gated learning, bounded proof-checked
reasoning, contextual dialogue state, and a portable SQLite model format.
Controlled end-to-end slices show that source-backed rules can be accepted,
held-out checked, recombined into procedures, used in chat, and carried into a
copied model. Reasoning also has controlled paths through chat, independent
proof verification, correction, and invalidation of derived results.

The missing evidence is generalization across the complete user path. Current
successes rely on small or synthetic fixtures, hand-coded extraction/mapping,
Codex-provided labels, and deliberately orchestrated experiments. The latest
arXiv audit found 8 full papers among 1,697 records and no useful procedure
candidates in those papers; that index is unsuitable for the tested grammar,
not evidence against academic sources in general. A read-only scan of 415
NumPy and 100 pandas callable API docstrings now shows the grammar can find
candidate material in relevant reference text, but its 327 candidate spans
are not yet useful-rule evidence: repeated boilerplate dominates, and a
source replay exposed lost subject and condition information. The source
learning route has corpus-fit evidence but still needs labeled proposal and
non-proposal review, better role/context preservation, and a frozen,
source-disjoint transfer test.
Dialogue has targeted fixes for topic switches, source-only context, and
pronoun grounding, but its independent transfer results remain weak and do
not establish reliable conversation. Recombination and reasoning work, but
not yet as a broadly learned capability. Self-learning by write-back is
designed and partly prototyped, but must remain governed until independent
verification and correction propagation are demonstrated together.

**Assessment:** the architecture is pointed toward the goal; the capability
claim is not yet earned. The next work should improve held-out chat outcomes,
not increase experiment, corpus, or feature counts by themselves.

## Execution principles

1. Measure complete tasks through ordinary chat and a fresh process. Keep
   answer quality, evidence/proof validity, abstention, clarification,
   task completion, runtime, and storage as separate measures.
2. Freeze test material before tuning. Split by source document, publisher, or
   complete conversation as appropriate. Keep negative cases and known
   failures as permanent controls.
3. Treat intent as contextual and revisable. It may route, clarify, and repair;
   it cannot add facts or authorize unsupported actions.
4. Keep Codex labels and teacher examples explicit. They are supervision, not
   independent validation. Preserve citations, labels, review decisions, and
   correction lineage.
5. Recombination, self-learning rules, reasoning, and dialogue remain the
   central work. Add domains or storage features only when they clear a gate
   below or address a measured user-facing failure.

## Focused path

Dialogue evaluation runs alongside the capability path and is a release gate
for every chat-facing change. Source-derived rule transfer is a research
track; recombination can proceed using independently reviewed components.
Only dependent capability gates are sequential: a failed gate calls for
redesign of that mechanism before widening its scope.

### 1. Lock the shared chat evaluation and dialogue safety baseline

Preserve the current targeted regressions for topic switching, source-only
answers, paragraph/entity grounding, unanswered turns, stale `why?`, history,
ordinal references, corrections, and save/reload. Add a compact set of
independently authored multi-turn transcripts with varied paragraph layouts,
competing entities, and follow-up wording. Include the reported Eiffel
Tower/Colosseum sequence and “and Italy?” after source-only evidence. Score
wrong referents, irrelevant evidence, correct resolution, clarification,
abstention, omission, and task completion separately. Keep intent label
agreement separate from task success.

**Exit:** fixed regressions pass in clean processes; the held-out set has no
confident wrong referent; unresolved context leads to a focused clarification
or abstention; every factual answer is supported by the evidence shown. If the
gate fails, fix context lifetime and source/entity grounding before adding
intent classes or learned dialogue moves.

The latest roughly 30-turn Rome/Paris drive is a small diagnostic, not a
transfer benchmark. It confirmed useful follow-ups, named topic changes,
source citations, and abstention, but found a high-severity wrong answer:
after switching from the Eiffel Tower to the Colosseum, “when was it
completed?” selected the Eiffel Tower's 1889 sentence because both paragraphs
used “It”. It also found that source-only answers lose usable context, failed
turns clear all referents, and a later “why?” can explain an older answer.
“What did I just ask?” and “the first one” remain unsupported. The immediate
dialogue task is therefore a full-turn regression packet for topic changes,
paragraph/entity grounding, source-only continuity, failed turns, explanation
anchoring, history, and ordinal references. Require a unique paragraph or
explicit entity link before resolving a pronoun-led sentence; if none exists,
ask which entity the user means. Preserve typed visible context through
recoverable source-only answers and abstentions, and make each explanation
refer to the answer from the immediately relevant turn. Treat the submitted
code-review observations (large `turn()` and `_resolve_pronoun`, duplicated
candidate gathering, brittle persisted referents) as simplification targets
only after these behaviors are locked by end-to-end tests.

### 2. Establish whether source-derived rules transfer

Use complete technical references or another corpus that contains enough
instances of the target construction. Do not use the current arXiv index as a
positive set for the tested “subject will predicate” grammar. Freeze the
candidate method before labeling; split discovery and holdout by document and
publisher. Label both proposals and sampled non-proposals. Include role
reversals, negation, quotation, contrast, conditions, scope, and misleading
near misses. Keep each candidate cited, review-only, and unable to alter the
rule store until accepted through existing gates. Record labeler identity,
teacher effort, precision, useful yield, missed cases, and review burden.

The `v1_474` audit establishes candidate yield in two installed API-reference
collections: NumPy produced 303 candidates from 13,391 sentences, and pandas
produced 24 from 5,384. This is corpus fit, not precision or transfer. A
source-backed `/suggest-procedure-phrases` replay hid the candidate subject;
review of its cited `numpy.add` sentence showed the candidate had dropped
`out` and the conditional location. Repeated NumPy boilerplate accounts for
168 of its candidates, and the spot-check found other incomplete spans around
qualifiers and inline code. Preserve these as failure cases. Before changing
the frozen grammar, review a fixed sample of proposals and non-proposals and
decide whether its current representation can retain a usable, licensed
operation claim. If not, redesign role, condition, and markup extraction as a
general boundary model, then reserve new documents for confirmation.

That review is now done in `v1_475`: in a deterministic but non-probability
sample from the same two package corpora, all 20 candidate field sets needed
their source sentences to restore a role, condition, qualifier, contrast, or
markup boundary; all 20 sampled no-candidate sentences described plausible
API behavior outside the current subject grammar. This is unblinded Codex
error analysis, not a precision/recall estimate, and the source-cited review
path still prevents these candidates from becoming accepted knowledge. Keep
these cases as development controls; the current clause-aware redesign is
described below, and confirmation must use untouched API units and a new
publisher.

The clause-aware redesign is now implemented as a review-only proposal path
and exercised by `v1_476`. Its 19 cited fixtures cover full subjects,
conditions, contrast, list items, parenthesized values, literals, polarity,
quotation, denial, uncertainty, one-word predicates, and a fresh chat replay;
candidates remain review-only. The full-package replay `v1_477` finds 657
candidate sentences across 250 NumPy API units and 216 candidate sentences /
217 proposals across 60 pandas units, compared with 303/177 and 24/16 in
`v1_474`; NumPy has 279 normalized candidate patterns. A re-run of six
topic-switch, source-only,
paragraph-grounding, multi-turn, cross-paragraph, and unsupported-switch
dialogue controls passed 6/6; this is regression coverage, not dialogue
transfer evidence. The source counts are yield only: the replay
still exposes malformed boundaries in complex parameter and conditional
prose, and the frozen sample was used during redesign. Do not call the yield
increase improved precision or transfer. The current `v1_478` review selected
ten candidates and ten non-candidates per package, with exact citations and
sentence hashes. Codex marked 10/20 candidate field sets structurally
reviewable, 5/20 context-dependent, and 5/20 boundary errors. Of 20 sampled
non-candidates, 14 appeared to state behavior that needs context, shared-
subject recovery, or broader clause structure; six were fragments or not
behavior claims. This is an unblinded, single-rater diagnostic from the same
corpora used during parser development, not a precision/recall estimate or
independent validation. See [`v1_478 report`](../experiments/reports/v1_478_api_candidate_boundary_review.json).

The next learner task is context-aware claim assembly: use complete source-unit
structure to resolve omitted or shared subjects and antecedents, retain
separate citations for each supporting span, and abstain when the source does
not determine a unique claim. Develop against the frozen sample, then freeze
the method and measure proposal quality and missed claims on untouched API
units and a new publisher. Keep candidates review-only throughout.

The first narrow runtime slice is now exercised by
`experiments/v1_479_contextual_procedure_candidates.py`. It covers two omitted
subjects recovered from nearby parameter headings and two simple coordinated
predicates with shared subjects. Source and context citations are checked
separately; stale section context and context-free missing subjects abstain;
the fresh chat path keeps the proposals review-only. The 19-fixture
`v1_476` source controls and nine selected source/dialogue regressions also
pass on this checkout. This only validates the named cases and compatibility
controls: four hand-selected contextual examples do not establish proposal
precision, recall, or transfer. The next step is to freeze this implementation
and measure it on untouched API units and a new publisher, reviewing both
proposals and non-proposals.

The exploratory third-source scan `v1_480` now applies the frozen proposal
path to scikit-learn 1.9.0 callable docstrings from six API modules. Among 209
canonical units it found 342 sentences containing `will`; 327 were handled by
the local parser and 15 by parameter-heading context, yielding 343 proposals
and no abstentions in that deliberately narrow sentence universe. A
deterministic one-per-unit sample reviewed 12 candidates: six were structurally
reviewable from the cited text, three needed unresolved source context, and
three had boundary errors. These are diagnostic counts, not a precision
estimate: the corpus was inspected before the sample was frozen, the review is
single-rater and unblinded, and docstrings are not full documentation pages.
The corpus is now development data, not a future holdout. The next valid
transfer test must use a publisher not yet inspected, freeze its documents and
sample before review, and include independently selected proposal and
non-proposal cases. See [`v1_480 report`](../experiments/reports/v1_480_sklearn_procedure_candidate_review.json).

The PyTorch 2.13.0 sample was then frozen before review in `v1_481`, on a
corpus fingerprint distinct from the NumPy/pandas/scikit-learn development
material. It covers 251 callable API units from four modules; among 320
`will`-sentences, the current route returned 301 proposals (297 direct, 4
parameter-context) and abstained on 19. The sample contains 20 candidate and
all 19 non-candidate sentences, selected by hash with at most one row per API
unit. In the recorded Codex review (`v1_482`), six candidate rows were
structurally reviewable, two needed context, and twelve had boundary errors.
Of the 19 no-candidate rows, 18 stated behavior that the current path missed
(17 conditional and one shared-subject case); one was an incomplete fragment.
These are labeled row counts from one unblinded reviewer, not accuracy or
precision estimates; the non-candidate sample also contains repeated API
boilerplate. Still, the boundary errors and missed claims are concrete
counterexamples to treating the implementation as transferred. No parser
change was made against the frozen sample, and source discovery was not routed
through chat for this corpus, so the full learning/review/chat gate remains
open. Keep the PyTorch rows as development controls from now on. Redesign the
general clause/context representation using these controls, then freeze a
different publisher and a new sample before the next transfer evaluation.
See [`v1_481 manifest`](../experiments/reports/v1_481_torch_publisher_transfer_manifest.json)
and [`v1_482 review`](../experiments/reports/v1_482_torch_transfer_review.json).

The same PyTorch corpus exposed a chat-level natural-language error: “When
does an LSTM use projections?” was classified as a calendar-date question and
rejected for lacking a year, despite a cited condition in the source. The
quoted-evidence gate now accepts explicit date, time, or condition cues for
`when` questions and rejects a same-entity sentence with no such cue.
`v1_483_when_condition_evidence_gate.py` passes direct positive/negative
checks and a fresh-process replay; the answer is still labeled as quoted
evidence, not an accepted fact. This repairs one question-type boundary, not
general paraphrase understanding or source-derived learning. The other
source-only yes/no question in the same probe still abstains and remains an
open natural-language coverage gap.

The follow-up `v1_484_coordinated_clause_subjects.py` addresses one PyTorch
API-source boundary from that review: in the Adam parameter description,
“the algorithm will not accumulate weight decay …” follows another finite
clause joined by `and`. The candidate parser now isolates the explicit later
subject, keeps negative polarity and the `if True` condition, and shows the
cited result in fresh chat without installing a rule. A regression caught an
over-split of “shape and buffer length … but the type …”; the splitter was
narrowed to require an explicit new subject, and both cases now pass. This is
one structural source-learning improvement, not resolution of “the algorithm”
to Adam in a user yes/no question. That source-only polarity route still needs
an independently checked subject/context binding and conflict behavior.

`v1_485_conditioned_api_polar_evidence.py` adds a narrow source-only yes/no
route for this API case. It binds a generic source subject such as “the
algorithm” to a uniquely named API title only when the user states the same
explicit true/enabled parameter condition. The reply quotes the exact cited
sentence and remains review-only; missing or mismatched conditions and
duplicate matching API titles abstain. Its fresh-process replay initially
exposed a crash when this route created candidates while `turn.research` was
absent; that path now initializes the review result before attaching them.
The chat regression, source-grounded positive/negative flow, open-world polar
questions, and six selected dialogue controls pass. The older polar tests
needed alignment with current reply wording and a repeated query after review
acceptance. This closes one state-dependent crash and one explicit-condition
coverage gap; it does not show general source-subject resolution or publisher
transfer. Keep the matcher narrow and review-only until independent subject
binding and source-conflict behavior are measured.

The SciPy 1.18.0 installed API docstrings provide an adjacent corpus-fit check
in `v1_486`. The frozen method scanned 2,038 public callable/class docstrings
(65,660 sentence spans) and found 1,805 sentences containing `will`; it
proposed on 1,665 of those, while a hash-selected sample of 20 proposed field
sets had 0 promotion-ready without review. A separate, text-deduplicated
sample of 20 unhandled sentences contained 13 plausible behavior/property
claims. These are one-rater sample observations, not precision/recall or a
publisher-level transfer result. They show the current grammar is both too
permissive and misses common claims; candidate count is not useful yield. Keep
SciPy as a development corpus and redesign claim boundaries, role binding,
conditions, and clause scope against the frozen diagnostics before testing a
new publisher. The script and cited sample are
[`v1_486 audit`](../experiments/audits/v1_486_scipy_will_claim_fit.py) and
[`v1_486 report`](../experiments/reports/v1_486_scipy_will_claim_fit.json).

An optional spaCy dependency-parser proposal path was then prototyped against
the same frozen SciPy development sample in `v1_487`. It produced candidates
for 19/20 previously proposed rows and 11/20 sampled non-proposal rows; the
single-rater review initially found four structurally coherent rows. A
development-only refinement then stripped Markdown delimiters for parsing
while preserving source offsets, recovered several explicit leading
conditions, and improved the reviewed result to 11/20 structurally coherent
candidate rows; seven of 20 sampled non-proposal rows still gained plausible
behavior candidates. The same review also prompted a small production fix:
“not well defined which …” and “as though/as if” now mark embedded claims as
uncertain, so they cannot be rendered as ordinary positive evidence. The
refined parser still misbinds some inline-code subjects, fragments, contrast,
ellipsis, and metadata. This remains an exploratory comparison on development
data, not transfer evidence; the parser and model are optional and are not
wired into CRMS. Keep both methods as development baselines, and only continue
with dependency parsing if a revised representation reduces review burden
while preserving positive, negative, conditional, uncertainty, and
malformed-boundary controls. See the
[`v1_487 prototype`](../experiments/audits/v1_487_spacy_dependency_prototype.py)
and [`v1_487 report`](../experiments/reports/v1_487_spacy_dependency_prototype.json).

The refined method was then frozen at commit `65b151c` and applied to the
installed Pydantic 2.13.4 package in `v1_489`, before inspecting its selected
rows. The corpus contains 685 public callable/class docstrings, 3,402 sentence
spans, and 184 sentences with `will`; the method proposed on 176 and missed 8.
In the hash-selected proposal sample, Codex labeled 3/20 structurally usable
from the sentence alone, 11/20 as needing cited context, and 6/20 as boundary
errors. Of the eight non-proposals, five appeared to state behavior, two
needed context, and one was not a target claim. This is a single-rater,
package-docstring diagnostic, not a precision/recall estimate or complete
publisher-document test. It shows that context preservation is now the main
loss for this parser, while boundary errors remain. Keep Pydantic as
development data; redesign candidate records to keep claim, antecedent,
parameter heading, and condition spans separately cited, then freeze a new
package before testing that design. See the [`v1_489 audit`](../experiments/audits/v1_489_pydantic_dependency_transfer.py)
and [`v1_489 report`](../experiments/reports/v1_489_pydantic_dependency_transfer.json).

The follow-up `v1_490` context-bundle probe attaches the nearest paragraph or
bounded source windows, adjacent same-paragraph sentences, and API-unit
identity as separate fields. All source text spans were verified against the
Pydantic docstring hash and exact character offsets. In a single-Codex review
of the same 11 rows previously labeled context-needed, three bundles added a
cited antecedent or condition, three showed the anchor sentence already
contained enough subject context, three supplied only package-symbol metadata,
and two remained unresolved. This small, reused development sample does not
measure transfer or extraction quality; it demonstrates that context can help
selectively and must not be treated as a blanket repair. The next learner
checkpoint should keep candidate structure and contextual evidence separate,
and test whether reviewers can recover a correct claim without relying on
uncited API identity. See the [`v1_490 audit`](../experiments/audits/v1_490_pydantic_context_bundle.py)
and [`v1_490 report`](../experiments/reports/v1_490_pydantic_context_bundle.json).

Use the existing excerpt and real-source acceptance experiments as regression
controls, not as a corpus-level result. If a suitable corpus does not contain
enough examples, change the learning signal or narrow the claim; do not add
phrase-specific rules to make the study pass.

**Exit:** the frozen method produces useful, source-supported proposals on
held-out documents and a held-out publisher, with negative controls measured
and review effort reported. If it fails, redesign candidate discovery before
promoting autonomous rule learning.

### 3. Prove recombination through reasoning in ordinary chat

This is the main capability milestone. Learn or accept components separately,
then ask a genuinely unseen multi-step request in ordinary language. Route it
through retrieval, rule/procedure selection, reasoning, and the appropriate
proof or task-specific checker. Run it after fresh-process reload. Keep source
evidence, learned components, connective supervision, derived rule, proof, and
output validator distinct in provenance. Exercise changed wording, values,
and operation order, plus unsupported operations, missing steps, explicit
negatives, conflicts, cycles/integrity failures, and search limits.

**Exit:** at least one source-disjoint composition succeeds through chat and
reload; an independent checker accepts valid results and rejects invalid
ones; incomplete, contradictory, or unsupported requests do not produce a
confident positive. Report which steps were learned, hand-coded, or labeled.
If only the experiment orchestrator can compose the steps, the gate remains
open.

### 4. Close the self-learning loop under correction controls

Only after phase 3, enable derived outputs as proposals: retrieve → compose →
verify independently → propose with lineage. Keep derived knowledge separate
from taught/source-backed knowledge and lower-trust until revalidated. Test
source and rule corrections, dependent-case invalidation, conflicts, duplicate
suppression, retrieval weighting, abstention on invalid lineage, and storage
growth. A derived result must never validate its own generating rule.

**Exit:** correcting a source or rule identifies and disables all affected
derivations until they pass verification again; no invalid or incomplete proof
can be reused; growth and trust policies have measured limits. Until then,
write-back remains review-gated rather than automatic.

### 5. Validate dialogue intent and moves against task outcomes

Model user intent as a contextual hypothesis over the utterance and explicit,
bounded discourse state: active task/subgoal, current topic and referents,
open question or choice, previous move, and unresolved ambiguity. Compare it
with the explicit baseline on held-out conversations, including the same
utterance under different contexts. Continue the dialogue-move research as a
separate experiment: cited corpus examples and Codex labels can suggest frames,
but the context and product-policy gates must remain explicit.

**Exit:** contextual intent improves held-out task completion without raising
wrong referents, stale context, or inappropriate moves. Learned dialogue
moves enter runtime only if they improve the explicit baseline on held-out
outcomes; label agreement alone is insufficient.

### 6. Expand task breadth one validated slice at a time

Use the same natural-language interface for one bounded task at a time in
coding, math, translation, and creative work. Choose the first task from
measured user-facing failures. Define held-out requests, negative cases,
independent validation, evidence policy, and repair behavior before
implementation. Validate each domain alone before cross-domain compositions;
evaluate creative coherence and constraint-following separately from factual
grounding.

**Exit:** each slice reports held-out coverage, correct and wrong results,
abstentions, completeness, provenance, repair success, and cost through chat.
Do not infer domain breadth from a single worked example or component pass.

### 7. Verify the distributable model as the complete runtime

When record and correction lifecycles are stable, package searchable source
text, accepted knowledge, rules/procedures, and provenance in the SQLite model.
Copy it to a clean location with original source files unavailable. Query it,
inspect citations, learn and correct through supported paths, save/reload, and
rerun the shared scorecard using the copy alone. Record size, compatibility,
migration behavior, and unsupported cases.

**Exit:** the copied model supports the tested chat, retrieval, learning,
reasoning, correction, and reload paths without original files. Keep source
acquisition and licensing metadata with imported documents, including
academic-paper sources.

## Immediate sequence

The project is architecturally aligned, but it is not yet on track to claim
broad capability: success still depends on controlled examples, hand-coded
routes, and supervised labels. The near-term objective is to move the existing
proof-filter/procedure slice from a narrow demonstration toward transferable
task completion, while keeping dialogue safety in the release path. Source
rule discovery proceeds as a separate research lane; it must not block
recombination with already reviewed components.

### Next execution card

This is the order for the next development cycle, based on the current checkout
(`68b3214`) and the latest dialogue and recombination findings. It deliberately
starts by checking current behavior: reports describe earlier commits, and a
regression already fixed in the current tree should not trigger duplicate code.

| Order | Work | Concrete output | Advance when |
| --- | --- | --- | --- |
| 1 | Re-run the reported conversation failures on current code, in a fresh process. Include Eiffel Tower/Colosseum topic switching, “and Italy?” after source-only evidence, failed-turn context retention, `why?`, “what did I just ask?”, and “the first one”. Preserve the existing uncommitted dialogue artifacts. | A frozen end-to-end transcript packet and a result report separating wrong referents, completion, clarification, abstention, omissions, and evidence support. | No confident wrong referents or stale explanations on controls; unresolved context clarifies or abstains. Any failure becomes the next small fix. |
| 2 | Broaden the proof-backed recombination slice through ordinary chat. Vary wording, entities, values, order of operations, and source layout; include at least two compositions where one inferred result feeds a later operation. Use independently authored held-out requests and an independent output/proof checker. | A frozen transfer set, task-level scorecard, and clean-process replay using separately reviewed knowledge and procedures. | More held-out tasks complete than the explicit baseline, with no increase in confident unsupported answers; invalid, conflicting, incomplete, or tampered results are rejected. |
| 3 | Add governed derivation as a proposal path on top of verified recombination. Record full proof, rule, procedure, and source lineage; test correction, retraction, stale dependencies, duplicate filtering, and an intentionally bad derivation. | A derived-case lifecycle report covering proposal, review/revalidation, write-back, reload, and invalidation. | Correcting any dependency disables or revalidates every dependent result; derived outputs cannot validate their own producing rules; growth follows a measured policy. |
| 4 | Run the source-rule learner as a separate transfer study, frozen before review on untouched units from a new publisher. Review both proposals and sampled non-proposals; retain claim and context citations. | A labeled transfer report with useful yield, false proposals, missed claims, abstentions, and teacher/review effort. | Evidence supports useful transfer without hand-coded semantic mappings. Otherwise redesign the representation or record a no-go for that learner. |
| 5 | Use the common scorecard to select one bounded task each in coding, math, translation, and creative work, after steps 1–3 establish a stable chat and recombination baseline. | For each selected task: held-out prompts, a validator independent of generation, ordinary-chat and repair results, and a portability check. | Each task shows useful completion, valid outputs, honest limits, and repair on unseen examples before scope expands. |
| 6 | Exercise the SQLite model as the complete distributable runtime after the preceding learning paths stabilize. | A clean copied model with source files unavailable, replaying query, learn, compose, reason, explain, correct, save/reload, and the shared scorecard. | Behavior, provenance, searchable source text, and correction lineage survive from the copy alone; size and compatibility are documented. |

**Current checkpoint (2026-10-20):** the fixed multi-turn regression packet
passes 8/8, including the reported topic switch, source-only continuity,
history, ordinal selection, and follow-ups after abstention. These are targeted
controls, not independently authored transfer evidence. The latest recombination
slice now passes seven requests across four bounded frames, including an
“after removing” construction. It converts that gerund only when the existing
procedure learner accepts the resulting taught operation sequence, and shows
the mapping in the answer. This improves one compositional language seam; broad
paraphrase, task planning, and transfer remain unproven.

Dialogue intent and multi-turn safety are evaluated in every chat-facing step,
not deferred to step 5. Research into induced dialogue moves may proceed
alongside the baseline, but it advances only if it improves held-out task
outcomes over the explicit dialogue baseline without increasing wrong
referents or unsupported claims. The source-rule study can also proceed in
parallel; it is not a prerequisite for recombination from reviewed components.

The highest-priority implementation loop is therefore **step 1, then step 2**.
Do not add more parser branches, domains, or self-write behavior until the
corresponding failure set and gate are fixed. Preserve experiment outputs and
user-owned working files; commit only authored plan or code paths.

### Milestone 1 — Freeze one end-to-end scorecard and verify current failures

Build a small, versioned packet of ordinary chat tasks covering (a) the
reported Eiffel Tower/Colosseum topic switch, source-only follow-ups, failed
turns, `why?`, history and ordinal references; (b) relation proofs combined
with learned procedures; and (c) negative, incomplete, conflicting, cyclic,
and unsupported cases. Re-run the reported failures against a clean current
process before changing code, because later commits may already have fixed
some. Record task completion, wrong answers, omissions, clarification,
abstention, proof validity, evidence validity, latency, and reload behavior as
separate measures. Keep development cases out of the frozen transfer set.

**Gate:** all fixed safety controls pass; ambiguous referents clarify or
abstain; every answer is supported by the shown evidence or a verified proof.
If this fails, repair the smallest dialogue or answer-routing seam and rerun
the whole packet.

### Milestone 2 — Make proof-backed recombination transfer through chat

Extend `v1_491` from one exact request shape into a small set of user-written
tasks with changed entities, values, wording, and operation order. Keep the
learned procedures and knowledge components independently sourced or reviewed
and label every supervision step. Exercise at least two composition shapes,
including proof-based selection followed by a procedure and a multi-step
reasoning conclusion used by a later operation. Include missing premises,
explicit negatives, conflicts, cycles/integrity violations, unsupported
operations, and search limits. Run through ordinary chat, a new process, and
the copied model once its serialization path is exercised.

The integrated `v1_492` probe now covers four request frames across six cases
through fresh-process chat. An interleaved-duplicate input confirms `reverse
then deduplicate` differs from `deduplicate then reverse`; both target
sequences are composed from separately learned primitives and other ordered
examples rather than taught directly. A source-cited, Codex-taught
fact-pattern alignment also lets `Nia can reach` use the stored `reaches`
relation, with exact citations shown in the answer and `why?`; a single-
document alignment and an unlicensed phrase both abstain.
Proof gates and evidence lineage remain intact. These synthetic fixtures and
Codex-taught phrase/connective examples do not establish independent semantic
transfer. Continue with frozen, independently reviewed tasks rather than
treating these controls as a completed recombination milestone.

**Gate:** frozen held-out requests complete through chat; an independent
checker accepts valid outputs and rejects tampered or invalid ones; unknown,
conflicting, or incomplete inputs never become confident positives. Report
coverage and abstention as well as accuracy. If only a test harness can
coordinate the parts, this gate is still open.

### Milestone 3 — Turn verified outputs into governed learning proposals

After the recombination gate, let successful outputs create *proposals* with
complete source, rule, proof, and procedure lineage. Keep proposals separate
from taught knowledge and require review or independent revalidation before
they influence ordinary retrieval. Test correction and retraction propagation,
invalidated ancestors, duplicate suppression, trust weighting, stale-lineage
abstention, and storage growth. Include a deliberately injected bad derivation
and show it cannot validate itself or amplify through repeated use.

**Gate:** correcting any dependency identifies and disables every affected
derived result until revalidated; invalid or incomplete proofs cannot be
reused; growth stays within an explicit policy. Until then, write-back remains
review-gated.

### Milestone 4 — Make dialogue and contextual intent reliable enough to use

Treat dialogue as both a priority research area and a release gate for changes
to chat. First stabilize referent grounding, context lifetime, topic changes,
history, clarification, repair, and task/subgoal tracking on complete held-out
conversations. Compare contextual intent with the explicit baseline on task
outcomes, not label agreement alone. In a separate scoped pilot, test cited,
context-licensed dialogue moves against the scripted baseline; retain them only
if they improve appropriate task completion without increasing wrong
referents, unsupported claims, or inappropriate actions.

The `v1_493` runtime probe fixes coordinated follow-ups (“and when …?” / “and
how …?”) after visible source-only answers. `v1_494` then fixes a narrower
compound case: a pronoun in the second WH clause binds to the one entity named
in the same utterance, even after a topic change; two possible local entities
cause clarification. Both retain cited evidence. These are explicit
regressions, not dialogue transfer: questions whose clauses need separate
source sentences and lexical paraphrases such as “constructed” for “built”
remain open.

`v1_495` now covers the separate-sentence case for two or three WH clauses
joined by “and”. It returns exact source quotations per clause, revalidates
both on `why?`, abstains when any requested part lacks evidence, and rejects
pronoun-ambiguous compound requests before decomposition. This closes one
runtime gap, but remains a bounded parser over authored fixtures rather than
general multi-part understanding; evaluate independently authored compounds
and varied source layouts before widening the parser.

**Gate:** unseen conversations complete more tasks than the baseline without
more confident errors; ambiguous or unsupported turns recover through a
focused question or honest abstention. If learned moves do not improve the
baseline, keep the simpler handlers and record the result.

### Milestone 5 — Establish source-derived rule transfer, then widen domains

Continue the clause/context-aware source learner as a bounded research lane.
Freeze its method, candidate and non-candidate samples, and evaluation before
testing untouched API units from a new publisher. Measure reviewed useful
claims, false proposals, missed claims, abstentions, and review effort; retain
separate citations for claim and context. Do not let increasing candidate
yield count as learning progress. In parallel, use the shared scorecard to
select one bounded coding, math, translation, or creative task and test it
through the same natural-language interface, including recombination with
knowledge or procedures where appropriate.

**Gate:** extracted rules preserve roles, conditions, polarity, and evidence
on the frozen transfer set. Each new domain shows held-out task completion,
independent output validation, honest abstention, and repair behavior before
another domain is added.

### Milestone 6 — Validate the portable model as the whole product

When learning and correction lifecycles are stable, copy the SQLite model to a
clean location with original sources unavailable. Query, learn, compose,
reason, explain, correct, save/reload, and rerun the shared scorecard from the
copy alone. Verify searchable source text, accepted knowledge, procedures,
provenance, and licensing metadata survive distribution; measure size,
compatibility, migration, and runtime.

**Gate:** tested behavior depends only on the copied model and runtime, and
corrections and evidence remain inspectable after reload.

### Working cadence

Keep the next implementation loop narrow: **reproduce a failure → add it to
the frozen controls → change one seam → run targeted and cross-domain runtime
checks → update the baseline and roadmap → commit**. At each milestone, review
the qualitative 70B-class comparison in terms of task breadth, handling of
paraphrase and compound requests, completeness, dialogue continuity, and
repair. The comparison identifies user-visible gaps; it is not a parity target
or a substitute for independent correctness checks.

Do not count corpus size, new dialogue mechanisms, domain names, or storage
migrations as progress by themselves. Keep verified reasoning,
recombination, and governed self-learning on the critical path; dialogue
protects the path to those capabilities, while domain expansion tests their
generality. After every gate, ask whether held-out users can complete more of
their actual task without an increase in confident errors. Preserve failures
that disprove the current design and change the smallest part of the path that
caused them.

## Detailed references

- [Goal execution plan](goal_execution_plan.md)
- [Current development history](current_development_plan.md)
- [Benchmark baselines](benchmark_baselines.md)
- [Learning dynamics](design_learning_dynamics.md)
- [Evidence independence and transfer](design_evidence_independence_and_transfer.md)
- [Natural-language handling](design_natural_language_handling.md)
- [Contextual user intent](design_user_intent_model.md)
- [Dialogue moves](design_dialogue_moves.md)
- [SQLite memory](sqlite_memory_design.md)
- [70B-class capability comparison](capability_comparison_70b.md)
