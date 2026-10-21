# Phase 9 external-validation fixture

This directory freezes the external-validation lane. Do not edit a holdout task
after its first scored run. Update the digest only for a deliberate new fixture
version.

Contents:

- `fixture.json` — 35 supported-subset tasks, 12 independent-model-authored
  literary breadth tasks, and 10 comparison probes.
- `fixture.sha256` — content lock for `fixture.json`.
- `sources/` — four public-domain Project Gutenberg excerpts and six
  project-authored fact sheets.
- `licence_inventory.json` — source, edition, licence, attribution, retrieval
  date, revision, and body digest for every document.
- `authoring_prompt.txt` — the prompt used for the independent breadth author;
  it contains no CRMS code or output examples.

Run:

```sh
python3 run_phase9_eval.py
python3 run_phase9_eval.py --skip-baseline --skip-raters
```

The full run needs the `opencode` CLI and hosted models for the baseline and
raters. The fast run measures only the frozen CRMS scorecard and breadth probes.
