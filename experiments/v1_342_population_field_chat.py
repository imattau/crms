"""Check population answers use exact-title, review-only infobox evidence."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_population_field_evidence  # noqa: E402
from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def command(root: Path) -> list[str]:
    return [sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.sqlite"), "--index-read-only",
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json")]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-342-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "index.sqlite")
        index.add_document(
            "chicago", "Chicago",
            "Infobox settlement\nname = Chicago\npopulation_total = 2746388\n"
            "population_as_of = 2020\n", "chicago.txt")
        index.add_document(
            "conflict-a", "Mercury",
            "Infobox settlement\npopulation_total = 10\n", "mercury-a.txt")
        index.add_document(
            "conflict-b", "Mercury",
            "Infobox settlement\npopulation_total = 20\n", "mercury-b.txt")
        index.add_document(
            "non-infobox", "Nowhere",
            "Nowhere has population_total = 99.\n", "nowhere.txt")

        evidence = _natural_population_field_evidence(
            index, "What is the population of Chicago?")
        if evidence is None:
            raise SystemExit("exact-title population field was not found")
        if index.resolve_citation(evidence["citation"]) != (
                "population_total = 2746388\npopulation_as_of = 2020"):
            raise SystemExit("citation omitted or altered population metadata")
        if _natural_population_field_evidence(
                index, "What is the population of Mercury?") is not None:
            raise SystemExit("conflicting exact-title values were ranked")
        if _natural_population_field_evidence(
                index, "What is the population of Nowhere?") is not None:
            raise SystemExit("ordinary prose was treated as infobox metadata")
        index.close()

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        run = subprocess.run(
            command(root),
            input=("What is the population of Chicago?\n"
                   "/pending-candidates\n/accept 1\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60)
        output = run.stdout + run.stderr
        if run.returncode or "Traceback" in output:
            raise SystemExit(f"chat failed:\n{output}")
        for expected in (
                "The source lists Chicago's population as 2746388 (as of 2020).",
                "field “population_total = 2746388\npopulation_as_of = 2020”",
                "quoted structured evidence, not an accepted fact",
                "Chicago — population → 2746388",
                "Accepted positive fact: Chicago — population → 2746388."):
            if expected not in output:
                raise SystemExit(f"chat omitted {expected!r}:\n{output}")
        learned = CRMSKnowledgeBase.load(knowledge_path)
        fact = next((fact for fact in learned.facts()
                     if fact.subject == "Chicago"
                     and fact.relation == "population"), None)
        if fact is None or dict(fact.qualifiers) != {"as_of": "2020"}:
            raise SystemExit("explicit acceptance lost the as-of qualifier")
        print("PASS: exact-title total population field answers naturally")
        print("PASS: citation includes exact value and as-of source fields")
        print("PASS: duplicate-conflicting and non-infobox sources abstain")
        print("PASS: source metadata remains review-only until accepted")
        print("PASS: accepted population retains its as-of qualifier")


if __name__ == "__main__":
    main()
