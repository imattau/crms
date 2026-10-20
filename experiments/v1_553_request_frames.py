"""Contract tests for learned request frames.

A frame is licensed only by varied grounded examples, matches literal tokens
exactly, parses typed slots, refuses adjacent free-text slots without a
boundary, and never executes an ambiguous match.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_request_frames import (  # noqa: E402
    FrameExample, RequestFrameError, RequestFrameStore,
)


SEED = PROJECT / "crms_request_frames_seed.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    store = RequestFrameStore()
    require(store.add_seed_file(SEED) == 58,
            "seed file did not load the expected example count")
    require(store.add_seed_file(SEED) == 0,
            "seed examples were not deduplicated")
    frames = store.frames()
    require(len(frames) == 29,
            f"expected 29 derived seed frames, got {len(frames)}")
    require(all(len(frame.examples) >= 2 for frame in frames),
            "a licensed frame has fewer than two examples")

    linked = store.match(
        "Which values in 23, 5, and 8 does Mira reach, and what do they "
        "sum to?")
    require(linked.status == "matched" and linked.match is not None,
            f"linked frame did not match: {linked}")
    require(linked.match.slots["values"] == (23, 5, 8),
            f"integer-list slot parsed incorrectly: {linked.match.slots}")
    require(linked.match.slots["claim"] == "Mira reach",
            f"claim slot parsed incorrectly: {linked.match.slots}")
    require(linked.match.frame.fixed_procedure == "sum every value",
            "linked frame lost its fixed procedure")

    reordered = store.match(
        "Mira reaches some of 23, 5, 23, and 8. Sum every value.")
    require(reordered.status == "matched"
            and reordered.match is not None
            and reordered.match.slots["values"] == (23, 5, 23, 8)
            and reordered.match.slots["procedure"] == "Sum every value",
            f"sentence boundary did not separate two slots: {reordered}")

    unknown = store.match(
        "Which numbers in 23, 5, and 8 does Mira reach, and what do they "
        "sum to?")
    require(unknown.status == "no_match",
            f"unlicensed wording matched a frame: {unknown}")

    invalid_values = store.match(
        "From values 1, cat, keep only the values Mira reaches, then sum the "
        "values.")
    require(invalid_values.status == "no_match",
            f"non-integer value entered an integer-list slot: {invalid_values}")
    too_many = ", ".join(str(number) for number in range(1, 34))
    over_bound = store.match(
        f"From values {too_many}, keep only the values Mira reaches, then "
        "sum the values.")
    require(over_bound.status == "no_match",
            f"oversized value list entered an integer-list slot: {over_bound}")

    # Licensing requires two examples and variation in at least one slot.
    learner = RequestFrameStore()
    first = learner.add_example(
        "Send {values:integer-list:1, 2} to {claim:claim:Mira reaches}.",
        "select-then-procedure", "lesson:frame:1", "sum every value")
    require(first.status == "need_more_examples",
            f"one example licensed a frame: {first}")
    duplicate = learner.add_example(
        "Send {values:integer-list:1, 2} to {claim:claim:Mira reaches}.",
        "select-then-procedure", "lesson:frame:1b", "sum every value")
    require(duplicate.status == "need_more_examples",
            f"an unvaried duplicate licensed a frame: {duplicate}")
    second = learner.add_example(
        "Send {values:integer-list:3, 4} to {claim:claim:Nia reaches}.",
        "select-then-procedure", "lesson:frame:2", "sum every value")
    require(second.status == "licensed" and second.frame is not None,
            f"two varied examples did not license a frame: {second}")
    learned = learner.match("Send 8, 9 to Mira reaches.")
    require(learned.status == "matched" and learned.match is not None
            and learned.match.slots["values"] == (8, 9)
            and learned.match.slots["claim"] == "Mira reaches"
            and learned.match.frame.fixed_procedure == "sum every value",
            f"newly licensed frame did not match: {learned}")

    # A missing literal token is not guessed.
    require(learner.match("Please send 8, 9 to Mira reaches.").status == "no_match",
            "extra literal wording still matched an exact frame")

    # Two distinct licensed templates matching the same text are ambiguous.
    ambiguous = RequestFrameStore()
    for text, source in (
            ("Do {values:integer-list:1, 2} for {claim:claim:Mira reaches}.",
             "ambiguous:claim:1"),
            ("Do {values:integer-list:3, 4} for {claim:claim:Nia reaches}.",
             "ambiguous:claim:2"),
            ("Do {values:integer-list:5, 6} for {target:text:Mira reaches}.",
             "ambiguous:target:1"),
            ("Do {values:integer-list:7, 8} for {target:text:Nia reaches}.",
             "ambiguous:target:2"),
            ("Do {values:integer-list:9, 10} for {claim:claim:Tavi reaches}.",
             "ambiguous:claim:3"),
            ("Do {values:integer-list:11, 12} for {target:text:Tavi reaches}.",
             "ambiguous:target:3")):
        ambiguous.add_example(
            text, "select-then-procedure", source, "sum every value")
    collision = ambiguous.match("Do 9, 10 for Mira reaches.")
    require(collision.status == "ambiguous" and len(collision.matches) == 2,
            f"two licensed frames were not ambiguous: {collision}")

    # Adjacent free-text slots are refused at learning time unless a literal
    # or sentence boundary separates them.
    try:
        learner.add_example(
            "Keep {claim:claim:Mira reaches} {target:text:the values}.",
            "select-then-procedure", "lesson:adjacent", None)
    except RequestFrameError:
        pass
    else:
        raise SystemExit("adjacent free-text slots were accepted")

    with tempfile.TemporaryDirectory(prefix="crms-frames-") as directory:
        path = Path(directory) / "frames.json"
        store.save(path)
        loaded = RequestFrameStore.load(path)
        require(loaded.frames() == store.frames(),
                "saved frames did not round-trip deterministically")
        require(loaded.match(
            "Filter 23, 5, 23, and 8 to values Mira reaches, then sum the "
            "values.").status == "matched",
            "reloaded frame store no longer matches")

    require(any("frame-" in line and "goal=" in line
                for line in store.describe()),
            "frame listing is not inspectable")

    print("seed licensing, exact matching, and typed slots: PASS")
    print("variation-gated learning and persistence: PASS")
    print("ambiguous, unlicensed, and malformed requests are refused: PASS")


if __name__ == "__main__":
    main()
