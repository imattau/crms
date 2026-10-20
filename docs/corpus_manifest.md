# Corpus manifest v0

**Status:** planning inventory. Candidate sources, licences, and rough sizes are
recorded; no source is approved for packaging until its per-document manifest
and licence audit are complete.
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

## Limitations and next work

- Estimates are planning numbers, not measured word counts.
- No importer, deduplication, boilerplate removal, PII filtering, or language
  detection is implemented for these sources yet.
- A per-document manifest and licence audit must precede ingestion.
- The core build still needs a measured size, licence coverage, ingestion
  throughput, index latency, and a clean-room scorecard delta.
- Evaluation sets must be built separately and never ingested.
