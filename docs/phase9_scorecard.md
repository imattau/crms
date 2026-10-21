# Phase 9 scorecard

Frozen at `2026-10-21`; content digest in `corpus/phase9_eval/fixture.sha256`.

## Supported subset

| Category | Tasks | Passed |
|---|---:|---:|
| abstention | 3 | 3/3 |
| coding | 3 | 3/3 |
| compound | 2 | 2/2 |
| creative | 2 | 2/2 |
| dialogue | 1 | 1/1 |
| math | 4 | 4/4 |
| paraphrase | 2 | 2/2 |
| reload | 1 | 1/1 |
| research | 13 | 13/13 |
| translation | 3 | 3/3 |
| unit | 1 | 1/1 |

Overall: **35/35** (100%); unsafe answers **0**; median **0.27 s**; p95 **0.38 s**.

Task ids by category:

- **abstention**: `abstain-atlantis`, `abstain-fact`, `math-abstain`
- **coding**: `code-reverse`, `code-double`, `code-add`
- **compound**: `compound-books`, `compound-places`
- **creative**: `creative-robot`, `creative-sea`
- **dialogue**: `dialogue-history`
- **math**: `math-plus`, `math-times`, `math-minus`, `math-divide`
- **paraphrase**: `paraphrase-ada`, `paraphrase-moon`
- **reload**: `reload-ada`
- **research**: `who-ada`, `who-grace`, `where-eiffel`, `where-colosseum`, `when-wall`, `when-moon`, `who-frankenstein`, `who-moby`, `who-python`, `who-linux`, `who-web`, `sqlite-ada`, `why-ada`
- **translation**: `translate-french-ada`, `translate-french-linus`, `translate-spanish-ada`
- **unit**: `math-unit`

## Independent breadth split

| Task | Category | Result |
|---|---|---|
| `wonderland-rabbit-watch` | research | fail / abstained |
| `holmes-seventeen-steps` | research | fail / answered |
| `frankenstein-elizabeth-arrival` | research | fail / clarified |
| `holmes-bohemia-paper` | research | fail / abstained |
| `moby-dick-spleen-plain` | paraphrase | fail / abstained |
| `holmes-grit-lens-plain` | paraphrase | fail / abstained |
| `frankenstein-single-offspring-plain` | paraphrase | fail / clarified |
| `falling-vs-fitting-size` | compound | fail / abstained |
| `who-fell-down-where` | compound | fail / abstained |
| `daisy-chain-followup` | continuity | fail / abstained |
| `frankenstein-creature-account` | abstention | fail / answered |
| `holmes-midnight-visitor` | abstention | fail / abstained |

Overall: **0/12**; unsafe answers **1**. Failures are published; see `docs/phase9_failure_taxonomy.md`.

## Comparison probes

- `breadth-sky` — breadth: Open-ended explanation with no supplied source.
- `paraphrase-rabbit` — paraphrase: Same source, paraphrased colour question.
- `compound-books` — compound: Two-part completion.
- `continuity-ada` — continuity: Context continuity without repeating the question.
- `repair-python` — repair: User repairs an entity after the answer.
- `coding-reverse` — coding: Code generation from learned examples.
- `math-times` — math: Exact arithmetic after examples.
- `research-sherlock` — research: Literary source question.
- `translation-french` — translation: Bounded translation from aligned examples.
- `creative-robot` — creative: Open creative request.

Rater packet: `experiments/reports/phase9_rater_packet.json`. Human protocol: `docs/phase9_rater_protocol.md`.
