"""Measure transfer from positional phrase roles to ordinary request syntax.

The model learns six labeled action/object/direction combinations and is then
asked five semantically positive requests with different syntax, plus an
unsupported descending request. This baseline tracks partial transfer and
safe abstention as the learner improves. The positive forms and expected
operation are Codex-authored labels.
"""
from __future__ import annotations

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


SEEDS = (
    "sort values ascending",
    "sort items upward",
    "order items increasing",
    "order numbers ascending",
    "arrange numbers upward",
    "arrange values increasing",
)
MORPHOLOGY_SEEDS = (
    "order numbers ascendingly",
    "arrange values increasingly",
)
MULTIWORD_DIRECTION_SEEDS = (
    "sort numbers from low to high",
    "arrange values from low to high",
)
EXAMPLES = (
    ([5, 2, 3, 1, 4], [1, 2, 3, 4, 5]),
    ([1, -1, 1], [-1, 1, 1]),
    ([0, 1, -1], [-1, 0, 1]),
)
POSITIVE_REQUESTS = (
    "put items in increasing order",
    "sort numbers from minimum to maximum",
    "arrange values in ascending order",
    "order the numbers ascendingly",
    "make the values go from smallest to largest",
    "sort the values in ascending order",
    "sort numbers in ascending order",
    "order the numbers in ascending order",
    "arrange numbers upwardly",
    "sort values increasingly",
    "order items from low to high",
)
NEGATIVE_REQUESTS = (
    "sort items descending",
    "arrange numbers downwardly",
    "order items from high to low",
)
LABELER = "codex:natural-request-frame-baseline-v1"
MORPHOLOGY_LABELER = "codex:natural-request-morphology-v1"
MULTIWORD_DIRECTION_LABELER = "codex:multiword-direction-role-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    training_phrases = set(SEEDS + MORPHOLOGY_SEEDS
                           + MULTIWORD_DIRECTION_SEEDS)
    require(not training_phrases.intersection(POSITIVE_REQUESTS),
            "a held-out positive request overlaps a training phrase")
    with tempfile.TemporaryDirectory(prefix="crms-natural-request-frame-") as folder:
        root = Path(folder)
        model_path = root / "rules.json"
        model = CRMSModel(model_path, max_composition_depth=1, max_workers=1)
        for phrase in SEEDS:
            learned = model.teach(
                phrase, EXAMPLES,
                labeler_ids=[LABELER] * len(EXAMPLES))
            require(learned.status == "learned",
                    f"seed procedure failed to learn for {phrase!r}: {learned}")
        for phrase in MORPHOLOGY_SEEDS:
            learned = model.teach(
                phrase, EXAMPLES,
                labeler_ids=[MORPHOLOGY_LABELER] * len(EXAMPLES))
            require(learned.status == "learned",
                    f"morphology example failed to learn for {phrase!r}: "
                    f"{learned}")
        for phrase in MULTIWORD_DIRECTION_SEEDS:
            learned = model.teach(
                phrase, EXAMPLES,
                labeler_ids=[MULTIWORD_DIRECTION_LABELER] * len(EXAMPLES))
            require(learned.status == "learned",
                    f"multiword direction failed to learn for {phrase!r}: "
                    f"{learned}")
            records = model.example_records(phrase)
            require(records and all(
                record.get("labeler_id") == MULTIWORD_DIRECTION_LABELER
                for record in records),
                f"multiword direction lost labeler provenance: {phrase!r}")

        transferred = model.predict(
            POSITIVE_REQUESTS[2], [3, 1, 2])
        require(transferred.status == "ok"
                and transferred.output == [1, 2, 3]
                and transferred.matched_templates
                and transferred.matched_templates[0].startswith("role_frame:")
                and "learned role frame" in (transferred.message or "")
                and set(transferred.evidence_phrases or ()) >= {
                    "arrange numbers upward", "arrange values increasing",
                    "order numbers ascending", "sort values ascending",
                },
                f"role transfer lost output or source phrases: {transferred}")
        inflected = model.predict(
            POSITIVE_REQUESTS[3], [3, 1, 2])
        require(inflected.status == "ok" and inflected.output == [1, 2, 3]
                and inflected.matched_templates
                and inflected.matched_templates[0].startswith("role_frame:")
                and set(inflected.evidence_phrases or ()) >= {
                    "order numbers ascending", "order numbers ascendingly",
                    "arrange values increasing",
                    "arrange values increasingly",
                },
                f"two-root affix transfer lost its supporting evidence: "
                f"{inflected}")
        productive_inflection = model.predict(
            POSITIVE_REQUESTS[8], [3, 1, 2])
        require(productive_inflection.status == "ok"
                and productive_inflection.output == [1, 2, 3]
                and any("upwardly" in phrase
                        for phrase in (productive_inflection.matched_templates
                                       or [])),
                "learned -ly transfer did not apply to a second unseen stem: "
                f"{productive_inflection}")
        multiword_direction = model.predict(
            POSITIVE_REQUESTS[10], [3, 1, 2])
        require(multiword_direction.status == "ok"
                and multiword_direction.output == [1, 2, 3]
                and multiword_direction.matched_templates
                and multiword_direction.matched_templates[0].startswith(
                    "role_chunk_frame:")
                and set(multiword_direction.evidence_phrases or ()) >= {
                    "sort numbers from low to high",
                    "arrange values from low to high",
                    "order items increasing",
                    "order numbers ascending",
                    "sort items upward",
                },
                f"multiword role composition lost support: "
                f"{multiword_direction}")
        weak_support_model = CRMSModel(max_composition_depth=1, max_workers=1)
        for phrase in (*SEEDS, *MORPHOLOGY_SEEDS,
                       MULTIWORD_DIRECTION_SEEDS[0]):
            learned = weak_support_model.teach(
                phrase, EXAMPLES,
                labeler_ids=[LABELER] * len(EXAMPLES))
            require(learned.status == "learned",
                    f"weak-support control failed to learn {phrase!r}")
        weak_support = weak_support_model.predict(
            POSITIVE_REQUESTS[10], [3, 1, 2])
        require(weak_support.status != "ok" and weak_support.output is None,
                "one multiword-direction example licensed recombination: "
                f"{weak_support}")
        require(weak_support_model._procedure_role_frame_cache is not None,
                "role-frame query did not build its reusable evidence index")
        learned = weak_support_model.teach(
            MULTIWORD_DIRECTION_SEEDS[1], EXAMPLES,
            labeler_ids=[MULTIWORD_DIRECTION_LABELER] * len(EXAMPLES))
        require(learned.status == "learned"
                and weak_support_model._procedure_role_frame_cache is None,
                "teaching did not invalidate the cached role evidence")
        newly_supported = weak_support_model.predict(
            POSITIVE_REQUESTS[10], [3, 1, 2])
        require(newly_supported.status == "ok"
                and newly_supported.output == [1, 2, 3]
                and set(newly_supported.evidence_phrases or ()) >= {
                    MULTIWORD_DIRECTION_SEEDS[0],
                    MULTIWORD_DIRECTION_SEEDS[1],
                },
                "new direction evidence did not enter the rebuilt role index: "
                f"{newly_supported}")
        for request in (POSITIVE_REQUESTS[2], POSITIVE_REQUESTS[3],
                        POSITIVE_REQUESTS[8], POSITIVE_REQUESTS[9],
                        POSITIVE_REQUESTS[10]):
            artifact = generate_python(model, request)
            require(artifact is not None,
                    f"learned frame did not generate code for {request!r}")
            namespace: dict[str, object] = {}
            exec(compile(artifact.source, "<natural-role-frame>", "exec"),
                 namespace)
            for values in ([3, 1, 2], [7, -2, 7], [], [5]):
                require(namespace["transform"](values) == sorted(values),
                        f"role-frame code for {request!r} failed oracle "
                        f"on {values}")

        for path, save in (
                (root / "knowledge.json", CRMSKnowledgeBase().save),
                (root / "math.json", CRMSMath().save),
                (root / "index.json", CRMSResearchIndex().save),
                (root / "translations.json", CRMSTranslation().save)):
            save(path)

        requests = (*POSITIVE_REQUESTS, *NEGATIVE_REQUESTS)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(model_path),
            "--knowledge", str(root / "knowledge.json"),
            "--math", str(root / "math.json"),
            "--index", str(root / "index.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        chat = subprocess.run(
            command,
            input="\n".join(
                f"Write Python code to {request}" for request in requests)
                + "\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = chat.stdout + chat.stderr
        require(chat.returncode == 0 and "Traceback" not in output,
                f"fresh chat failed: {output[-2500:]}")

        generated = [request for request in requests
                     if f"Generated Python for '{request}'" in output]
        missed_positive = [request for request in POSITIVE_REQUESTS
                           if request not in generated]
        false_positive = [request for request in NEGATIVE_REQUESTS
                          if request in generated]
        require(not false_positive,
                f"unsupported direction received generated code: {false_positive}")
        require(POSITIVE_REQUESTS[2] in generated,
                "learned role support did not transfer through the article and "
                "directional function words in 'arrange values in ascending order'")
        require(set(POSITIVE_REQUESTS[2:4] + POSITIVE_REQUESTS[5:11])
                <= set(generated),
                "a regression lost a licensed function-word or morphology "
                "transfer")
        lowered_output = output.casefold()
        for request in missed_positive:
            require(f"could not resolve '{request}'" in lowered_output,
                    f"missed positive request did not abstain clearly: {request!r}")
        for request in NEGATIVE_REQUESTS:
            require(f"could not resolve '{request}'" in lowered_output,
                    f"negative request did not abstain clearly: {request!r}")

        print("fresh chat preserved learned role and span evidence: PASS")
        print("positive syntactic paraphrase coverage: "
              f"{len(POSITIVE_REQUESTS) - len(missed_positive)}/"
              f"{len(POSITIVE_REQUESTS)}")
        print(f"unsupported descending requests generated: {len(false_positive)}")
        print("single-evidence multiword direction abstention: PASS")
        print("teaching invalidates and rebuilds cached role evidence: PASS")
        print("scope: Codex-labeled natural wording; not an independent language benchmark")


if __name__ == "__main__":
    main()
