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
| Domains are narrow prototypes | Math, code, translation are bounded slices | Phase 6 |
| Corpus skew | Project + arXiv abstracts + SimpleWiki; little code/docs/books | Phase 7 corpus program |
| Distribution unproven end to end | Partial copied-model slices | Phase 8 |
| Scale ceiling unknown | Depth-4 search ~95 s; canonicalizer hot spot | Phase 8 |

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
- `crms_planner.py`: bounded best-first planner (≤6 steps, explicit expansion
  budget) over a uniform action registry. Actions declare preconditions,
  postconditions, evidence, and a verifier. Ambiguity or missing support
  abstains; no partial execution.
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

### Phase 7 — Corpus program (weeks 18–48, continuous)

**Goal:** exposure breadth comparable in *kind* to a general assistant's
training mix, sized for a workstation.

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

### Phase 9 — External validation and release (weeks 72+)

- v2 scorecard authored outside the project; blind held-out split.
- Two independent raters for evidence validity and answer adequacy; report
  agreement.
- Qualitative 70B comparison on breadth, paraphrase, compound completion,
  continuity, repair, coding, math, research — gap analysis, not parity claim.
- Publish scorecard, failure taxonomy, limitations, and licence inventory.

**Gate:** §2 criteria met, with failures published rather than hidden.

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
| Scope creep | New feature without a gate | Reject; the 533-experiment habit is the main delivery risk |

**Kill criteria are part of the plan.** A lane that misses its gate twice is
redesigned or dropped.

---

## 10. Immediate work queue

1. **Phase 0 harness** — `crms_eval/`, `run_scorecard.py`, smoke suite,
   baseline report.
2. **Freeze controls** — topic switch, source-only continuity, stale `why?`,
   history, ordinals, compound omissions, where-question wording.
3. **Land `v1_411`/`v1_412`** as dialogue controls.
4. **RFC for `crms_tasks.py`** — types, planner bounds, action contract.
5. **RFC for `crms_rule_registry.py`** — record schema, lifecycle, validation
   ladder, rollback, and how existing procedure/frame/rule stores migrate.
6. **Learning baseline** — instrument current rules/procedures with use counts
   and outcomes; measure today's compounding curve before changing it.
7. **Family A specification** — 10 tasks + independent oracle, frozen before
   planner code.
8. **Corpus manifest v0** — inventory of candidate sources, licences, sizes,
   and domain targets.
9. **Consolidate plan docs** — this file is canonical; link the others as
   history.

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
