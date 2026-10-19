# Design: evidence independence, source reliability, and a cross-surface transfer benchmark

**Audience:** the developer (human or AI) implementing this.
**Status:** staged. Section 3 has a deterministic first implementation in
`experiments/v1_315_cross_surface_question_transfer.py` with its baseline recorded in
`benchmark_baselines.md`. A read-only fact/rule dependency and independent-origin report is
implemented in `crms_support_report.py` and covered by
`experiments/v1_344_fact_support_dependency_report.py`. Source-backed sentence-frame examples are
also reported, but frame dependents, question-frame source lineage, and section 2's
source-reliability ledger remain proposed.
**Origin:** diagnostics and test designs taken from the HPM working paper ("Human Learning as
Hierarchical Pattern Modelling", included in the HPM Learning Agent repo), re-expressed for
CRMS without vectors. The paper is a hypothesis, not validated science, and says it is not an AI
architecture proposal; treat its ideas as sources of failure modes and tests.
**Relationship to other docs:** complements [design_learning_dynamics.md](design_learning_dynamics.md)
(evidence ledger, missing-premise follow-through, equivalence conjectures). The ground rules in
section 0 of that document apply here unchanged. Section 2 below supplies one input its open
question 2 asks for.

## 0. Why these three, and what they guard against

The paper's central warning is that **stability is not truth**. A pattern becomes sticky when it
is (1) heavily interconnected with other patterns, (2) reinforced by several evaluators at once,
and (3) repeated by its environment, none of which requires it to be correct. CRMS has direct
analogues:

| Paper | CRMS analogue | Risk |
|---|---|---|
| Internal connectivity | A fact that many derived cases, frames, and rules depend on | An error in it spreads everywhere |
| Evaluator saturation | An item that passes several gates for the same reason | Looks well checked, is not independently checked |
| Field amplification | One document, copied or quoted widely, supplies all the support | Looks corroborated, is a single origin |

The three work items:

1. **Evidence independence and dependency report** (section 1): measure how many *independent*
   origins support an item and how much depends on it.
2. **Source reliability** (section 2): learn how reliable each origin has been.
3. **Cross-surface transfer benchmark** (section 3): measure whether structure learned from one
   wording carries to others, the paper's operational test for real (not memorised) learning.

All three are read-only or ranking-only. None may accept, reject, or delete anything.

### 0.1 Fit with the current CRMS design

These are useful roadmap items, but should not be implemented as one coupled feature:

- **Transfer benchmark first.** It measures recombination and language generalization without
  changing answer behavior or depending on new provenance infrastructure.
- **Evidence/dependency reporting next.** Its accuracy depends on stable fact, rule, frame,
  derived-case, and source identifiers. Where the store cannot provide a trustworthy link, report
  the count as unavailable rather than infer lineage from display text.
- **Reliability last and ranking-only.** A score may order review items, but must not decide which
  conflicting proposition is true. Accepted facts and proofs still need existing evidence and
  validation paths.

The fact report now groups URL citations by host, known `wiki:` citations by corpus, hierarchical
paths by parent folder, and teacher inputs separately; an optional regex-to-origin map can merge
additional publishers. With a research index, it resolves cited spans and hashes normalized text,
so verbatim copies across origins count as one independent statement. Without resolvable text,
multiple origins remain unassessed rather than being assumed independent. It flags a fact as thin
only when at least the configured number of verified derived cases depend on it and the available
independent-origin count is below the configured minimum. Other rows say `unassessed`, not `ok`.
Accepted inference rules report the stored positive training and holdout evidence and count
verified derived cases whose proof cites the rule ID. Manually installed rules without saved
validation provenance remain unassessed. Source-backed declarative frames report their distinct
fact-pair examples and resolved sources, but current teaching counts do not track which stored
claims were later produced through a frame. Explicit question-frame teaching also does not retain
the exact fact proof that licensed each example, so those frame dependents and origins remain
unassessed. The report uses exact proof leaves and does not change facts, rules, derived cases,
weights, or answers.

These diagnostics supplement recombination, rule discovery, reasoning, and evidence validation;
they do not replace them.

### 0.2 Real-corpus alignment yield check

The current review-only predicate-alignment learner requires the same two distinct entity pairs
to appear under both predicate frames. A read-only replay of the local SimpleWiki index found no
proposals in eight separated windows (125 documents and up to 6,000 sentences per window;
offsets 0, 5,000, 20,000, 50,000, 100,000, 150,000, 200,000, and 275,000). Reproduce with
`python3 experiments/v1_343_real_corpus_predicate_alignment_yield.py`.

This is a yield result for these windows, not an estimate of corpus-wide precision or recall. It
shows that exact shared-pair matching does not yet provide useful self-learning coverage on these
ordinary encyclopedia slices. Keep its evidence threshold intact. A next discovery mechanism
should propose role-compatible candidate relations from broader evidence (for example, repeated
subject/object type combinations), then test them on held-out pairs and present them for review;
it must not treat type compatibility or lexical similarity as proof of synonymy. Track proposal
yield, held-out precision, and abstentions separately before using that mechanism in chat.

## 1. Evidence independence and dependency report

### 1.1 Purpose
Find items that are *dense but thinly supported*: many things depend on them, but all support
traces to one origin. Report them so a human can review before more is built on them.

### 1.2 Definitions

- **Document:** `source.split("#", 1)[0]`. This is how `crms_inference.py` already derives
  independent sources (see around line 1165 and the `insufficient-independent-sources` status).
  Reuse that normalisation; do not invent another.
- **Origin:** a grouping of documents that are not independent of each other. Computed by
  `origin_of(source) -> str` (new, in `crms_sources.py`), deterministic:
  - teacher labels (`teacher:conversation`, `t:...`, `user-taught`, and similar) -> `"teacher"`;
  - a file path -> its top-level corpus folder relative to the indexed root (or the file's
    parent directory if no root is known);
  - a URL -> its host name;
  - anything else -> the document string itself.
  Origins are configurable: allow an optional JSON map `{"pattern": "origin"}` so a user can say
  that two folders are the same publisher.
- **Support record:** `(origin, sentence_hash)`, where `sentence_hash` is a hash of the
  normalised cited sentence (use the existing `normalized_tokens` from `crms_text.py`). Same-origin
  repeats count once. Exact duplicate text across different origins is listed under both origins
  and flagged `copied`, but counts as **one independent statement** for corroboration; syndication
  must not manufacture evidence independence. Distinctly worded statements from distinct origins
  may count separately, with the limitation that paraphrased copying is not detectable from hashes
  alone.
- **Independent origin count** of an item: distinct origins with non-duplicate support statements,
  excluding `"teacher"` (reported separately). Expose nominal `origin_count` and `copied` too, so
  the report makes this distinction visible.
- **Dependents** of an item:
  - for a fact: the number of derived cases whose stored proof contains it (match on normalised
    subject, relation, object, polarity, and qualifiers), plus the number of learned frames or
    patterns whose licensing evidence cites it (find where `language_evidence` or equivalent
    stores the example fact; if frame evidence does not currently reference facts by id, report
    derived-case dependents only and note the limitation);
  - for a rule: derived cases whose proof cites the rule id;
  - for a frame or pattern: the facts or candidates created through it.

### 1.3 Report
New module `crms_support_report.py`:

```python
@dataclass(frozen=True)
class SupportRow:
    item_kind: str            # 'fact' | 'rule' | 'frame'
    item_id: str
    label: str                # human-readable, e.g. "Ann - parent of -> Bob"
    dependents: int
    independent_origins: int
    origins: tuple[str, ...]
    copied: bool
    teacher_supported: bool
    risk: str                 # 'thin' | 'ok'

def support_report(knowledge_base, *, min_dependents=3, min_origins=2) -> list[SupportRow]
```

`risk` rules (defaults are starting points; keep them as parameters and tune against real data):

- `thin`: `dependents >= min_dependents` and `independent_origins < min_origins`, whether or not
  teacher support exists. Teacher support is a separate field, not a reason to hide thin external
  evidence.
- `ok`: otherwise.

Output ordered by `dependents` descending, then label, for determinism.

### 1.4 Chat surface
- New command `/support-report [N]` listing the top N (default 10) rows with `risk == 'thin'`,
  each as one line: `3 dependents, 1 origin (geography.txt): Paris - capital of -> France`.
- When a derived case or frame is about to be created from an item whose `risk` is `thin`,
  append one line to the existing confirmation text: "This rests on one source (geography.txt)."
  This is a notice only; it must not block or change the result.
- `why?` (when it renders a proof) should show each leaf's source support, for example
  `[1 source]` or `[3 documents; 2 independent origins]`. `InferenceResult.source_count` and
  `source_documents` count/identify documents, not the origin groups proposed here; map documents
  to origins before using the word “independent.” Until then, retain document wording.

### 1.5 Interaction with the ledger
In the evidence ledger (design_learning_dynamics.md, section 1.3), `corroborated` fires only when
a non-duplicate statement comes from an independent origin not yet counted for that proposition.
Same-origin copies and exact copies across origins do not count. This protects the ledger from
rewarding repetition and syndication.

### 1.6 Tests (add as `experiments/v1_NNN_*.py`)
1. **Thin and dense:** a fact with five dependent derived cases and one origin is `thin`; adding
   a second distinct origin makes it `ok`.
2. **Same-origin copies:** the same sentence added to a second file in the same folder does not
   raise `independent_origins`.
3. **Cross-origin copies:** the same sentence in a different origin lists both origins, leaves
   independent-statement count at 1, and sets `copied`.
4. **Teacher facts:** teacher support is shown separately; an item with thin external support may
   still be flagged `thin`.
5. **Determinism:** two runs over the same store give identical ordered rows.
6. **No effect on answers:** answers and proofs for a fixed question set are identical with and
   without the report enabled.
7. **Notice only:** creating a derived case on a `thin` item succeeds and adds the one-line
   notice.

## 2. Source reliability ("pattern fields")

### 2.1 Purpose
Record how often facts from each origin were later corroborated, contradicted, or rejected. In the
first implementation, use this only to order the review queue and report source history. Never
use it to accept, reject, silence, or resolve a source conflict.

### 2.2 Storage
SQLite table in the memory store (same transaction rules as the other tables):

```sql
CREATE TABLE source_stats (
  origin       TEXT PRIMARY KEY,
  accepted     INTEGER NOT NULL DEFAULT 0,   -- facts accepted from this origin
  corroborated INTEGER NOT NULL DEFAULT 0,   -- later supported by another origin
  contradicted INTEGER NOT NULL DEFAULT 0,   -- later in conflict with another origin's fact
  rejected     INTEGER NOT NULL DEFAULT 0    -- user marked an answer using it wrong
);
```

The aggregate table cannot enforce idempotency by itself. Add an event table with a unique key such
as `(event_type, origin, proposition_key)` and source/support identity where needed, then update
both tables in one transaction. `proposition_key` includes canonical subject, relation, object,
polarity, and qualifiers. Repeated observations of the same proposition by the same origin do not
increment counters. Corrections/retractions require separate auditable events; do not silently
decrement aggregates. Exact copied statements across origins do not qualify as independent
corroboration.

### 2.3 Reliability score
```
reliability(origin) = (corroborated + 1) / (corroborated + contradicted + rejected + 2)
```
(Laplace smoothing.) Return **0.5** (neutral) until an origin has at least **5** events
(`corroborated + contradicted + rejected`), so a new source is neither trusted nor distrusted on
thin data. `"teacher"` is excluded and treated as protected.

### 2.4 Uses (and only these)
1. **Review queue ordering.** `/pending-candidates` lists candidates from higher-reliability
   origins first (stable sort; ties by existing order).
2. **Reporting.** `/sources` shows the score next to each origin once it has 5 events.

Do not use reliability to choose a winner in a conflict in this phase. A score can reflect
exposure or review history rather than truth, and using it to penalise an accepted fact would let
an aggregate score change answer status. Keep conflicts ambiguous unless the existing evidence
policy resolves them; revisit conflict ranking only after a separate calibration study.
Explicitly **not** a use: refusing candidates from a low-reliability origin, or hiding their
sentences from retrieval.

### 2.5 Tests
1. Neutral below 5 events (returns 0.5).
2. Scores move in the expected direction: origin A corroborated 8 times, contradicted 0 gives
   about 0.9; origin B contradicted 6 times, corroborated 1 gives about 0.2.
3. Conflicts remain governed by existing policy. Reliability may reorder review, but must not
   resolve a conflict or alter the answer result.
4. Repeating the same corroboration does not change the counters (idempotent).
5. A low-reliability origin's candidate is still accepted by the same gates when the user accepts
   it; only its queue position changes.
6. Teacher facts are never penalised.

## 3. Cross-surface transfer benchmark

### 3.1 Purpose
The paper predicts that real structural learning shows as transfer: the same deep structure in a
different surface form should still work, while memorisation would show gains only on trained
wordings. For CRMS this is the measurable form of "recombination works". The benchmark turns
the paraphrase-coverage gap into numbers that can be tracked across commits.

### 3.2 Design
The first implementation is `experiments/v1_315_cross_surface_question_transfer.py` (run directly;
it uses deterministic fixtures and no network). It builds invented entities, teaches through the
public fact and language-learning APIs, then asks held-out questions through `ask()` and selected
CLI sessions. The specification below is a target for successive benchmark extensions, not a claim
that every listed condition is already implemented.

Benchmark validity requirements learned during implementation:

- **Separate language transfer from fact lookup.** A question can be answered from a stored fact
  even when no frame transferred. Record the route and require an explicit derived-frame trace
  for transfer claims; do not count a direct fact answer as learned language transfer.
- **Hold out both entities and sources.** Training and test questions must use disjoint entity
  facts, and the derived-frame lineage must not include the held-out source. Keep test facts
  available so the benchmark can measure whether the language route can use them.
- **Teach the intended structure through a real public path.** Passive sentence patterns can be
  taught through `teach_fact_pattern`; additional question-frame teaching must use an already
  licensed relation/answer role and a fact-backed example. Do not specify a teaching command the
  current public API rejects.
- **Classify answers by route and evidence.** Exact answer text alone is insufficient: require the
  expected held-out fact as evidence and, for a transfer score, the expected language derivation
  record. Keep wrong, abstained, direct-evidence, inferred, and transferred outcomes distinct.
- **Include role-swapped and underspecified negatives.** `What created X?` and `Who created?`
  must abstain unless a corresponding typed/complete frame is licensed; a plausible sentence is
  not a correct answer to a structurally different question.

**Relations (start with six):** `created`, `capital of`, `located in`, `discovered`, `parent of`,
`flows through`. Use invented-but-plausible entity names (for example `Mara Vell`, `the Orrin
Engine`) so results cannot come from pretrained knowledge, and generate 12 entities per relation.

**Wording classes.** For each relation define fixed wordings in these classes. The experiment
must hard-code the exact strings (an example set for `created` is below) so results are
comparable across runs.

| Class | Meaning | `created` example |
|---|---|---|
| T (trained) | The wording(s) used to teach | `Who created X?` |
| S (surface variant) | Same structure, trivially different surface | `Who created the X?`, `who created x`, `Who has created X?` |
| P (paraphrase) | Different words, same structure | `Who is the creator of X?`, `X was created by whom?` |
| L (lexical synonym) | Needs a grounded synonym | `Who made X?` |
| N (near-miss negative) | Looks similar, must NOT be answered | `Who destroyed X?`, `Who created?`, `What created X?` (role swap) |
| G (additional taught frame) | A separate fact-backed wording explicitly taught in this k regime, evaluated on held-out entities | `Who was the creator of X?` or `X was created by whom?` |

**Teaching regimes.** Include `k = 0` as the no-question-frame-teaching baseline, reported as
class B. Then run `k = 1` (T only) and add wordings from P one at a time (`k = 2, 3`). Report each
separately. Where a regime teaches a source sentence pattern, label it separately from explicit
question-frame teaching so the measured transfer is attributable to the right learned structure.

**Procedure per (relation, k):**
1. Create a fresh store with distinct training and held-out entity facts.
2. Teach the k wordings via the supported public teaching paths and record the teaching regime;
   do not teach a question frame for `k = 0`.
3. Ask every held-out question in classes B (only at `k = 0`), T, S, P, L, N, and G for held-out
   entities. G measures entity-slot transfer for additional taught frames; it is distinct from
   untaught paraphrase transfer.
4. Classify each reply by both outcome and route: `correct-transfer` requires the expected
   held-out fact and an explicit transfer derivation; `correct-direct` uses the expected fact but
   no transfer derivation; `wrong` is a different answer or confident mismatched claim; `abstained`
   gives no answer. Evidence-only quotations are not correct answers.
5. For each negative wording, require either a justified alternate licensed route or abstention;
   specifically list any answer to a role-swapped or underspecified query as a benchmark failure.

### 3.3 Metrics
Print one table per run:

```
relation  k  class  n   correct  wrong  abstained
created   1  T      12  12       0      0
created   1  S      36  ...
...
```

and these summaries:

- **Accuracy on B, T, and G**: B is the untrained canonical baseline; T is canonical wording
  after explicit frame teaching; G measures the additional taught frames. Report direct, explicitly
  licensed-frame, and induced-frame routes separately. Correct answer text plus a matching fact is
  not enough to count as language transfer.
- **Transfer ratio** = `correct-transfer` held-out, untaught S/P/L examples divided by all such
  examples, normalized by trained-template accuracy. Exclude exact templates used for teaching in
  that `k` regime; report their trained-template results separately.
- **Wrong rate on N**: expected **0**, including entity-less and role-swapped queries.
- **Wrong rate overall**: reported; list each wrong result with the route and evidence used.
- **Direct-answer contamination**: report the number answered correctly from direct facts without
  a transfer trace, but do not count these as transfer successes.
- **Coverage curve:** transfer ratio versus k, the quantity to watch as recombination improves.

### 3.4 Pass/fail
For the first version, record the baseline and fail the experiment only on invariants:

1. For `k > 0`, T accuracy is 100%; B is reported without a pass threshold.
2. Wrong rate on N is 0.
3. The run is deterministic (a second run gives identical tables).

Do **not** fail on transfer ratio yet. Write the baseline numbers into the experiment's output
and into `docs/` (a short `benchmark_baselines.md`), and tighten thresholds as capabilities
land. A regression is then any commit that lowers transfer ratio without a stated reason.

### 3.5 Known expectations (from earlier manual testing, to be replaced by the baseline)
Earlier chat sessions suggested that article insertion and some paraphrases failed while the
trained wording worked, and that a lexical synonym such as `Who made X?` returned evidence text
without stating an answer. Those observations predate several recent commits, so do not treat
them as current; run the benchmark to find out.

### 3.6 Extensions (later, not part of the first version)
- Add a second structural family (yes/no questions, then two-hop path questions).
- Add sentence-side variation: teach facts from one sentence form, extract from others.
- Report time per question, so transfer gains can be weighed against cost.

## 4. Delivery order

1. Section 3 benchmark and baseline. It needs no new mechanism and gives a measuring stick
   before anything else changes behaviour.
2. `crms_sources.py` with `origin_of` and tests (needed by sections 1 and 2).
3. `crms_support_report.py` and `/support-report` (section 1), read-only and explicit about
   provenance links it cannot establish.
4. `source_stats` plus an idempotency/event table (section 2), initially reporting and review
   ordering only.
5. Do not wire reliability into answer conflict resolution without a separate proposal and
   calibration evidence. The evidence ledger from `design_learning_dynamics.md` must exist before
   score updates are connected.

Each step lands separately, with `python3 run_experiments.py` passing before and after.

## 5. Out of scope (deliberately)

- Using any score to accept, reject, delete, or hide a fact, source, or sentence.
- Inferring origin groupings automatically beyond the deterministic rules in 1.2.
- Vector similarity, density trackers, or new dependencies.
- The paper's affective evaluators (fear, pleasure, status) as mechanisms; they are human
  phenomena, useful here only as a catalogue of failure modes.
- Other ideas from the paper (maturity levels, route reliability, learnability-ranked review
  queues, round-trip generation checks). They are candidates for a later document.

## 6. Open questions for the owner

1. Should the default origin for a file be its top-level corpus folder, or should each indexed
   document be its own origin unless mapped? (Default here: folder, which is more conservative
   about independence.)
2. Is a threshold of three dependents and two origins the right starting point for `thin`, or
   should it scale with store size?
3. Should the transfer benchmark use only synthetic entities, or also a small real-corpus
   slice for realism? (Default here: synthetic only, so results cannot leak from outside
   knowledge.)
