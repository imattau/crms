# Phase 9 human-rater protocol

The automated panel is complete; this protocol is for closing the human gate.
Use `experiments/reports/phase9_rater_packet.json`. Do not edit it.

## Raters

Recruit two people who did not build CRMS and have not seen its source or this
report. Give each rater the packet independently. Do not let them compare notes
until both have submitted.

## Task

For every item, read the task, supplied source (if any), and responses A and B.
Do not try to identify which system is which. Rate each response:

| Field | 2 | 1 | 0 |
|---|---|---|---|
| `evidence_validity` | every factual claim is supported by the supplied source or a shown calculation | partly supported | unsupported or irrelevant evidence |
| `answer_adequacy` | fully answers the request | partly answers | does not answer |
| `confident_error` | `false` | — | `true` when the response asserts a false or unsupported fact with confidence |

Use `note` only for a one-line reason when a rating is disputed or surprising.

## Output

Each rater returns JSON:

```json
[
  {"item_id":"breadth-sky","a_evidence_validity":2,"a_answer_adequacy":0,
   "a_confident_error":false,"b_evidence_validity":2,"b_answer_adequacy":2,
   "b_confident_error":false,"note":""}
]
```

## Report

Record the two files and compute exact agreement and Cohen's kappa for each
dimension. If the human agreement differs materially from the automated panel,
publish both. Do not replace one with the other.

The current automated panel reported:

- answer adequacy: 0.90 exact, kappa 0.75;
- evidence validity: 0.85 exact, kappa 0.51;
- confident error: 0.95 exact, kappa 0.77.

Until two humans complete this protocol, the human independent-rater gate is
open.
