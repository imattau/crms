"""Answer every supported item in a coordinated Who question or disclose gaps."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_coordinated_who
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(_natural_coordinated_who("Who created Python and Linux?")
            == ("created", ("Python", "Linux")), "two-item list parse failed")
    require(_natural_coordinated_who(
        "Who created Python, Linux, and Ruby?")
            == ("created", ("Python", "Linux", "Ruby")),
            "serial-comma list parse failed")
    require(_natural_coordinated_who("Who is a parent of Python and Linux?") is None,
            "be-verb question was misparsed as an action conjunction")

    with tempfile.TemporaryDirectory(prefix="crms-who-list-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document("python", "Python", "Guido van Rossum created Python.",
                           "python.txt")
        index.add_document("linux", "Linux", "Linus Torvalds created Linux.",
                           "linux.txt")
        index.add_document(
            "research-development", "Research and Development",
            "Ada Lovelace created Research and Development.", "rd.txt")
        index.add_document("research", "Research", "Grace Hopper created Research.",
                           "research.txt")
        require(_natural_coordinated_who(
            "Who created Research and Development?", index=index) is None,
            "exact-title conjunction was parsed as an object list")
        require(_natural_coordinated_who(
            "Who created the Research and Development?", index=index) is None,
            "article-prefixed exact-title conjunction was parsed as a list")
        index.close()
        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        run = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--index", str(index_path), "--knowledge", str(knowledge_path),
             "--rules", str(root / "rules.json"), "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "rule-session.json")],
            input=("Who created Python, Linux, and Ruby?\n"
                   "Who created Research and Development?\n/quit\n"), text=True,
            capture_output=True, cwd=root, timeout=30)
        output = run.stdout + run.stderr
        require(run.returncode == 0 and "Traceback" not in output,
                f"chat crashed on coordinated list: {output}")
        require("Guido van Rossum created Python." in output
                and "Linus Torvalds created Linux." in output,
                f"chat did not answer all supported list items: {output}")
        require("couldn't find evidence for Ruby" in output
                and "does not answer every part" in output,
                f"chat failed to disclose the missing item: {output}")
        exact_title_turn = output.split(
            "does not answer every part of your question.", maxsplit=1)[-1]
        require("Ada Lovelace created Research and Development." in exact_title_turn
                and "Partial source evidence:" not in exact_title_turn,
                f"exact-title conjunction was incorrectly split: {output}")

    print("coordinated Who lists: PASS")
    print("two/three-item parsing, full supported answers, missing-item disclosure, "
          "and exact-title conjunction handling: PASS")


if __name__ == "__main__":
    main()
