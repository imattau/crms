"""Keep repeated explicit questions from silently dropping all but one part."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_coordinated_who, _split_explicit_compound_questions
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    compound = "Who created Python? Also who developed Linux?"
    require(_split_explicit_compound_questions(compound)
            == ("Who created Python?", "who developed Linux?"),
            "repeated explicit question clauses were not split")
    require(_split_explicit_compound_questions(
        "Who created Python, and who developed Linux?")
            == ("Who created Python", "who developed Linux?"),
            "repeated question clauses joined by 'and' were not split")
    shared_verb = "Who created Python and Linux?"
    require(not _split_explicit_compound_questions(shared_verb)
            and _natural_coordinated_who(shared_verb)
            == ("created", ("Python", "Linux")),
            "a shared-verb coordinated list was incorrectly split")

    with tempfile.TemporaryDirectory(prefix="crms-explicit-compound-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        index.add_document(
            "python", "Python",
            "Infobox software\ncreator = Guido van Rossum\n\n"
            "Guido van Rossum created Python.", "python.txt")
        index.add_document(
            "guido", "Guido van Rossum",
            "Infobox person\nbirth_place = Budapest\n\n"
            "Guido van Rossum was born in Budapest.", "guido.txt")
        index.add_document("linux", "Linux", "Linus Torvalds developed Linux.",
                           "linux.txt")
        index.add_document(
            "linus", "Linus Torvalds",
            "Infobox person\nbirth_place = Helsinki\n\n"
            "Linus Torvalds was born in Helsinki.", "linus.txt")
        index.save(root / "research.json")
        CRMSKnowledgeBase().save(root / "knowledge.json")
        run = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "research.json"),
             "--rules", str(root / "rules.json"),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "rule-session.json"),
             "--candidate-session", str(root / "candidate-session.json")],
            input=("Who developed Linux? Also where was he born?\n/quit\n"),
            text=True, capture_output=True,
            cwd=root, timeout=30)
        output = run.stdout + run.stderr
        require(run.returncode == 0 and "Traceback" not in output,
                f"compound chat failed: {output}")
        require("Part 1 of 2:" in output and "Linus Torvalds developed Linux."
                in output and "Part 2 of 2:" in output
                and "Linus Torvalds's birthplace as Helsinki" in output
                and "Processed all 2 question parts separately." in output,
                f"chat omitted an explicit question part: {output}")

        # The original two non-pronominal parts must also remain independently
        # answerable in a separate scratch interaction.
        independent = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "research.json"),
             "--rules", str(root / "rules.json"),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue2.json"),
             "--rule-session", str(root / "rule-session2.json"),
             "--candidate-session", str(root / "candidate-session2.json")],
            input=compound + "\n/quit\n", text=True, capture_output=True,
            cwd=root, timeout=30)
        independent_output = independent.stdout + independent.stderr
        require(independent.returncode == 0
                and "Guido van Rossum" in independent_output
                and "Linus Torvalds developed Linux." in independent_output
                and "Part 1 of 2:" in independent_output
                and "Part 2 of 2:" in independent_output,
                f"independent question parts were not both answered: {independent_output}")

        partial = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "research.json"),
             "--rules", str(root / "rules.json"),
             "--math", str(root / "math.json"),
             "--translations", str(root / "translations.json"),
             "--dialogue-state", str(root / "dialogue3.json"),
             "--rule-session", str(root / "rule-session3.json"),
             "--candidate-session", str(root / "candidate-session3.json")],
            input=("Who created Python? Also who developed Minix?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30)
        partial_output = partial.stdout + partial.stderr
        require(partial.returncode == 0 and "Part 1 of 2:" in partial_output
                and "Guido van Rossum" in partial_output
                and "Part 2 of 2:" in partial_output
                and "Minix" in partial_output
                and "Processed all 2 question parts separately." in partial_output,
                f"mixed supported/unsupported clauses were not both processed: "
                f"{partial_output}")
        require(any(marker in partial_output.lower() for marker in (
                    "couldn't find", "no source", "no evidence", "no matching",
                    "not supported", "i don't know")),
                f"unsupported second clause was not identified as a gap: "
                f"{partial_output}")

    print("PASS: repeated explicit question clauses are processed separately")
    print("PASS: shared-verb lists remain with the coordinated-question route")
    print("PASS: a uniquely extracted Who answer binds a later pronoun in the same request")
    print("PASS: mixed supported/unsupported clauses are both processed and the gap is disclosed")
    print("PASS: each answer is labeled with its part and source")


if __name__ == "__main__":
    main()
