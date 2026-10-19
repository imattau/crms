"""Check exact-title answers from structured source fields stay grounded."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (_natural_capital_field_evidence,
                       _natural_who_evidence)
from crms_research import CRMSSQLiteResearchIndex


def command(root: Path) -> list[str]:
    return [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--index", str(root / "index.sqlite"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rules", str(root / "rules.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidate-session.json"),
        "--math", str(root / "math.json"),
        "--math-session", str(root / "math-session.json"),
        "--translations", str(root / "translations.json"),
        "--translation-session", str(root / "translation-session.json"),
    ]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-318-") as folder:
        root = Path(folder)
        index = CRMSSQLiteResearchIndex(root / "index.sqlite")
        index.add_document(
            "python-language", "Python (programming language)",
            "Infobox programming language\n"
            "name = Python\n"
            "designer = Guido van Rossum\n"
            "\nPython is an open-source programming language.",
            "python-language.txt")
        index.add_document(
            "quarn-device", "Quarn Beacon",
            "Infobox device\nname = Quarn Beacon\n"
            "manufacturer = Bree Hollis\n\nThe Quarn Beacon is a device.",
            "quarn-device.txt")
        index.add_document(
            "germany", "Germany",
            "Infobox country\nname = Germany\n"
            "efn ; structured explanatory continuation\n"
            "capital = Berlin\n"
            "efn ; Berlin is the constitutional capital\n"
            "\nGermany is a country in Europe.", "germany.txt")
        index.add_document(
            "ambiguous-a", "Tavel Compass",
            "Infobox device\ndesigner = Neve Aldric\n",
            "tavel-a.txt")
        index.add_document(
            "ambiguous-b", "Tavel Compass",
            "Infobox device\ndesigner = Orren Vale\n",
            "tavel-b.txt")
        index.add_document(
            "unstructured", "Unstructured Device",
            "A note about metadata.\ndesigner = Unverified Person\n",
            "unstructured.txt")

        evidence = _natural_who_evidence(
            index, "Who designed the Python programming language?")
        if evidence is None or not evidence.get("structured_metadata"):
            raise SystemExit(f"exact-title field was not found: {evidence}")
        realized = evidence.get("realized_answer", {})
        if realized.get("text") != (
                "Guido van Rossum is listed as the designer of "
                "Python programming language."):
            raise SystemExit(f"structured field was not realized as expected: {realized}")
        if index.resolve_citation(evidence["citation"]) != (
                "designer = Guido van Rossum"):
            raise SystemExit("citation did not resolve to the exact source field")
        capital = _natural_capital_field_evidence(
            index, "What is the capital of Germany?")
        if (capital is None
                or capital.get("realized_answer", {}).get("text")
                != "Berlin is listed as the capital of Germany."
                or index.resolve_citation(capital["citation"])
                != "capital = Berlin"):
            raise SystemExit(f"capital field did not answer with an exact citation: {capital}")
        if _natural_who_evidence(
                index, "Who created Quarn Beacon?") is not None:
            raise SystemExit("manufacturer field was guessed to mean creator")
        if _natural_who_evidence(
                index, "Who designed Tavel Compass?") is not None:
            raise SystemExit("conflicting exact-title field records were resolved by rank")
        if _natural_who_evidence(
                index, "Who designed Unstructured Device?") is not None:
            raise SystemExit("a non-infobox key-value line was treated as structured metadata")
        index.close()

        result = subprocess.run(
            command(root),
            input=("Who designed the Python programming language?\n"
                   "Who is the designer of the Python programming language?\n"
                   "What is the capital of Germany?\n"
                   "/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = result.stdout + result.stderr
        if result.returncode or "Traceback" in output:
            raise SystemExit(f"chat failed on structured source evidence:\n{output}")
        for required in (
                "Guido van Rossum is listed as the designer",
                "Berlin is listed as the capital of Germany",
                "field “designer = Guido van Rossum”",
                "field “capital = Berlin”",
                "quoted structured evidence, not an accepted fact"):
            if required not in output:
                raise SystemExit(f"chat omitted {required!r}:\n{output}")
        print("PASS: exact-title designer field answers the natural-language question")
        print("PASS: field citation resolves exactly and remains review-free")
        print("PASS: unrelated fields and conflicting page records do not produce answers")


if __name__ == "__main__":
    main()
