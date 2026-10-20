"""Parity and abstention tests for learned request frames in composition.

The frame path must reproduce the reference composition on licensed, bounded
wording, and it must not execute unknown, ambiguous, incomplete, conflicting, or
untaught requests.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_500_learned_and_reasoned_composition import learn_components  # noqa: E402
from v1_502_reasoned_numeric_aggregation import (  # noqa: E402
    build_knowledge, sum_training_data,
)
from v1_503_sum_first_reasoned_composition import teach_sum_phrase  # noqa: E402
from v1_507_reasoned_count_aggregation import teach_count  # noqa: E402
from v1_509_taught_operation_phrase_recombines_list_first import (  # noqa: E402
    teach_phrase,
)

from crms_request_frames import RequestFrameStore  # noqa: E402
from crms_task_composition import (  # noqa: E402
    compose_verified_filter, compose_verified_filter_via_frames,
    create_derived_composition_record, revalidate_derived_composition,
)


FIELDS = (
    "status", "text", "subject", "relation", "input_values",
    "included_values", "excluded_negative", "unresolved_values",
    "output_values", "procedure", "evidence_sources", "proof_checks",
    "evidence", "inference_proofs", "procedure_records", "language_evidence",
)

REQUESTS = (
    "Which values in 23, 5, 23, and 8 does Mira reach, and what do they sum to?",
    "What is the total of the values Mira reaches among 23, 5, 23, and 8?",
    "What is the total of the values that Mira reaches among 23, 5, 23, and 8?",
    "From values 23, 5, 23, and 8, keep only the values Mira reaches, then "
    "sum the values.",
    "From values 4, 12, 4, 9, and 7, keep only the values Mira reaches, then "
    "remove duplicate values then reverse the list.",
    "From values 4, 12, 4, 9, and 7, keep only the values that Mira can reach, "
    "then remove duplicate values then reverse the list.",
    "Filter 23, 5, 23, and 8 to values Mira reaches, then sum the values.",
    "Filter 23, 5, 23, and 8 to the values Mira reaches, then sum the values.",
    "Given 23, 5, 23, and 8, keep the values Mira reaches, and then sum the "
    "values.",
    "Given 23, 5, 23, and 8, keep only the values Mira reaches, and then sum "
    "the values.",
    "From [23, 5, 23, 8], return the values Mira reaches, then sum the values.",
    "From [23, 5, 23, 8], return values Mira reaches, then remove duplicate "
    "values and reverse the list.",
    "Please filter [23, 5, 23, 8] to the values Mira reaches, then sum the "
    "values.",
    "Sum every value in 23, 5, 23, and 8 that Mira reaches.",
    "Mira reaches some of 23, 5, 23, and 8. Sum every value.",
    "Count the matching entries among 23, 5, 23, and 8 that Mira reaches.",
    "From 23, 5, 23, and 8, add together only the numbers Mira reaches.",
    "From 23, 5, 23, and 8, keep the values Mira reaches, then add up every "
    "value.",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def snapshot(result):
    if result is None:
        return None
    return tuple(getattr(result, name) for name in FIELDS)


def parity(request: str, knowledge, procedures, frames) -> None:
    reference = compose_verified_filter(request, knowledge, procedures)
    framed = compose_verified_filter_via_frames(
        request, knowledge, procedures, frames)
    require(framed is not None and framed.request_frame_id is not None,
            f"licensed request did not use a frame: {request!r}: {framed}")
    require(snapshot(reference) == snapshot(framed),
            f"frame/reference mismatch for {request!r}\n"
            f"  reference: {snapshot(reference)}\n"
            f"  frame:     {snapshot(framed)}")


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)
    teach_count(procedures)
    teach_phrase(procedures)
    frames = RequestFrameStore()
    frames.add_seed_file(PROJECT / "crms_request_frames_seed.json")

    for request in REQUESTS:
        parity(request, knowledge, procedures, frames)

    unknown_wording = (
        "Which numbers in 23, 5, and 8 does Mira reach, and what do they "
        "sum to?")
    require(frames.match(unknown_wording).status == "no_match"
            and compose_verified_filter_via_frames(
                unknown_wording, knowledge, procedures, frames) is None,
            "unknown wording entered the frame composition path")

    unknown_values = (
        "From values 23, 5, 11, and 8, keep only the values Mira reaches, "
        "then sum the values.")
    parity(unknown_values, knowledge, procedures, frames)
    unknown_result = compose_verified_filter_via_frames(
        unknown_values, knowledge, procedures, frames)
    require(unknown_result is not None
            and unknown_result.status == "unknown"
            and unknown_result.unresolved_values == (11,)
            and not unknown_result.output_values,
            f"unknown value was not blocked: {unknown_result}")

    conflict = copy.deepcopy(knowledge)
    conflict.add_negative_fact("Mira", "reaches", "23", "conflict:record-23")
    conflict_request = (
        "Which values in 23, 5, 23, and 8 does Mira reach, and what do they "
        "sum to?")
    parity(conflict_request, conflict, procedures, frames)
    conflict_result = compose_verified_filter_via_frames(
        conflict_request, conflict, procedures, frames)
    require(conflict_result is not None
            and conflict_result.status == "conflict"
            and not conflict_result.output_values,
            f"positive/negative conflict was not blocked: {conflict_result}")

    untaught = (
        "From values 23, 5, 23, and 8, keep only the values Mira reaches, "
        "then deduplicate the values then reverse the list.")
    parity(untaught, knowledge, procedures, frames)
    untaught_result = compose_verified_filter_via_frames(
        untaught, knowledge, procedures, frames)
    require(untaught_result is not None
            and untaught_result.status == "unsupported_procedure"
            and not untaught_result.output_values,
            f"untaught procedure executed: {untaught_result}")

    # A licensed wording with an unlearnt aggregate phrase must abstain with a
    # procedure clarification. The legacy generic path may fall through instead.
    alias = "Add up every value in 23, 5, 23, and 8 that Mira reaches."
    alias_result = compose_verified_filter_via_frames(
        alias, knowledge, procedures, frames)
    require(alias_result is not None
            and alias_result.status == "unsupported_procedure"
            and not alias_result.output_values,
            f"unlearnt aggregate alias executed: {alias_result}")

    # A frame collision never executes either candidate.
    ambiguous = RequestFrameStore()
    for text, source in (
            ("Do {values:integer-list:1, 2} for {claim:claim:Mira reaches}.",
             "ambiguous:claim:1"),
            ("Do {values:integer-list:3, 4} for {claim:claim:Nia reaches}.",
             "ambiguous:claim:2"),
            ("Do {values:integer-list:5, 6} for {target:text:Mira reaches}.",
             "ambiguous:target:1"),
            ("Do {values:integer-list:7, 8} for {target:text:Nia reaches}.",
             "ambiguous:target:2")):
        ambiguous.add_example(
            text, "select-then-procedure", source, "sum every value")
    ambiguous_result = compose_verified_filter_via_frames(
        "Do 9, 10 for Mira reaches.", knowledge, procedures, ambiguous)
    require(ambiguous_result is not None
            and ambiguous_result.status == "ambiguous"
            and not ambiguous_result.output_values,
            f"ambiguous frame executed: {ambiguous_result}")

    # Derived compositions remember the licensing frame. Revalidation succeeds
    # only while that frame still matches, so removing it marks the artifact
    # stale instead of silently switching to the reference parser.
    answered_request = (
        "Which values in 23, 5, 23, and 8 does Mira reach, and what do they "
        "sum to?")
    answered = compose_verified_filter_via_frames(
        answered_request, knowledge, procedures, frames)
    require(answered is not None and answered.status == "answered"
            and answered.request_frame_id is not None,
            f"derived-frame fixture did not answer: {answered}")
    artifact = create_derived_composition_record(
        answered_request, answered, knowledge)
    require(artifact is not None
            and artifact.get("request_frame_id") == answered.request_frame_id,
            f"derived artifact lost its frame id: {artifact}")
    validity, _reason = revalidate_derived_composition(
        artifact, knowledge, procedures, frames)
    require(validity == "current",
            f"current frame artifact did not revalidate: {validity}")
    without_frames = RequestFrameStore()
    validity, reason = revalidate_derived_composition(
        artifact, knowledge, procedures, without_frames)
    require(validity == "stale" and "frame" in reason,
            f"removed frame did not stale its artifact: {validity} {reason}")

    print("licensed frame/reference parity (18 requests): PASS")
    print("unknown wording, unknown values, conflict, and untaught controls: PASS")
    print("licensed unlearnt alias and ambiguous collision abstain: PASS")
    print("derived artifact stays tied to its licensing frame: PASS")


if __name__ == "__main__":
    main()
