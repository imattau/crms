"""Measure the phrase support needed for a small three-role composition.

Six Codex-authored phrases provide two examples of each role value. The test
checks every action/object/direction combination, distinguishing exact seeds
from 21 held-out recombinations. This is a controlled transfer diagnostic,
not evidence of source-derived or broad natural-language learning.
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


ACTIONS = ("sort", "order", "arrange")
OBJECTS = ("values", "items", "numbers")
DIRECTIONS = ("ascending", "increasing", "upward")
SEED_COORDINATES = (
    (0, 0, 0), (0, 1, 2), (1, 1, 1),
    (1, 2, 0), (2, 2, 2), (2, 0, 1),
)
LABELER = "codex:minimal-phrase-role-grid-v1"
EXAMPLES = (
    ([5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
TEST_LISTS = ([8, 2, 8, -1], [3, 1, 2], [], [-5])


def phrase(coordinates: tuple[int, int, int]) -> str:
    return " ".join((ACTIONS[coordinates[0]], OBJECTS[coordinates[1]],
                     DIRECTIONS[coordinates[2]]))


def transform(values: list[int]) -> list[int]:
    return sorted(values)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    all_coordinates = list(product(range(3), repeat=3))
    seeds = {phrase(coordinates) for coordinates in SEED_COORDINATES}
    require(len(seeds) == 6 and len(all_coordinates) == 27,
            "seed design or full role grid has unexpected size")

    with tempfile.TemporaryDirectory(prefix="crms-minimal-role-grid-") as folder:
        root = Path(folder)
        rules_path = root / "rules.json"
        model = CRMSModel(rules_path, max_composition_depth=1, max_workers=1)
        for coordinates in SEED_COORDINATES:
            seed = phrase(coordinates)
            result = model.teach(
                seed, EXAMPLES, labeler_ids=[LABELER] * len(EXAMPLES))
            require(result.status == "learned"
                    and result.procedure == [
                        {"operation": "sort_ascending", "parameters": {}}],
                    f"seed did not learn the intended single operation: {seed}: "
                    f"{result}")

        exact = 0
        recombined = 0
        evidence_union = set()
        for coordinates in all_coordinates:
            query = phrase(coordinates)
            result = model.predict(query, TEST_LISTS[0])
            require(result.status == "ok"
                    and result.output == transform(TEST_LISTS[0]),
                    f"grid request was wrong or abstained: {query}: {result}")
            evidence_union.update(result.evidence_phrases or [])
            if query in seeds:
                exact += 1
            else:
                recombined += 1
                require(result.matched_templates
                        and result.matched_templates[0].startswith("analogy_frame:"),
                        f"unseen phrase did not use the role-analogy path: "
                        f"{query}: {result}")
        require((exact, recombined) == (6, 21)
                and evidence_union == seeds,
                f"unexpected exact/recombined counts or evidence: "
                f"{exact}, {recombined}, {evidence_union}")

        for query in ("sort values downward", "mean values ascending",
                      "numbers upward arrange", "sort quantities upward"):
            result = model.predict(query, [4, 1, 3])
            require(result.status != "ok" and result.output is None,
                    f"negative control did not abstain: {query}: {result}")

        query = phrase((2, 1, 2))
        artifact = generate_python(model, query)
        require(artifact is not None,
                "a held-out phrase did not generate code")
        namespace: dict[str, object] = {}
        exec(compile(artifact.source, "<minimal-role-grid>", "exec"), namespace)
        for values in TEST_LISTS:
            require(namespace["transform"](values) == transform(values),
                    f"generated transform failed on {values}")

        model.save()
        restored = CRMSModel(rules_path, max_composition_depth=1, max_workers=1)
        records = [record for seed in seeds
                   for record in restored.example_records(seed)]
        require(len(records) == len(seeds) * len(EXAMPLES)
                and all(record.get("labeler_id") == LABELER
                        for record in records),
                "seed labeler provenance did not survive reload")
        replay = restored.predict(query, TEST_LISTS[0])
        require(replay.status == "ok"
                and replay.output == transform(TEST_LISTS[0])
                and tuple(replay.evidence_phrases or [])
                    == artifact.evidence_phrases,
                "held-out composition changed after reload")

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
            command, input=f"Write Python code to {query}\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(chat.returncode == 0
                and f"Generated Python for '{query}'" in chat.stdout
                and all(seed in chat.stdout for seed in seeds),
                f"fresh chat did not use the six-seed composition:\n"
                f"{chat.stdout[-1800:]}\n{chat.stderr}")

    print("minimal phrase-role transfer: PASS")
    print("6 seeds × 3 demonstrations; 6 exact and 21 held-out requests correct: PASS")
    print("4 unsupported role/order controls abstained: PASS")
    print("code oracle, labeler provenance, reload, and fresh chat: PASS")
    print("scope: controlled Codex-authored language grid, not raw-source learning")


if __name__ == "__main__":
    main()
