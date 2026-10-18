# CRMS knowledge and rule storage: SQLite design

**Status:** staged implementation. Learned transformation-rule memory now supports a normalized SQLite file; fact-sidecar replacement is transactional. Knowledge/rule portability and the canonical knowledge store remain in transition.

## Recommendation

Move learned knowledge and rules toward a versioned SQLite memory database, but do it in stages. SQLite should become the authoritative writable store for learned state; JSON should remain a supported import/export interchange format during migration. Do not treat the current `facts.sqlite` sidecar as the finished design: it is an indexed projection rebuilt from JSON, not the source of truth.

For a distributable model, embed the memory tables and searchable source documents in the existing portable SQLite model file. At runtime, either update that model database transactionally or make a writable copy first when the model is installed read-only/shared. This preserves the current single-file distribution goal and avoids a mandatory external knowledge file. Keep original documents out of the package; retain extracted text, source identifiers, and citations as the current packaging design does.

## Current state observed

- `CRMSKnowledgeBase.save/load` serializes facts, negative facts, rules, derivations, aliases, question frames, extraction patterns, and their support/provenance into `knowledge.json`.
- `SQLiteFactMap` gives positive and negative facts indexes at runtime, but `CRMSKnowledgeBase.load(..., fact_db=...)` clears and repopulates those tables from JSON. Saving still writes facts back to JSON. Thus the SQLite fact sidecar is a cache/index, not canonical memory.
- `CRMSModel.save/load` persists rule examples, procedures, accepted primitive artifacts, no-fit cases, and search settings as one JSON document. The current checked-in `crms_rules.json` is only 781 bytes, and the packaged rule memories are about 454 bytes; the case for migration is future scale and coherent durability, not current file size.
- `CRMSModel.save/load` also accepts `.sqlite`, `.sqlite3`, and `.db` paths. That backend stores settings, each rule example, each accepted procedure, and auxiliary artifacts in separate versioned tables. Chat can use it with `--rules rules.sqlite`; the portable-model exporter accepts it.
- The portable v1 model still converts rule memory to JSON in `learned_memories` and installs sidecar JSON files. The standalone SQLite rule backend is therefore a working first step, not yet the distributable model's canonical SQL schema.
- `crms_package.py` already produces a portable SQLite database, but stores knowledge/rules/math/translations as JSON text in `learned_memories`. Source documents are separate rows. This is a natural compatibility bridge, but embedding JSON blobs in that table alone would not provide SQL queries or transactional updates per learned record.
- Existing memory sidecars contain separately persisted knowledge/rule/math/translation JSON plus a `facts.sqlite` projection and a research SQLite index. Runtime edits are tracked and re-packaged from those memory files.
- Rebuilding the fact projection now starts a transaction before clearing old rows and commits only after the entire knowledge payload validates. Failed loads preserve the prior database snapshot.

## Target data model

Use one `crms_memory.sqlite` schema (or the same tables inside the portable model DB), with explicit ownership, versioning, and migration metadata:

| Area | Initial table design | Why |
|---|---|---|
| Header | `crms_metadata(key, value)` including format, schema version, model id, created/updated timestamps | Detect format and migrate predictably |
| Facts | `facts(fact_id, polarity, subject, relation, object, qualifiers_json, status, created_at)` with uniqueness over normalized proposition + polarity | Indexed lookup and independent positive/negative support |
| Evidence | `fact_sources(fact_id, source_id, source_kind, excerpt_id, provenance_json, confidence, created_at)` | Preserve many-source support, citations, and evidence lineage without packing it into one row |
| Rules | `inference_rules(rule_id, premises_json, conclusion_json, constraints_json, status, validation_json)` | Keep multi-premise and qualified rules extensible; index stable IDs/status |
| Derived cases | `derived_cases(case_id, conclusion_fact_id, lineage_json, proof_json, validation_fingerprint, practice_count, retrieval_count, reuse_count, status)` | Explicit derived learning, proof lineage, validation and invalidation |
| Acquired language | `memory_records(record_id, kind, key_json, payload_json, provenance_json, status)` | Migrate the many heterogeneous learned frames/patterns without forcing premature normalization |
| Rule learner | `rule_examples`, `procedures`, `primitive_artifacts`, `no_fit_cases` keyed by rule/phrase and example identity | Allow selective retrieval and provenance while retaining structured parameters |
| Model sources | Existing `research_documents` table plus evidence/source IDs | Keep source text portable and citations resolvable in one DB |

The table list is a logical boundary, not a requirement to normalize every nested structure on day one. Facts, evidence, rules, derived cases, and rule examples deserve queryable rows because recombination, self-learning rules, provenance checks, reasoning, and correction propagation depend on them. Existing language-frame and extraction state can initially be stored as versioned, typed records in `memory_records` with JSON payloads, then promoted to columns/tables where query patterns and scale justify it.

Avoid using one opaque JSON column as the *only* representation for facts or rules: it would retain the current all-at-once load/save behavior and weaken indexing, lineage invalidation, conflict checking, and rule selection. JSON columns remain appropriate for variable-shaped qualifiers, proof snapshots, constraints, and less stable learned payloads.

## Storage and transaction rules

1. Every mutation that changes a learned unit and its provenance is one transaction. A fact without evidence, or a derived case without lineage and verification state, must not be committed.
2. Derived memory remains distinguishable from taught/source-backed memory. Retrieval can rank them differently; validation or correction can invalidate descendants through lineage links.
3. Use foreign keys where practical (`fact_sources.fact_id`, derived conclusion IDs); enable `PRAGMA foreign_keys=ON`. Use WAL for an actively written local memory DB, but use a clean checkpoint/close and a consistent SQLite backup/export when packaging a portable model.
4. Give the portable DB an application ID and schema `user_version`; keep model-format version separate from memory-schema version. Migrations are ordered, transactional, and idempotent.
5. Store normalized lookup keys alongside display text. Preserve exact user/source wording, stable IDs, timestamps/order where behavior depends on it, and deterministic iteration in the compatibility layer.
6. Never mutate a shared installed model in place without an explicit writable policy. A read-only distributed model can be copied to a user memory DB and attached/read alongside it, or first-run can create a writable personal copy. This policy needs a deliberate product decision before implementation.

## Migration path

### Phase 0 — Baseline and contract

Capture representative knowledge/rule JSON fixtures and hashes, including aliases, positive/negative facts, qualifiers, citations, inference rules, proof-bearing derived cases, question/extraction frames, learned procedures, accepted primitives, and no-fit records. Record answers/proofs/retrieval results for a small deterministic chat-and-reasoning corpus. Existing import/export remains the reference contract.

### Phase 1 — Import/export bridge

Implement a versioned SQLite memory store and a one-way importer from existing JSON. Import into a temporary DB inside one transaction; validate row counts, canonical fact keys, evidence/lineage, rule configuration, and required schema; run SQLite integrity and foreign-key checks; only then atomically publish it. Keep JSON export and verify export → import → export semantic equality (not byte equality where ordering/format differs). A failed import leaves the input and destination untouched.

The transformation-rule substore is an initial implementation of this phase: it has separate rows for examples and accepted procedures, preserves JSON import/export, is readable by chat through `--rules`, and can be consumed by the current model exporter. Its portable package representation still needs conversion to relational tables.

### Phase 2 — Backend compatibility interfaces

Route fact and rule operations through narrow repository interfaces while retaining the current in-memory API and `SQLiteFactMap` behavior. Add SQLite implementations for durable writes and indexed reads. First run old JSON and new SQLite backends against the same fixture and compare answers, proofs, rule candidates, and retrieval ordering. Keep the JSON backend as a rollback option while parity gaps are fixed.

### Phase 3 — Make SQLite canonical

Switch new installations to SQLite. Existing JSON-only users are migrated on startup only after a backup and successful validation; avoid silently deleting or overwriting JSON. Chat changes should commit mutations immediately or at explicit command boundaries rather than relying on a large end-of-session full-file save. Continue JSON import/export for portability and diagnostics.

### Phase 4 — Portable model packaging

Update `crms_package.py` to export/import canonical memory rows and source documents into one SQLite file, with hashes for each source document and a schema manifest. `inspect` should validate schema, integrity, provenance references, and content hashes. Keep a reader for v1 packages where `learned_memories` contains JSON blobs; package version migration should be tested against existing model fixtures before changing defaults.

## Validation criteria

- Semantic round-trip of facts (including negative facts, multiple citations, qualifiers), rule examples/procedures, rule settings, aliases, language frames, and derived proofs/lineage.
- Identical chat answers, abstentions, provenance, reasoning proofs, recombination inputs, and self-learning-rule behavior on a fixed corpus under JSON and SQLite backends.
- Correction of a taught fact reliably flags or invalidates every dependent derived case; deleting one source preserves propositions supported by other sources.
- Interruption/failure during writes leaves a valid previous database; concurrent readers see a consistent snapshot; packaged model can be copied and queried without the source files or source-index DB.
- Performance measurements distinguish startup/serialization cost from retrieval and rule-search cost. SQLite is justified by atomicity, growth, indexing, and provenance operations even if small corpora show no speed gain.

## Decisions to settle before implementation

1. Is a portable model immutable by default, with per-user writable memory, or should chat directly update the distributable file? The safer default is immutable/shared base plus a writable user memory DB, merged at query time.
2. Should chat load all memory into Python objects or query SQLite incrementally? Start with the current repository-shaped API and indexed fact/rule lookups; move high-volume paths to incremental queries only where measured.
3. Which less-structured learned language records should become first-class tables? Keep them typed in `memory_records` initially and promote based on concrete query/index needs.

## Bottom line

SQLite is a good target now because CRMS already has a portable SQLite model container, an indexed fact-map abstraction, and learning mechanisms that need atomic provenance and derived-case invalidation. The important change is to make SQLite canonical, not to rename JSON files or put the same large JSON documents inside SQLite. Start with a reversible import/export bridge and preserve recombination, self-learning rule evidence, proof lineage, and derivation provenance as first-class test contracts.
