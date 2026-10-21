# Phase 7 held-out evaluation set

This directory contains a frozen **question-level** evaluation set. The target
documents are ordinary corpus documents; the questions and expected phrases are
what is held out. No question text or expected phrase is ingested.

`fixture.json` contains:

- 39 evaluation target documents, each with a content SHA-256 and domain;
- 39 positive questions across reference, science, math, code/docs, and
  research;
- 10 negative controls about entities absent from the corpus.

The question set was frozen on 2026-10-21, before the measured core build;
`fixture.sha256` records its content digest and the loader refuses a mismatch. The
runner copies the built corpus to a temporary clean room, moves the original
directory aside, and scores the fixture against the copy. The corpus therefore
has to answer from its own stored text, not from the build inputs.

Positive questions are not scored by lexical overlap alone. A correct answer
must resolve its exact citation and the expected phrase must appear in the
resolved passage. A target-document match is reported separately. Negative
controls require an explicit abstention.

Run the gate with:

```sh
python3 run_phase7_eval.py
```

The report is `experiments/reports/phase7_corpus.json`.

Source-disjoint retrieval (holding out whole documents and asking questions
whose facts are only in those documents) is not the Phase 7 gate because a
retrieval index cannot answer a question about a document it never received.
That stronger transfer test belongs with an external evaluation set in a later
phase. Here the frozen questions are disjoint from the build and tuning, and
the clean-room copy proves the model is self-contained.
