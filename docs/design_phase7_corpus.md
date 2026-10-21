# Phase 7 corpus program

**Status:** bounded Phase 7 gate measured 2026-10-21.
**Code:** `crms_corpus_program.py`, `crms_phase7_benchmark.py`,
`run_phase7_eval.py`.
**Contract test:** `experiments/v1_563_phase7_corpus.py`.
**Frozen evaluation:** `corpus/phase7_eval/fixture.json`.
**Report:** `experiments/reports/phase7_corpus.json`.

## Goal

Phase 7 turns the planning inventory in `corpus/manifest_v0.json` into a
measured, licence-audited corpus that can answer held-out questions with exact
citations. It does not try to reproduce a web-scale training set. It builds the
smallest defensible core corpus that exercises the same *kinds* of material:
encyclopedic prose, project documentation, code, academic abstracts and full
text, and reference notes.

The Phase 7 gate is deliberately narrower than "70B-class breadth":

1. a clean-room corpus model is copied away from its build inputs;
2. the original corpus directory is moved aside during scoring;
3. a frozen held-out question set is answered from the copied model;
4. every accepted answer resolves to an exact `document_id#sha256=…&chars=…`
   passage containing the expected fact;
5. negatives abstain;
6. corpus size, licence coverage, ingestion throughput, and query latency are
   reported.

## Corpus layout

A built corpus is a directory, not a mutable global index:

```text
phase7_core/
  model.json                  format, shard list, counts, clean-room flag
  corpus.json                 measured build report
  catalog.sqlite              one row per document and per rejection
  shard-00.sqlite … shard-07.sqlite
```

Each shard is an ordinary `CRMSSQLiteResearchIndex` with an FTS5 index. The
catalog is the manifest. It contains no document body; the body lives in
exactly one shard. A reader opens the catalog plus all shards read-only and
merges their ranked hits. Citation verification still happens against the
stored body and SHA-256 digest, so a shard cannot return an unverifiable quote.

The shard count is chosen at build time. Eight shards is the default. Sharding
is by stable SHA-256 of the document ID, so a rebuild puts the same document in
the same partition without a lookup table.

## Per-document manifest

Every accepted document has one catalog row with:

- `document_id`, `title`, `source_id`, `shard`;
- `source_url` and the importer's `location` string;
- `retrieved_at`, `revision`, `source_sha256`, `body_sha256`;
- `licence`, `licence_class`, `licence_url`, `attribution`;
- `redistribution`, `retrieval`, `importer_version`;
- `domains`, `language`, `script`;
- `word_count`, `byte_count`, `original_chars`, `cleaned_chars`;
- `boilerplate_removed`, `redactions_json`, `fingerprint`.

Rejected documents are retained in `catalog.sqlite` with a reason and detail:
licence audit, optional held-out diagnostic, duplicate (exact or near), too short, non-English,
non-Latin script, encoding damage, PII/secret, or low alphabetic ratio. A
rejection is evidence, not a silently dropped row.

The manifest validator is `audit_licence`. A core document must have a known
licence class in `public-domain`, `permissive`, or `share-alike`, an attribution
string, a licence URL, a retrieval date, a revision or content hash, and
`redistribution=allowed`. Unknown user-supplied notes are excluded rather than
packaged.

## Pipeline

### Importers

The default core build reads existing CRMS SQLite source indexes and the current
project tree:

- `wiki:` SimpleWiki pages, revision IDs, page URLs, and CC BY-SA 4.0 notices;
- `arxiv:` metadata records (CC0 bibliographic metadata) and licence-verified
  full text (CC BY only);
- `pmc:` PMC Open Access records with a recorded CC BY or CC0 redistribution
  licence;
- `curated:` local notes with a `Page license:` line;
- `project:` current `*.py`, `*.md`, `LICENSE`, and `docs/**/*.md` files under
  the MIT licence.

The same builder accepts any SQLite index written by the existing importers
(`crms_import_wikidump.py`, `crms_import_jats.py`, `crms_import_pmc.py`,
`crms_import_arxiv.py`) and any local text/code file. Existing `add_file`
support for PDF, EPUB, office documents, and spreadsheets can produce a
temporary CRMS index; the builder then applies the same manifest and filters.
Git repositories and Q&A exports are directory or file inputs under the same
rules.

The Phase 7 core deliberately does **not** ingest:

- `corpus/phase3_eval/` or `corpus/phase7_eval/`;
- user-supplied design-note attachments;
- generated reports, SQLite indexes, or `data/` files;
- sources with an unknown or unverified licence.

### Cleaning

Cleaning is deterministic and conservative:

- Unicode NFC normalization, newline normalization, NUL removal;
- SimpleWiki link/file/category markup removal;
- infobox/taxobox field blocks and navigation lines removed;
- reference, "other websites", "related pages", and similar tails removed;
- standard site boilerplate lines removed;
- whitespace collapsed for prose, indentation preserved for code;
- runs of blank lines collapsed.

Cleaning records how many lines it removed. It does not rewrite sentences or
paraphrase source text; the cited span must still be the source's own words.

### Filters

- **Length:** at least 20 CRMS word units, at most 4M characters.
- **Encoding:** at most two Unicode replacement characters.
- **Alphabetic ratio:** at least 0.15, which keeps code and tables while
  rejecting binary or symbol dumps.
- **Language:** a six-language stopword profile; the core accepts English and
  Latin-script records whose profile is too sparse to classify. Non-English
  prose is rejected with `non_english` rather than silently indexed.
- **Script:** Latin-script records only for this English core.
- **Secrets:** private-key blocks, cloud access keys, and high-entropy named
  secrets are rejected.
- **PII:** email addresses, US SSNs, and phone numbers are redacted to
  `[email]`, `[ssn]`, and `[phone]`; the redaction count is retained in the
  manifest.

### Deduplication

- **Exact:** SHA-256 of the cleaned body.
- **Near:** 64-bit word-frequency SimHash, banded into four 16-bit buckets, with
  a bottom-k 5-word shingle sketch as a second check. A candidate is rejected
  as a near duplicate only when the SimHash distance is at most 6 and shingle
  overlap is at least 0.75.

The shingle check matters: arXiv metadata records share a template, so SimHash
alone falsely collapses distinct abstracts. The combined check keeps distinct
records while still catching copied or lightly edited text.

## Held-out evaluation

`corpus/phase7_eval/fixture.json` was frozen before the corpus build. It lists
39 evaluation target documents with their content SHA-256, 39 positive
questions across reference, science, math, code/docs, and research, and 10
negative controls about entities absent from the corpus.

This is a **question-level** holdout: the target documents remain in the
searchable corpus, while the question wording and expected phrases are frozen
and never ingested. A retrieval index cannot answer a question about a document
it never received; a source-disjoint test belongs with an external evaluation
set in a later phase. The clean-room copy still proves the runtime is
self-contained.

Positives are scored against the exact cited passage:

- the answer must be labelled `answered`;
- an `expected_any` phrase must appear in the answer and in the resolved cited
  text;
- the citation digest and character offsets must resolve through the shard's
  verifier;
- a target-document match is reported separately so source precision is visible
  even when another document supports the same fact.

Negatives must abstain. The answer route requires the most specific query term
plus coverage of the query (50% for prose; a lower, explicitly reported
threshold for module/code questions), and the citation is verified before it is
rendered.

## Commands

```sh
# Build the audited core corpus (about 8 shards, all local sources).
python3 crms_corpus_program.py build \
  --out data/phase7_core \
  --shards 8

# Inspect counts and licence coverage.
python3 crms_corpus_program.py inspect --corpus data/phase7_core

# Ask a question with an exact citation.
python3 crms_corpus_program.py answer \
  --corpus data/phase7_core \
  "What is a planet?"

# Run the full gate: build if needed, copy to a clean room, hide the original,
# score the frozen fixture, and write the report.
python3 run_phase7_eval.py

# Contract test (small synthetic corpus, no large data required).
python3 experiments/v1_563_phase7_corpus.py
```

## Measured result

The measured report is `experiments/reports/phase7_corpus.json`.

| Measure | Value |
|---|---:|
| Accepted documents | 268,148 |
| CRMS word units | 69,283,305 |
| Extracted text | 432,852,289 bytes |
| Eight-shard FTS index | 996,376,576 bytes |
| Catalog / manifests | 301,314,048 bytes |
| Ingestion | 501.47 documents/s; 129,567.64 words/s |
| Licence coverage | 100% (268,148/268,148) |
| Positive tasks | 39/39, zero confident errors |
| Invalid citations | 0 |
| Target-document matches | 39/39 |
| Negative controls | 10/10 abstained |
| Median / p95 latency | 315.5 ms / 1,034.3 ms |
| Clean-room | copied; original hidden; no build input required |

Accepted source mix: SimpleWiki 264,924; arXiv metadata 2,525; arXiv full text
7; PMC Open Access 20; current CRMS project files 671; curated local note 1.
Rejected records: 20,647, led by 17,306 too-short records, 2,817 non-English,
310 exact duplicates, 64 near duplicates, and 92 licence-audit failures.

The exact numbers are read from the report; regenerate the report after any
corpus change. The core remains SimpleWiki-dominated, so this is a measured
core gate, not a claim that the domain target mix is complete.

## Limitations

- This is a retrieval-and-citation corpus, not a trained language model. The
  answer route quotes an exact passage or code window; it does not synthesize a
  new paragraph.
- The frozen set is question-level. Whole-document, source-disjoint transfer is
  a later external-validation task, not a claim of this gate.
- The core mix is dominated by SimpleWiki. Books, Q&A, parallel text, and
  manuals remain thin, so domain balance is measured but not yet achieved.
- The language filter is a small stopword profile, not a full language
  identifier.
- Near-duplicate detection is deterministic but approximate.
- The clean-room gate copies a 1–2 GB directory and hides the original during
  scoring; it does not prove cryptographic non-use of every build input.
- The corpus does not include web-scale material and never claims 70B parameter
  equivalence. It is the packaged evidence layer that later phases can query.
