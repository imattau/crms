"""Ground plural paper follow-ups in the visible preceding paper list."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex

PAPERS = (
    ("paper-a", "Machine Learning for Robust Graph Search",
     "2026-10-18",
     "This paper studies graph search under noisy edge observations. "
     "It reports a bounded robustness result."),
    ("paper-b", "Machine Learning for Reliable Speech Recognition",
     "2026-10-17",
     "This paper evaluates speech recognition under acoustic noise. "
     "It compares three decoding strategies."),
    ("paper-c", "Machine Learning for Protein Structure Prediction",
     "2026-10-16",
     "This paper examines protein structure prediction from sequence data. "
     "It presents a held-out evaluation."),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(index_path: Path, state: Path, questions: list[str]) -> str:
    args = []
    for flag, name in (
            ("--knowledge", "knowledge.json"),
            ("--dialogue-state", "dialogue.json"),
            ("--candidate-session", "candidate.json"),
            ("--rule-session", "rule-session.json"),
            ("--math", "math.json"),
            ("--math-session", "math-session.json"),
            ("--translations", "translations.json"),
            ("--translation-session", "translation-session.json")):
        args.extend((flag, str(state.parent / name)))
    command = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--index", str(index_path), "--index-read-only", *args]
    result = subprocess.run(
        command, input="\n".join([*questions, "/quit", ""]),
        text=True, capture_output=True, cwd=state.parent,
        check=False, timeout=45)
    require(result.returncode == 0 and "Traceback" not in result.stdout
            + result.stderr,
            f"fresh chat failed ({result.returncode}):\n"
            + result.stdout + result.stderr)
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-paper-followup-") as folder:
        root = Path(folder)
        index_path = root / "papers.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        for document_id, title, date, abstract in PAPERS:
            index.add_document(
                document_id, title,
                f"Published: {date}\nPrimary category: cs.LG\n"
                f"Abstract: {abstract}\n",
                f"https://papers.example/{document_id}")
        index.close()

        output = run_chat(
            index_path, root / "state.json",
            ["What is the latest research on machine learning?",
             "What topics do these papers cover?",
             "What does the second paper say?"])
        for _document_id, title, _date, abstract in PAPERS:
            first_sentence = abstract.split(".", 1)[0] + "."
            require(title in output and first_sentence in output,
                    f"recent-paper follow-up omitted {title!r}:\n{output}")
        require("These papers cover:" in output or
                "opening abstract sentences" in output,
                "plural follow-up did not identify its evidence-limited form")
        require("model retrieves cited papers" not in output.casefold(),
                "a project-source decoy answered the plural follow-up")
        for _document_id, title, _date, abstract in PAPERS:
            citation_match = re.search(
                rf"\[Source: {re.escape(title)}; ([^\]]+)\]", output)
            require(citation_match is not None,
                    f"missing exact citation for {title!r}:\n{output}")
            check = CRMSSQLiteResearchIndex(index_path, read_only=True)
            try:
                cited_text = check.resolve_citation(citation_match.group(1))
            finally:
                check.close()
            require(cited_text == abstract.split(".", 1)[0] + ".",
                    f"citation for {title!r} did not resolve to its abstract sentence")

        no_context = run_chat(
            index_path, root / "no-context.json",
            ["What topics do these papers cover?"])
        require("recent paper list" in no_context.casefold()
                and "model retrieves cited papers" not in no_context.casefold(),
                "plural reference without a visible list did not ask for context")

    print("plural recent-paper follow-up uses the visible paper list: PASS")
    print("each listed abstract sentence has an exact source citation: PASS")
    print("context persists to the next ordinal paper follow-up: PASS")
    print("missing paper-list context prompts instead of searching unrelated text: PASS")


if __name__ == "__main__":
    main()
