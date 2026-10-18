"""Check role recombination for a parameterized successful procedure scaffold."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from itertools import product
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel
from crms_chat import _print_rule_explanation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def examples(amount: int):
    inputs = ([1, 4, -2], [5, -3, 8], [0, 6, -7], [9, 2, 1])
    return [(list(values), list(reversed([value + amount for value in values])))
            for values in inputs]


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "language.json"
        model = CRMSModel(path, max_composition_depth=2, max_workers=1)
        sources = {
            "add 1 to each value then reverse the list": 1,
            "increase 2 to every item then reverse the list": 2,
            "add 3 to every item then reverse the list": 3,
            "increase 4 to each value then reverse the list": 4,
        }
        for phrase, amount in sources.items():
            result = model.teach(phrase, examples(amount))
            require(result.status == "learned"
                    and [step["operation"] for step in result.procedure]
                    == ["add_k", "reverse"],
                    f"source did not learn the shared scaffold: {phrase}: {result}")

        # No source phrase uses this exact combination of role values, and the
        # surface frame differs from every taught phrase.
        query = "add 5 to every value then reverse the list"
        prediction = model.predict(query, [3, -1, 7])
        require(prediction.status == "ok" and prediction.output == [12, 4, 8]
                and prediction.procedure == [
                    {"operation": "add_k", "parameters": {"k": 5}},
                    {"operation": "reverse", "parameters": {}},
                ]
                and set(prediction.evidence_phrases) == set(sources)
                and prediction.matched_templates
                and prediction.matched_templates[0].startswith(
                    "procedure_scaffold_frame:"),
                f"grounded role recombination failed: {prediction}")
        for action, quantifier, item in product(
                ("add", "increase"), ("each", "every"), ("value", "item")):
            variant = (f"{action} 5 to {quantifier} {item} then "
                       "reverse the list")
            result = model.predict(variant, [3, -1, 7])
            require(result.status == "ok" and result.output == [12, 4, 8],
                    f"role combination failed: {variant}: {result}")
        explanation_output = StringIO()
        with redirect_stdout(explanation_output):
            _print_rule_explanation(model, query, [3, -1, 7])
        explanation = explanation_output.getvalue()
        require("Scaffold frame: positional_recombination" in explanation
                and "validated scaffold: procedure-scaffold-v1-" in explanation
                and "word role" in explanation
                and "number slot 1: 5 → step 1 add_k.k=5" in explanation
                and "add 1 to each value then reverse the list" in explanation,
                f"/explain-rule omitted scaffold role/binding evidence: {explanation}")
        model.save()
        cli = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(Path(directory) / "knowledge.json"),
             "--index", str(Path(directory) / "index.json"),
             "--dialogue-state", str(Path(directory) / "dialogue.json"),
             "--rules", str(path),
             "--rule-session", str(Path(directory) / "rule-session.json")],
            input=f"/explain-rule {query}|3,-1,7\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(cli.returncode == 0
                and "Scaffold frame: positional_recombination" in cli.stdout
                and "number slot 1: 5 → step 1 add_k.k=5" in cli.stdout
                and "add 1 to each value then reverse the list" in cli.stdout,
                f"terminal /explain-rule omitted scaffold trace:\n{cli.stdout}\n{cli.stderr}")

        # Every addition must be supported at its own position; familiar words
        # in an unsupported role cannot act as an implicit synonym.
        unsupported = model.predict(
            "add 5 to every vegetable then reverse the list", [3, -1, 7])
        require(unsupported.status != "ok",
                "unsupported lexical role was treated as a known synonym")
        reordered = model.predict(
            "every 5 add to value then reverse the list", [3, -1, 7])
        require(reordered.status != "ok",
                "role evidence licensed a reordered instruction")

        restored = CRMSModel(path, max_composition_depth=2, max_workers=1)
        restored.load()
        after_load = restored.predict(query, [3, -1, 7])
        require(after_load.status == "ok" and after_load.output == [12, 4, 8]
                and set(after_load.evidence_phrases) == set(sources),
                "scaffold frame transfer changed after persistence")
        with patch.object(restored, "propose_procedure_scaffolds", return_value=[]):
            without_validated_scaffold = restored.predict(query, [3, -1, 7])
        require(without_validated_scaffold.status != "ok",
                "unseen-frame transfer bypassed the MDL/holdout scaffold gate")

        # The same alignment contract must preserve distinct roles when two
        # numeric slots bind to different parameters in a composed procedure.
        multi = CRMSModel(max_composition_depth=2, max_workers=1)
        multi_sources = (
            ("add 1 to each value then keep multiples 3", 1, 3),
            ("increase 2 to every item then retain multiples 4", 2, 4),
            ("add 3 to every item then retain multiples 5", 3, 5),
            ("increase 4 to each value then keep multiples 6", 4, 6),
        )
        multi_inputs = ([1, 4, -2, 8], [5, -3, 8, 6], [0, 6, -7, 3],
                        [9, 2, 1, -4], [11, -8, 5, 2])
        for phrase, add_amount, modulus in multi_sources:
            outputs = [
                [value for value in (item + add_amount for item in values)
                 if value % modulus == 0]
                for values in multi_inputs
            ]
            result = multi.teach(
                phrase, list(zip((list(row) for row in multi_inputs), outputs)))
            require(result.status == "learned"
                    and [step["operation"] for step in result.procedure]
                    == ["add_k", "keep_multiples_k"],
                    f"two-parameter scaffold did not learn: {phrase}: {result}")
        multi_query = "add 5 to every value then retain multiples 3"
        multi_prediction = multi.predict(multi_query, [3, -1, 7])
        require(multi_prediction.status == "ok"
                and multi_prediction.output == [12]
                and multi_prediction.procedure == [
                    {"operation": "add_k", "parameters": {"k": 5}},
                    {"operation": "keep_multiples_k", "parameters": {"k": 3}},
                ]
                and set(multi_prediction.evidence_phrases)
                == {phrase for phrase, _add, _modulus in multi_sources},
                f"two numeric roles were conflated during recombination: {multi_prediction}")
        binding_trace = (multi_prediction.retrieval_evidence or [{}])[0]
        require([(binding["slot"], binding["operation"],
                  binding["parameter_value"])
                 for binding in binding_trace.get("numeric_bindings", [])]
                == [(1, "add_k", 5), (2, "keep_multiples_k", 3)]
                and all(len(binding["training_evidence"]) == len(multi_sources)
                        for binding in binding_trace["numeric_bindings"]),
                f"two-slot explanation lost alignment evidence: {binding_trace}")

    print("success-scaffold language composition diagnostic: PASS")
    print("eight action/quantifier/item combinations, parameter transfer, lexical/order controls, persistence: PASS")


if __name__ == "__main__":
    main()
