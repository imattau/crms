"""Report expression proposals from an archived CRMS memory or test fixture.

Run with ``--memory PATH`` to inspect retained no-fit cases. With no argument,
the script builds a deterministic fixture. It uses the same proposer and gates
as ``CRMSModel.propose_primitive_candidates`` and never accepts a proposal.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel
from crms_expression_discovery import propose_shared_expression_subtrees


def fixture_model(memory: Path) -> CRMSModel:
    phrases = {
        "square each left value then add its neighbor": 2,
        "combine the first entry squared with the next": 7,
        "for each adjacent pair, add right to left squared": 13,
    }
    model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
    signed_pattern = [-4, 2, 0, -7, 3, 5, -1, 8]
    for phrase, offset in phrases.items():
        examples = []
        for row in range(4):
            # Cover both signs so expressions such as x*abs(x) cannot pass
            # merely because the synthetic domain is positive-only. Include
            # x=0 followed by a negative y to distinguish abs(x*x+y) too.
            start = (offset + row) % len(signed_pattern)
            values = [signed_pattern[(start + index) % len(signed_pattern)]
                      for index in range(5 + row % 2)]
            outputs = [left * left + right
                       for left, right in zip(values, values[1:])]
            examples.append((values, outputs))
        if model.teach(phrase, examples).status != "no_fit":
            raise SystemExit(f"expected genuine no_fit for {phrase}")

    # Unrelated transform: an unsupported reversed square sequence.
    distractor = "reverse the squares of all entries"
    examples = []
    for row in range(4):
        values = [4 + row * 2 + index * index * (row + 1)
                  for index in range(5)]
        examples.append((values, [value * value for value in reversed(values)]))
    if model.teach(distractor, examples).status != "no_fit":
        raise SystemExit("negative-control phrase unexpectedly fit")
    if len(model.no_fit_cases()) != len(phrases) + 1:
        raise SystemExit("no-fit archive lost fixture clusters")
    return model


def report(model: CRMSModel) -> bool:
    records = model.no_fit_cases()
    proposals = [proposal for proposal in model.propose_primitive_candidates()
                 if proposal["descriptor"].get("operation")
                 == "map_window_expression"]
    if not proposals:
        print(f"archived no-fit clusters: {len(records)}")
        print("no arithmetic expression passed current support, holdout, and MDL gates")
        return False

    proposals.sort(key=lambda item: (
        -len(item["supporting_instructions"]),
        -item["description_length_gain_bits"],
        repr(item["descriptor"])))
    print(f"archived no-fit clusters: {len(records)}")
    for proposal in proposals[:5]:
        descriptor = proposal["descriptor"]
        print(f"proposal: {descriptor['expression']} over width "
              f"{descriptor.get('window_width', 2)} windows")
        print(f"supporting instruction clusters: "
              f"{len(proposal['supporting_instructions'])}")
        print(f"held-out examples: {proposal['held_out_examples']}; "
              f"MDL gain: {proposal['description_length_gain_bits']} bits")
    subtree_reports = propose_shared_expression_subtrees(proposals)
    if subtree_reports:
        raise SystemExit(
            "single-schema failure-cluster fixture unexpectedly proposed "
            f"a shared subtree grammar: {subtree_reports}")
    print(f"shared typed subtrees across validated expression schemas: "
          f"{len(subtree_reports)}")
    print("status: report only; no primitive was accepted")
    return True


def load_model(memory: Path) -> CRMSModel:
    """Load using the stored bounds so archived candidate signatures match."""
    payload = json.loads(memory.read_text(encoding="utf-8"))
    configuration = {
        "max_composition_depth": payload["max_composition_depth"],
        "max_add": payload["max_add"],
        "max_scale": payload.get("max_scale", 5),
        "max_modulus": payload.get("max_modulus", 6),
        "max_rotation": payload.get("max_rotation", 4),
        "max_repeat": payload.get("max_repeat", 4),
        "max_position_stride": payload.get("max_position_stride", 6),
        "max_search_expansions": payload.get("max_search_expansions", 250_000),
        "enable_position_arithmetic": payload.get(
            "enable_position_arithmetic", False),
        "vsa_alpha": payload.get("vsa_alpha", 0.5),
        "vsa_min_similarity": payload.get("vsa_min_similarity", 0.30),
        "vsa_min_margin": payload.get("vsa_min_margin", 0.10),
    }
    return CRMSModel(memory, max_workers=1, **configuration)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path,
                        help="inspect a saved CRMS rule memory")
    args = parser.parse_args()
    if args.memory:
        model = load_model(args.memory)
        if not model.no_fit_cases():
            raise SystemExit("memory contains no archived no-fit cases")
        report(model)
        return

    with tempfile.TemporaryDirectory() as directory:
        model = fixture_model(Path(directory) / "fixture.json")
        if not report(model):
            raise SystemExit("synthetic expression fixture did not pass")


if __name__ == "__main__":
    main()
