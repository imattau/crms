"""Test held-out single-step action/object/direction recombination.

All phrases and labels in this controlled grid are Codex-authored. The test
measures whether CRMS can recombine repeated positional roles into one unseen
request; it is not evidence of source-derived synonym learning.
"""
from __future__ import annotations

from itertools import product
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_codegen import generate_python
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


ACTION_ROLES = ("sort", "order", "arrange")
OBJECT_ROLES = ("values", "items", "numbers")
DIRECTION_ROLES = ("ascending", "increasing", "upward")
HELD_OUT = ("arrange", "numbers", "upward")
LABELER = "codex:single-step-phrase-grid-v1"
EXAMPLES = (
    ([5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
HELD_OUT_LISTS = ([8, 2, 8, -1], [3, 1, 2], [], [-5])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def expected(values: list[int]) -> list[int]:
    return sorted(values)


def main() -> None:
    combinations = list(product(ACTION_ROLES, OBJECT_ROLES, DIRECTION_ROLES))
    require(len(combinations) == 27,
            "phrase grid did not contain 27 role combinations")

    with tempfile.TemporaryDirectory(prefix="crms-single-step-roles-") as folder:
        root = Path(folder)
        rules_path = root / "rules.json"
        model = None
        query = " ".join(HELD_OUT)
        prediction = None
        phrases = [" ".join(parts) for parts in combinations
                   if parts != HELD_OUT]
        for held_out in combinations:
            training_phrases = [" ".join(parts) for parts in combinations
                                if parts != held_out]
            trial = CRMSModel(
                rules_path if held_out == HELD_OUT else None,
                max_composition_depth=1, max_workers=1)
            for phrase in training_phrases:
                result = trial.teach(
                    phrase, EXAMPLES,
                    labeler_ids=[LABELER] * len(EXAMPLES))
                require(result.status == "learned"
                        and result.procedure == [
                            {"operation": "sort_ascending", "parameters": {}}],
                        f"labeled phrase did not learn the same operation: "
                        f"{phrase}: {result}")
            held_out_query = " ".join(held_out)
            held_out_prediction = trial.predict(held_out_query,
                                                HELD_OUT_LISTS[0])
            require(held_out_prediction.status == "ok"
                    and held_out_prediction.output
                        == expected(HELD_OUT_LISTS[0]),
                    f"leave-one-out phrase composition failed for "
                    f"{held_out_query}: {held_out_prediction}")
            if held_out == HELD_OUT:
                model = trial
                prediction = held_out_prediction

        require(model is not None and prediction is not None
                and prediction.matched_templates
                and "{arrange|order|sort}" in prediction.matched_templates[0]
                and set(prediction.evidence_phrases or []) == set(phrases),
                f"representative held-out roles lack support: {prediction}")

        for phrase in ("sort values downward", "mean values ascending",
                       "numbers upward arrange", "sort quantities upward"):
            result = model.predict(phrase, [4, 1, 3])
            require(result.status != "ok" and result.output is None,
                    f"unsupported role or order produced an answer: "
                    f"{phrase}: {result}")

        generated = generate_python(model, query)
        require(generated is not None,
                "role recombination did not produce a code artifact")
        for values in HELD_OUT_LISTS:
            namespace: dict[str, object] = {}
            exec(compile(generated.source, "<held-out-role-grid>", "exec"),
                 namespace)
            require(namespace["transform"](values) == expected(values),
                    f"generated code was wrong for {values}")

        model.save()
        restored = CRMSModel(rules_path, max_composition_depth=1, max_workers=1)
        for phrase in phrases:
            records = restored.example_records(phrase)
            require(records and all(record.get("labeler_id") == LABELER
                                    for record in records),
                    f"Codex labeler provenance was lost for {phrase}")
        after_load = restored.predict(query, HELD_OUT_LISTS[0])
        require(after_load.status == "ok"
                and after_load.output == expected(HELD_OUT_LISTS[0])
                and after_load.evidence_phrases == prediction.evidence_phrases,
                "held-out role recombination changed after reload")

        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rules_path),
            "--math", str(root / "math.json"),
            "--knowledge", str(root / "knowledge.json"),
            "--translations", str(root / "translations.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input=f"Write Python code to {query}\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(chat.returncode == 0
                and f"Generated Python for '{query}'" in chat.stdout
                and all(phrase in chat.stdout for phrase in phrases),
                f"ordinary chat could not use held-out role composition:\n"
                f"{chat.stdout[-1800:]}\n{chat.stderr}")

    print("single-step phrase-role recombination: PASS")
    print("leave-one-combination-out: 27/27 action × object × direction phrases composed: PASS")
    print("four unsupported role/order controls abstained: PASS")
    print("generated code oracle, labeler provenance, reload, and fresh chat: PASS")
    print("scope: Codex-authored labels and phrases; not raw-source induction")


if __name__ == "__main__":
    main()
