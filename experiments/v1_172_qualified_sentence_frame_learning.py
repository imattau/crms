"""Learn cited sentence frames that extract explicit qualifier values."""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach(kb: CRMSKnowledgeBase, sentence: str, subject: str, obj: str,
          year: str, source: str) -> bool:
    kb.add_fact(subject, "designed", obj, source, qualifiers={"year": year})
    return kb.teach_context_fact_pattern(
        sentence, subject=subject, relation="designed", obj=obj, source=source,
        qualifiers={"year": year}, predicate_phrase="designed")


def main() -> None:
    kb = CRMSKnowledgeBase()
    training_examples = [
        ("Ada designed the Engine in 2024.", "Ada", "the Engine", "2024"),
        ("Grace designed a Compiler in 2025.", "Grace", "a Compiler", "2025"),
    ]
    if teach(kb, *training_examples[0], "doc-a#p1"):
        raise SystemExit("one example must not license transfer")
    if not teach(kb, *training_examples[1], "doc-b#p1"):
        raise SystemExit("varied, independently sourced examples did not license")

    sentence = "Zoe designed the Device in 2026."
    candidates = kb.propose_facts(sentence, source="doc-c#p1")
    if len(candidates) != 1:
        raise SystemExit(f"expected one qualified proposal, got {candidates}")
    candidate = candidates[0]
    if ((candidate.subject, candidate.relation, candidate.object)
            != ("Zoe", "designed", "the Device")
            or candidate.qualifiers != (("year", "2026"),)):
        raise SystemExit(f"held-out sentence was misparsed: {candidate}")
    if len(kb.facts()) != 2:
        raise SystemExit("review-only candidate was automatically committed")

    with TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        loaded = CRMSKnowledgeBase.load(path)
        again = loaded.propose_facts(sentence, source="doc-c#p1")
        if len(again) != 1 or again[0].qualifiers != candidate.qualifiers:
            raise SystemExit("qualified sentence frame did not survive persistence")

        # Exercise the user-facing command against two independent documents.
        index_path = Path(directory) / "research.json"
        index = CRMSResearchIndex()
        index.add_document("doc-a", "Engine design", training_examples[0][0])
        index.add_document("doc-b", "Compiler design", training_examples[1][0])
        index.save(index_path)
        cli_kb = Path(directory) / "cli-knowledge.json"
        common = [sys.executable,
                  str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
                  "--knowledge", str(cli_kb), "--index", str(index_path),
                  "--dialogue-state", str(Path(directory) / "dialogue.json"),
                  "--rules", str(Path(directory) / "rules.json")]
        for source_sentence, source_subject, source_obj, source_year in training_examples:
            command = (
                f"/teach-context-frame {source_subject}|designed|{source_obj}|"
                f"designed {source_obj} {source_year}|designed|{source_sentence}|"
                f"year={source_year}\n/quit\n")
            process = subprocess.run(common, input=command, text=True,
                                     capture_output=True, check=True, timeout=20)
            if "Context sentence" not in process.stdout:
                raise SystemExit(f"CLI context-frame teaching failed:\n{process.stdout}")
        cli_loaded = CRMSKnowledgeBase.load(cli_kb)
        cli_candidates = cli_loaded.propose_facts(
            "Zoe designed the Device in 2026.", source="doc-c#p1")
        if (len(cli_candidates) != 1
                or cli_candidates[0].qualifiers != (("year", "2026"),)):
            raise SystemExit("CLI-trained frame did not transfer to held-out text")

    kb.remove_fact("Ada", "designed", "the Engine", "doc-a#p1",
                   qualifiers={"year": "2024"})
    if kb.propose_facts(sentence, source="doc-c#p1"):
        raise SystemExit("retracted training support still licensed transfer")
    print("v1_172 qualified sentence-frame checks passed")


if __name__ == "__main__":
    main()
