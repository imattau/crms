"""Report behavior-based conjectures about CRMS procedure equivalence.

This is a diagnostic only. It never changes ``_semantic_key`` or prunes live
rule search. Any reported law needs an exact proof before it can affect
learning.

Run the default probe and holdout:
    python3 crms_equivalence_dream.py --output /tmp/crms-equivalence.json

Try a deliberately weak probe:
    python3 crms_equivalence_dream.py --no-exhaustive-short --random-probes 150
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import itertools
import json
from pathlib import Path
import random
from typing import Iterable

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


DEFAULT_PROBE_SEED = 104729
DEFAULT_HOLDOUT_SEED = 130363


def _procedure_record(procedure: tuple[Step, ...]) -> list[dict]:
    return [{"operation": step.operation,
             "parameters": dict(sorted(step.parameters.items()))}
            for step in procedure]


def _behavior_digest(procedure: tuple[Step, ...],
                     inputs: Iterable[list[int]]) -> str:
    """Hash a sequence of exact outputs using an unambiguous encoding."""
    digest = sha256()
    for values in inputs:
        output = _apply_procedure(procedure, values)
        encoded = ",".join(str(value) for value in output).encode("ascii")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _random_lists(seed: int, count: int, *, minimum_length: int,
                  maximum_length: int, minimum_value: int,
                  maximum_value: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randint(minimum_value, maximum_value)
             for _ in range(rng.randint(minimum_length, maximum_length))]
            for _ in range(count)]


def _probe_lists(*, exhaustive_short: bool, random_count: int,
                 random_seed: int) -> list[list[int]]:
    probes: list[list[int]] = []
    if exhaustive_short:
        probes.extend(list(values)
                      for length in range(5)
                      for values in itertools.product(range(-3, 4), repeat=length))
    probes.extend(_random_lists(
        random_seed, random_count, minimum_length=0, maximum_length=10,
        minimum_value=-15, maximum_value=20))
    return probes


def _enumerate_depth_two(model: CRMSModel) -> list[tuple[Step, ...]]:
    return [(first, second)
            for first in model._steps for second in model._steps]


def analyze(*, exhaustive_short: bool = True, random_probes: int = 2_000,
            holdout_size: int = 3_000,
            probe_seed: int = DEFAULT_PROBE_SEED,
            holdout_seed: int = DEFAULT_HOLDOUT_SEED) -> dict:
    """Group depth-two programs by probe behavior, then validate on holdout."""
    if type(random_probes) is not int or random_probes < 0:
        raise ValueError("random_probes must be a non-negative integer")
    if type(holdout_size) is not int or holdout_size < 1:
        raise ValueError("holdout_size must be a positive integer")
    if type(exhaustive_short) is not bool:
        raise ValueError("exhaustive_short must be bool")

    model = CRMSModel(max_composition_depth=2, max_workers=1)
    procedures = _enumerate_depth_two(model)
    probes = _probe_lists(exhaustive_short=exhaustive_short,
                          random_count=random_probes,
                          random_seed=probe_seed)
    holdout = _random_lists(
        holdout_seed, holdout_size, minimum_length=0, maximum_length=10,
        minimum_value=-15, maximum_value=20)

    behavior_groups: dict[str, list[tuple[Step, ...]]] = defaultdict(list)
    for procedure in procedures:
        behavior_groups[_behavior_digest(procedure, probes)].append(procedure)

    conjectures = []
    rejected = []
    for probe_digest, members in sorted(behavior_groups.items()):
        semantic_groups: dict[str, list[tuple[Step, ...]]] = defaultdict(list)
        for procedure in members:
            semantic = _semantic_key(procedure)
            semantic_groups[repr(semantic)].append(procedure)
        if len(semantic_groups) < 2:
            continue

        holdout_signatures = {
            _behavior_digest(procedure, holdout) for procedure in members
        }
        record = {
            "probe_behavior_sha256": probe_digest,
            "probe_member_count": len(members),
            "semantic_key_count": len(semantic_groups),
            "holdout_behavior_sha256": (
                next(iter(holdout_signatures))
                if len(holdout_signatures) == 1 else None),
            "programs": [_procedure_record(procedure) for procedure in members],
        }
        if len(holdout_signatures) == 1:
            conjectures.append(record)
        else:
            rejected.append(record | {
                "holdout_behavior_count": len(holdout_signatures),
                "reason": "members disagree on independent holdout",
            })

    warnings = []
    if rejected:
        warnings.append(
            f"{len(rejected)} probe group(s) merged distinct behaviors that "
            "disagreed on holdout; they are excluded from conjectures.")
    if not exhaustive_short and random_probes < 1_000:
        warnings.append(
            "Probe is intentionally weak: no exhaustive short-list set and "
            "fewer than 1,000 random lists.")

    return {
        "format": "crms-equivalence-dream-v1",
        "policy": "report-only; conjectures never prune live search",
        "configuration": {
            "step_count": len(model._steps),
            "program_count": len(procedures),
            "exhaustive_short": exhaustive_short,
            "exhaustive_value_range": ({"minimum": -3, "maximum": 3}
                                        if exhaustive_short else None),
            "exhaustive_max_length": 4 if exhaustive_short else None,
            "random_probe_count": random_probes,
            "random_probe_seed": probe_seed,
            "holdout_count": holdout_size,
            "holdout_seed": holdout_seed,
        },
        "probe_count": len(probes),
        "probe_behavior_class_count": len(behavior_groups),
        "conjecture_count": len(conjectures),
        "rejected_group_count": len(rejected),
        "warnings": warnings,
        "conjectures": conjectures,
        "rejected_groups": rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="write the JSON report here; default is stdout")
    parser.add_argument("--random-probes", type=int, default=2_000)
    parser.add_argument("--holdout-size", type=int, default=3_000)
    parser.add_argument("--probe-seed", type=int, default=DEFAULT_PROBE_SEED)
    parser.add_argument("--holdout-seed", type=int, default=DEFAULT_HOLDOUT_SEED)
    parser.add_argument("--exhaustive-short", action=argparse.BooleanOptionalAction,
                        default=True)
    args = parser.parse_args()
    report = analyze(
        exhaustive_short=args.exhaustive_short,
        random_probes=args.random_probes,
        holdout_size=args.holdout_size,
        probe_seed=args.probe_seed,
        holdout_seed=args.holdout_seed)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {report['conjecture_count']} conjectures and "
              f"{report['rejected_group_count']} rejected groups to {args.output}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
