"""Runtime diagnostic for learned predicate wording in typed questions."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-typed-wording-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        learner = CRMSKnowledgeBase()
        for number in range(2):
            subject = f"The Serein River {number:04d}"
            object_ = f"Nacre City {number:04d}"
            for label, phrase in (("canonical", "flows through"),
                                  ("alternate", "passes through")):
                sentence = f"{subject} {phrase} {object_}."
                document_id = f"{label}-{number:04d}"
                index.add_document(document_id, label, sentence,
                                   f"{document_id}.txt")
                hit = next(hit for hit in index.search(sentence, limit=10)
                           if hit.document_id == document_id)
                citation = index.citation(hit)
                learner.add_fact(subject, "flows through", object_, citation)
                learner.teach_fact_pattern(
                    sentence, subject=subject, relation="flows through",
                    obj=object_, predicate_phrase=phrase, source=citation)
            type_sentence = f"{subject} is a river."
            type_id = f"type-{number:04d}"
            index.add_document(type_id, "river classification", type_sentence,
                               f"{type_id}.txt")
            type_hit = next(hit for hit in index.search(
                type_sentence, limit=10) if hit.document_id == type_id)
            learner.add_fact(subject, "is-a", "river",
                             index.citation(type_hit))

        # The held-out entity has only canonical source wording and no stored
        # relation fact. The query uses the learned alternate wording.
        route = "The Serein River 0002 flows through Nacre City 0002."
        type_sentence = "The Serein River 0002 is a river."
        index.add_document("heldout-route", "held-out river route", route,
                           "heldout-route.txt")
        index.add_document("heldout-type", "held-out classification",
                           type_sentence, "heldout-type.txt")
        index.close()

        empty_path, learned_path = root / "empty.json", root / "learned.json"
        CRMSKnowledgeBase().save(empty_path)
        learner.save(learned_path)
        question = "Which river passes through Nacre City 0002?"

        def run_chat(name: str, knowledge_path: Path) -> str:
            args = {key: root / f"{name}-{key}.json" for key in (
                "rules", "rule-session", "candidates", "math",
                "math-session", "translations", "translation-session",
                "dialogue-state")}
            command = [
                sys.executable, str(PROJECT / "crms_chat.py"),
                "--index", str(index_path), "--knowledge", str(knowledge_path),
                "--rules", str(args["rules"]),
                "--rule-session", str(args["rule-session"]),
                "--candidate-session", str(args["candidates"]),
                "--math", str(args["math"]),
                "--math-session", str(args["math-session"]),
                "--translations", str(args["translations"]),
                "--translation-session", str(args["translation-session"]),
                "--dialogue-state", str(args["dialogue-state"]),
            ]
            result = subprocess.run(
                command, input=question + "\n/quit\n", text=True,
                capture_output=True, check=False, timeout=45)
            if result.returncode:
                raise SystemExit(f"{name} chat failed: {result.stderr}")
            return result.stdout

        baseline = run_chat("baseline", empty_path)
        if "held-out river route" in baseline:
            raise SystemExit("unlearned query retrieved the mismatched predicate")
        learned = run_chat("learned", learned_path)
        for required in (
                "The Serein River 0002 flows through Nacre City 0002.",
                "reviewed relation alignment links 'flows through'",
                "'passes through'", "candidate facts still need review"):
            if required not in learned:
                raise SystemExit(
                    f"learned alignment did not expose {required!r}: {learned}")
        if "Accepted fact" in learned:
            raise SystemExit("the held-out source fact bypassed review")

        # A surface form linked to two canonical relations must not broaden
        # the query to either one. Teach a second, equally reviewed family.
        ambiguous_learner = CRMSKnowledgeBase.load(learned_path)
        ambiguous_index = CRMSSQLiteResearchIndex(index_path)
        for number in range(4, 6):
            subject = f"Arin Brook {number:04d}"
            object_ = f"Stone City {number:04d}"
            for label, relation, phrase in (
                    ("travel-canonical", "travels through", "travels through"),
                    ("travel-alternate", "travels through", "passes through")):
                sentence = f"{subject} {phrase} {object_}."
                document_id = f"{label}-{number:04d}"
                ambiguous_index.add_document(
                    document_id, label, sentence, f"{document_id}.txt")
                hit = next(hit for hit in ambiguous_index.search(
                    sentence, limit=10) if hit.document_id == document_id)
                citation = ambiguous_index.citation(hit)
                ambiguous_learner.add_fact(
                    subject, relation, object_, citation)
                ambiguous_learner.teach_fact_pattern(
                    sentence, subject=subject, relation=relation,
                    obj=object_, predicate_phrase=phrase, source=citation)
        ambiguous_index.close()
        ambiguous_path = root / "ambiguous.json"
        ambiguous_learner.save(ambiguous_path)
        ambiguous = run_chat("ambiguous", ambiguous_path)
        if "held-out river route" in ambiguous:
            raise SystemExit(
                "ambiguous learned wording selected a canonical relation "
                f"without clarification: {ambiguous}")

    print("learned typed relation wording: PASS")
    print("two cited pairs licensed passes-through/flows-through retrieval; "
          "the held-out source was cited and remained review-only; an "
          "ambiguous alternate relation abstained")


if __name__ == "__main__":
    main()
