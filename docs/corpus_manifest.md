# Corpus manifest v0

**Status:** planning inventory plus a measured Phase 7 core. The v0 candidate
list below remains a planning inventory; the actual holdings are recorded
separately under "Measured Phase 7 core" and in
`experiments/reports/phase7_corpus.json`.
**Date:** 2026-10-21
**Data:** `corpus/manifest_v0.json`
**Validator:** `crms_corpus_manifest.py`, `experiments/v1_557_corpus_manifest.py`

## Purpose

The corpus program needs breadth comparable in kind to a general assistant's
exposure without pretending that a workstation can hold a web-scale corpus. The
manifest makes the intended mix explicit before importers are written:

- **core** — packaged with the model; target 50–100M words;
- **extended** — optional local corpus; target 1–10B words;
- **research** — not packaged; acquired only under explicit licences and
  manifests.

Every candidate records its licence, attribution obligation, domains, formats,
retrieval route, and a planning word estimate. Estimates are labelled
`low`/`medium`/`high` confidence and are not measured holdings.

## Current inventory

| Tier | Source groups | Known word estimate | Packaged |
|---|---:|---:|---|
| Core | 8 | 94.5M | yes |
| Extended | 10 | 1.76B known; one variable | no |
| Research | 2 | variable | no |

The core slice is deliberately dominated by SimpleWiki, a public-domain book
subset, the CRMS project itself, curated local notes, Python documentation,
RFCs, selected OpenStax textbooks, and Tatoeba sentence pairs. It is a starting
curriculum, not a claim that 94.5M words is sufficient for 70B-class breadth.

Extended candidates include MDN, Stack Exchange, permissive code, arXiv
metadata, the PMC Open Access subset, the full English Wikipedia, selected
GitHub repositories, OPUS parallel text, the full Gutenberg library, and
user-supplied documents. Research candidates are Common Crawl and permissively
licensed arXiv full text.

## Measured Phase 7 core

**Report:** `experiments/reports/phase7_corpus.json`
**Build:** `data/phase7_core/` (ignored by git; rebuild with
`run_phase7_eval.py`)

| Measure | Value |
|---|---:|
| Documents | 268,148 |
| CRMS word units | 69,283,305 |
| Extracted UTF-8 text | 432,852,289 bytes |
| Eight-shard FTS index | 996,376,576 bytes |
| Catalog / per-document manifests | 301,314,048 bytes |
| Ingestion throughput | 501.47 documents/s; 129,567.64 words/s |
| Licence coverage | 100% (268,148/268,148 redistributable) |
| Held-out positives | 39/39 with valid citations |
| Confident wrong answers | 0 |
| Negative controls | 10/10 abstained |
| Median / p95 query latency | 315.5 ms / 1,034.3 ms |
| Clean-room | temporary copy; originals hidden; no build inputs required |

Accepted source mix:

| Source | Documents | Licence class |
|---|---:|---|
| SimpleWiki | 264,924 | share-alike (CC BY-SA 4.0) |
| arXiv metadata | 2,525 | public-domain (CC0 metadata) |
| arXiv full text | 7 | permissive (CC BY 4.0) |
| PMC Open Access | 20 | permissive (CC BY 4.0) |
| CRMS project files | 671 | permissive (MIT) |
| Curated local note | 1 | permissive (PSF) |

The build rejected 20,647 records with retained reasons: 17,306 too short,
2,817 non-English, 310 exact duplicates, 64 near duplicates, 92 licence-audit
failures, 41 empty after cleaning, 8 non-Latin script, 5 low alphabetic ratio,
3 encoding damage, and 1 sensitive-content record. These are rejection
evidence, not silent drops.

The measured core is still SimpleWiki-dominated. Code and docs are present, but
books, Q&A, and parallel text remain thin; the domain-target table above is a
planning target, not the measured composition.

## Domain targets

The percentages are planning targets for the core corpus. They are not the
current index composition.

| Domain | Target |
|---|---:|
| Reference | 22% |
| General | 4% |
| Code | 18% |
| Math | 10% |
| Science | 12% |
| Books | 9% |
| Docs/manuals | 9% |
| Q&A | 7% |
| Translation | 6% |
| Dialogue | 3% |

The validator requires the targets to sum to 100 and every target to name a
known domain. Actual composition is measured after ingestion; a large source
does not justify skew.

## Licence policy

Core sources must be public domain, permissive, or share-alike with attribution.
A share-alike source keeps its own licence; the project does not relicense its
text. Copyleft and restricted sources require review before packaging. Unknown
licences are excluded.

Per-document manifests must eventually record:

- source URL and publisher;
- retrieval date and revision/hash;
- licence and licence URL;
- attribution text;
- importer version and transformations;
- redistribution decision.

`Books3`, `The Pile`, `OpenWebText`, and `OpenSubtitles` are documented as
excluded because their redistribution terms are unclear. Common Crawl and arXiv
full text remain research-only.

## Schema

Top-level fields:

```text
format, version, generated, description,
tiers, domain_targets, licence_policy, sources, excluded
```

Each source has:

```text
id, title, tier, domains, formats, licence, licence_class, licence_url,
attribution_required, packaged_ok, status, estimated_words,
estimate_confidence, estimate_basis, retrieval, url, notes
```

Rules enforced by `validate_manifest`:

- tier is `core`, `extended`, or `research`;
- source ids are unique slugs and do not collide with excluded ids;
- core sources must be `packaged_ok`, non-restricted, and have a word estimate;
- non-core sources must not be packaged;
- unknown licence classes cannot be candidates;
- candidate and approved sources need a URL and licence URL;
- domain targets are known and sum to 100;
- every exclusion records a reason and licence status.

Add a source by editing the JSON and running:

```text
python3 experiments/v1_557_corpus_manifest.py
```

## Evaluation corpora (never ingested)

Phase 3 uses a separate frozen, clean-room evaluation corpus at
`corpus/phase3_eval/`: seven complete short documents from four publisher
identities (Northwind Documentation, Hearthlight Press, Meridian Notes, and the
Python Software Foundation), two genres (technical reference and prose), three
licence classes, per-document SHA-256 hashes, 15 accepted seeded claims, one
rejected wrong-role proposal, and seven non-proposal controls. It is
evaluation-only and must never be added to a training or retrieval index. See
`corpus/phase3_eval/README.md` and `docs/design_document_learning.md`.

The Phase 3 result is a controlled boundary and transfer test, not an estimate
of arbitrary internet-prose precision. A real-publisher sample and independent
human review remain follow-ups.

Phase 7 uses a **question-level** frozen set at `corpus/phase7_eval/`. The
target documents remain in the searchable core; the questions and expected
phrases were frozen before the measured build and are never ingested. The
clean-room scorecard copies the corpus, hides the original, and verifies every
citation against the stored digest and offsets. Whole-document, source-disjoint
transfer remains a later external-validation test.

## Limitations and next work

- The v0 table is still a planning estimate; only the Phase 7 core is measured.
- The measured core is SimpleWiki-dominated. Books, Q&A, and parallel text are
  the next source increment; the domain targets are not yet achieved.
- The question-level held-out set is frozen, but whole-document source-disjoint
  transfer is not measured here.
- The language filter is a stopword profile, not a full language identifier;
  near-duplicate detection is deterministic but approximate.
- The clean-room copy proves runtime self-containment, not cryptographic
  non-use of every build input.
- Evaluation sets must be built separately and the questions must never be
  ingested or tuned on.
