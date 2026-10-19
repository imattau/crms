# Design: learning dynamics for CRMS (evidence ledger, gap follow-through, equivalence conjectures, revision tests)

**Audience:** the developer (human or AI) implementing this.
**Status:** staged implementation. Section 2's exact, review-only missing-premise source
follow-through is implemented in `crms_chat.py` and covered by
`experiments/v1_296_missing_premise_source_followup.py`. Section 3's report-only equivalence
analysis is implemented in `crms_equivalence_dream.py` and covered by
`experiments/v1_297_equivalence_dream_diagnostic.py`. The evidence ledger and belief-revision
mechanisms in sections 1 and 4 remain proposed. Prototype results below are design evidence;
their throwaway code (`ledger.py`, `exp_belief*.py`, `gap_followup.py`, `dream2.py`) is not
imported. Separately, explicit `practice_relation` and `practice_question` can write a complete,
independently reverified proof to bounded derived-case storage; ordinary `ask()` stays read-only.
The `practice_question` retained flag is true only when the case can be retrieved and revalidated,
so a zero storage cap cannot be reported as learning. `experiments/v1_65_heldout_rule_validation.py`
also checks the learning loop after acceptance: adding an explicit negative fact makes the rule
query ambiguous, invalidates the practiced case for retrieval, and preserves that behavior after
SQLite reload. Validated, discovered rules that predict the explicit negative are marked
`needs_review` and withheld from other conclusions until source-separated validation is run again;
the exact contradicted conclusion remains ambiguous with its supporting proof. Teacher-supplied
rules remain active and report the conflict at the affected conclusion. `/inference-rules` exposes
rule status and the cited counterexample so a user can inspect and correct it. Loading an older
accepted-rule store also rechecks saved negative evidence and suspends rules that it contradicts.
**Origin:** ideas reviewed from the HPM Learning Agent repo (belief weights, demand-driven
learning, "dreaming"), re-expressed without vectors.

## 0. Ground rules (read first)

These are invariants. A change that breaks one is wrong even if it passes tests.

1. **The exact gates stay in charge.** Nothing here may cause a fact, rule, frame, or primitive to
   be accepted. Acceptance continues to go through the existing validated paths (for facts:
   `accept_fact_candidate`, [crms_knowledge.py:7126](../crms_knowledge.py)).
2. **Numbers rank and flag; they never answer.** A weight may order already-valid candidates,
   trigger an "ambiguous" outcome, or mark an item for review. It must not turn an unsupported
   answer into a supported one.
3. **Never silently delete.** Auto-learned items can become `dormant` (excluded from ranking,
   still inspectable and restorable). Teacher-supplied items are `protected` and never change
   status automatically. Items with dependents are never retired.
4. **Retrieval is not evidence.** Using an item in an answer must not by itself raise its weight
   (rich-get-richer). Only the events in 1.3 count.
5. **Deterministic.** Same inputs and same event order give the same weights. No randomness in
   updates. Stored with explicit event order, not wall-clock.
6. **Provenance preserved.** Every ledger change records its cause (event type, source ids).
7. **Stdlib only.** No new dependencies.

## 1. Evidence ledger

### 1.1 Purpose
Record how an accepted item has fared since acceptance, so CRMS can (a) prefer better-supported
items when two valid ones compete, (b) report "ambiguous" when competing beliefs are close,
(c) flag items that keep failing, and (d) let unused auto-learned items fade.

### 1.2 Storage
Add to the SQLite memory store (see [sqlite_memory_design.md](sqlite_memory_design.md)); use the
same transaction rules. Do not add JSON files.

```sql
CREATE TABLE item_ledger (
  item_kind   TEXT NOT NULL,      -- 'fact' | 'rule' | 'frame' | 'primitive' | 'derived_case'
  item_id     TEXT NOT NULL,      -- id of the existing row (fact_id, rule_id, ...)
  weight      REAL NOT NULL,      -- 0..1
  hits        INTEGER NOT NULL DEFAULT 0,
  misses      INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'dormant'
  protected   INTEGER NOT NULL DEFAULT 0,      -- 1 = teacher-supplied, never auto-changed
  updated_seq INTEGER NOT NULL,   -- value of ledger_event.seq when last changed
  PRIMARY KEY (item_kind, item_id)
);
CREATE TABLE ledger_event (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,   -- defines event order
  item_kind  TEXT NOT NULL, item_id TEXT NOT NULL,
  event      TEXT NOT NULL,       -- see 1.3
  detail_json TEXT NOT NULL       -- source ids, question id, etc.
);
```

Create a module `crms_ledger.py` (new) exposing:

```python
class Ledger:
    def __init__(self, connection, params=LedgerParams())
    def register(self, kind, item_id, *, protected=False, weight=None)   # idempotent
    def record(self, kind, item_id, event, **detail)                      # applies 1.4, logs event
    def weight(self, kind, item_id) -> float                             # 0.0 if unknown
    def prefer(self, kind, item_ids) -> Preference                       # 1.5
    def stale(self, kind, *, max_weight, min_misses) -> list[str]        # for review listings
```

`register` is called wherever an item is first committed (fact accepted, rule installed, frame
licensed, primitive accepted). Teacher commands (`/teach-*`, "Remember that ...", explicit rule
teaching) register with `protected=True`. Items committed through a corpus-derived candidate or
auto-discovery register with `protected=False`.

### 1.3 Events (the only things that move weights)

| Event | Effect | Notes |
|---|---|---|
| `corroborated` | hit | A second independent source (different document) supports the same proposition. |
| `confirmed` | hit | The user explicitly confirms an answer that used the item. |
| `contradicted` | miss | A new accepted fact conflicts (positive vs. negative on the same proposition and scope). Applies to the *weaker-sourced* side only; if equal, apply to neither and let the margin policy answer "ambiguous". |
| `rejected` | miss | The user marks an answer wrong; applies to the items in that answer's proof/evidence. |
| `held_out_pass` / `held_out_fail` | hit / miss | Re-validation of a rule, frame, or primitive on new data. |
| `idle_tick` | decay | See 1.4. Only for non-protected items. |

Explicitly **not** events: being retrieved, being shown, being used in a derivation.

Requires one new user signal: a way to say an answer was wrong or right. Add a short natural
phrase and a slash command (`/wrong`, `/right`) that refer to the last answer, and record the
proof/evidence ids of that answer so the event can be attributed. Without this signal only
`corroborated`, `contradicted`, and held-out events exist, which is acceptable for a first
version.

### 1.4 Update rule and parameters
Defaults (from the prototype; keep them in `LedgerParams` so experiments can vary them):

```
initial weight   : 0.20 for auto-learned, 1.00 for protected
hit              : w <- w + 0.15 * (1 - w)
miss             : w <- w * (1 - 0.35)          (skipped if protected)
idle_tick decay  : w <- w * (1 - 0.00)          (OFF by default; 0.02 tested, 0.0 is the safe default)
dormant below    : w < 0.02 and no dependents and not protected
```

`idle_tick` is a per-session or per-N-events counter, not wall-clock. Leave decay off until
real traffic shows stale auto-learned items accumulating.

### 1.5 Preference and the margin policy (important)
`prefer()` is how the ledger affects answers. It compares the weights of competing items for the
same slot (for example two accepted facts for one functional relation):

```python
@dataclass
class Preference:
    outcome: str            # 'prefer' | 'ambiguous'
    winner: str | None
    margin: float
```

- If `abs(w_top - w_next) >= MARGIN` (default **0.30**): `prefer` the top item.
- Otherwise: `ambiguous`. The answer layer must report disagreement using the existing
  ambiguous path ("The sources or facts I have disagree; I can't choose an answer yet." in
  `crms_knowledge.py`), with both items and their sources shown.

Why a margin: in a noisy-flip simulation (60 confirmations of C, then the truth flips to D, 20%
of later observations still report C), a bare highest-weight rule flipped 4.6 times on average
and gave 5.7 stale answers per 60. A margin of 0.3 cut that to 1.3 flips and 2.1 stale answers
at the price of about 15 abstentions per 60. That trade is the right one for CRMS because
abstaining is the system's default for uncertainty. Make MARGIN configurable and report it.

### 1.6 Hook points
- Registration: after `add_fact` / `add_negative_fact` calls inside `accept_fact_candidate`
  (crms_knowledge.py:7126), rule installation, frame licensing, primitive acceptance.
- Preference: where `ask` (crms_knowledge.py:11183) resolves multiple supported candidates for
  one slot, call `prefer()` before returning `ambiguous` or a single answer.
- Conflict handling: where positive/negative conflicts are detected (search for the existing
  "conflict" markers in `ask` and `infer_relation`), record `contradicted`.
- Listings: extend `/facts`, `/rules`, and the pending/derived listings with weight, hits,
  misses, status (one short column). Add `/stale` (new) to list `stale()` results.

### 1.7 Tests (add under `experiments/`, named `v1_NNN_*.py`)
1. **Revision:** entrench C with 60 `corroborated` events, then flip to D. Assert the answer
   changes from C to D within **5** steps with the default parameters, `residual conflict`
   (both within 10% of the leader) ends within **5** steps, and exactly one flip occurs.
2. **Noise:** repeat with 0%, 10%, 20%, 30%, 40% contradicting observations over 200 seeds.
   Assert with margin 0.3 that mean flips <= 2.5 at 20% noise and that stale answers are fewer
   than with margin 0, and record abstention counts.
3. **Protected:** a protected item receives 20 `rejected` events and keeps its weight and
   `active` status.
4. **No self-reinforcement:** 1,000 retrievals of an item leave its weight unchanged.
5. **Dependents:** an item with a dependent derived case is never made `dormant`.
6. **Determinism:** the same event sequence run twice yields identical rows.

## 2. Missing-premise follow-through

### 2.1 Purpose
`infer_relation` already returns `missing_premises` and the answer layer already says "I need X
to derive this. Tell me that fact or point me to a source." Close the loop: before asking the
user, look in the indexed corpus for a sentence that states X, and offer it as a review
candidate. If none states it, say so and stop.

### 2.2 Behaviour
Given a result with `reason_code == 'missing_premise'` and entries
`{missing_premise: {subject, relation, object}, rule_id, premise_index, supported_premises}`:

1. For the first K entries (default K = 3), search the research index for sentences containing
   the subject and object of `missing_premise` (use the existing retrieval and the existing
   learned sentence frames for `relation`).
2. A sentence qualifies only if an existing learned frame for that relation parses it into
   exactly this subject, relation, and object. Do not accept a sentence that merely mentions
   both entities.
3. Exactly one qualifying sentence (or several that parse to the identical triple, which is
   corroboration): create a **review candidate** using the existing candidate type and queue
   (`/pending-candidates`). Reply: "I have A — r → B. To derive this I need B — r → C. This
   sentence states it: “...” [source]. Accept it to complete the answer."
4. Several sentences that parse to different triples: show them as ambiguous; propose nothing.
5. None: reply with the existing "I need ... Tell me that fact or point me to a source." text,
   plus "I found no sentence in the indexed sources that states it." Never invent or relax the
   match.
6. After the user accepts the candidate, re-run the original question so the derivation
   completes in one step. The candidate goes through `accept_fact_candidate` unchanged.

### 2.3 Hook points
- Where `ask` builds the missing-premise reply (crms_knowledge.py around lines 7101 and
  11718-11745), call a new helper `propose_for_missing_premises(entries, research_index)` that
  returns candidates and a short explanation.
- Put the helper in a new module `crms_gap_followup.py` so it can be tested without the chat.
- Use the existing `FactCandidate` type (carries sentence, source, polarity, language evidence).

### 2.4 Expected results (prototype)
Over 500 generated cases using the real `infer_relation`: a supporting sentence present gave a
proposal in 100/100 cases and a correct answer after acceptance in 100/100; sentence absent,
wrong-relation distractor, and reversed roles each gave 0/100 proposals (correct refusals).
Limits to state in the docs: phrasings that the learned frames do not parse were not found (0/100
for "X was born to Y", "Y's child is X", "Y, a parent of X, attended"). Extending paraphrase
coverage is a separate task and should not be solved here by loosening the match.

### 2.5 Tests
- The four generated cases above, plus a case where two sentences state the same triple
  (treated as corroboration, one candidate with two sources).
- A case where the corpus has the sentence but no learned frame for the relation: expect the
  "no sentence states it" reply, not a guess.
- End to end in chat: ask, receive candidate, `accept candidate 1`, receive the derived answer
  with its proof.

## 3. Equivalence conjectures from "dreaming" (report-only)

### 3.1 Purpose
Find pairs of rule-search programs that behave identically but that `_semantic_key`
([crms_model.py:1612](../crms_model.py)) keeps apart, and report them as *conjectured laws* for a
human or a proof step to review. This could shrink the depth-2 search space by about 6%.

### 3.2 Behaviour
New script `crms_equivalence_dream.py`:

1. Enumerate depth-2 programs from `CRMSModel(max_composition_depth=2)._steps` (72 steps ->
   5,184 programs at default settings).
2. Compute each program's behaviour on a **probe set**: all integer lists of length 0-4 over
   values -3..3 (2,801 lists) plus **2,000** random lists (length 0-10, values -15..20, fixed
   seed). Group programs by behaviour.
3. Keep groups that contain programs with more than one `_semantic_key`.
4. Validate each such group on an **independent holdout** of 3,000 random lists drawn with a
   different seed. Drop any group whose members disagree on the holdout.
5. Write the surviving groups to a report (`json`), one entry per conjectured law: the
   programs, behavior digests, probe and holdout sizes, and seeds. Rejected weak-probe groups
   remain visible with their reason and warnings.

**Do not use the report to prune the live search.** It is input to a later step that either
proves the law in `_semantic_key` or records it as a conjecture with its evidence.

### 3.3 Why the probe must be strong
Measured on the real model: with a weak probe (150 random lists only) 26 of 98 merges were false
on fresh data. With the exhaustive short lists plus 2,000 random lists the result was 181
fewer behaviour classes (3,151 canonical classes -> 2,970, a 5.7% reduction) spread over 81
probe classes that each merge several canonical classes, and 0 of those 81 disagreed on 3,000
holdout lists. The one-off cost was about 20 seconds.

### 3.4 Tests
- On the default step set the script reports at least one conjecture and zero holdout
  disagreements.
- Passing a deliberately weak probe (150 random lists, no exhaustive set) must produce a visible
  warning in the report if any group fails holdout.
- Deterministic output for fixed seeds.

The checked-in implementation is `crms_equivalence_dream.py`. Its initial default run evaluated
5,184 two-step programs over 4,801 probes (2,801 exhaustive short lists plus 2,000 seeded random
lists), produced 2,969 probe behavior classes, and reported 81 conjecture groups with zero
holdout disagreements on 3,000 independent lists. The exact law that `absolute_values` commutes
with `keep_every_kth_position` was then proved and canonicalized in `_semantic_key`, reducing the
report to 77 groups. The exact `stable_unique` commutations with injective value maps, value-only
filters, and sorting are now also canonicalized. `experiments/v1_311_stable_unique_commutation.py`
checks 13 safe pairs across 4,406 exhaustive/seeded inputs per pair and guards four unsafe cases
(zero scaling and position selectors) with counterexamples. The latest full report retains 2,969
behavior classes, reports 65 conjecture groups, and has zero holdout disagreements. A further
exact law now canonicalizes stable magnitude sorting with value-only filters (`keep_evens`,
`keep_odds`, and `keep_multiples_k`); positional and first-relative filters remain excluded.
`experiments/v1_312_magnitude_sort_value_filter_commutation.py` checks eight filter variants on
20,608 exhaustive/seeded inputs each and guards both excluded families with counterexamples. A
further exact law canonicalizes `sort_by_magnitude` followed by `square_values` with
`square_values` followed by `sort_ascending`; the second ordering uses the fact that squaring is
monotone in magnitude and makes equal-magnitude ties identical. Its regression,
`experiments/v1_313_magnitude_order_square_commutation.py`, checks all three forms over 21,531
inputs. Finally, `keep_evens` is now the canonical spelling of `keep_multiples_k(2)` (including
negative two); this aligns the square-divisibility preimage with the parity-filter normal form.
`experiments/v1_314_even_filter_modulus_alias.py` checks seven equivalent forms in two behavior
groups over 20,531 inputs each and keeps odd filtering distinct. The latest full report retains
2,969 behavior classes, reports 57 conjecture groups, and has zero holdout disagreements. The
weak-probe regression in
`experiments/v1_297_equivalence_dream_diagnostic.py` rejects false merges and checks warning and
deterministic-output paths. Remaining report groups are finite-test conjectures, not proofs.

## 4. Belief-revision experiments (tests only, no new mechanism)

Adopt the shape used in the HPM design notes: each experiment script starts with a header
stating **Objective**, **Setup**, **Metrics**, **Failure modes**, and **Definition of success**
(add this to the template used by `CONTRIBUTING.md`). Add three experiments:

1. **Adversarial flip:** teach fact A, corroborate it repeatedly, then supply stronger
   contradicting evidence. Metrics: steps until the answer changes, steps of residual conflict.
   Failure modes: refuses to revise; overwrites on first contradiction; oscillates.
2. **Noise recovery:** inject N wrong facts into a store; measure steps until they stop being
   used in answers once users mark them wrong.
3. **Entrenched teacher fact:** a protected fact is contradicted by many auto-learned items; it
   must still be answered, with the conflict reported (not silently replaced).

These depend on section 1 but the scripts can be written first against the current behaviour to
record a baseline.

## 5. Delivery order

1. `crms_ledger.py` + tables + registration hooks + tests 1.7.1-1.7.6. No behaviour change yet.
2. Ledger listings and `/stale`. Still no change to answers.
3. `prefer()` wired into conflict resolution with the margin policy. Add the experiments in 4.
4. [Implemented] Exact missing-premise source follow-through in `crms_chat.py`; see
   `experiments/v1_296_missing_premise_source_followup.py`.
5. [Implemented] `crms_equivalence_dream.py` (section 3). Keep its report out of live search
   until a conjectured law has an exact proof.

Each step lands separately, with `python3 run_experiments.py` passing before and after.

## 6. Out of scope (deliberately)

- Vector/Gaussian representations, density trackers, or any numpy/scikit-learn dependency.
- Letting weights decide acceptance, or auto-deleting learned items.
- Loosening sentence matching to find more gap-fillers; paraphrase coverage is its own task.
- Co-use counting of rules in proofs. A prototype showed only structural (trivial) signals on a
  small sample; revisit once real usage logs exist.
- Free-form probabilistic scoring of answers.

## 7. Open questions for the owner

1. What should the user-facing words for `/wrong` and `/right` be, and should natural phrases
   ("that's wrong") also work?
2. Should `contradicted` always favour the better-sourced side, or should it apply to neither
   until a human decides? (Default here: the weaker-sourced side only.)
3. Is the conflict margin 0.30 acceptable as a default, or should it be tuned per relation?

## 8. Reasoning scalability and integrity roadmap

This section records runtime and code-review feedback on `crms_inference.py`, `crms_proof.py`,
and the chat reasoning path. The measurements below came from fresh synthetic graphs and chat
sessions, not from the equivalence-dream experiments in this document. Treat them as a baseline
to reproduce before changing the engine. This work is separate from acquiring more facts: corpus
growth cannot fix search bounds, proof enumeration, invalid rule declarations, or explanation
rendering.

### 8.1 Observed gaps and follow-up validation

The first feedback pass reported depth and proof-enumeration failures. A follow-up run against
commit `60c93ea` found that those two areas have since improved; this run did not exercise the
chat-level routing path:

- **Transitive chains now exceed the old nesting limit.** Chains of 12 and 20 hops, previously
  unknown at the default depth, now answer.
- **Proof search now answers large lattices with a support-list cap.** An 8-layer diamond
  (256 paths) and a 10-layer diamond both answer; the reply lists 64 proofs and says support
  listing was capped at 64. The engine should preserve this distinction between a proven answer
  and a truncated list of supporting proofs.
- **Recursive rules are graph-size consistent but still depth-limited.** Feedback against commit
  `60c93ea` reports that recursive `ancestor` queries through 8 hops answer at the old default,
  12 hops needs `max_depth=16`, and 20/35 hops need `max_depth=40`. The same query behaves
  consistently on 7- and 40-person chains. A 2,047-node binary-tree query at depth 9 also needs a
  higher default. The remaining issue is recursive rule depth, not transitive chain proof nesting
  or unrelated entity count.
- **Declared integrity constraints work; unannotated cyclic support now produces an explicit
  ambiguity.** A parent cycle can still prove `Ann grandparent of Ann`, but the engine now reports
  that the proof returns to its starting entity through a cycle in the supporting facts, and that
  no relation schema establishes whether the self-relation is valid. This is a diagnostic, not an
  inferred claim that every relation is irreflexive. Declared `irreflexive`, `asymmetric`, and
  `functional` relation types retain their specific integrity-conflict checks. The reasoning
  contract verifies both the untyped cycle warning (including a natural-language yes/no query)
  and the declared-schema path. Conflict with an explicit negative fact remains correctly
  ambiguous. The remaining design gap is source-backed proposal and review of relation constraints;
  current declarations are explicit teacher input.
- **Reported timings remain below 0.1 seconds** for these cases, including 3,000 facts with
  two-level rules. This is evidence that a higher default could be affordable, but not a
  substitute for measuring adversarial branching and memory use.

The remaining issues are:

- **Recursive rules still consume depth per recursive application.** Defaults are now 40 across
  inference, abduction, practice, and derived-case APIs, matching the reported limit needed for
  35-hop recursion. `v1_310` verifies complete proofs for 12- and 35-hop chains and a depth-9 path
  in a 2,047-node binary tree; explicit `max_depth=8` remains incomplete by design. The higher
  ceiling preserves the 10,000-expansion work bound but does not make recursion unbounded.
- **Constraint teaching is explicit and checked; automatic discovery remains open.** The
  `/teach-relation-type` path stores cited declarations for irreflexive, asymmetric, functional,
  transitive, symmetric, and closed-world behavior. The reasoning contract verifies constraint
  conflicts, cyclic-support ambiguity without a declaration, and persistence. CRMS must not infer
  constraints from a relation label. A source-backed proposal-and-review path for constraints is
  still future work.
- **Query-local tabling is implemented.** The inference call memoizes complete positive proof sets
  by goal and remaining depth. `v1_309` checks two reused recursive subgoals on a converging graph,
  verifies the resulting proof independently, and confirms that fact retraction is visible to the
  next inference call. Cross-query caching remains intentionally absent; adding it would require a
  reliable fact/rule store version and explicit invalidation tests.
- **The open-world answer boundary is underspecified in chat.** Failure to prove a positive does
  not imply false. A future closed-world declaration may support a negative answer for selected
  relations, but only with explicit relation scope and a clear distinction between `no`,
  `unknown`, and `conflict`.
- **Queries with variables now use indexed base and recursive joins.** Learned frames can answer
  derived relations by joining premise facts from the bound endpoint. The common linear form
  `edge + relation -> relation` is closed to a bounded fixed point for subject answers, with the
  inverse orientation for object answers. `experiments/v1_340_indexed_variable_inference.py`
  verifies both directions, independent proof trees, complete misses, SQLite persistence, and
  honest abstention after the fact-scan budget is reached. It also finds all nine ancestors of a
  deepest leaf in a 2,047-node binary tree despite the 256-entity cutoff. Other recursive shapes
  and mutually recursive rules still use the bounded entity-scan fallback; broader recursive join
  ordering and visible expansion-truncation handling remain open.
- Learned path-question frames can also do bounded forward expansion from a known entity. A
  two-example frame handles possessive wording such as “Who are Ann's grandchildren?”, including
  ASCII and curly apostrophes, and returns the two-edge proof. The system still needs those
  fact-backed examples; it does not infer that `grandchildren` means two `parent` edges from the
  word alone.
- **The rule language is narrow.** Rules currently use short chains of two or three premises.
  A Datalog-style body (a list of atoms sharing variables) could later add more premises,
  constants, multiple conclusions, comparisons, and safe negation. This is a larger language and
  proof-format change; defer it until search bounds, proof behavior, and integrity checks are
  dependable.
- **Premise enumeration can scale poorly.** Where variables are unbound, bind from the more
  selective indexed direction first (`known_outgoing` / `known_incoming`) and order joins by
  estimated selectivity. Preserve deterministic tie-breaking.
- **Chat can explain the selected inference proof.** `v1_320` checks a natural-language derived
  answer followed by “Why?” and verifies the exact rule and source premises appear while an
  unrelated retrieved passage does not. Broader explanation coverage for ambiguous and partial
  searches remains to be evaluated.
- **Failure states need distinct next steps.** Distinguish a known counterexample or a longer
  chain than the queried relation allows from a missing link, exhausted search budget, no
  applicable rule, and genuine unknown. Never claim “false” from a budget exhaustion.

### 8.2 Recommended implementation order

1. **Broaden the reasoning benchmark.** The focused regressions now cover chains through 35 rule
   applications, a 2,047-node tree, repeated recursive subgoals, proof caps, shortest paths, and
   retraction between calls. Add larger branching graphs and report rule depth, expansions, proof
   count, elapsed time, peak memory, and termination reason before raising limits further.
2. **Extend variable queries and inverse relations.** Indexed joins now cover extensional rules
   and a common linear recursive form in either supported endpoint orientation. Next, evaluate
   mutually recursive rules, selective join ordering, and explicit partial-answer presentation.
   Keep candidate and fact-scan bounds, with incomplete status whenever they prevent an exhaustive
   answer set.
3. **Measure recursive and premise-join performance** on broader graph shapes, including multiple
   converging subgoals and adversarial branching. Keep support-cap and shortest-proof reporting
   explicit; never interpret 64 listed proofs as the total.
4. **Consider richer Datalog rules** only after variable-query behavior, proof semantics, and
   boundedness are stable and benchmarked.

### 8.3 Benchmark requirements

The focused regression `experiments/v1_310_recursive_reasoning_default_depth.py` checks 12- and
35-hop chains and a depth-9 path in a 2,047-node binary tree at the new default, verifies their
proofs independently, and checks that explicitly requesting depth 8 still reports an incomplete
search. `experiments/v1_309_long_transitivity_proofs.py` additionally checks memoized overlapping
recursive subgoals, a ten-layer proof-capped diamond, shortest-path selection, and fact retraction
between inference calls. These complement, but do not replace, a broader deterministic benchmark
covering recursive rules across chain and branching graph sizes, cycles and planted contradictions,
and positive, negative, unknown, and budget-exhausted queries. Record answer status, shortest proof
length, proofs materialized, expansion count, elapsed time, peak memory, and termination reason.
Score correctness and abstention separately: an unknown caused by a documented budget is not a
false answer, but remains a completeness failure for cases whose proof fits the declared target
limits.

The initial follow-up measurements are an external validation report for `60c93ea`. The targeted
depth-40 change has passed the local runtime regression and reasoning contract. Reproduce the
remaining external cases,
especially recursion beyond 12 hops and chat-level routing, against the current checkout and
retain before/after results with each implementation step.
Do not let this roadmap displace the active priorities of recombination, self-learning rule
discovery, and trustworthy reasoning; the benchmark should show whether an improvement in search
or proof handling also helps those capabilities.
