# Phase 3 frozen evaluation corpus

**Status:** frozen benchmark input. This corpus is evaluation-only and is never
ingested as training or retrieval material.
**Date:** 2026-10-21
**Manifest:** `manifest.json`
**Harness:** `crms_document_learning.py`, `run_phase3_eval.py`,
`experiments/v1_559_document_learning.py`

## What this is

Seven complete short documents from four publisher identities and two genres:

| Publisher | Licence | Genre | Documents |
|---|---|---|---|
| Northwind Documentation | CC BY 4.0 | technical reference | 2 |
| Hearthlight Press | CC0 1.0 | prose | 2 |
| Meridian Notes | CC BY-SA 4.0 | technical reference | 2 |
| Python Software Foundation | PSF License 2.0 | technical reference | 1 |

Most text is authored for this clean-room benchmark. One short Python history
passage is retained from the Python 3.12 documentation under the PSF License
Version 2; its source URL and attribution are recorded in the manifest. Each document records its publisher,
licence, licence URL, attribution, retrieval date, and SHA-256. The manifest
validator rejects a missing field, an unapproved licence class, an unknown
publisher, a path escape, or a hash mismatch.

## Frozen labels

`manifest.json` records:

- **15 accepted seeded claims**: facts and procedures with exact subject,
  relation, object/predicate, and where relevant condition, contrast scope,
  antecedent, or table role;
- **1 rejected wrong-role proposal**: “Python created Guido van Rossum” is a
  deliberately reversed adversarial sentence. The extractor proposes it; the
  frozen reviewer rejects it with taxonomy `wrong_role`;
- **7 non-proposal controls**: uncertainty, quotation, negation, attribution,
  and explicit denial passages that must not become eligible proposals.

The reviewer is a frozen adjudication ledger, not a human-factors study. Its
per-claim seconds are part of the fixture and drive the review-time gate.
`run_phase3_review.py` is the interactive alternative and records real
wall-clock seconds and reviewer identity.

## Reproduce

```text
python3 run_phase3_eval.py
python3 experiments/v1_559_document_learning.py
```

## Limitations

This is a controlled transfer benchmark, not a web-scale publisher sample. It
tests whether the pipeline respects boundaries and whether a rule learned from
one publisher identity transfers to held-out publisher documents. It does not
estimate precision on arbitrary internet prose. Expanding the corpus to
licensed real publisher samples remains a measured follow-up, not a claim made
by this fixture.
