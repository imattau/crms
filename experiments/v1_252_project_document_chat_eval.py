"""Drive chat over CRMS's own design document using real project language.

Unlike the generated scale fixture, this diagnostic uses the current README as
its complete corpus. It measures source sentence retrieval for architecture,
uncertainty, language-learning limits, and model distribution questions.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def response_chunks(output: str, turns: list[str]) -> list[str]:
    chunks = output.split("you> ")[1:]
    if len(chunks) != len(turns):
        raise SystemExit(
            f"chat emitted {len(chunks)} prompt responses for {len(turns)} turns")
    return [chunk.strip() for chunk in chunks]


def main() -> None:
    cases = {
        "How can I distribute searchable source text without the original files?":
            (("The optional `--research-index` copies extracted readable text, "
              "page boundaries, titles, and locations into the model database; "
              "it does not copy the original files.",
              "Create one portable SQLite model database from learned "
              "knowledge and rule memories, with optional math, translation "
              "memories, and extracted searchable source text:",
              "portable SQLite model and retrieves from it with the original "
              "sources and index unavailable."), "paraphrase"),
        "Does the word count prove that CRMS knows as much as a large model?":
            ("word units are not an LLM tokenizer count and do not establish "
             "knowledge equivalence to a model by parameter count.", "paraphrase"),
        "What does a missing proposition mean in the open-world store?":
            ("the absence of a proposition is unknown, not a negative example",
             "direct"),
        "How much of the current language layer is hand specified?":
            ("The active grammar and language layer are still substantially "
             "hand-specified.", "direct"),
        "What can the induced question frames generalize?":
            ("These forms do not generalize to arbitrary paraphrases.",
             "paraphrase"),
    }
    with tempfile.TemporaryDirectory(prefix="crms-project-doc-chat-") as folder:
        root = Path(folder)
        source = root / "sources"
        source.mkdir()
        readme = (PROJECT / "CRMS_README.md").read_text(encoding="utf-8")
        # Do not train this diagnostic on its own report: such a paragraph
        # repeats the query vocabulary and can outrank the substantive design
        # passages it is meant to evaluate.
        corpus_paragraphs = [
            paragraph for paragraph in readme.split("\n\n")
            if "v1_252_project_document_chat_eval.py" not in paragraph
        ]
        corpus_text = "\n\n".join(corpus_paragraphs)
        (source / "CRMS_README.md").write_text(corpus_text, encoding="utf-8")
        turns = [f"/source-dir {source}", *cases, "/quit"]
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "research.sqlite"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        run = subprocess.run(
            command, input="\n".join(turns) + "\n", text=True,
            capture_output=True, cwd=root, timeout=120, check=False)
        if run.returncode:
            raise SystemExit(
                f"project-document chat failed ({run.returncode}):\n"
                f"{run.stderr}")
        responses = response_chunks(run.stdout, turns)
        by_turn = dict(zip(turns, responses))
        results = {
            question: any(
                " ".join(expected.casefold().split())
                in " ".join(by_turn[question].casefold().split())
                for expected in (expected if isinstance(expected, tuple)
                                 else (expected,)))
            and "may not answer your question" not in
                by_turn[question].casefold()
            and "does not support a grounded answer" not in
                by_turn[question].casefold()
            and "quoted evidence" in by_turn[question].casefold()
            for question, (expected, _kind) in cases.items()
        }
        direct_results = [results[question]
                          for question, (_expected, kind) in cases.items()
                          if kind == "direct"]
        paraphrase_results = [results[question]
                              for question, (_expected, kind) in cases.items()
                              if kind == "paraphrase"]
        print(json.dumps({
            "documents": 1,
            "source_bytes": (source / "CRMS_README.md").stat().st_size,
            "questions": len(cases),
            "retrieved_expected_sentences": sum(results.values()),
            "direct_coverage": f"{sum(direct_results)}/{len(direct_results)}",
            "paraphrase_coverage": (
                f"{sum(paraphrase_results)}/{len(paraphrase_results)}"),
            "results": results,
            "responses": {question: by_turn[question]
                          for question in cases},
        }, indent=2))
        if not all(results.values()):
            failed = [question for question, passed in results.items()
                      if not passed]
            raise SystemExit(
                "project-document chat missed expected evidence for: "
                + "; ".join(failed))


if __name__ == "__main__":
    main()
