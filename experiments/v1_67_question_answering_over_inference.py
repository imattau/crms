"""Use recursive rule proofs to answer learned entity-slot questions."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_dialogue import CRMSDialogue


PROJECT = Path(__file__).resolve().parents[1]


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, middle, target, source in (
            ("Ada", "Bea", "Cal", "one"),
            ("Dee", "Eli", "Fay", "two"),
            ("Nia", "Oren", "Pia", "three")):
        kb.add_fact(subject, "parent", middle, f"{source}:first")
        kb.add_fact(middle, "parent", target, f"{source}:second")
    kb.add_inference_rule("parent-transitivity", "parent", "parent", "ancestor")
    return kb


def teach_two_examples(kb: CRMSKnowledgeBase) -> None:
    licensed = kb.teach_question(
        "Who is an ancestor of Cal?", relation="ancestor", answer_field="subject",
        bound_entity="Cal", answer="Ada")
    if licensed:
        raise SystemExit("one question example licensed its frame too early")
    licensed = kb.teach_question(
        "Who is an ancestor of Fay?", relation="ancestor", answer_field="subject",
        bound_entity="Fay", answer="Dee")
    if not licensed:
        raise SystemExit("two proof-backed answers did not license the question frame")
    for subject, obj in (("Ada", "Bea"), ("Dee", "Eli")):
        kb.teach_question(
            f"What did {subject} parent?", relation="parent",
            answer_field="object", bound_entity=subject, answer=obj)


def main() -> None:
    kb = seed()
    teach_two_examples(kb)
    result = kb.ask("Who is an ancestor of Pia?")
    if (result.status != "answered" or result.answer != "Nia"
            or not result.inference_proofs):
        raise SystemExit(f"learned slot question did not find inferred answer: {result}")
    rendered = kb.render(result)
    if "parent-transitivity" not in rendered or "three:first" not in rendered:
        raise SystemExit(f"answer omitted recursive proof provenance:\n{rendered}")
    kb.add_fact("Leo", "parent", "Mara", "four:first")
    kb.add_fact("Mara", "parent", "Cal", "four:second")
    multiple = kb.ask("Who is an ancestor of Cal?")
    if (multiple.status != "ambiguous"
            or set(multiple.candidates or []) != {"Ada", "Leo"}):
        raise SystemExit(f"multiple inferred answers were not surfaced: {multiple}")

    bounded_kb = seed()
    teach_two_examples(bounded_kb)
    for index in range(110):
        bounded_kb.add_fact(f"NoiseSubject{index}", "unrelated",
                            f"NoiseObject{index}", f"noise:{index}")
    noise_result = bounded_kb.ask("Who is an ancestor of Cal?")
    if (noise_result.status != "answered" or noise_result.answer != "Ada"):
        raise SystemExit(
            f"unrelated facts prevented a complete inference answer: {noise_result}")

    branching_kb = seed()
    teach_two_examples(branching_kb)
    width = 8
    for middle_index in range(width):
        middle = f"SharedMiddle{middle_index:03d}"
        branching_kb.add_fact(middle, "parent", "Cal",
                              f"shared:{middle_index}")
        for answer_index in range(width):
            branching_kb.add_fact(
                f"DenseAnswer{answer_index:03d}", "parent", middle,
                f"dense:{answer_index}:{middle_index}")
    partial = branching_kb.ask(
        "Who is an ancestor of Cal?", max_inference_expansions=10)
    if (partial.status != "unknown" or partial.candidates
            or "complete answer set" not in (partial.request or "")):
        raise SystemExit(
            f"partial inference results escaped a genuinely branching search: {partial}")
    try:
        branching_kb.ask("Who is an ancestor of Cal?", max_inference_expansions=0)
    except ValueError:
        pass
    else:
        raise SystemExit("invalid aggregate inference budget was accepted")
    if kb.ask("Which person precedes Pia as an ancestor?").status != "unknown":
        raise SystemExit("unlicensed wording was generalized")

    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who is an ancestor of Pia?")
    if first.response is None or first.response.answer != "Nia":
        raise SystemExit(f"dialogue did not preserve inferred answer: {first}")
    with tempfile.TemporaryDirectory() as folder:
        state_path = Path(folder) / "dialogue.json"
        dialogue.save(str(state_path))
        dialogue = CRMSDialogue.load(kb, str(state_path))
    pronoun_target = dialogue.turn("Who is an ancestor of it?")
    if (pronoun_target.resolved_question != "Who is an ancestor of Pia?"
            or pronoun_target.response is None
            or pronoun_target.response.answer != "Nia"):
        raise SystemExit(f"inferred answer did not bind object referent: {pronoun_target}")
    pronoun_subject = dialogue.turn("What did she parent?")
    if (pronoun_subject.resolved_question != "What did Nia parent?"
            or pronoun_subject.response is None
            or pronoun_subject.response.answer != "Oren"):
        raise SystemExit(f"inferred answer did not bind subject referent: {pronoun_subject}")

    kb.add_negative_fact("Nia", "ancestor", "Pia", "explicit:negative")
    conflict = kb.ask("Who is an ancestor of Pia?")
    if conflict.status != "ambiguous" or not conflict.inference_proofs:
        raise SystemExit(f"negative evidence did not conflict with inferred answer: {conflict}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json", "session.json")}
        cli_kb = seed()
        cli_kb.save(paths["knowledge.json"])
        CRMSResearchIndex().save(paths["index.json"])
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(paths["knowledge.json"]),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"])]
        commands = [
            "/teach-question Who is an ancestor of Cal?|ancestor|subject|Cal|Ada",
            "/teach-question Who is an ancestor of Fay?|ancestor|subject|Fay|Dee",
            "Who is an ancestor of Pia?",
            "Why?",
            "/quit",
        ]
        output = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if ("Nia is an ancestor of Pia." not in output
                or "parent-transitivity" not in output
                or "three:first" not in output):
            raise SystemExit(f"CLI did not answer the learned question with proof:\n{output}")
        loaded = CRMSKnowledgeBase.load(paths["knowledge.json"])
        persisted = loaded.ask("Who is an ancestor of Pia?")
        if persisted.status != "answered" or persisted.answer != "Nia":
            raise SystemExit("learned inferential question did not persist")
    print("question answering over inference diagnostic: PASS")
    print("proof-backed frame learning, slot search, ambiguity, noise pruning, true budget abstention, CLI and persistence: PASS")


if __name__ == "__main__":
    main()
