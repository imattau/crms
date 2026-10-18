"""Measure VSA retrieval cost as grounded phrase memory grows.

This isolates the current serial retrieval path from rule induction. Synthetic
phrases share a grounded, in-order query and one known procedure; they do not
add language-learning claims or use an LLM.

Run from the project root with:
    python3 experiments/v1_19_retrieval_scaling_diagnostic.py
"""

from __future__ import annotations

import sys
import random
from itertools import product
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _VSAEncoder


def timed_retrieval(model: CRMSModel, query: str, repetitions: int = 5) -> float:
    samples = []
    for _ in range(repetitions):
        start = perf_counter()
        result = model._retrieve_vsa_procedure(query)
        samples.append(perf_counter() - start)
        if result[0] is None:
            raise RuntimeError("grounded retrieval unexpectedly abstained")
    return median(samples)


def suffix(index: int) -> str:
    """Encode each fixture phrase uniquely with a small shared vocabulary."""
    tokens = []
    for _ in range(5):
        index, digit = divmod(index, 10)
        tokens.append(f"marker{digit}")
    return " ".join(tokens)


def main() -> None:
    encoder = _VSAEncoder(dimension=4)
    vectors = list(product((-1, 0, 1), repeat=4))
    parity_ok = all(
        encoder.similarity(left, right) == encoder.packed_similarity(
            encoder._pack(left), encoder._pack(right))
        for left in vectors for right in vectors
    )
    encoding = _VSAEncoder(dimension=64)
    token_sequences = ([], ["a"], ["a", "b"], ["a", "b", "c"],
                       ["a", "a", "b", "c"], ["z", "y", "x", "w"])
    encoding_ok = all(
        tuple(encoding._pack(vector) for vector in encoding.encode(tokens))
        == encoding.encode_packed(tokens)
        for tokens in token_sequences
    )
    print(f"packed similarity/encoding parity: "
          f"{'PASS' if parity_ok and encoding_ok else 'FAIL'}")
    if not (parity_ok and encoding_ok):
        raise SystemExit("packed VSA differs from the original encoder")
    procedure = (Step("reverse", {}),)

    examples = [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])]
    lifecycle = CRMSModel(max_composition_depth=1, max_workers=1)
    if lifecycle.teach("reverse the list", examples).status != "learned":
        raise SystemExit("could not ground retrieval-index lifecycle fixture")
    lifecycle._retrieve_vsa_procedure("reverse the list")  # build the index
    if lifecycle.teach("flip the entries", examples).status != "learned":
        raise SystemExit("could not add a phrase after index creation")
    added_visible = lifecycle._retrieve_vsa_procedure("flip the entries")[0] is not None
    lifecycle.forget("flip the entries")
    forgotten_hidden = lifecycle._retrieve_vsa_procedure("flip the entries")[0] is None
    print(f"index learn/forget invalidation: "
          f"{'PASS' if added_visible and forgotten_hidden else 'FAIL'}")
    if not (added_visible and forgotten_hidden):
        raise SystemExit("retrieval index did not track memory mutations")

    # Dense individual postings can still have a selective exact intersection.
    # Keep every candidate's shared rule identical so this checks pruning,
    # not a change in ranking policy.
    selective = CRMSModel(max_composition_depth=1, max_workers=1)
    rng = random.Random(190)
    for index in range(3_000):
        tokens = []
        for token, probability in (("reverse", 0.76), ("the", 0.62),
                                   ("list", 0.60)):
            if rng.random() < probability:
                tokens.append(token)
        tokens.append(f"case{index}")
        selective._procedures[" ".join(tokens)] = procedure
    selective._procedures["reverse the list exact"] = procedure
    postings = selective._ensure_vsa_token_index()
    dense_sizes = [len(postings[token]) for token in ("reverse", "the", "list")]
    intersection_size = len(postings["reverse"] & postings["the"] & postings["list"])
    if (min(dense_sizes) <= len(selective._procedures) // 2
            or intersection_size >= min(dense_sizes) // 2
            or selective._retrieve_vsa_procedure("reverse the list")[0] != procedure):
        raise SystemExit("dense-posting intersection failed to retain grounded retrieval")
    print("dense-posting intersection retrieval: PASS")

    print("CRMS VSA retrieval scaling diagnostic")
    print("common-token and shared-vocabulary multiword workload")
    print("grounded phrases | cold-common | warm-common | warm-combo | correct")
    query = "reverse the list"
    for count in (100, 1_000, 5_000, 20_000, 50_000):
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        for index in range(count):
            # Distinct suffixes keep phrases unique while the query remains an
            # in-order subsequence of every candidate.
            phrase = f"reverse the list {suffix(index)}"
            model._procedures[phrase] = procedure
        start = perf_counter()
        cold_result = model._retrieve_vsa_procedure(query)
        cold_elapsed = perf_counter() - start
        if cold_result[0] is None:
            raise RuntimeError("cold grounded retrieval unexpectedly abstained")
        common_elapsed = timed_retrieval(model, query)
        combo_query = f"reverse the list {suffix(count // 2)}"
        combo_elapsed = timed_retrieval(model, combo_query)
        common_found = model._retrieve_vsa_procedure(query)[0]
        combo_found = model._retrieve_vsa_procedure(combo_query)[0]
        common_correct = common_found == procedure
        combo_correct = combo_found == procedure
        negative_gates = all(
            model._retrieve_vsa_procedure(negative)[0] is None
            for negative in (
                "list reverse the",       # known tokens, wrong order
                "reverse reverse the list",  # query token multiplicity is absent
                "reverse the unknown",    # no posting for one query token
            )
        )
        print(f"{count:16d} | {cold_elapsed:11.4f} | {common_elapsed:11.4f} | "
              f"{combo_elapsed:10.6f} | "
              f"{common_correct and combo_correct and negative_gates}")
        if not (common_correct and combo_correct and negative_gates):
            raise SystemExit("retrieval failed to preserve the grounded behavior")
        del model

        # A separate fixture gives each phrase one genuinely rare lexical item.
        # Only the matching phrase should need vector encoding after postings
        # have reduced the candidate set to one.
        unique_model = CRMSModel(max_composition_depth=1, max_workers=1)
        for index in range(count):
            unique_model._procedures[
                f"reverse the list landmark{index}"] = procedure
        unique_query = f"reverse the list landmark{count // 2}"
        start = perf_counter()
        unique_cold = unique_model._retrieve_vsa_procedure(unique_query)
        unique_cold_elapsed = perf_counter() - start
        unique_warm_elapsed = timed_retrieval(unique_model, unique_query)
        unique_correct = unique_cold[0] == procedure
        print(f"{count:16d} | unique-word cold={unique_cold_elapsed:.4f}s "
              f"warm={unique_warm_elapsed:.6f}s | correct={unique_correct}")
        if not unique_correct:
            raise SystemExit("unique-word retrieval failed")


if __name__ == "__main__":
    main()
