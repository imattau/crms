"""Keep natural-language inference prompts and missing-premise replies grounded."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSResearchIndex  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_rule_base() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    kb.add_inference_rule("grandparent-rule", "parent", "parent", "grandparent")
    return kb


def main() -> None:
    complete = make_rule_base()
    complete.add_fact("Ann", "parent", "Bob", "source:ann-bob")
    complete.add_fact("Bob", "parent", "Cara", "source:bob-cara")
    who = complete.ask("Who is a grandparent of Cara?")
    require(who.status == "answered" and who.answer == "Ann"
            and who.inference_proofs,
            f"natural relation question did not reach rule inference: {who}")
    polar = complete.ask("Is Ann a grandparent of Cara?")
    require(polar.status == "answered" and polar.truth is True
            and polar.inference_proofs,
            f"natural polar relation question did not reach inference: {polar}")

    partial = make_rule_base()
    partial.add_fact("Ann", "parent", "Bob", "source:ann-bob")
    partial.add_fact("Cara", "likes", "coffee", "source:cara")
    missing = partial.ask("Who is a grandparent of Cara?")
    require(missing.status == "unknown"
            and missing.reason_code == "missing_premise"
            and any(
                item.get("missing_premise", {}).get("subject") == "Bob"
                and item.get("missing_premise", {}).get("relation") == "parent"
                and item.get("missing_premise", {}).get("object") == "Cara"
                and any(premise.get("subject") == "Ann"
                        and premise.get("relation") == "parent"
                        and premise.get("object") == "Bob"
                        for premise in item.get("supported_premises", []))
                for item in missing.missing_premises or []),
            f"partial proof did not identify its grounded missing link: {missing}")

    unsupported = make_rule_base()
    unsupported.add_fact("Bob", "likes", "tea", "source:bob")
    unsupported.add_fact("Cara", "likes", "coffee", "source:cara")
    no_evidence = unsupported.ask("Is Bob a grandparent of Cara?")
    require(no_evidence.status == "unknown"
            and "cannot answer yes or no" in (no_evidence.request or "")
            and not no_evidence.missing_premises,
            f"unsupported polar question invented a missing link: {no_evidence}")
    require("Bob — parent → Bob" not in (no_evidence.request or "")
            and "Cara — parent → Cara" not in (no_evidence.request or ""),
            "unsupported polar question named an ungrounded premise")

    with tempfile.TemporaryDirectory(prefix="crms-grounded-abduction-") as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json",
            "rule-session.json", "candidate-session.json")}
        unsupported.save(paths["knowledge.json"])
        CRMSResearchIndex().save(paths["index.json"])
        output = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(paths["knowledge.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(paths["dialogue.json"]),
             "--rules", str(paths["rules.json"]),
             "--rule-session", str(paths["rule-session.json"]),
             "--candidate-session", str(paths["candidate-session.json"])],
            input="Is Bob a grandparent of Cara?\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30, cwd=root)
        require(output.returncode == 0
                and "cannot answer yes or no" in output.stdout
                and "Bob — parent → Bob" not in output.stdout
                and "Cara — parent → Cara" not in output.stdout,
                f"terminal displayed speculative premises as facts:\n{output.stdout}\n{output.stderr}")

    with tempfile.TemporaryDirectory(prefix="crms-grounded-missing-link-") as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json",
            "rule-session.json", "candidate-session.json")}
        partial.save(paths["knowledge.json"])
        CRMSResearchIndex().save(paths["index.json"])
        output = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(paths["knowledge.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(paths["dialogue.json"]),
             "--rules", str(paths["rules.json"]),
             "--rule-session", str(paths["rule-session.json"]),
             "--candidate-session", str(paths["candidate-session.json"])],
            input=("Is Ann a grandparent of Cara?\n"
                   "Who is a grandparent of Cara?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30, cwd=root)
        require(output.returncode == 0
                and "I have Ann — parent → Bob." in output.stdout
                and "I still need:" in output.stdout
                and "Bob — parent → Cara." in output.stdout
                and "direct source statement for this exact proposition"
                    not in output.stdout,
                f"source abstention masked the grounded missing premise:\n{output.stdout}\n{output.stderr}")

    print("grounded natural-language abduction diagnostic: PASS")
    print("unframed wh/polar inference, grounded missing link, open-world abstention, terminal wording, and response precedence: PASS")


if __name__ == "__main__":
    main()
