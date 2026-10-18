"""Check evidence-backed question-frame learning without an LLM.

Run from the project root with:
    python3 experiments/v1_29_grounded_question_answering.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada Lovelace", "designed", "Analytical Engine", "book:history-1")
    kb.add_fact("Grace Hopper", "designed", "Compiler", "paper:compiler-history")
    kb.add_fact("Ada Lovelace", "designed", "Compiler", "archive:design-notes")
    kb.add_fact("Ada Lovelace", "designed", "Analytical Engine", "museum:catalog")

    if kb.teach_question(
        "Who designed Analytical Engine?", relation="designed",
        answer_field="subject", bound_entity="Analytical Engine",
        answer="Ada Lovelace",
    ):
        raise SystemExit("one grounded example should not license a variable frame")
    unlicensed = kb.ask("Who designed Compiler?")
    if unlicensed.status != "unknown":
        raise SystemExit(f"single example generalized too early: {unlicensed}")

    if not kb.teach_question(
        "Who designed Compiler?", relation="designed",
        answer_field="subject", bound_entity="Compiler", answer="Grace Hopper",
    ):
        raise SystemExit("two distinct grounded objects did not license the question frame")

    answer = kb.ask("Who designed Analytical Engine?")
    if (answer.status != "answered" or answer.answer != "Ada Lovelace"
            or len(answer.evidence or []) != 1
            or set(answer.evidence[0]["sources"])
            != {"book:history-1", "museum:catalog"}):
        raise SystemExit(f"fact conflict or provenance was lost: {answer}")

    # A third fact makes this query ambiguous; answers are never guessed.
    compiler = kb.ask("Who designed Compiler?")
    if (compiler.status != "ambiguous"
            or set(compiler.candidates or []) != {"Ada Lovelace", "Grace Hopper"}):
        raise SystemExit(f"competing answers were not surfaced: {compiler}")
    rendered_conflict, conflict_text = kb.respond("Who designed Compiler?")
    if (rendered_conflict.status != "ambiguous"
            or "multiple supported answers" not in conflict_text
            or "Ada Lovelace" not in conflict_text
            or "Grace Hopper" not in conflict_text):
        raise SystemExit(f"controlled ambiguous response failed: {conflict_text}")

    kb.add_fact("Ada Lovelace", "designed", "Notes", "archive:design-notes")
    kb.add_fact("Grace Hopper", "designed", "Compiler", "paper:compiler-history")
    if kb.teach_question(
        "Which thing did Ada Lovelace design?", relation="designed",
        answer_field="object", bound_entity="Ada Lovelace", answer="Notes",
    ):
        raise SystemExit("one forward frame example should remain unlicensed")
    if kb.teach_question(
        "Which thing did Ada Lovelace design?", relation="designed",
        answer_field="object", bound_entity="Ada Lovelace", answer="Compiler",
    ):
        raise SystemExit("repeated bound entity should not count as independent frame support")
    kb.add_fact("Katherine Johnson", "designed", "Trajectory", "report:flight")
    if not kb.teach_question(
        "Which thing did Katherine Johnson design?", relation="designed",
        answer_field="object", bound_entity="Katherine Johnson", answer="Trajectory",
    ):
        raise SystemExit("two distinct subjects did not license the forward frame")
    forward = kb.ask("Which thing did Katherine Johnson design?")
    if forward.status != "answered" or forward.answer != "Trajectory":
        raise SystemExit(f"forward question failed: {forward}")

    synonym = kb.ask("Who created Compiler?")
    if synonym.status != "unknown":
        raise SystemExit(f"unlearned wording was treated as a synonym: {synonym}")
    _, unknown_text = kb.respond("Who created Compiler?")
    if "don't have a grounded answer" not in unknown_text:
        raise SystemExit(f"unknown response was not rendered as abstention: {unknown_text}")
    unknown_entity = kb.ask("Who designed Unknown Machine?")
    if unknown_entity.status != "unknown" or not unknown_entity.matched_templates:
        raise SystemExit(f"unknown entity did not yield grounded abstention: {unknown_entity}")

    kb.add_fact("Marie Curie", "born in", "Warsaw", "bio:curie")
    kb.add_fact("Warsaw", "located in", "Poland", "geo:warsaw")
    kb.add_fact("Albert Einstein", "born in", "Ulm", "bio:einstein")
    kb.add_fact("Ulm", "located in", "Germany", "geo:ulm")
    path_relations = ["born in", "located in"]
    if kb.teach_path_question(
        "Which country is Marie Curie born in?", relations=path_relations,
        bound_entity="Marie Curie", answer="Poland",
    ):
        raise SystemExit("one path question should not license a variable frame")
    if not kb.teach_path_question(
        "Which country is Albert Einstein born in?", relations=path_relations,
        bound_entity="Albert Einstein", answer="Germany",
    ):
        raise SystemExit("two grounded path questions did not license a frame")
    path_question = kb.ask("Which country is Marie Curie born in?")
    if path_question.status != "answered" or path_question.answer != "Poland":
        raise SystemExit(f"grounded path question was not answered: {path_question}")
    unknown_path_entity = kb.ask("Which country is Ada Lovelace born in?")
    if (unknown_path_entity.status != "unknown"
            or not unknown_path_entity.matched_templates):
        raise SystemExit(f"unknown path entity did not abstain: {unknown_path_entity}")
    unseen_path_wording = kb.ask("Which nation is Marie Curie born in?")
    if unseen_path_wording.status != "unknown":
        raise SystemExit(f"unseen path wording generalized without evidence: {unseen_path_wording}")

    path_answer = kb.ask_path("Marie Curie", ["born in", "located in"])
    if (path_answer.status != "answered" or path_answer.answer != "Poland"
            or len(path_answer.proofs or []) != 1
            or len(path_answer.proofs[0]) != 2):
        raise SystemExit(f"two-hop answer lacked an explicit proof: {path_answer}")
    path_text = kb.render(path_answer)
    if ("Marie Curie" not in path_text or "Warsaw" not in path_text
            or "Poland" not in path_text or "geo:warsaw" not in path_text):
        raise SystemExit(f"proof response omitted its path or provenance: {path_text}")
    missing_path = kb.ask_path("Unknown Person", ["born in", "located in"])
    if missing_path.status != "unknown":
        raise SystemExit(f"missing path did not abstain: {missing_path}")
    kb.add_fact("Warsaw", "located in", "Mazovia", "geo:region")
    ambiguous_path = kb.ask_path("Marie Curie", ["born in", "located in"])
    if (ambiguous_path.status != "ambiguous"
            or set(ambiguous_path.candidates or []) != {"Poland", "Mazovia"}):
        raise SystemExit(f"competing path endpoints were not surfaced: {ambiguous_path}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "facts.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        frame_after_load = restored.ask("Which thing did Katherine Johnson design?")
        path_frame_after_load = restored.ask("Which country is Albert Einstein born in?")
        after_load = restored.ask_path("Marie Curie", ["born in", "located in"])
    if frame_after_load.status != "answered" or frame_after_load.answer != "Trajectory":
        raise SystemExit(f"question frame did not survive persistence: {frame_after_load}")
    if (path_frame_after_load.status != "answered"
            or path_frame_after_load.answer != "Germany"):
        raise SystemExit(f"path question frame did not survive persistence: {path_frame_after_load}")
    if (after_load.status != "ambiguous"
            or set(after_load.candidates or []) != {"Poland", "Mazovia"}):
        raise SystemExit(f"fact path did not survive persistence: {after_load}")
    if not any(set(fact["sources"]) == {"geo:warsaw"}
               for fact in after_load.evidence or []):
        raise SystemExit(f"path source provenance did not survive persistence: {after_load}")

    print("grounded question answering diagnostic: PASS")
    print("two-example frame learning, ambiguity, unknowns, two-hop proof, provenance, persistence: PASS")


if __name__ == "__main__":
    main()
