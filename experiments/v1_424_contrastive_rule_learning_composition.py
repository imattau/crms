"""A chat-taught contrastive rule composes with math and survives reload."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from v1_357_cross_domain_list_math_composition import trained_math

_LAUNCH_COUNT = 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def launch(root: Path, lines: list[str]) -> subprocess.CompletedProcess[str]:
    global _LAUNCH_COUNT
    feedback_path = root / f"feedback-{_LAUNCH_COUNT}.sqlite3"
    _LAUNCH_COUNT += 1
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--knowledge", str(root / "knowledge.json"),
        "--index", str(root / "index.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--feedback-db", str(feedback_path),
    ]
    return subprocess.run(command, input="\n".join([*lines, "/quit", ""]),
                          text=True, capture_output=True, cwd=root,
                          timeout=30, check=False)


def main() -> None:
    request = ("Write Python code to sort the numbers then apply x times x "
               "plus 3 to each value")
    with tempfile.TemporaryDirectory(prefix="crms-contrastive-compose-") as folder:
        root = Path(folder)
        CRMSModel(max_workers=1).save(root / "rules.json")
        trained_math().save(root / "math.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "index.json")

        examples = [
            "/teach-rule sort the numbers|3,1,2|1,2,3",
            "/teach-rule sort the numbers|4,-1,7|-1,4,7",
            "/teach-rule sort the numbers|0,5,-2,8|-2,0,5,8",
            "/teach-rule sort the numbers|-5,9|-5,9",
            "/teach-rule sort the numbers|12|12",
        ]
        run = launch(root, [request, *examples, "[0,0]", request,
                            "Explain that code", "Show the examples for that code"])
        require(run.returncode == 0,
                f"interactive learning chat exited {run.returncode}: {run.stderr}")
        require("I couldn't resolve the first list step" in run.stdout,
                "unlearned code request did not abstain on its unsupported step")
        require("Please provide the intended output for input [0, 0]" in run.stdout
                and "Rule learning status: learned." in run.stdout,
                "contrastive probe did not license the taught sort procedure")
        require("Generated composed Python" in run.stdout
                and "Both stages" in run.stdout
                and "Evidence for generated artifact crms-code-v1-" in run.stdout
                and "'sort the numbers': [0, 0] -> [0, 0]" in run.stdout,
                "chat did not compose and expose the taught rule and math evidence")

        artifact_ids = re.findall(r"Artifact id: (crms-code-v1-[a-f0-9]{64})",
                                  run.stdout)
        require(len(artifact_ids) == 1,
                f"expected one composed artifact id, found {artifact_ids!r}")

        rules = CRMSModel(root / "rules.json", max_workers=1)
        prediction = rules.predict("sort the numbers", [17, -3, 0, 4])
        require(prediction.status == "ok" and prediction.output == [-3, 0, 4, 17],
                f"saved rule did not transfer to an unseen list: {prediction!r}")

        restarted = launch(root, [request])
        require(restarted.returncode == 0
                and "Generated composed Python" in restarted.stdout,
                f"reloaded chat could not reuse the learned rule: {restarted.stdout}")
        require(artifact_ids[0] in restarted.stdout,
                "same learned components did not recreate the same composed artifact: "
                f"first={artifact_ids!r}, "
                f"stdout={restarted.stdout[-1800:]!r}")
        unsupported = launch(root, [
            "Write Python code to rotate the numbers then apply x times x plus 3 "
            "to each value"])
        unsupported_routes = [
            line for line in unsupported.stdout.splitlines()
            if "Generated composed" in line or "couldn't resolve" in line]
        require("I couldn't resolve the first list step" in unsupported.stdout
                and "Generated composed Python" not in unsupported.stdout,
                "unsupported list operation was treated as licensed: "
                f"{unsupported_routes!r}")

    print("unknown natural-language code task abstains before teaching: PASS")
    print("contrastive chat feedback learns and commits the exact procedure: PASS")
    print("learned rule composes with exact math and exposes component evidence: PASS")
    print("unseen list values and clean chat restart preserve the rule: PASS")
    print("unsupported composition still abstains; artifact id is deterministic: PASS")


if __name__ == "__main__":
    main()
