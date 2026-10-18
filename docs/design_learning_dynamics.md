# Design: learning dynamics for CRMS (evidence ledger, gap follow-through, equivalence conjectures, revision tests)

**Audience:** the developer (human or AI) implementing this.
**Status:** staged implementation. Section 2's exact, review-only missing-premise source
follow-through is implemented in `crms_chat.py` and covered by
`experiments/v1_296_missing_premise_source_followup.py`. Section 3's report-only equivalence
analysis is implemented in `crms_equivalence_dream.py` and covered by
`experiments/v1_297_equivalence_dream_diagnostic.py`. The evidence ledger and belief-revision
mechanisms in sections 1 and 4 remain proposed. Prototype results below are design evidence;
their throwaway code (`ledger.py`, `exp_belief*.py`, `gap_followup.py`, `dream2.py`) is not
imported.
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

The checked-in implementation is `crms_equivalence_dream.py`. Its default run evaluated 5,184
two-step programs over 4,801 probes (2,801 exhaustive short lists plus 2,000 seeded random
lists), produced 2,969 probe behavior classes, and reported 81 conjecture groups with zero
holdout disagreements on 3,000 independent lists. The weak-probe regression in
`experiments/v1_297_equivalence_dream_diagnostic.py` rejects false merges and checks the warning
and deterministic-output paths. These remain finite-test conjectures, not proofs.

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
