"""Check relation intent and instance-versus-definition handling in chat."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index_path = (PROJECT / "data" / "crms_project_model_academic.sqlite.memories"
                  / "research.sqlite")
    require(index_path.is_file(), f"large-corpus index is missing: {index_path}")
    index = CRMSSQLiteResearchIndex.load(index_path)
    knowledge = CRMSKnowledgeBase()

    action = knowledge.research("What does the parser do?", index)
    action_text = knowledge.render_research_brief(action)
    require(action.status == "sources_found"
            and "no accepted fact states what parser does" in action_text
            and "Which parser do you mean" in action_text
            and "narrow learned" not in action_text,
            f"one-word parser overlap was presented as an answer: {action_text}")

    taught = CRMSKnowledgeBase()
    taught.add_fact("parser", "tokenizes", "input", "reviewed-function-fact")
    known_action = taught.research("What does the parser do?", index)
    known_action_text = taught.render_research_brief(known_action)
    require("Known facts:" in known_action_text
            and "parser" in known_action_text
            and "tokenizes" in known_action_text
            and "no accepted fact states what parser does" not in known_action_text,
            f"a generic action question ignored its accepted action fact: {known_action_text}")

    definition = knowledge.research("What is the parser?", index)
    definition_text = knowledge.render_research_brief(definition)
    require(definition.status == "needs_review"
            and "parser — is-a → tokenizer" in definition_text
            and "The parser is a tokenizer." in definition_text,
            f"article-bearing definition question missed its reviewed type fact: {definition_text}")

    instance = knowledge.research("What is a tokenizer?", index)
    instance_text = knowledge.render_research_brief(instance)
    require(instance.status == "needs_review"
            and "Unverified example, not a definition" in instance_text
            and "does not give a full definition of tokenizer" in instance_text,
            f"an instance claim was presented as a complete definition: {instance_text}")

    with tempfile.TemporaryDirectory(prefix="crms-question-role-") as folder:
        root = Path(folder)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        output = subprocess.run(
            command,
            input=("What does the parser do?\n"
                   "What is the parser?\n"
                   "What is a tokenizer?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=45).stdout
        require("Which parser do you mean" in output
                and "parser — is-a → tokenizer" in output
                and "Unverified example, not a definition" in output
                and "narrow learned" not in output,
                f"natural-language chat did not preserve relation and type roles: {output}")

    print("question-role and answerability diagnostic: PASS")


if __name__ == "__main__":
    main()
