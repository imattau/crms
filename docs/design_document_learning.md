# Design: document self-learning (Phase 3)

**Status:** bounded Phase 3 lane implemented and measured.
**Date:** 2026-10-21
**Modules:** `crms_document_learning.py`, `crms_rule_registry.py`,
`crms_procedure_discovery.py`, `crms_research.py`
**Corpus:** `corpus/phase3_eval/manifest.json`
**Report:** `experiments/reports/phase3_document_learning.json`

## Principle

A document can propose. It cannot answer.

The pipeline has four explicit gates:

1. **Licence audit** — a document is readable only if its per-document manifest
   names a publisher, genre, URL, licence, licence class, attribution, retrieval
   date, and content hash. Unknown licences and hash mismatches fail closed.
2. **Clause-aware extraction** — claims preserve the source sentence, exact
   citation, subject/predicate/object roles, condition scope, polarity,
   quotation, uncertainty, attribution, and pronoun antecedent. Tables can
   contribute structured rows.
3. **Proposal registry** — every eligible claim enters the governed rule
   registry as `proposed` with `source-reviewed` trust. No proposed rule may
   affect runtime.
4. **Review** — a reviewer decides accept/reject, with identity, citation,
   roles, conditions, taxonomy, and time-per-claim recorded in SQLite. Only
   accepted rules are validated and activated.

## Extraction boundary

The extractor deliberately wraps existing bounded components rather than
inventing a general parser:

- `CRMSKnowledgeBase._discover_surface_relation_candidates` supplies narrow
  active/passive relation candidates;
- `propose_procedure_phrase_candidates` supplies `will` clauses with explicit
  conditions, negation, quotation, and denial status;
- a sentence-local antecedent pass rewrites a leading pronoun only when exactly
  one subject was established in the immediately preceding claim and the
  rewrite produces a candidate;
- a table pass accepts only a header with explicit subject/relation/object (or
  entity/predicate/value) columns.

Uncertainty, attribution, quotation, denial, and explicit negation remain in
the record for audit but are not proposal-eligible. This is a conservative
choice: the first document lane measures precision before expanding recall.

## Registry mapping

| Claim family | Registry family | Statement |
|---|---|---|
| fact-frame | `fact-frame` | `<subject> <relation> <object>` |
| procedure | `procedure` | `<subject> will <predicate>` |

Rule IDs are `phase3-<claim hash>`. Payloads retain the full claim, citation,
publisher, genre, roles, conditions, antecedent, status, and extractor version.
Acceptance uses oracle `frozen-phase3-adjudication`, then `activate(mode="review")`.
Rejected proposals are retired; they never become active.

## Frozen corpus and metrics

The Phase 3 corpus has seven complete short documents from four publisher
identities and two genres. It contains 15 accepted seeded claims, one rejected
wrong-role proposal, and seven non-proposal controls.

Metrics:

- **precision** — accepted / (accepted + rejected) reviewed proposals;
- **seeded recall** — accepted seeded claims / seeded claims;
- **useful yield** — accepted proposals per extracted claim and per document;
- **false-positive taxonomy** — rejection categories;
- **review minutes per claim** — mean recorded review seconds / 60;
- **source diversity** — publishers and genres;
- **second-publisher transfer** — held-out publisher claims covered by active
  rules learned from the named learning publisher only;
- **proposal-to-active conversion** — active accepted rules / accepted claims;
- **retention after 100 documents** — active rules and citations still resolve
  after 100 distractor documents.

The current report is:

| Metric | Result |
|---|---:|
| Precision | 93.8% |
| Seeded recall | 100% |
| Controls | 7/7 |
| Review minutes/claim | 0.36 |
| Transfer | 4/4 held-out labels |
| Retention | 15/15 active rules, 15/15 citations |
| Proposal-to-active | 15/15 |

Gate: precision ≥0.8, seeded recall ≥0.5, controls all pass, transfer >0,
retention 1.0, review ≤2 minutes/claim, and no pre-review activation.

## Limitations

- The corpus is authored and small. It is a controlled boundary and transfer
  test, not an estimate for arbitrary internet prose or a real publisher sample.
- The frozen review ledger is an adjudication fixture, not a human usability
  study. `run_phase3_review.py` records real wall-clock review time but has not
  yet been run with independent reviewers.
- The relation extractor is narrower than the procedure extractor; several
  ordinary active/passive sentences abstain rather than risk a wrong role.
  That is intentional for the precision gate and is the next recall lane.
- Review promotion is local to the governed registry. Runtime chat integration
  for document-derived rules is not enabled until a later phase's safety gate.
- The 100-document retention check uses generated distractors, not 100 further
  licensed publisher documents.
