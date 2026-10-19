"""Check exact-title type fields as quoted answers, without fact promotion."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_type_field_evidence  # noqa: E402
from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def command(root: Path) -> list[str]:
    return [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--index", str(root / "index.sqlite"), "--index-read-only",
        "--dialogue-state", str(root / "dialogue.json"),
        "--rules", str(root / "rules.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidate-session.json"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
    ]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-336-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "index.sqlite")
        index.add_document(
            "albury", "Albury",
            "Infobox Australian place\n"
            "type = city\nname = Albury\n\n"
            "Albury is a city in New South Wales.", "albury.txt")
        index.add_document(
            "conflict-a", "Tavel Compass",
            "Infobox device\ntype = compass\n", "tavel-a.txt")
        index.add_document(
            "conflict-b", "Tavel Compass",
            "Infobox device\ntype = navigation tool\n", "tavel-b.txt")
        index.add_document(
            "unstructured", "Unstructured Place",
            "Unstructured Place is a town.\ntype = town\n",
            "unstructured.txt")

        evidence = _natural_type_field_evidence(
            index, "What type of place is Albury?")
        if evidence is None:
            raise SystemExit("exact-title infobox type was not found")
        if index.resolve_citation(evidence["citation"]) != "type = city":
            raise SystemExit("citation did not resolve to the exact type field")
        if _natural_type_field_evidence(index, "What type is Tavel Compass?") is not None:
            raise SystemExit("conflicting exact-title type fields were ranked")
        if _natural_type_field_evidence(
                index, "What type is Unstructured Place?") is not None:
            raise SystemExit("a non-infobox key-value line was treated as metadata")
        index.close()

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        run = subprocess.run(
            command(root),
            input=("What type of place is Albury?\n"
                   "/pending-candidates\n"
                   "/accept 1\n"
                   "Is Albury a city?\n"
                   "/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60)
        output = run.stdout + run.stderr
        if run.returncode or "Traceback" in output:
            raise SystemExit(f"chat failed:\n{output}")
        for expected in (
                "The source lists Albury's type as city.",
                "field “type = city”",
                "quoted structured evidence, not an accepted fact",
                "Albury — is-a → city",
                "Accepted positive fact: Albury — is-a → city.",
                "CRMS> Yes."):
            if expected not in output:
                raise SystemExit(f"chat omitted {expected!r}:\n{output}")
        learned = CRMSKnowledgeBase.load(knowledge_path)
        if not any((fact.subject, fact.relation, fact.object)
                   == ("Albury", "is-a", "city")
                   and any("#" in source for source in fact.sources)
                   for fact in learned.facts()):
            raise SystemExit("explicitly accepted type field was not stored")
        print("PASS: exact-title type field answers the natural question")
        print("PASS: citation resolves to the exact field")
        print("PASS: conflicting and non-infobox values abstain")
        print("PASS: type claim enters review without automatic promotion")
        print("PASS: explicit acceptance stores the cited is-a fact")
        print("PASS: accepted type fact answers a later yes/no question")


if __name__ == "__main__":
    main()
