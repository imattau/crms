"""Check the narrow, self-generated answer-type templates for ranker eval.

Run with: python3 experiments/v1_347_sentence_ranker_cloze_types.py
"""
from __future__ import annotations

from pathlib import Path
import importlib.util


PROJECT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT / "experiments" / "v1_346_fts_sentence_ranker_evaluation.py"
SPEC = importlib.util.spec_from_file_location("ranker_fts_evaluation", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("could not load FTS ranker evaluation module")
RANK_EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RANK_EVAL)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    positives = {
        "WHO": ("Ada Lovelace designed the Analytical Engine.",
                "Ada Lovelace"),
        "WHEN": ("Marie Curie was born in 1867.", "1867"),
        "WHERE": ("Alan Turing was born in London, England.",
                  "London, England"),
        "MEASURE": ("Mount Everest is 8,849 metres tall.", "8,849 metres"),
        "COUNT": ("Marie Curie won two Nobel Prizes.", "two"),
        "DEF": ("Python is a programming language.", "a programming language"),
    }
    for question_type, (sentence, expected_answer) in positives.items():
        generated = RANK_EVAL._question_and_answer(
            sentence, question_type=question_type)
        require(generated is not None and generated[1] == expected_answer,
                f"{question_type} cloze extracted the wrong answer: {generated}")

    for question_type, sentence in (
            ("WHEN", "They were born in 1867."),
            ("WHERE", "It was born in London, England."),
            ("MEASURE", "Mount Everest is not 8,849 metres tall."),
            ("COUNT", "They won two Nobel Prizes."),
            ("DEF", "Python is not a programming language.")):
        require(RANK_EVAL._question_and_answer(
            sentence, question_type=question_type) is None,
            f"{question_type} cloze accepted a pronoun or negated near-miss: {sentence}")

    print("sentence-ranker self-cloze types: PASS")
    print("WHO, WHEN, WHERE, MEASURE, COUNT, DEF plus pronoun/negation near-misses: PASS")


if __name__ == "__main__":
    main()
