"""Check that ambiguous retrieval asks for a discriminating example.

The VSA score is an inspectable similarity measure, not a probability. When
two behaviorally distinct grounded cases are too close, prediction must abstain
and request an input whose candidate outputs differ. Teaching that example
under the query phrase then resolves the exact association.

Run from the project root with:
    python3 experiments/v1_22_metacognitive_retrieval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = (
        ("please reverse list", [([1, 2, 3], [3, 2, 1]),
                                 ([3, 1, 4], [4, 1, 3])]),
        # Avoid cyclically ordered lists: after adding rotation primitives,
        # the old sort examples also fit a one-place rotation.
        ("please sort array", [([3, -1, 5], [-1, 3, 5]),
                               ([5, -2, 4, 0], [-2, 0, 4, 5])]),
    )
    for phrase, demonstrations in examples:
        result = model.teach(phrase, demonstrations)
        if result.status != "learned":
            raise RuntimeError(f"could not ground {phrase!r}: {result.status}")

    prediction = model.predict("please", [1, 2, 3])
    separating_probe = (
        prediction.status == "need_examples"
        and prediction.retrieval_score is not None
        and prediction.retrieval_margin is not None
        and prediction.retrieval_margin < model.vsa_min_margin
        and prediction.contrastive_input is not None
        and prediction.candidate_outputs is not None
        and len(set(map(tuple, prediction.candidate_outputs))) > 1
    )
    print(
        f"ambiguous query: {prediction.status}; "
        f"score={prediction.retrieval_score}; margin={prediction.retrieval_margin}; "
        f"probe={prediction.contrastive_input}; "
        f"outputs={prediction.candidate_outputs}; "
        f"{'PASS' if separating_probe else 'FAIL'}"
    )
    if not separating_probe:
        raise SystemExit(1)

    low_similarity_model = CRMSModel(
        max_composition_depth=1, max_workers=1,
        vsa_min_similarity=0.9, vsa_min_margin=0.0,
    )
    for phrase, demonstrations in examples:
        low_similarity_model.teach(phrase, demonstrations)
    low_similarity = low_similarity_model.predict("please", [1, 2, 3])
    low_similarity_probe = (
        low_similarity.status == "need_examples"
        and low_similarity.retrieval_score is not None
        and low_similarity.retrieval_score < low_similarity_model.vsa_min_similarity
        and low_similarity.retrieval_margin is not None
        and low_similarity.retrieval_margin >= low_similarity_model.vsa_min_margin
        and low_similarity.contrastive_input is not None
        and low_similarity.candidate_outputs is not None
        and len(set(map(tuple, low_similarity.candidate_outputs))) > 1
    )
    print(
        f"low-similarity abstention: score={low_similarity.retrieval_score}; "
        f"margin={low_similarity.retrieval_margin}; "
        f"probe={low_similarity.contrastive_input}; "
        f"{'PASS' if low_similarity_probe else 'FAIL'}"
    )
    if not low_similarity_probe:
        raise SystemExit(1)

    probe = prediction.contrastive_input
    intended = prediction.candidate_outputs[0]
    # Confirm the selected behavior on a second input as part of the teacher's
    # response, so the underlying operation search can distinguish procedures.
    second_input = [2, 0, 1]
    second_output = [1, 0, 2] if intended == [1, 0] else [0, 1, 2]
    taught = model.teach("please", [(probe, intended),
                                    (second_input, second_output)])
    resolved = model.predict("please", [1, 2, 3])
    learns_from_request = (
        taught.status == "learned"
        and resolved.status == "ok"
        and resolved.output == [3, 2, 1]
    )
    print(
        f"after teacher answer: {resolved.status}:{resolved.output}; "
        f"{'PASS' if learns_from_request else 'FAIL'}"
    )
    if not learns_from_request:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
