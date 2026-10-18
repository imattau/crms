"""Ensure explicit `, then` composition is compared with retrieval routes."""
from __future__ import annotations

import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "experiments")]

from crms_model import CRMSModel
from crms_chat import _print_candidate_routes


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    sort_examples = [
        ([3, 1, 2], [1, 2, 3]),
        ([5, -1, 4], [-1, 4, 5]),
        ([4, 1, 4, -2], [-2, 1, 4, 4]),
    ]
    add_examples = [
        ([1, 3, 2], [2, 4, 3]),
        ([6, -1, 4], [7, 0, 5]),
        ([1, 3, 1, 2], [2, 4, 2, 3]),
        ([-3, 0], [-2, 1]),
    ]
    for phrase, examples in (("sort the list", sort_examples),
                             ("add one to values", add_examples)):
        if model.teach(phrase, examples).status != "learned":
            raise SystemExit(f"component fixture failed: {phrase}")

    # Teach a competing full-phrase positional frame under search depth one,
    # so the phrases are valid one-step examples despite containing a connective.
    model.max_composition_depth = 1
    reverse_examples = [
        ([1, 2, 3], [3, 2, 1]),
        ([3, 7, -2], [-2, 7, 3]),
        ([8, 0, 4], [4, 0, 8]),
    ]
    for phrase in (
            "sort the list then add one to numbers",
            "sort the list then add two to values",
            "reverse the list then add two to values",
            "reverse the array then add one to numbers"):
        if model.teach(phrase, reverse_examples).status != "learned":
            raise SystemExit(f"analogy fixture failed: {phrase}")
    model.max_composition_depth = 2

    query = "sort the list, then add one to values"
    explanation = None
    for values in ([3, 1, 2], [], [-4, 9, 0], [0], [5, -2, 5]):
        result = model.predict(query, values)
        if (result.status != "need_examples" or result.output is not None
                or "competing rules" not in (result.request or "")
                or result.contrastive_input is None
                or result.candidate_outputs is None
                or len({tuple(output) for output in result.candidate_outputs}) < 2
                or not result.candidate_routes
                or {tuple(item.get("probe_output") or [])
                    for item in result.candidate_routes}
                != {tuple(output) for output in result.candidate_outputs}
                or not {"sort the list", "add one to values"}
                <= set(result.evidence_phrases or ())):
            raise SystemExit(
                f"explicit composition overrode a competing route: {result}")
        explanation = result

    if explanation is None or not explanation.candidate_routes:
        raise SystemExit("route alternatives were not retained for the teacher")
    captured = StringIO()
    with redirect_stdout(captured):
        _print_candidate_routes(explanation)
    rendered = captured.getvalue()
    if ("explicit sequence composition" not in rendered
            or "positional analogy" not in rendered
            or "sort_ascending" not in rendered
            or "reverse" not in rendered
            or f"on {explanation.contrastive_input}:" not in rendered):
        raise SystemExit(f"clarification omitted competing rule details: {rendered}")

    print("explicit `, then` composition vs positional analogy: PASS")
    print("five input shapes, contrastive probe, component provenance, "
          "and teacher-visible alternatives: PASS")


if __name__ == "__main__":
    main()
