# Master plan: CRMS to a 70B-class user experience

**Created:** 2026-10-20
**Status:** canonical execution plan. Supersedes the sequencing in
`focused_roadmap_to_goal.md`, `goal_execution_plan.md`,
`plan_from_current_to_goal.md`, and `next_steps_to_goal.md`; those remain
historical records.
**Mode:** solo developer.
**Ambition:** match the *user experience* of a 70B-class assistant for general
work, chat, coding, research, math, translation, and creative tasks, while
keeping CRMS's distinguishing contract: deterministic, evidence-first,
inspectable, correctable, CPU-only, and distributable.

"70B-class user experience" is defined operationally in §2. It does not mean
parameter parity or hidden neural inference. It means a user can bring a broad
range of ordinary requests and get a useful, appropriately hedged, inspectable
result without needing to learn CRMS's internals.

---

## 1. Decisions locked by this plan

1. **Solo development.** Every phase must fit one person. Work is sequenced, not
   parallelised across people. Research lanes run only when the critical path
   is blocked on measurement or when a lane directly feeds the current gate.
2. **Small learned components are allowed, but only as proposers.**
   A compact, offline, inspectable model may generate or rank candidates for
   language routing, paraphrase, intent, sentence selection, and retrieval.
   It may never be the source of a fact, a proof step, or an unverified answer.
   Every use must be reproducible, size-budgeted, documented, and bypassable.
   Exact checks decide acceptance.
3. **Corpus breadth is a first-class workstream.** CRMS should see the same
   *kinds* of material a general assistant is exposed to: encyclopedic text,
   books, reference documentation, code, technical manuals, academic papers,
   Q&A, news, multilingual parallel text, and structured tables. Licensing and
   provenance are part of ingestion, not an afterthought.
4. **Evaluation precedes every capability claim.** One frozen scorecard is the
   instrument of record. No feature is "done" because an experiment passes.
5. **Correctability is designed in from the start.** Every derived artifact has
   a dependency record. Corrections propagate. Derived knowledge never
   validates its generator.
6. **Self-learning is a core capability, especially rule learning.** CRMS must
   continuously propose, validate, consolidate, and retire its own rules from
   teaching, documents, corrections, usage, failures, and verified work. It is
   not a late add-on: the rule lifecycle (§5) is built alongside the task
   layer, and every phase reports learning yield, retention, and held-out
   effect. Safety is preserved by proposing before trusting, independent
   validation, source/scope discipline, and instant rollback — never by
   disabling learning.

---

## 2. Final state: the capability contract

CRMS 1.0 is done when the following hold on a frozen, independently authored
suite. Thresholds are provisional until the Phase 0 baseline, then frozen
before optimisation.

| # | Dimension | Criterion |
|---|---|---|
| 1 | General requests | ≥80% completion on ~300 ordinary tasks across 10 categories; ≥95% on the supported subset |
| 2 | Trust | ≤2% confidently wrong answers; zero on safety controls; 100% of factual answers carry resolvable evidence or a verified proof |
| 3 | Abstention | Missing, conflicting, incomplete, and unsupported cases abstain or ask a focused question; measured separately |
| 4 | Chat & context | ≥90% completion on frozen multi-turn conversations; zero wrong referents; context survives reload |
| 5 | Composition | Two or more independent held-out task families require ≥2 steps and complete through normal chat |
| 6 | Coding | Held-out beginner/intermediate tasks over a declared language subset: ≥80% correct, executable, and provenance-linked |
| 7 | Math & units | Held-out word problems, equations, and conversions: ≥80% correct with exact arithmetic and shown checks |
| 8 | Translation | For each declared pair/register: ≥80% on held-out aligned sentences with role/meaning checks |
| 9 | Research | Cited answers on held-out questions over a source-disjoint corpus: evidence validity 100%, useful completion ≥70% |
| 10 | Learning | Source-derived rules with measured precision/recall and second-publisher transfer; review-gated |
| 11 | Self-learning efficacy | Three successive learning rounds on a frozen task family improve held-out completion by ≥15% relative with zero increase in confident errors; gains plateau rather than degrade |
| 12 | Rule health | Every active rule has provenance, validation, scope, and utility; conflict/duplicate rate measured; retirement is deterministic; the whole store is auditable and bounded |
| 13 | Correctability | 100% of source/rule corrections disable or revalidate dependents within one turn and survive reload/copy |
| 14 | Distribution | A copied SQLite model passes the full scorecard with original files deleted, offline and deterministic |
| 15 | Cost | CPU-only; p95 turn <2 s at 1M facts and a 2 GB index; <4 GB RAM; packaged model <2 GB |
| 16 | Honesty | Published scorecard, failure taxonomy, and limitations accompany the release |

**Out of scope for 1.0:** frontier-level open-ended writing, arbitrary web
knowledge, real-time information, multi-user hosting, and claims of
consciousness or general reasoning. The target is a trustworthy assistant for a
broad, declared task class — not an LLM clone.

---

## 3. Current position

**Assets.** ~62k lines of deterministic Python; provenance-rich facts; learned
integer-list procedures; bounded proof-checked inference; review-gated corpus
extraction; exact math/units; frame translation; code generation over learned
procedures; portable SQLite model; 533 regression experiments.

**Gaps.**

| Gap | Evidence | Plan response |
|---|---|---|
| No shared scorecard | 533 one-off diagnostics; no comparable task metric | Phase 0 |
| Narrow language coverage | v1_540: 4/14 paraphrase probes answered | Phase 5, propose-only ranker |
| Composition is fixed regex families | `crms_task_composition.py` accepts a finite set of phrasings | Phase 2 typed task IR + planner |
| Extraction precision unknown | v1_478: 10/20 reviewable, boundary/antecedent failures | Phase 3 measured pipeline |
| Dialogue state is ad hoc | Many targeted fixes; no typed discourse model | Phase 1 |
| Correction lacks a dependency graph | Fingerprint revalidation, no reverse index | Phase 4 |
| Learning is fragmented and unmeasured | Procedures, frames, rules, and primitives each have separate ad-hoc stores; no lifecycle, registry, utility accounting, or compounding measurement | §5 rule registry, all phases |
| Domains are narrow prototypes | Phase 6 measures bounded math/code/translation/creative/cross-domain slices; wider coverage remains | Phase 6 lane plus later domain work |
| Corpus skew | Phase 7 core is measured at 69.3M words, but SimpleWiki supplies 264,924 of 268,148 documents; books, Q&A, and parallel text remain thin | Phase 7 follow-up and extended sources |
| Distribution unproven end to end | Bounded Phase 8 release gate passed; the full Phase 7 corpus is not yet packaged into one release | Phase 8 follow-up |
| Scale ceiling unknown | Phase 7 sharding works; million-fact / 2 GB p95 targets are not yet measured | Phase 8 follow-up |
| General breadth unproven | Phase 9 supported subset is 35/35, but independently authored literary breadth is 0/12 with one unsafe answer | Phase 9 follow-up |
| Human external raters missing | Phase 9 used two automated model raters; no two independent humans have rated the frozen packet | Phase 9 follow-up |
| 70B comparison is a proxy | Baseline is a hosted model with undisclosed parameter count, not a measured 70B checkpoint | Phase 9 follow-up |
| Answers are retrieved sentences | Ordinary research chat still returns quoted whole sentences; the Phase 10 `/compose` path emits composed content only from structured propositions, not arbitrary source text | Phase 10 source-to-proposition intake and chat routing |
| Rule sufficiency is only partially measured | 12 cases cover all 10 genres and 40 moves, with class/back-off/evidence diagnostics; the independent 300-prompt suite, two-corpus split, and full 10^2–10^5 scaling curve are open | Phase 10 rule-sufficiency and generalisation gates |
| LLM-guided improvement lacks human calibration | The teacher proposal loop now records model/prompt/change and accepts only on frozen no-regression; the judge is automated and uncalibrated against humans | Phase 10 human judge calibration |
| Conversation data unused | The feedback ledger is empty; rephrase-after-failure signals are not mined | Phase 10 conversation learning |
| Matching is ad-hoc regex | 851 regex call sites in 71 modules; about 85% in ten modules (`crms_chat.py` 250, `crms_knowledge.py` 143); paraphrase, reversed orientation, gaps, and form variants fail (prototype: 76% of infobox-oracle questions return no candidate) | Phase 11 pattern-matching transition |
| Pattern layer exists only as a prototype | Matcher, relation specs, spec verifier, and SQL store live in a session scratchpad, not the repository or the packaged model | Phase 11 Stage A |

---

## 4. Architecture target

```
                 ┌────────────────────────────────────────────┐
 user language → │ construction grammar + propose-only ranker │
                 └───────────────────┬────────────────────────┘
                                     ▼
                 ┌────────────────────────────────────────────┐
                 │ typed TaskRequest → bounded planner → Plan │
                 └───────────────────┬────────────────────────┘
                                     ▼
   ┌───────────┬───────────┬─────────┴─────────┬───────────┬───────────┐
   │ knowledge │ reasoning │ procedures        │ domains   │ retrieval │
   │ + review  │ + proofs  │ + composition     │ math/code │ + corpus  │
   └───────────┴───────────┴─────────┬─────────┴───────────┴───────────┘
                                     ▼
                 ┌────────────────────────────────────────────┐
                 │ independent verifier per action/plan       │
                 └───────────────────┬────────────────────────┘
                                     ▼
                 ┌────────────────────────────────────────────┐
                 │ render answer + evidence + uncertainty     │
                 │ record dependencies + correction lineage   │
                 └────────────────────────────────────────────┘
```

Four new seams: `crms_tasks.py` (typed IR), `crms_planner.py` (composition),
`crms_dependency.py` (correction graph), `crms_eval/` (measurement). Everything
else is adapted behind those seams rather than rewritten.

---

## 5. Self-learning architecture (core workstream)

Self-learning here means **explicit rule acquisition and refinement**, not
gradient training. CRMS already learns procedures, sentence frames, question
frames, morphology, relation alignments, and primitives; what is missing is one
governed lifecycle that ties those mechanisms together, measures whether
learning compounds, and lets the system improve with decreasing supervision.

### 5.1 The loop

```
observe → propose → validate → activate → monitor → consolidate / retire
   ▲                                                        │
   └──────────────────── corrections, usage, failures ──────┘
```

The loop runs continuously. Human review is a dial, not a permanent bottleneck:
every rule family starts review-gated, and earns scoped auto-acceptance only
after measured, independent evidence.

### 5.2 Rule families

| Family | Example | Risk | Default acceptance |
|---|---|---|---|
| Lexical / construction | "flip the array" → reverse | Low | Review, then scoped auto-accept |
| Morphology | `study → studied`, `quiz → quizzes` | Low | Review, then scoped auto-accept |
| Procedure | instruction → operation program | Medium | Review; auto-accept only with varied examples + holdout |
| Sentence → fact frame | "X designed Y" → designed | High | Review + source independence |
| Inference schema | parent∘parent → grandparent | High | Review + source-disjoint validation |
| Relation type | transitive, symmetric, functional | High | Explicit review only |
| Task / plan rule | request shape → plan template | Medium | Review; auto-accept after repeated success |
| Domain rule | unit ratio, translation frame, math identity, code template | Medium | Review + exact checker |
| Dialogue policy | act → route/clarify | High | Explicit review; cannot add facts |

Facts themselves are never "learned rules". A fact is evidence; a rule licenses
inference, language, or action. Only rules enter this lifecycle.

### 5.3 Rule record

Every rule is one inspectable record with:

- stable ID, family, version, scope (language pair, domain, relation, entity
  class, qualifier scope);
- human-readable statement plus machine form;
- provenance: teaching events, source citations, labeler identity, extractor
  version;
- evidence summary: distinct examples, distinct sources, source independence,
  counterexamples;
- validation record: held-out cases, oracle/verifier, result, date, bounds;
- acceptance mode (`review`, `scoped-auto`), trust level, authoriser;
- dependencies (rules, facts, schemas, procedures it relies on);
- utility: applications, successes, corrections, last used, saved work;
- status: proposed / active / contested / retired, with transition history;
- rollback: the exact prior state to restore.

Rules live in `knowledge.sqlite`/a dedicated `rules.sqlite` table set and travel
with the packaged model.

### 5.4 Lifecycle

| State | Meaning | Exit |
|---|---|---|
| Observed | Signal captured (query, failure, correction, source pattern) | Proposer emits a candidate |
| Proposed | Report-only; never affects answers | Validation or rejection |
| Validated | Passed its family's oracle and holdout gates | Activation policy |
| Active | Used at runtime, with utility tracking | Contest, retirement |
| Contested | New counterexample or conflict | Revalidation or retirement |
| Retired | Removed from use; history retained | — |

Corrections move dependent rules to `contested` immediately. A rule that cannot
be revalidated is retired, not silently kept.

### 5.5 Acceptance ladder

| Level | Behaviour | Allowed for |
|---|---|---|
| L0 | Log only | All signals |
| L1 | Report-only proposal | All rule families |
| L2 | Explicit review acceptance | Default for every family |
| L3 | Scoped auto-accept | Low/medium-risk families only, after ≥2 independent sources or ≥3 varied successes, zero counterexamples, held-out pass, bounded scope |
| L4 | Consolidate, dedupe, retire | Active rules with measured utility |

**Never auto-accepted:** facts, inference schemas mined from unlabelled prose,
relation-type declarations, safety/abstention policy, cross-scope
generalisation, anything derived only from CRMS's own output.

Auto-accept is itself a rule: versioned, reversible, logged, and disabled by
default in the packaged model until the user opts in.

### 5.6 Learning signals

| Signal | May propose | Trust |
|---|---|---|
| Explicit teaching | Any rule family | Highest |
| Accepted source claim + review | Frames, alignments, schemas | High |
| User correction / feedback | Frame, procedure, preference rules | High (negative evidence) |
| Repeated successful use | Utility, scoped generalisation | Medium |
| Ambiguity / failure | Target for active-learning question | Diagnostic |
| Verified derivation with lineage | Task/plan or procedure proposal | Proposal only |
| Corpus repetition | Extraction/inference candidates | Proposal only |

### 5.7 Anti-self-deception rules

1. An independent oracle, checker, or source-disjoint holdout decides
   validation. The generator never certifies itself.
2. A derived conclusion cannot validate the rule that produced it, directly or
   transitively.
3. Generation and validation data are separated by source, document, publisher,
   entity, or task family — never by random row split alone.
4. Counterexamples are sought before promotion, not after.
5. Rules learn from behaviour and evidence, not from their own prose.
6. Confidence scores are never presented as probabilities or as evidence.
7. Drift monitoring compares held-out task outcomes, not rule counts.
8. Every promotion is reversible in one operation.

### 5.8 Compounding measurement

Freeze task families and measure learning rounds:

- **Round 0:** baseline with no learning from the family.
- **Round N:** after 100 reviewed learning events (teachings, corrections,
  accepted source rules, validated uses).
- Evaluate on held-out tasks from the same family and on a disjoint family.

Targets:
- each round improves held-out completion or leaves it unchanged — never a
  regression in confident errors;
- three rounds produce ≥15% relative completion gain on the learning family;
- transfer to a disjoint family is reported, even when zero;
- rule store growth, duplicate rate, conflict rate, retirement rate, review
  minutes, and rollback time are reported alongside.

A rising rule count with flat held-out performance is a failure, not progress.

### 5.9 Implementation

- `crms_rule_registry.py` — rule records, lifecycle, validation records,
  utility counters, rollback, SQLite persistence.
- `crms_induction.py` — one proposer interface over existing mechanisms
  (frames, morphology, alignments, inference discovery, primitive/procedure
  discovery, plan templates).
- `crms_active_learning.py` — chooses the next question or example that best
  separates competing rules; records the answer as supervision.
- `crms_rule_audit.py` — conflict, duplicate, stale-scope, drift, and utility
  audits; `/rule-health` reports.
- Chat/API: `Review rule proposals`, `Accept rule proposal ID`,
  `Retire rule ID`, `Why is this rule active?`, `/rule-health`.
- Packaging: rule registry, validation records, and dependency edges ship in
  the model; a copied model can audit and roll back.

### 5.10 Where the project stands

Existing: procedure learning with contrastive probes; frame and morphology
alignment; rule discovery with held-out validation; primitive proposals; a
derived-case cache with revalidation; feedback and retraction; and a governed
rule registry with lifecycle, validation, scoped auto-accept gates, correction
propagation, rollback, and SQLite persistence. Learned procedures are mirrored
into the registry at commit time, use is counted, and forgetting retires the
rule.

Missing: registry integration for fact frames, inference schemas, domain rules,
and task plans; cross-mechanism conflict detection; drift measurement; and a
compounding benchmark over those families. Those are the deliverables of
§5.9, integrated from Phase 2 onward.

---

## 6. Phase plan (solo-adjusted)

Durations assume one full-time developer. Checkpoints every 6 weeks. If a gate
is missed twice, redesign the lane rather than extending it.

### Phase 0 — Instrumentation (weeks 1–4)

**Goal:** a frozen, reproducible end-to-end baseline.

Deliverables:
- `crms_eval/` package: schema, clean-process chat driver, oracles, metrics,
  report writer.
- `run_scorecard.py` with `smoke` (~40 tasks) and `full` (~300 tasks) suites;
  locked held-out split; JSON + Markdown output under
  `experiments/reports/scorecard/<date>/`.
- Task schema records provenance separately: authored, Codex-labelled,
  hand-coded, independently checked.
- Baseline run on the current checkout; known failures frozen as controls.
- CI entry point for the smoke suite; `run_experiments.py` remains the unit
  regression layer.

Oracles: exact, set, regex, must-abstain, proof verification, citation
resolution, procedure parity, and independent script.

**Gate:** baseline committed; every task has expectation, oracle, and
provenance; clean-process and reload runs reproduce; no user-owned report is
modified.

### Phase 1 — Dialogue safety gate (weeks 4–8)

**Goal:** no confident wrong referent or stale explanation.

Deliverables:
- Versioned `DiscourseState`: active task/subgoal, topic, referents with
  evidence links, QUD, open question/choice, previous move, answer under
  discussion, expiry rules.
- Turn pipeline split into act classification, referent resolution, evidence
  selection, answering, and state update, each independently testable.
- Repairs for the frozen controls: Eiffel/Colosseum switch, source-only
  continuity, stale `why?`, history, ordinal selection, compound omissions,
  Marie Curie/Einstein retrieval confusion.
- Land the in-progress dialogue controls (`v1_411`, `v1_412`).

**Gate:** zero wrong referents and zero stale explanations on controls and
independent transcripts; dialogue scorecard section green; reload preserves
state.

### Phase 2 — Recombination milestone (weeks 6–20)

**Goal:** held-out multi-step tasks through ordinary chat in two families, with
the first self-learning loop instrumented.

Deliverables:
- `crms_tasks.py`: `TaskRequest`, `Goal`, `Step`, `ActionRef`, `EvidenceRef`,
  `Check`, `Plan`, `PlanResult`; stable IDs; JSON serialization.
- `crms_planner.py`: bounded deterministic plan constructor/executor (≤6 steps)
  over a uniform action registry. Actions declare preconditions, evidence, and
  a verifier. Ambiguity or missing support abstains; no partial execution.
- `crms_rule_registry.py` v0: records for procedure and plan rules, lifecycle
  states, utility counters, rollback; wiring from the procedure learner.
- Adapters for fact lookup, inference, list procedures, math, translation,
  codegen, writing, and retrieval.
- Natural language → goal through learned request frames with typed slots.
  Explicit admin commands remain; the user path must not depend on new regexes.
- Family A: proof-selected values → learned procedure → arithmetic, with proof
  and procedure lineage.
- Family B: retrieval → reasoning → domain action (compute, convert, translate,
  write, or generate code).
- ≥30 frozen tasks per family, independent oracles, varied wording/entities/
  values/order/layout, plus missing, negative, conflicting, cyclic, tampered,
  unsupported, and partial cases.
- Chat renders the plan, each step's evidence, and verifier results; `why?`
  explains them; corrections invalidate dependents.
- Learning instrumentation: every completed task records which rules/procedures
  were used, whether they succeeded, and what would have been learned from a
  failure or correction.

**Gate:** ≥80% completion per family; zero confidently invalid results; oracles
reject tampered outputs; incomplete/conflicting cases abstain; works after
reload; harness does not choose evidence or sequence steps; rule-use records are
complete enough to compute the first compounding baseline.

**Status (2026-10-21): bounded Phase 2 gate passed.** Family A: 30/30.
Family B: 30/30 scenario tasks plus 6/6 abstention controls. Smoke: 12/12.
Zero unsafe answers in every suite. Action-level tampering tests reject altered
research and math outputs. Chat renders a plan line with step checks and
evidence; `why?` expands it. `crms_plan_log.py` and `run_compounding.py` compute
the first baseline from completed and failed plans
(`experiments/reports/phase2_compounding_baseline.json`: 8 plans, 7 answered,
6/6 Family B domains, one unsupported control). Family B remains bounded to
the six declared domain actions; general planning search and derived Family B
artifacts are later work.

### Phase 3 — Self-learning from documents (weeks 10–24, measured lane)

**Goal:** evidence that CRMS can learn useful rules — frames, alignments,
inference schemas, and procedures — from documents, with measured precision.

Deliverables:
- Freeze the clause-aware extractor; add context-aware claim boundaries:
  antecedent/subject resolution, separate claim vs. context citations,
  condition scope, role preservation, contrast/negation/uncertainty, structured
  fields and tables.
- Route all document-derived candidates through the §5 rule registry as
  `proposed` records; no candidate may affect runtime.
- Wide, licence-audited evaluation corpus: complete documents from at least
  three publishers and two genres (technical reference and prose), with seeded
  claims, sampled non-proposals, and adversarial passages.
- Review queue with citation, roles, conditions, reviewer identity, and
  time-per-claim.
- Metrics: precision, seeded recall, useful yield, false-positive taxonomy,
  review minutes per claim, source diversity, second-publisher transfer,
  proposal-to-active conversion, retention after 100 further documents.

**Gate:** ≥0.8 precision on reviewed proposals, ≥0.5 seeded recall, measurable
second-publisher transfer, ≤2 minutes review per claim. Miss twice → pivot to
curated technical documentation/manuals and stop claiming open-corpus learning.

**Status (2026-10-21): bounded Phase 3 lane passed.** Frozen clean-room corpus:
7 complete documents, 4 publisher identities, 2 genres. 16 reviewed proposals;
precision 93.8%, seeded recall 100%, 7/7 non-proposal controls, review 0.36
minutes/claim, 4/4 held-out publisher labels transferred from rules learned on
one publisher, 15/15 active rules and citations retained after 100 distractors.
Pre-review registry activation: 0. The lane is deliberately conservative and
does not claim arbitrary internet-prose precision.

### Phase 4 — Self-learning from verified work, corrections, and consolidation (weeks 16–28)

**Goal:** provable correctability, safe supervised write-back, and the first
measured compounding curve.

Deliverables:
- `crms_dependency.py`: reverse index from fact/source/rule/schema/procedure to
  derived artifacts, stored in SQLite and packaged with the model.
- Trust levels: taught > source-reviewed > derived. Taught evidence is
  authoritative on conflict.
- Correction propagation: on retract/correct/rule change, mark dependents and
  dependent rules `contested`, block reuse, revalidate through existing proof
  checkers.
- Learning from verified work: completed plans and proofs become `proposed`
  task/plan or procedure rules with lineage; never active without validation.
- Learning from corrections and failures: every correction yields a scoped
  negative example and, where identifiable, a proposed rule revision.
- `crms_active_learning.py`: when competing rules remain, ask the single
  question or example that best separates them; record the answer as
  supervision.
- Consolidation: dedupe, merge compatible rules, detect cross-mechanism
  conflicts, retire rules whose utility is zero over a measured window.
- Scoped auto-accept pilot (§5.5, L3) limited to lexical, morphology, and
  procedure families with independent evidence; off by default.
- Compounding benchmark: three learning rounds on frozen families, with
  held-out and disjoint-family transfer reported.

**Gate:** injected bad derivation cannot validate its rule; 100% correction
propagation; the compounding benchmark shows no confident-error regression and
either a measured gain or an explicit plateau diagnosis; provenance and trust
survive save, reload, and model copy; storage growth bounded.

**Status (2026-10-21): bounded Phase 4 lane passed.** Dependency index covers
source → fact → schema → derived artifact → rule → plan; correction propagation
is 100% (5/5 expected nodes contested) while an independently supported fact is
retained. An injected bad derivation leaves its rule proposed and contests the
active revision. Three compounding rounds move held-out completion from 0/12 to
12/12 with zero confident errors; the learned plan skeleton transfers to a
second family once its procedure is verified, while the disjoint family remains
at 0/4 and is diagnosed as a plateau. Provenance and trust survive save, reload,
and copied model/registry/dependency state; dependency growth is bounded by
pruning.

### Phase 5 — Language breadth and construction learning (weeks 20–40)

**Goal:** close the paraphrase cliff without increasing wrong answers, learning
constructions as rules rather than adding hand-coded frames.

Deliverables:
- Learned construction grammar: token classes, generalised slots (entity,
  predicate, number, condition, manner), clause composition (coordination,
  relative, conditional) with example lineage per production; every
  construction is a §5 rule record with scope and holdout evidence.
- Morphology expansion; irregular forms remain lexical and evidence-only.
- Propose-only ranker/intent model (decision from §1.2): offline, deterministic,
  size-budgeted, candidate generation only, always bypassable.
- Active construction learning: when a query fails, propose the smallest
  missing construction or slot and ask for the example that licenses it.
- Paraphrase suite: ~200 held-out paraphrases over 10 constructions; same
  utterance/different context; ambiguity and abstention calibration.
- Dialogue moves remain experimental until they beat the explicit baseline.

**Gate:** paraphrase coverage at least doubles baseline with no wrong-answer
increase; learned constructions beat hand-coded frames on held-out wording;
unlicensed productions abstain; new constructions enter through the registry
and can be retired without leaving dangling references.

**Status (2026-10-21): bounded Phase 5 lane passed.** Ten construction shapes
(direct, wh, relative, coordination, conditional, passive, fronted PP, manner,
comparative, purpose) are induced from teacher-marked examples, with learned
token classes and typed slots. On 200 held-out paraphrases, exact hand-coded
frames score 60/200 (30%) and learned constructions score 200/200 (100%), with
zero confident wrong answers in both. The 60 same-wording controls are 60/60 for
both systems; on 140 reworded paraphrases the exact baseline scores 0/140 and
the learned grammar 140/140. Unlicensed, malformed, single-example, and
ambiguous productions abstain. Every active construction carries 20 held-out
cases and 20 sources; retirement removes it from matching with no dangling
references and rollback restores it. Regular morphology expands while irregular
forms remain evidence-only. The ranker is bounded, deterministic, and
bypassable. A failed query asks for the smallest missing class member and is
fixed by one marked example.

### Phase 6 — Domain breadth (weeks 30–56, one slice at a time)

Each slice: held-out requests → negative cases → independent checker or rubric →
evidence policy → repair behaviour → scorecard integration.

- **Math:** typed expressions, equations, units, bounded inequalities/systems
  only when a held-out need exists; independent symbolic checks; word problems
  through the task IR.
- **Coding:** typed operation IR, contracts, multi-step composition, static
  checks and sandboxed execution; extend beyond integer lists only with
  verifiable semantics.
- **Translation:** aligned corpora, morphology/agreement, register; semantic
  role checks; round-trip as diagnostic only.
- **Creative:** constraint grammar and planner; rubric scores for constraint
  following and coherence, separate from factual grounding.
- **Cross-domain:** two-stage compositions through the same task IR.
- Every domain rule (identity, ratio, frame, template) is registered, scoped,
  validated by its domain checker, and carries utility/rollback data.

**Gate per slice:** ≥80% held-out completion, zero confident wrong outputs,
provenance present, repair demonstrated, cost reported.

**Status (2026-10-21): bounded Phase 6 lane passed.** Five slices are measured
against a frozen 90-task fixture: math (20), coding (20), translation (20),
creative (20), and cross-domain (10 two-step tasks). Every slice completed
20/20 or 10/10 with zero confident wrong outputs, all 15 negative controls
abstained, every answer carried provenance, and each slice demonstrated a
repair. Median/p95 costs were: math 0.04/0.10 ms, coding 14.48/18.53 ms,
translation 0.01/0.02 ms, creative 0.03/0.06 ms, cross-domain 0.08/0.16 ms.
The slice adds exact word problems, rational inequalities, unique 2x2 systems,
a typed list-operation code IR with static checks and sandboxed execution,
agreement-aware English->Spanish translation with registers, a constraint story
planner with an independent rubric, and two-stage task-IR plans. 47 domain rules
are active; retiring a code operation abstains and rollback restores it.
Runtime chat wiring for the expanded slices remains a follow-up.

### Phase 7 — Corpus program (weeks 18–48, continuous)

**Goal:** exposure breadth comparable in *kind* to a general assistant's
training mix, sized for a workstation.

**Inventory:** the v0 source, licence, and domain inventory is
`corpus/manifest_v0.json` (documented in `docs/corpus_manifest.md`). It is a
planning inventory; per-document manifests and licence audits precede
ingestion.

Tiered corpora:
- **Core packaged corpus (target 50–100M words, 1–2 GB compressed SQLite):**
  SimpleWiki/Wikipedia subset, public-domain books, project docs, reference
  manuals, permissively licensed code, curated Q&A, math/translation examples.
- **Extended local corpus (optional, 1–10B words):** user-supplied books,
  documentation, code repositories, academic full text where licensed.
- **Research corpus (not packaged):** web-scale text acquired under explicit
  licences and manifests.

Pipeline:
- Importers for text, markup, code, tables, PDFs, EPUB, JATS/PMC, Wikipedia
  dumps, Git repositories, Q&A exports, and parallel text.
- Deduplication (exact and near), boilerplate removal, quality filters,
  language/script detection, PII and secret filtering.
- Per-document manifest: source, retrieval date, licence, revision/hash,
  attribution, importer version.
- Sharded FTS index with on-demand page reads; no full-corpus RAM load.
- Evaluation sets built separately and never trained on.

**Gate:** a clean-room model built from the core corpus answers a broad
held-out question set with valid citations; corpus size, licence coverage,
ingestion throughput, and index latency reported.

**Status (2026-10-21): bounded Phase 7 corpus gate passed.** The measured core
has 268,148 audited documents and 69,283,305 words in eight disk-backed FTS
shards (432.9 MB extracted text; 996.4 MB index; 301.3 MB catalog). Every
accepted document has a known redistributable licence, attribution, licence
URL, retrieval date, and revision/content hash: licence coverage 1.000.
Ingestion measured 501.47 documents/s and 129,567.64 words/s. A frozen
question-level holdout of 39 positives across reference, science, math,
code/docs, and research scored 39/39 with zero confident errors, zero invalid
citations, and 39/39 target matches; 10/10 negative controls abstained. Median
latency was 315.5 ms and p95 1,034.3 ms. The scorecard ran from a temporary copy
of the corpus with the original directory hidden for the whole run, so the
model required no build inputs. Rejections are retained: 17,306 too-short
records, 2,817 non-English, 310 exact duplicates, 64 near duplicates, 92
licence-audit failures, and smaller encoding/empty/script/PII counts. The core is
still SimpleWiki-dominated; books, Q&A, and parallel text are the next corpus
increment, not a claim of 70B-class breadth.

### Phase 8 — Scale, productization, distribution (weeks 48–72)

Deliverables:
- Performance: profile canonicalizer and planner search; incremental
  canonicalization; SQLite query plans; optional sharding; caches that never
  change semantics. Targets in §2.
- Model v4: unified schema, migrations, integrity digests, dependency index,
  derived store, rule registry with lifecycle/validation/utility, licence
  metadata, read-only mode, compatibility policy for v1–v3.
- UX: natural-language-first help, actionable teaching prompts, review queue,
  correction inspector, rule-health inspector, export/import, clear uncertainty
  rendering.
- Clean-room suite: copy model, delete originals, run full scorecard, learn,
  correct, reload.

**Gate:** scorecard passes from the copied model alone; evidence, corrections,
and lineage inspectable; no original files required; size/runtime reported.

**Status (2026-10-21): bounded Phase 8 release gate passed.** A release is a
read-only directory containing a chat-compatible `model.sqlite`, a
`phase8.sqlite` metadata store, and `release.json` with file digests and
compatibility. The metadata records per-document licences, dependency lineage,
governed registry history, corrections, and integrity. `model_schema` is 4 and
the compatibility range covers package schemas 1–5; older models migrate through
`crms_phase8_model.py migrate`. The frozen clean-room scorecard passed 12/12
with zero unsafe answers. It covers source citation, a second source answer,
learned math, dialogue history, abstention, source reload, learn-a-new-math-
phrase then reload, rule-health inspection, release inspection, lineage,
corrections, and per-document licence evidence. Licence coverage was 100% over
two embedded sources; the release had six dependency nodes, five edges, one
registry rule, and one correction. Release size was 167,936 bytes (98,304 model
+ 69,632 metadata); build 0.41 s, scoring 4.27 s, median task 0.31 s, p95
0.58 s. The original release was hidden and each task used a fresh copy with no
seed source directory. Existing regression baselines remain green: smoke 12/12,
Family A 30/30, Family B 36/36, zero unsafe. This is a compact deterministic release fixture, not a
packaged copy of the 1.3 GB Phase 7 corpus; full-corpus packing, million-fact
p95, and the external v2 scorecard remain follow-ups.

### Phase 9 — External validation and release (weeks 72+)

- v2 scorecard authored outside the project; blind held-out split.
- Two independent raters for evidence validity and answer adequacy; report
  agreement.
- Qualitative 70B comparison on breadth, paraphrase, compound completion,
  continuity, repair, coding, math, research — gap analysis, not parity claim.
- Publish scorecard, failure taxonomy, limitations, and licence inventory.

**Gate:** §2 criteria met, with failures published rather than hidden.

**Status (2026-10-21): bounded external-validation lane completed; full gate
open.** The frozen fixture has 35 supported-subset tasks, 12 literary breadth
probes independently authored by `qwen3.8-flash` from public-domain excerpts,
and 10 comparison probes. The supported subset passed 35/35 with zero unsafe
answers at 0.27 s median and 0.38 s p95. The independent breadth split passed
0/12, including one confident answer where abstention was required. Ten probes
were compared blind against `qwen3.8-max`, recorded as a hosted 70B-class proxy
with undisclosed parameter count: CRMS mean adequacy 1.20 and evidence validity
1.80, proxy 2.00 and 1.80. Two automated raters agreed 0.90 on adequacy (kappa
0.75), 0.85 on evidence validity (kappa 0.51), and 0.95 on confident errors
(kappa 0.77). The raters are not human; the baseline is not a measured 70B
checkpoint; and the full ~300-task/1M-fact §2 gate remains open. The published
result is deliberately split, not collapsed into one score.

### Phase 10 — Rule-complete generation and LLM-supervised rule development (weeks 72–100, starts from the Phase 9 failure taxonomy)

**Goal:** generate clear, coherent, audience-adapted, multi-paragraph content
in a declared set of genres. Content is *composed* from cited propositions or
explicitly fictional premises, not selected as whole source sentences. No LLM,
neural student, or network dependency runs at answer time. An external offline
LLM may act as teacher, examiner, and rule proposer; CRMS induces, verifies,
versions, and owns every rule that reaches generation. Detail:
`docs/design_phase10_generation_learning.md`.

**Why now.** Phase 9 left two measured gaps: independently authored breadth
passed 0/12, and every answer is a retrieved sentence. The current story path
is five fixed templates; the request-frame path is exact-token templates; the
composer has no discourse planner, general grammar, open lexicon, clarity
rewriter, or candidate search. Those are sufficiency gaps, not a proof that
visible rules cannot generate LLM-like content.

**Scope correction.** A finite rule system can generate unbounded output. The
difference between an LLM and CRMS is not “rules versus no rules”; it is the
coverage, composition, selection, and acquisition cost of the regularities.
This phase makes rule sufficiency measurable over a declared distribution
rather than claiming either parity with every possible request or a hard
template ceiling.

**Decision amendment (needs owner sign-off before teacher-driven work).**
Decision 2 lets small learned components propose. Phase 10 extends this to an
*external, offline LLM teacher*. It may author questions, exemplars, critiques,
and data/rule/code proposals. It may never run at answer time, never be a source
of a fact, and never accept its own proposal. Every interaction records model
id, prompt digest, and artifact. No distilled neural generator is part of this
phase; rule weights, counts, and utility are explicit and inspectable.

Workstreams and deliverables:

1. **Generation contract** (`crms_generation.py`). Parse genre, audience,
   length, format, evidence policy, and clarity target. Declared genres:
   explanation, comparison, procedure, analysis, summary, argument,
   professional writing, narrative, technical note, dialogue. Unknown genres
   clarify or abstain.
2. **Content planner.** Turn the request into propositions: required content
   points, source facts with spans, proof-bearing inferences, missing
   information, and a clarify/abstain decision. It selects propositions, never
   whole source sentences.
3. **Discourse and paragraph planner.** Genre schemas and rhetorical relations
   decide move order, section allocation, topic sentences, support, examples,
   qualifications, transitions, and conclusions. Rules live in the generation
   rule store, not in one-off code branches.
4. **Sentence planner and realizer.** Build clauses from propositions; choose
   referring expressions, lexical frames, voice, aggregation, coordination, and
   subordination; realize with a feature-based construction grammar (relative
   clauses, conditionals, concession, cause, contrast, purpose, definition,
   comparison, sequence). Separate factual content tokens from function/style
   vocabulary so open-class realization does not require closed templates.
5. **Clarity, style, and revision** (`crms_clarity.py`). Define terms, keep one
   main idea per sentence, split overlong sentences, prefer active voice, add
   necessary background and examples, use signposting, remove unexplained
   jargon, keep terminology consistent, and suppress repetition, forced
   metaphor, and “LLM slop.” Style profiles cover plain, professional,
   academic, friendly, persuasive, and narrative registers.
6. **Critic and candidate search.** Generate several valid plans and
   realizations; score coverage, clause faithfulness, relation/polarity
   correctness, coherence, clarity, copy ratio, style/format/length, repetition,
   and audience fit. Choose the best; otherwise fall back to a quote, ask a
   focused question, or abstain.
7. **Rule induction from an LLM teacher** (`crms_generation_rules.py`,
   `crms_examiner.py`). The teacher generates annotated exemplars, contrast
   pairs, critiques, and rule proposals. CRMS induces move sequences,
   constructions, lexical frames, connectives, clarity edits, and critic
   weights, then keeps a proposal only if held-out quality rises, faithfulness
   holds, and controls do not regress. This is rule extraction/induction, not
   model distillation.
8. **Rule store and lifecycle** (`crms_composition_memory.py`). Schemas,
   constructions, lexicon, style profiles, judgments, and audit records live in
   SQLite with CRMS conventions. Every rule has origin, rationale, version,
   scope, utility, and rollback. Composition rules join the registry as a
   `composition` family.
9. **Evaluation and publication** (`run_phase10_eval.py`). Frozen, blind,
   independently authored tasks over at least two source-disjoint corpora;
   content coverage checklists; clarity/comprehension tests; expert and
   calibrated judge ratings; copy ratio; 70B-class comparison; failure taxonomy;
   licence inventory; limitations.
10. **Packaging and clean room.** Rules reload from SQL; a copied release
    answers identically with no teacher, network, or original files; rollback is
    one operation; corpus and rule provenance survive the copy.
11. **Generalisation and rule scaling** (`crms_generalisation.py`). Learned
    lexical classes, back-off hierarchy, report-only analogical candidates, and
    evidence-count weights. Publish a rule-scaling curve: coverage and
    confident-error rate against training examples, fact counts, and rule counts,
    with per-mechanism ablations. The curve makes the sufficiency assumption
    testable instead of asserting that a finite rule set either can or cannot
    generalise.
11. **Generalisation mechanisms** (`crms_generalisation.py`). Make rules cover
    more than they were taught, without gradient training or an answer-time
    model. What an LLM appears to generalise is largely what its training put
    in; rules can be built to reach the same regularities through four
    deterministic mechanisms, all stored in SQL and inspectable:
    - **Learned classes.** Induce word and phrase classes from corpus
      co-occurrence and from the slots rules fill (verbs taking an agent
      phrase, place nouns, month names, genres). A rule over a class covers
      members it was never taught; the hand-written verb lexicon is replaced by
      induced classes.
    - **Back-off hierarchy.** General-to-specific rule inheritance; a request
      matches the most specific applicable rule and falls back to a more
      general one. Every fallback is recorded.
    - **Analogical matching.** Nearest-example lookup over stored exemplars with
      a fixed, reproducible similarity, used to propose a rule or construction
      for a novel input. Proposal only.
    - **Evidence-count weights.** Explicit hits, misses, scope, and source
      counts rank competing rules; weights are numbers in SQL with no hidden
      state.

    A generalised rule starts `proposed`, requires counterexample search and
    source-disjoint validation before activation, records the class or back-off
    path on every use, and can be bypassed. Exact checks still decide
    acceptance. **Rule-scaling curve:** on frozen task families, plot held-out
    coverage and confident-error rate against training examples seen and against
    active rule count (about 10² to 10⁵), with each mechanism ablated on and off,
    and report coverage per training example and cost beside the §2 thresholds.

**Gate** (thresholds provisional until the baseline is frozen, then locked):
- **Faithfulness:** 100% of factual clauses resolve to a cited span; relation,
  role, number, and polarity are independently checked.
- **Trust:** ≤2% confidently wrong on a frozen, blind, independently authored
  set of ≥300 prompts over at least two corpora; zero on safety controls.
- **Content:** ≥90% required-point coverage; ≥60% of answers synthesize two or
  more facts; ≥70% are multi-sentence; every declared genre has coverage.
- **Clarity:** ≥85% comprehension on reader questions; expert clarity ≥4/5;
  ≤5% unexplained jargon; no answer relies on readability alone.
- **Composition:** mean copy ratio ≤0.4 with the metric defined as the share of
  answer tokens covered by one verbatim source run; no answer above 0.7.
- **Style and control:** ≥90% adherence to requested format, length, audience,
  and register.
- **Comparison:** ≥80% of a measured 70B-class baseline’s adequacy and ≥90% of
  its clarity on the declared genres, with no genre below 70%; gap analysis,
  not parity claim.
- **Judge validity:** human/judge agreement on ≥100 graded answers reported with
  kappa ≥0.6; judge differs from proposer; blind sets never used for tuning.
- **Rule sufficiency:** coverage matrix over genres × moves × constructions ×
  knowledge domains; unseen-combination and ablation tests; every failure
  attributed to missing rule, bad selection, missing knowledge, or evaluator
  error.
- **Generalisation:** class hierarchy and back-off published; analogical
  candidates report-only; evidence weights inspectable; rule-scaling curve
  covers fact count, rule count, and per-mechanism ablations, with confident
  errors reported separately.
- **Learning efficacy:** three teacher-assisted rule rounds give ≥15% relative
  held-out gain with no confident-error increase; teacher calls and human
  minutes are reported.
- **Generalisation:** the rule-scaling curve is published with per-mechanism
  ablations; each mechanism's held-out gain and confident-error change are
  reported; no generalised rule is active without counterexample search and
  source-disjoint validation; a plateau is diagnosed, not hidden.
- **Clean room:** copied release answers identically with no LLM, network, or
  originals; rules reload and roll back; CPU-only packaging stays within budget.

**Status (2026-10-21): bounded Phase 10 lane completed; full external gate
open.** The rule-only stack is implemented: generation contract, content
planner, discourse plan, sentence plan, construction realizer, clarity/critic,
candidate search, SQL snapshot memory, offline teacher proposal loop, clean-room
copy, CLI, `/compose` chat path, generalisation diagnostics, and frozen
evaluation. Measured bounded lane: **12/12** frozen cases
across **all 10 declared genres**, mean copy ratio **0.157**, mean **6.2**
sentences, with abstention and clarification controls. A teacher-proposed
clarity alignment was accepted with no regression; a deliberately bad sentence
cap was rejected. SQL snapshots, judgments, active selection, rollback, and
clean-room reload pass. The automated 70B-class comparison scores CRMS adequacy
**1.75/2**, clarity **1.90/2**, coverage **1.85/2**, evidence **1.85/2**, and
three confident errors versus the proxy's 2.00, 2.00, 2.00, 1.85, and six.
Open: human clarity calibration, an independently authored 300-prompt suite over
two source-disjoint corpora, and a measured 70B checkpoint. The bounded gate
report is `experiments/reports/phase10_external.json`; the full gate remains
false by construction.

### Phase 11 — Pattern-matching transition, generation layer first (weeks 100–140, staged)

**Goal:** replace ad-hoc regex and word-list matching with one structure-aware
pattern layer (tokenizer, shallow chunker, pattern language, backtracking
matcher with captures and a trace), owned by CRMS and stored as data. The
transition is staged and reversible: new layer first, old route as fallback,
old route retired one family at a time only after measured parity. **Stage A is
the generation layer**; later stages move evidence extraction, request
understanding, and knowledge extraction. Detail:
`docs/design_phase11_pattern_transition.md`.

**Why now.** Phase 10 made generation rule-complete over structured
propositions, but its source-to-proposition intake is open: ordinary research
chat still returns whole retrieved sentences. A prototype outside the repository
(session scratchpad) showed that sentence patterns with gaps, alternation,
verb forms, induced classes, and typed values can feed that intake, and that
pattern specs can be proposed by an offline teacher and accepted only by a
deterministic gate. Regex footprint today: 851 call sites in 71 modules; about
85% sit in ten modules (`crms_chat.py` 250, `crms_knowledge.py` 143,
`crms_conversation.py` 88, `crms_research.py` 37, `crms_dialogue.py` 32,
`crms_domains.py` 32, `crms_task_composition.py` 27, `crms_nl_gate.py` 28,
`crms_procedure_discovery.py` 42, `crms_corpus_program.py` 38). Generation
(`crms_generation.py`) has only 4, which is why it can move first and cheaply.

**Transition rules.**
1. **New layer first, old route as fallback.** A spec answers only when it
   matches and verifies; otherwise the request falls through unchanged.
2. **Retire only on parity.** A regex family is removed after the full
   experiment suite shows zero new failures against an unmodified baseline, the
   frozen exam sets do not regress, and the independent oracle shows no higher
   wrong-answer rate (reward rule: +1 correct, −3 wrong, 0 abstain).
3. **One family per change, reversible by registry status.** No bulk rewrite.
4. **Parameters are data.** Ranking weights, gap bounds, and thresholds live in
   SQL with origin and metrics. A learned replacement is adopted only when
   cross-validation beats the hand-set values (the prototype's learned ranker did
   not; that result is the baseline to beat).
5. **Commands and flags stay literal.** `/commands`, file paths, and CLI syntax
   are not natural language and are not migrated.
6. **No evaluation leakage.** Spec authors do not tune against a blind set; a
   blind set that influenced a change is retired and replaced.

**Stage A — generation layer (starts first).**
1. **Engine port** (`crms_patterns.py`, `crms_pattern_transforms.py`,
   `crms_relation_specs.py`, `crms_spec_verifier.py`). Tokenizer with features,
   rule-based chunker (NP/PP/VG/appositive/parenthetical), pattern language,
   matcher, derived-variant transformations with synthetic probes, relation
   specs, and the deterministic spec verifier (replay, held-out, contrast,
   verb-swap, corpus fire-rate, variant probes, non-regression).
2. **SQL store.** Extend `crms_composition_memory.py` with classes, agentive
   nouns, match specs, parameters, and an audit trail; register specs as a rule
   family in `crms_rule_registry.py` with lifecycle, utility, contest, retire,
   and rollback; include the tables in the packaged model and Phase 8 migration.
3. **Source-to-proposition intake.** Patterns turn retrieved sentences into
   propositions (subject, relation, object, source span) for the content planner,
   closing the Phase 10 gap; `/compose` accepts a topic or question and builds
   propositions from retrieved sources instead of requiring structured input.
4. **Pattern-based generation rules.** Clarity rewrite rules and critic checks
   (relation, role, number, polarity) move from regex/word lists to pattern
   rules over chunks stored in SQL.
5. **Faithfulness and verification.** Every composed clause traces to a source
   span; the spec verifier gates new specs; the closed-template check remains.
6. **Evaluation** (`run_phase11_eval.py`). Frozen Phase 10 suite (12 cases) for
   parity; a new source-intake suite built from a fresh infobox-oracle sample of
   at least 1,000 questions plus hand-authored and unanswerable controls, with
   correct/wrong/abstain and coverage reported separately.

**Stage A gate:**
- **Parity:** Phase 10 frozen suite 12/12 unchanged; mean copy ratio and clarity
  no worse; full experiment suite shows zero new failures against an
  unmodified baseline.
- **Intake precision:** wrong-answer rate on the fresh oracle sample no higher
  than the quote baseline, with coverage reported (prototype: 219 correct,
  30 wrong, 780 no-candidate of 1,029).
- **Faithfulness:** 100% of composed clauses resolve to a cited span.
- **Specs:** every accepted spec passes the verifier; every transformation has a
  passing probe; no spec shadows another (detected by the bank).
- **Footprint:** matching regexes in `crms_generation*.py` are zero (tokenising
  and string cleanup excepted); remaining sites are listed with a reason.
- **Clean room:** a copied release runs the pattern layer with no LLM, network, or
  originals; patterns, classes, and parameters reload from SQL and roll back in
  one operation.

**Later stages (each gated like Stage A).**
- **Stage B — evidence extraction:** `crms_nl_gate.py`, `crms_research.py`
  sentence selection; relation specs ahead of the gate, then retire gate regex
  families on parity.
- **Stage C — request understanding:** `crms_chat.py`, `crms_conversation.py`,
  `crms_dialogue.py`, `crms_task_composition.py`, `crms_math.py` intent and route
  families, one family per change.
- **Stage D — knowledge extraction:** `crms_knowledge.py`,
  `crms_document_learning.py`, `crms_procedure_discovery.py` extraction patterns.
- **Stage E — retirement and audit:** remove dead regex, publish the footprint
  per module, and re-run the full gate.

**Status (2026-10-22): planned; not started.** Prototype evidence, not a gate
result: eight teacher-proposed relation specs passed the verifier after three
rounds and moved a dev set from 25 to 32 correct of 35; on a fresh hand-written
blind set the full stack went from 20 to 25 correct of 34 (one wrong), and on a
fresh 1,029-question infobox-oracle sample the relation layer returned 219
correct and 30 wrong, falling to 217 and 25 with a truncated-name veto. A learned
ranker did not beat the hand-set ranking under leave-one-set-out validation
(89 correct / 5 wrong vs 73–86 / 3–7), because only 9 of 94 candidate sets had
any ranking signal; ranking constants are now SQL parameters. Known limits:
about 76% of oracle questions produce no candidate, retrieval misses and stale
or conflicting facts are not solved by patterns, the chunker is rule-based and
English-only, induced classes are noisy, specs were authored by hand, and the
hand blind sets are consumed.


---

## 7. Corpus strategy in detail

A 70B assistant is exposed to trillions of tokens. CRMS cannot store or search
that on a workstation, and does not need to: its architecture retrieves rather
than memorises. The plan therefore optimises **coverage per byte** and
**provenance**, with three tiers.

| Tier | Size | Contents | Purpose |
|---|---|---|---|
| Core | 50–100M words | Encyclopedic subset, public-domain books, project docs, reference manuals, permissive code, Q&A, parallel text | Packaged model; broad demo and scorecard |
| Extended | 1–10B words | User corpora, full documentation sets, code repositories, licensed academic text | Local power-user model |
| Research | 10B+ words | Web-scale, licence-managed, streamed into sharded indexes | Retrieval research only; never packaged |

Selection principles:
- Prefer **diverse genres** over raw volume: prose, reference, code, tables,
  dialogue, math, multilingual.
- Prefer **licensed, versioned, attributable** sources; record licence per
  document.
- Balance domains deliberately (target mixtures in the manifest) so code and
  technical documentation are not drowned by encyclopedic text.
- Keep a held-out, source-disjoint evaluation slice per domain.
- Treat corpus growth as an experiment with a measured scorecard delta, not a
  goal in itself.

---

## 8. Evaluation design

**Suite schema (JSONL).** Each task records:
- `id`, `category`, `provenance`, `notes`;
- workspace fixture (documents, facts, rules, math/translation memory);
- turns (`/source-dir`, teaching commands, questions, reload marker);
- expectations (contains, excludes, abstain, citation, proof, oracle script);
- metrics requested (completion, correctness, evidence, latency).

**Metrics.** Completion, correct, wrong, abstain, clarification, omissions,
wrong referent, evidence validity, repair, latency, reload, storage. Report
counts and rates; never collapse into one "score".

**Discipline.**
- Freeze held-out tasks before tuning; lock by content hash.
- Rotate a small private holdout to detect overfitting.
- Report authored/Codex-labelled/independent provenance separately.
- Keep every fixed failure as a permanent control.
- Re-run the smoke suite after every chat-facing change.

---

## 9. Risk register

| Risk | Trigger | Response |
|---|---|---|
| Symbolic language coverage plateaus | Phase 5 gain <25% | Expand propose-only model role (rank/route only) or narrow the declared request class |
| Extraction precision floor | Phase 3 gate missed twice | Pivot to curated manuals/reference docs |
| Planner overfits fixtures | Family B needs hand-coded steps | Redesign the action contract; do not add a third regex family |
| Benchmark overfitting | Scorecard up, external v2 flat | Rotate holdout; independent authors; publish failures |
| Corpus acquisition/licensing | Unclear reuse rights | Metadata + licence gate; drop the source |
| Scale wall | p95 turn or depth-4 search regresses | Profile, cap depth, document the ceiling |
| Solo bus factor | — | CI, runbooks, small commits, consolidated docs |
| Self-learning reward hacking / drift | Rules rise while held-out tasks stall or errors increase | Independent oracles, source-disjoint holdouts, counterexample-first promotion, drift audit, instant rollback |
| Rule-store bloat | Thousands of low-utility rules slow search and obscure provenance | Utility accounting, consolidation, retirement windows, bounded store |
| Judge self-preference | The teacher that proposes an edit also scores it, or one model grades its own wording | Separate judge and proposer, human-graded calibration slice, blind set never used for tuning, publish agreement |
| Reward hacking by abstention | Quality or correctness rises while answer rate falls | Report answered/abstained/wrong separately; wrong costs more than abstaining; abstention counted against the policy |
| Fluent unfaithful output | Composed clauses drift beyond their cited span | Closed template vocabulary, clause-level span verifier, fall back to the quote |
| Teacher knowledge leaks into facts | An LLM-proposed label or rule asserts something not in a source | Facts only from cited spans; teacher proposals carry provenance and enter as proposals |
| LLM patch regresses the system | A proposed code change fixes one failure and breaks others | Branch + full-suite diff vs unmodified baseline, human review, no auto-merge |
| Conversation privacy | Transcripts hold personal data | Local opt-in, redaction, retention limit, no export without consent |
| Overgeneralisation | A learned class or back-off rule covers cases it should not, as the region-and-country place shortening did in the prototype | Propose-only, counterexample search before activation, source-disjoint blind set, record the class/back-off path on every use, one-operation rollback |
| Regression during regex retirement | A migrated family changes behaviour in the 562-experiment suite (249 touch the chat or gate) | New layer first with fallback, one family per change, sharded full-suite diff against an unmodified baseline, reversible by registry status |
| Spec overfitting | A spec fits its development questions and fails elsewhere | Verifier replay/held-out/contrast/verb-swap/fire-rate checks, independent infobox-oracle sample, retire consumed blind sets |
| Hidden knowledge in old regex | A family encoded behaviour nobody remembers | Characterise before retiring: run the family's experiments, record its inputs and outputs as controls first |
| Rule shadowing | One spec captures questions meant for another (seen as 'Mapai established in 1930') | Bank non-regression check in the verifier; ordering and restriction tests |
| Scope creep | New feature without a gate | Reject; the 533-experiment habit is the main delivery risk |

**Kill criteria are part of the plan.** A lane that misses its gate twice is
redesigned or dropped.

---

## 10. Immediate work queue

1. **Phase 0 harness** — `crms_eval/`, `run_scorecard.py`, smoke suite,
   baseline report. — done; broaden the suite next.
2. **Freeze controls** — topic switch, source-only continuity, stale `why?`,
   history, ordinals, compound omissions, where-question wording. — in progress;
   controls exist, scorecard coverage is still partial.
3. **Land `v1_411`/`v1_412`** as dialogue controls. — `v1_412` lands; `v1_411`
   still needs teacher-labelled fixtures.
4. **RFC for `crms_tasks.py`** — types, planner bounds, action contract. — done
   (`docs/design_task_ir.md`).
5. **RFC for `crms_rule_registry.py`** — record schema, lifecycle, validation
   ladder, rollback, and how existing procedure/frame/rule stores migrate. —
   done for procedures and request frames; inference schemas and fact frames
   follow.
6. **Learning baseline** — instrument current rules/procedures with use counts
   and outcomes; measure today's compounding curve before changing it. —
   procedure and frame use counts are live; typed plan records and
   `run_compounding.py` now compute the first baseline.
7. **Family A specification** — 10 tasks + independent oracle, frozen before
   planner code. — done
   (`experiments/scorecard/family_a_spec.md`); the suite now has 30 tasks,
   including wording/entity/value variants and negative controls.
8. **Family B specification** — retrieval/reasoning/domain-action tasks through
   learned frames and typed actions. — done
   (`experiments/scorecard/family_b_spec.md`); 30 scenario tasks plus 6 controls
   cover research, math, units, translation, code generation, and writing.
9. **Phase 3 document learning** — licence-audited corpus, clause-aware
   proposals, governed review, transfer and retention metrics. — done for the
   frozen clean-room lane (`crms_document_learning.py`,
   `corpus/phase3_eval/manifest.json`,
   `experiments/reports/phase3_document_learning.json`); real-publisher
   corpus expansion and independent human review remain follow-ups.
10. **Phase 4 verified-work learning** — dependency index, trust conflict,
   correction/failure negatives, active learning, consolidation, scoped
   auto-accept policy, and three-round compounding. — done for the frozen lane
   (`crms_dependency.py`, `crms_verified_work.py`, `crms_corrections.py`,
   `crms_active_learning.py`, `crms_consolidation.py`,
   `experiments/reports/phase4_learning.json`); real user corrections and
   runtime chat integration remain follow-ups.
11. **Phase 5 construction learning** — learned token classes, typed slots, ten
   composition shapes, morphology, active construction learning, propose-only
   ranker, and a 200-paraphrase held-out suite. — done for the frozen lane
   (`crms_constructions.py`, `crms_morphology.py`,
   `crms_construction_ranker.py`, `experiments/reports/phase5_constructions.json`);
   runtime chat routing and broader open-domain constructions remain follow-ups.
12. **Phase 6 domain breadth** — math word problems/inequalities/systems,
   typed code IR with static checks and sandboxing, agreement-aware
   translation, constraint creative planning, and two-stage task-IR composition.
   — done for the frozen lane (`crms_domains.py`,
   `experiments/reports/phase6_domains.json`); runtime chat wiring and wider
   domain coverage remain follow-ups.
13. **Corpus manifest v0** — inventory of candidate sources, licences, sizes,
   and domain targets. — done
   (`corpus/manifest_v0.json`, `docs/corpus_manifest.md`,
   `experiments/v1_557_corpus_manifest.py`); 20 candidate groups, 4 documented
   exclusions, and a 94.5M-word core planning estimate.
14. **Phase 7 corpus program** — audited per-document manifests, licence
   classes, cleaning, exact/near dedup, language/script and PII filters, eight
   sharded FTS indexes, and a clean-room scored holdout. — done for the measured
   core (`crms_corpus_program.py`, `crms_phase7_benchmark.py`,
   `run_phase7_eval.py`, `experiments/reports/phase7_corpus.json`); books, Q&A,
   parallel text, and source-disjoint external validation remain follow-ups.
15. **Phase 8 release and clean room** — read-only release directory,
   licence/evidence metadata, dependency lineage, registry history, corrections,
   integrity digests, migration, release inspection commands, and a copied-model
   scorecard. — done for the bounded fixture
   (`crms_phase8_model.py`, `run_phase8_eval.py`,
   `experiments/reports/phase8_release.json`); full Phase 7 corpus packing and
   million-fact performance remain follow-ups.
16. **Phase 9 external validation** — frozen supported subset, independent
   literary breadth split, blind 70B-class comparison, two-rater agreement,
   failure taxonomy, limitations, and licence inventory. — bounded lane done
   (`run_phase9_eval.py`, `experiments/reports/phase9_external.json`); human
   raters, a measured 70B checkpoint, and the full §2 scale gate remain open.
17. **Phase 10 rule-complete generation and LLM-supervised rule development**
   — content/discourse/sentence planners, construction grammar and realizer,
   clarity/style revision, critic/search, rule induction and SQL lifecycle,
   generalisation workstream, frozen coverage/clarity/copy evaluation, and 70B
   comparison. — bounded lane complete: 12/12 cases, all 10 genres,
   teacher/SQL/clean-room/automated comparison
   (`experiments/reports/phase10_external.json`); human, independent-300,
   two-corpus, and measured-70B gates open.
18. **Phase 11 pattern-matching transition, generation layer first** — engine
   port, SQL store and registry family, source-to-proposition intake for
   `/compose`, pattern-based generation rules, spec verifier, parity gate, then
   evidence extraction, request understanding, and knowledge extraction in
   later gated stages. — planned (`docs/design_phase11_pattern_transition.md`);
   prototype evidence only.
19. **Consolidate plan docs** — this file is canonical; link the others as
   history. — canonical status recorded; remaining docs still need pruning.

---

## 11. Progress rule

For every cycle: reproduce a user-visible failure or name a gate; freeze the
case; change one responsible seam; validate in runtime; run the smoke suite and
relevant cross-capability controls; record outcomes and limitations; update this
plan; commit only intended files. If a cycle only increases fixture count or
corpus size, it has not advanced the goal.

---

## 12. Execution log

| Date | Work | Evidence |
|---|---|---|
| 2026-10-20 | Canonical plan written; self-learning made a core workstream | this file |
| 2026-10-20 | Phase 0 harness: `crms_eval/`, `run_scorecard.py`, smoke suite, report format | `experiments/reports/scorecard/2026-10-20-smoke-baseline/report.md` |
| 2026-10-20 | Harness self-check: pass/fail/unsafe detection, duplicate-id rejection | `experiments/v1_545_scorecard_harness.py` |
| 2026-10-20 | Rule registry v0: lifecycle, validation, scoped auto-accept gates, correction propagation, rollback, SQLite persistence | `crms_rule_registry.py`, `experiments/v1_546_rule_registry_lifecycle.py` |
| 2026-10-20 | Fixed pronoun date anchoring (determiner normalization, hit filtering, anchor citation); smoke suite now 12/12 with zero known failures | `crms_chat.py`, `experiments/v1_547_pronoun_date_anchor.py`, `experiments/v1_449_cross_paragraph_pronoun_grounding.py`, `experiments/reports/scorecard/2026-10-20-smoke-baseline/report.md` |
| 2026-10-21 | Procedure learner mirrors learned rules into the registry: validation by demonstration replay, activation, use counts, retirement on forget, reload reconstruction, versioned successors | `crms_model.py`, `experiments/v1_548_rule_registry_integration.py` |
| 2026-10-21 | Chat loads/saves the registry (default `_registry.sqlite` next to `--rules`) and exposes `/rule-health` and `/rule-detail`; anchor context preserved without widening exact citations | `crms_chat.py`, `CRMS_README.md`, `experiments/v1_527_paragraph_anchored_event_date.py`, `experiments/reports/scorecard/2026-10-21-smoke-baseline/report.md` |
| 2026-10-21 | Typed task/plan IR contract: deterministic ids, 6-step bound, dependency order, evidence/check kinds, result invariants, JSON round-trip | `crms_tasks.py`, `docs/design_task_ir.md`, `experiments/v1_549_task_ir_contract.py` |
| 2026-10-21 | Family A frozen specification (10 positive tasks, 8 negative controls, independent oracle) before planner code | `experiments/scorecard/family_a_spec.md` |
| 2026-10-21 | Deterministic plan executor: action registry, resolved step inputs, independent per-step and plan-level verification, no partial success | `crms_planner.py`, `docs/design_task_ir.md`, `experiments/v1_550_plan_executor_contract.py` |
| 2026-10-21 | First Family A adapters: proof-verified value selection with explicit negatives/qualifiers, learned-procedure execution with parity verification, tamper/unknown/conflict controls | `crms_actions.py`, `experiments/v1_551_family_a_actions.py` |
| 2026-10-21 | Legacy/plan parity for explicit verified-filter requests (status, evidence, procedure lineage, and rendered text); chat switched to the plan path, regex retained only as request compiler | `crms_task_composition.py`, `crms_chat.py`, `crms_tasks.py`, `crms_planner.py`, `experiments/v1_552_family_a_plan_parity.py` |
| 2026-10-21 | Family A scorecard suite (4/4): filter+sum with citations, fresh reload, unknown-value abstention, untaught-procedure clarification; scorecard oracle recognizes “can’t determine” as abstention | `experiments/scorecard/family_a.jsonl`, `crms_eval/oracles.py`, `experiments/reports/scorecard/2026-10-21-family_a-baseline/` |
| 2026-10-21 | Learned request frames replace the regex compiler in chat: exact literal templates, typed slots, two-varied-example licensing, procedure-vocabulary disambiguation, ambiguity/no-match abstention, persistence, `/teach-frame` and `/frames`; 40 seed demonstrations license 20 Family A frames; Family A scorecard grows to 5/5 with a taught-frame reload | `crms_request_frames.py`, `crms_request_frames_seed.json`, `crms_task_composition.py`, `crms_chat.py`, `docs/design_request_frames.md`, `experiments/v1_553_request_frames.py`, `experiments/v1_554_request_frame_composition.py`, `experiments/v1_555_request_frame_chat.py`, `experiments/scorecard/family_a.jsonl` |
| 2026-10-21 | Request frames join the governed rule registry: `request-frame` family, stored-template replay validation, active-rule matching gate, use counts, contest/retire/rollback, stale retirement, and versioned successors on explicit re-teaching | `crms_frame_registry.py`, `crms_rule_registry.py`, `crms_request_frames.py`, `crms_task_composition.py`, `crms_chat.py`, `experiments/v1_556_request_frame_registry.py` |
| 2026-10-21 | Family A scorecard grows to 12/12: explicit negative exclusion, conflict, missing output, and four licensed wording variants; conflict replies count as abstentions | `experiments/scorecard/family_a.jsonl`, `crms_eval/oracles.py`, `experiments/scorecard/family_a_spec.md` |
| 2026-10-21 | Corpus manifest v0: 20 candidate source groups across core/extended/research, licence classes, domain targets, 4 documented exclusions, and a validated 94.5M-word core planning estimate | `corpus/manifest_v0.json`, `crms_corpus_manifest.py`, `docs/corpus_manifest.md`, `experiments/v1_557_corpus_manifest.py` |
| 2026-10-21 | Family B typed composition: six new learned goals (research, math, unit conversion, translation, code generation, writing), independent replay/parity verifiers, cited research with re-resolved citations, and no fall-through after a failed plan | `crms_family_b.py`, `crms_request_frames.py`, `crms_request_frames_seed.json`, `crms_planner.py`, `crms_tasks.py`, `crms_chat.py` |
| 2026-10-21 | Plan instrumentation: append-only JSONL records for completed and failed plans, per-step actions/checks/evidence, failure learning candidates, `Plan plan-…` chat rendering, detailed `why?`, and `run_compounding.py` baseline summary | `crms_plan_log.py`, `crms_chat.py`, `run_compounding.py`, `experiments/v1_558_family_b_plan.py` |
| 2026-10-21 | Phase 2 gate measured: Family A 30/30, Family B 30/30 plus 6/6 controls, smoke 12/12, zero unsafe answers; tampered research/math outputs rejected; nested plan inputs and dialogue history wired | `experiments/scorecard/family_a.jsonl`, `experiments/scorecard/family_b.jsonl`, `experiments/scorecard/family_b_spec.md`, `crms_dialogue.py`, `crms_eval/oracles.py` |
| 2026-10-21 | Phase 3 document learning: audited per-document manifests, clause/condition/antecedent/table extraction, proposal-only registry ingestion, SQLite review ledger, accepted-rule promotion, false-positive taxonomy, second-publisher transfer, and 100-document retention | `crms_document_learning.py`, `corpus/phase3_eval/`, `run_phase3_eval.py`, `run_phase3_review.py`, `experiments/v1_559_document_learning.py`, `docs/design_document_learning.md` |
| 2026-10-21 | Phase 3 gate measured: 16 reviewed proposals, 93.8% precision, 100% seeded recall, 7/7 controls, 0.36 review minutes/claim, 4/4 transfer, 15/15 retention, zero pre-review active rules | `experiments/reports/phase3_document_learning.json` |
| 2026-10-21 | Phase 4 learning lane: SQLite dependency index, taught/source-reviewed/derived trust conflicts, support-aware correction propagation, verified-work replay learning, correction/failure scoped negatives, active probing, consolidation, and scoped auto-accept policy | `crms_dependency.py`, `crms_verified_work.py`, `crms_corrections.py`, `crms_active_learning.py`, `crms_consolidation.py`, `run_phase4_eval.py`, `experiments/v1_560_phase4_learning.py`, `docs/design_phase4_learning.md` |
| 2026-10-21 | Phase 4 gate measured: 100% correction propagation (5/5), bad derivation contested, compounding 0/12→12/12 with zero confident errors, skeleton transfer 0/4→4/4, disjoint plateau 0/4, provenance/trust across copied model state, bounded dependency storage | `experiments/reports/phase4_learning.json`, `experiments/scorecard/phase4_families.json` |
| 2026-10-21 | Phase 5 construction lane: learned token classes and typed slots over ten composition shapes, regular morphology with evidence-only irregulars, active construction gaps, propose-only size-budgeted ranker, registry entry/retirement, and 200 held-out paraphrases | `crms_constructions.py`, `crms_morphology.py`, `crms_construction_ranker.py`, `run_phase5_eval.py`, `experiments/v1_561_phase5_constructions.py`, `docs/design_phase5_constructions.md` |
| 2026-10-21 | Phase 5 gate measured: exact frames 60/200 (30%) vs learned constructions 200/200 (100%), controls 60/60, reworded 0/140→140/140, zero confident errors, unlicensed/ambiguous abstention, holdout-backed construction rules, clean retirement/rollback, evidence-only irregulars, bounded bypassable ranker | `experiments/reports/phase5_constructions.json`, `experiments/scorecard/phase5_constructions.json` |
| 2026-10-21 | Phase 6 domain lane implemented: exact word problems/inequalities/2x2 systems, typed list code IR with AST checks and sandboxed execution, agreement-aware English->Spanish translation, constraint story planner, two-stage task-IR plans, and 47 governed domain rules | `crms_domains.py`, `crms_phase6_benchmark.py`, `run_phase6_eval.py`, `experiments/v1_562_phase6_domains.py`, `docs/design_phase6_domains.md` |
| 2026-10-21 | Phase 6 gate measured: 90/90 held-out tasks across five slices, zero confident errors, 15/15 negatives abstained, provenance on every answer, one repair per slice, cost reported, registry retirement/rollback clean | `experiments/reports/phase6_domains.json`, `experiments/scorecard/phase6_domains.json` |
| 2026-10-21 | Phase 7 corpus program: audited per-document manifests, licence classes, source revision/hash, attribution, cleaning, exact/near dedup, language/script/PII filters, and eight disk-backed FTS shards | `crms_corpus_program.py`, `crms_phase7_benchmark.py`, `run_phase7_eval.py`, `experiments/v1_563_phase7_corpus.py`, `docs/design_phase7_corpus.md` |
| 2026-10-21 | Phase 7 gate measured: 268,148 documents / 69.3M words, 100% licence coverage, 501 docs/s, 8 shards, 39/39 held-out positives with valid citations, 0 confident errors, 10/10 negatives abstained, p95 1.03s, clean-room copy with originals hidden | `experiments/reports/phase7_corpus.json`, `corpus/phase7_eval/fixture.json` |
| 2026-10-21 | Phase 8 portable release: read-only model + metadata directory, licence evidence, dependency lineage, registry history, corrections, integrity digests, v1–v5 migration, and `/model-info` `/lineage` `/corrections` `/evidence` chat inspection | `crms_phase8_model.py`, `crms_chat.py`, `experiments/v1_564_phase8_model.py`, `docs/design_phase8_release.md` |
| 2026-10-21 | Phase 8 gate measured: 12/12 clean-room release tasks, zero unsafe answers, 100% licence coverage, 6 dependency nodes/5 edges, 1 registry rule, 1 correction, 167,936-byte release, 0.41s build, 4.27s scoring, 0.31s median task, 0.58s p95, originals hidden | `experiments/reports/phase8_release.json`, `corpus/phase8_eval/fixture.json` |
| 2026-10-21 | Phase 9 external validation: frozen supported subset 35/35 with zero unsafe answers; independent model-authored literary breadth 0/12 with one unsafe answer; two automated raters (adequacy agreement 0.90/kappa 0.75, evidence 0.65/0.16); blind 10-probe hosted 70B-class comparison; failure taxonomy, limitations, and 10-document licence inventory published | `run_phase9_eval.py`, `experiments/v1_565_phase9_external.py`, `experiments/reports/phase9_external.json`, `docs/design_phase9_external.md`, `docs/phase9_failure_taxonomy.md`, `docs/phase9_limitations.md`, `corpus/phase9_eval/` |
| 2026-10-21 | Phase 10 re-scoped to rule-complete generation: declared genres, content/discourse/sentence planning, construction grammar realizer, clarity/style revision, critic/search, LLM-supervised rule induction, no LLM at inference. First rule-only vertical slice and frozen generation evaluation added; gate open | `crms_generation.py`, `crms_generation_rules.py`, `crms_generation_rules.json`, `experiments/v1_566_phase10_generation.py`, `docs/design_phase10_generation_learning.md` |
| 2026-10-21 | Phase 10 gains a generalisation workstream: learned classes, back-off hierarchy, analogical matching proposals, and evidence-count weights, with a rule-scaling curve (coverage and confident errors against training examples and rule count, per-mechanism ablations) and a gate item; the rationale is that LLM generalisation largely reflects training coverage, so rules can be made to reach it deterministically | `docs/design_phase10_generation_learning.md`, `docs/master_plan_to_final_state.md` |
| 2026-10-21 | Phase 10 bounded lane completed: 12/12 cases across all 10 genres, mean copy 0.157; SQL snapshots/rollback; accepted teacher clarity proposal and rejected negative control; clean-room reload; `/compose` chat path; class/back-off/analogy/evidence generalisation diagnostics; automated 70B-class comparison (CRMS adequacy 1.75 vs 2.00, clarity 1.90 vs 2.00, coverage 1.85 vs 2.00); human/independent-300/two-corpus/measured-70B gates open | `crms_generation.py`, `crms_composition_memory.py`, `crms_examiner.py`, `crms_generate.py`, `run_phase10_eval.py`, `run_phase10_teacher.py`, `run_phase10_comparison.py`, `run_phase10_external.py`, `experiments/reports/phase10_external.json` |
| 2026-10-22 | Phase 11 planned: staged transition from ad-hoc regex to one structure-aware pattern layer, generation layer first (engine port, SQL store, source-to-proposition intake, pattern-based generation rules, spec verifier), with parity gate, retire-on-parity rule, and later stages for evidence extraction, request understanding, and knowledge extraction. Prototype evidence recorded with its limits; gate open | `docs/design_phase11_pattern_transition.md`, `docs/master_plan_to_final_state.md` |
