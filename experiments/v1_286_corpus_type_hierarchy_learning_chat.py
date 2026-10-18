"""Learn a cited type hierarchy through chat, then use it in a typed query."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase, _tokens
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-type-learning-chat-") as temp:
        root = Path(temp)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        for document_id, title, sentence in (
                ("route", "Serein River route",
                 "The Serein River flows through Nacre City."),
                ("kind", "Serein River classification",
                 "The Serein River is a river."),
                ("tax-river", "Waterway taxonomy",
                 "A river is a waterway."),
                ("tax-stream", "Waterway taxonomy",
                 "A stream is a waterway."),
                ("tax-canal", "Waterway taxonomy",
                 "A canal is a waterway."),
                ("tax-lake", "Landform taxonomy",
                 "A lake is a landform."),
                ("tax-mountain", "Landform taxonomy",
                 "A mountain is a landform.")):
            index.add_document(document_id, title, sentence,
                               f"fixture://{document_id}")
        index.close()

        def chat(state_path: Path, turns: str, session: str) -> str:
            command = [
                sys.executable, str(PROJECT / "crms_chat.py"),
                "--index", str(index_path),
                "--knowledge", str(state_path),
                "--rules", str(root / f"{session}-rules.json"),
                "--rule-session", str(root / f"{session}-rule-session.json"),
                "--candidate-session", str(root / f"{session}-candidates.json"),
                "--math", str(root / f"{session}-math.json"),
                "--math-session", str(root / f"{session}-math-session.json"),
                "--translations", str(root / f"{session}-translations.json"),
                "--translation-session",
                str(root / f"{session}-translation-session.json"),
                "--dialogue-state", str(root / f"{session}-dialogue.json"),
            ]
            result = subprocess.run(
                command, input=turns + "/quit\n", text=True,
                capture_output=True, check=False, timeout=45)
            require(result.returncode == 0,
                    f"{session} chat failed: {result.stderr}\n{result.stdout}")
            return result.stdout

        knowledge_path = root / "knowledge.json"
        first = chat(
            knowledge_path,
            "Which river flows through Nacre City?\n"
            "accept candidate 1\naccept candidate 1\n",
            "review-direct-type")
        require(first.count("Accepted positive fact:") == 2,
                f"the relation and direct type claims were not reviewed and accepted: {first}")
        reviewed = CRMSKnowledgeBase.load(knowledge_path)
        require(any(fact.subject == "The Serein River" and fact.relation == "is-a"
                    and fact.object == "river" for fact in reviewed.facts()),
                "accepted entity classification was not stored")
        before = len(reviewed.facts())

        proposals = chat(knowledge_path, "/suggest-corpus-frames\n",
                         "review-taxonomy-proposal")
        proposal_match = re.search(
            r"(?m)^you>\s*(\d+)\. is-a \(positive;", proposals)
        require(proposal_match is not None
                and "A river is a waterway." in proposals
                and "Report only: no facts or frames changed." in proposals,
                f"source taxonomy did not produce a review-only corpus frame: {proposals}")
        unchanged = CRMSKnowledgeBase.load(knowledge_path)
        require(len(unchanged.facts()) == before,
                "report-only taxonomy discovery mutated the fact store")

        proposal_number = proposal_match.group(1)
        learned = chat(
            knowledge_path,
            f"/accept-corpus-frame {proposal_number}\n"
            "Teach that the relation 'is-a' is transitive.\n"
            "Which waterway flows through Nacre City?\n",
            "accept-taxonomy-and-query")
        require("Accepted 'is-a'" in learned
                and "Stored explicit relation schema: is-a is transitive"
                in learned
                and "The Serein River is a waterway that flows through Nacre City."
                in learned,
                f"reviewed source taxonomy did not support the typed query: {learned}")
        for title in ("Serein River route", "Serein River classification",
                      "Waterway taxonomy"):
            require(title in learned,
                    f"inferred type answer lost source {title}: {learned}")
        final_store = CRMSKnowledgeBase.load(knowledge_path)
        type_result = final_store.infer_relation(
            "The Serein River", "is-a", "waterway")
        require(type_result.status == "answered" and type_result.proofs,
                f"the accepted hierarchy did not persist a proof: {type_result}")
        overlapping_pair = (_tokens("The Serein River"), _tokens("river"))
        require(any(
                    key[1] == _tokens("is-a")
                    and overlapping_pair in examples
                    for key, examples in final_store._fact_pattern_examples.items()),
                "role-ordered parsing did not retain the overlapping class frame")
        heldout = final_store.propose_facts(
            "A desert is a landform.", source="fixture://heldout-desert")
        require(len(heldout) == 1
                and heldout[0].subject == "desert"
                and _tokens(heldout[0].relation) == _tokens("is-a")
                and heldout[0].object == "landform"
                and not any(fact.subject == "desert"
                            and fact.relation == "is-a"
                            and fact.object == "landform"
                            for fact in final_store.facts()),
                f"reviewed class frame failed held-out extraction: {heldout}")

    print("corpus type hierarchy learning through chat: PASS")
    print("direct type claim reviewed; multi-source is-a frame proposed without "
          "mutation; reviewer accepted it; explicit transitivity schema enabled "
          "cited waterway answer; the learned class frame extracted a held-out "
          "claim without storing it")


if __name__ == "__main__":
    main()
