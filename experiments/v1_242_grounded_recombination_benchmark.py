"""Measure discrete phrase recombination and abstention in CRMS.

This deterministic benchmark generates a known grid of taught phrase parts,
measures held-out combinations at increasing numbers of taught phrases, and
checks controlled negative wordings. It also checks the current evidence-
anchored article normalization for fact questions. This is a generated
diagnostic, not a human paraphrase benchmark or a general language score.

Run from the project root with:
    python3 experiments/v1_242_grounded_recombination_benchmark.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_text import tokens


VERBS = ("reverse", "invert", "turn", "flip")
NOUNS = ("list", "values", "sequence", "entries")
K_VALUES = (1, 2, 4, 8, 12)
TRAINING_EXAMPLES = (
    ([1, 2, 3], [3, 2, 1]),
    ([4, -1, 7], [7, -1, 4]),
)
HELD_OUT_INPUTS = ([17, -3, 0, 4], [2, 2, -1])
NEGATIVE_PHRASES = (
    "list the reverse",             # known words, unsupported order
    "the reverse list",             # known words, unsupported order
    "reverse the widget",           # unsupported entity head
    "rotate the values",            # unsupported operation
    "reverse please the list",      # unsupported modifier placement
)
HAND_AUTHORED_UNSEEN_WORDINGS = (
    "Put the numbers in reverse order",
    "List these values backwards",
    "Please arrange the sequence backwards",
    "Take the list and reverse it",
    "Return the entries from last to first",
    "Flip this collection around",
    "Reorder the values in the opposite direction",
    "Turn around the supplied sequence",
    "Move each element to its mirrored position",
    "Reverse every item in the input",
)


def phrase_grid() -> list[str]:
    """Return a balanced deterministic grid order with held-out crossings."""
    return [f"{VERBS[(row + column) % len(VERBS)]} the {NOUNS[column]}"
            for row in range(len(VERBS))
            for column in range(len(NOUNS))]


def question_frame_check() -> dict[str, object]:
    knowledge = CRMSKnowledgeBase()
    for subject, obj, source in (("Alice", "tea", "source:tea"),
                                 ("Bob", "coffee", "source:coffee")):
        knowledge.add_fact(subject, "likes", obj, source)
        knowledge.teach_question(
            f"Who likes {obj}?", relation="likes", answer_field="subject",
            bound_entity=obj, answer=subject)

    questions = ("Who likes tea?", "who likes tea", "Who likes the tea?")
    results = [knowledge.ask(question) for question in questions]
    rendered = [knowledge.render(result) for result in results]
    signatures = [(
        result.status, result.answer, tuple(result.matched_templates or ()),
        tuple(json.dumps(item, sort_keys=True) for item in result.evidence or ()))
        for result in results]
    negatives = {
        question: knowledge.ask(question)
        for question in ("Who likes the?", "Who hates tea?")
    }
    taught_surfaces = {
        tuple(tokens(f"Who likes {obj}?")) for obj in ("tea", "coffee")}
    exact_frame_baseline = sum(
        tuple(tokens(question)) in taught_surfaces for question in questions)
    return {
        "questions": list(questions),
        "same_answer_and_trace": len(set(signatures)) == 1,
        "exact_frame_baseline_coverage": f"{exact_frame_baseline}/{len(questions)}",
        "normalized_question_coverage": f"{sum(result.status == 'answered' for result in results)}/{len(results)}",
        "answer": results[0].answer,
        "matched_templates": results[0].matched_templates,
        "rendered_question_frames": [
            next((line for line in text.splitlines()
                  if line.startswith("Matched question frame:")), None)
            for text in rendered],
        "negative_statuses": {
            question: result.status for question, result in negatives.items()},
        "negative_requests": {
            question: result.request for question, result in negatives.items()},
        "passed": (len(set(signatures)) == 1
                   and results[0].status == "answered"
                   and results[0].answer == "Alice"
                   and all("Matched question frame:" in text
                           for text in rendered)
                   and all(result.status == "unknown"
                           for result in negatives.values())),
    }


def run_benchmark() -> dict[str, object]:
    phrases = phrase_grid()
    hand_authored_model = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in phrases[:12]:
        hand_authored_model.teach(phrase, TRAINING_EXAMPLES)
    rows = []
    for k in K_VALUES:
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        for phrase in phrases[:k]:
            learned = model.teach(phrase, TRAINING_EXAMPLES)
            if learned.status != "learned":
                raise RuntimeError(
                    f"could not teach generated phrase {phrase!r}: {learned}")

        held_out = phrases[k:]
        correct = wrong = abstained = total = 0
        for phrase in held_out:
            for values in HELD_OUT_INPUTS:
                total += 1
                prediction = model.predict(phrase, values)
                expected = list(reversed(values))
                if prediction.status != "ok":
                    abstained += 1
                elif prediction.output == expected:
                    correct += 1
                else:
                    wrong += 1

        negative_wrong = []
        for phrase in NEGATIVE_PHRASES:
            prediction = model.predict(phrase, [5, -2, 8])
            if prediction.status == "ok":
                negative_wrong.append({
                    "phrase": phrase, "output": prediction.output})

        rows.append({
            "training_phrase_count": k,
            "held_out_wordings": len(held_out),
            "held_out_cases": total,
            "correct": correct,
            "wrong": wrong,
            "abstained": abstained,
            "coverage": (correct / total if total else None),
            "exact_match_baseline_coverage": 0.0,
            "controlled_negative_count": len(NEGATIVE_PHRASES),
            "controlled_negative_answers": negative_wrong,
            "controlled_negative_abstention_rate": (
                (len(NEGATIVE_PHRASES) - len(negative_wrong))
                / len(NEGATIVE_PHRASES)),
        })

    question = question_frame_check()
    result: dict[str, object] = {
        "benchmark": "crms-grounded-language-recombination-v1",
        "seed": "deterministic-grid",
        "generated_positive_phrases": phrases,
        "held_out_inputs": [list(values) for values in HELD_OUT_INPUTS],
        "controlled_negative_phrases": list(NEGATIVE_PHRASES),
        "hand_authored_unseen_wordings": list(HAND_AUTHORED_UNSEEN_WORDINGS),
        "hand_authored_wording_results": {
            phrase: hand_authored_model.predict(phrase, [1, 2, 3]).status
            for phrase in HAND_AUTHORED_UNSEEN_WORDINGS
        },
        "rule_recombination": rows,
        "question_article_normalization": question,
    }
    if any(row["wrong"] for row in rows):
        raise RuntimeError(f"recombination produced wrong unique outputs: {rows}")
    if any(row["controlled_negative_answers"] for row in rows):
        raise RuntimeError(f"a controlled negative wording was answered: {rows}")
    if any(status == "ok" for status in result["hand_authored_wording_results"].values()):
        raise RuntimeError("an unseen hand-authored wording was answered")
    if not question["passed"]:
        raise RuntimeError(f"question article trace check failed: {question}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path,
                        help="also write the machine-readable result to this path")
    args = parser.parse_args()
    result = run_benchmark()
    print("Grounded language recombination; generated phrase grid")
    print(f"{'phrases':>8} {'held-out':>9} {'exact-only':>11} "
          f"{'correct':>9} {'wrong':>7} {'abstain':>9} "
          f"{'coverage':>10} {'negative abstain':>18}")
    for row in result["rule_recombination"]:
        print(f"{row['training_phrase_count']:8d} "
              f"{row['held_out_wordings']:9d} "
              f"{row['exact_match_baseline_coverage']:11.3f} "
              f"{row['correct']:9d} {row['wrong']:7d} "
              f"{row['abstained']:9d} {row['coverage']:10.3f} "
              f"{row['controlled_negative_abstention_rate']:18.3f}")
    question = result["question_article_normalization"]
    print("question article and casing variants: exact-frame baseline "
          f"{question['exact_frame_baseline_coverage']}; normalized "
          f"{question['normalized_question_coverage']}; same trace "
          f"{'PASS' if question['passed'] else 'FAIL'}")
    print("authored unseen wording abstentions: "
          + json.dumps(result["hand_authored_wording_results"], sort_keys=True))
    if args.json_out is not None:
        output = args.json_out.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        print(f"JSON result: {output}")
    print("generated positives wrong=0; controlled negative answers=0; PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
