"""Mine, review, and use a corpus-derived relation frame on the academic index."""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index_path = (Path(__file__).resolve().parents[1]
                  / "data/crms_project_model_academic.sqlite.memories/research.sqlite")
    if not index_path.exists():
        raise SystemExit(f"large corpus index not found: {index_path}")
    index = CRMSSQLiteResearchIndex.load(index_path)
    learner = CRMSKnowledgeBase()
    bounds = {
        "maximum_documents": 2006,
        "maximum_sentences": 100_000,
        "maximum_proposals": 100,
    }
    proposals = learner.propose_corpus_relation_frames(index, **bounds)
    noisy_relations = {"this", "its", "is", "questions", "using", "rest of"}
    require(not (noisy_relations & {item["relation"] for item in proposals}),
            "fragment, function-word, or gerund-attachment relation survived mining")
    require(all(row["sentence"][-1:] in {".", "!", "?"}
                for item in proposals for row in item["support"]),
            "a non-sentence fragment was retained as corpus rule evidence")
    class_frame = next((item for item in proposals
                        if item["relation"] == "is-a" and item["polarity"]), None)
    require(class_frame is not None
            and class_frame["distinct_subjects"] >= 6
            and any(row["subject"] == "parser"
                    and row["object"] == "tokenizer"
                    for row in class_frame["support"]),
            "bounded common-noun classification did not increase corpus recall")
    class_learner = CRMSKnowledgeBase()
    class_learner.accept_corpus_relation_frame(
        class_frame["proposal_id"], index, **bounds)
    definition = class_learner.ask("What is the parser?")
    require(definition.status == "answered" and definition.answer == "tokenizer",
            f"learned type fact did not answer its definition question: {definition}")
    kind_definition = class_learner.ask(
        "What kind of thing is the parser?")
    require(kind_definition.status == "answered"
            and kind_definition.answer == "tokenizer",
            f"composed type-definition wording did not use the fact: {kind_definition}")
    type_definition = class_learner.ask(
        "What type of thing is the parser?")
    require(type_definition.status == "answered"
            and type_definition.answer == "tokenizer",
            f"type-of-thing wording did not use the fact: {type_definition}")
    typed_polar = class_learner.ask("Is the parser a tokenizer?")
    require(typed_polar.status == "answered" and typed_polar.answer == "Yes",
            f"learned type fact did not answer its polar question: {typed_polar}")
    open_world = class_learner.ask("Is the parser a compiler?")
    require(open_world.status == "unknown",
            "absence of a type fact was incorrectly treated as a negative")
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-corpus-type-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        class_learner.save(knowledge_path)
        command = [
            sys.executable, str(project / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(knowledge_path),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        chat = subprocess.run(
            command,
            input=("What kind of thing is the parser?\n"
                   "Is the parser a compiler?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=45)
        require(chat.returncode == 0,
                f"natural type-question chat exited {chat.returncode}: {chat.stderr}")
        require("parser is a tokenizer." in chat.stdout
                and "There is no explicit positive or negative evidence" in chat.stdout
                and "Source text:" not in chat.stdout,
                f"chat did not separate the supported type from the open-world unknown: {chat.stdout}")
    class_learner.add_negative_fact(
        "parser", "is-a", "compiler", "reviewed-negative-fixture")
    explicit_no = class_learner.ask("Is the parser a compiler?")
    require(explicit_no.status == "answered" and explicit_no.answer == "No"
            and explicit_no.truth is False,
            f"explicit negative type evidence did not answer No: {explicit_no}")
    class_learner.add_negative_fact(
        "parser", "is-a", "tokenizer", "conflicting-negative-fixture")
    conflict = class_learner.ask("Is the parser a tokenizer?")
    require(conflict.status == "ambiguous",
            f"conflicting type evidence did not produce ambiguity: {conflict}")

    proposal = next((item for item in proposals
                     if item["relation"] == "achieves"), None)
    require(proposal is not None and proposal["independent_documents"] >= 2,
            "the repeated achieves frame was not discovered across sources")
    accepted = learner.accept_corpus_relation_frame(
        proposal["proposal_id"], index, **bounds)
    require(len(accepted["support"]) == 2 and len(learner.facts()) == 2,
            "reviewed source examples were not committed as learned facts")

    for question, expected in (
            ("What does RSIFlow achieve?", "the SOTA average performance"),
            ("What does TITAN achieve?", "BLEU improvements")):
        answer = learner.ask(question)
        require(answer.status == "answered" and answer.answer == expected,
                f"learned corpus relation failed on {question}: {answer}")
    inverse = learner.ask("Who achieves BLEU improvements?")
    require(inverse.status == "answered" and inverse.answer == "TITAN",
            f"learned inverse question frame failed: {inverse}")
    unfamiliar_wh = learner.ask(
        "Which method achieves the SOTA average performance?")
    require(unfamiliar_wh.status == "unknown",
            "an unlearned wh-phrase was treated as supported")
    unknown = learner.ask("What does a new method achieve?")
    require(unknown.status == "unknown",
            "the new frame invented an answer for an unseen subject")
    with tempfile.TemporaryDirectory(prefix="crms-corpus-verb-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        learner.save(knowledge_path)
        command = [
            sys.executable, str(project / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(knowledge_path),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        chat = subprocess.run(
            command,
            input=("What does RSIFlow achieve?\n"
                   "Who achieves BLEU improvements?\n"
                   "What does a new method achieve?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=45)
        require(chat.returncode == 0,
                f"learned verb-frame chat exited {chat.returncode}: {chat.stderr}")
        require("RSIFlow achieves the SOTA average performance on all benchmarks."
                in chat.stdout
                and "TITAN achieves BLEU improvements of 33.75% on Hindi-to-Urdu"
                in chat.stdout
                and "I understand the 'achieves' question frame" in chat.stdout
                and "Source text:" not in chat.stdout,
                f"chat did not realize learned verbs or explain the missing fact: {chat.stdout}")

    print("corpus relation learning diagnostic: PASS")
    print(f"mined {len(proposals)} review-only frames from {index.document_count()} documents; "
          "reviewed class facts answered definition/polar forms; reviewed achieves "
          "facts answered two subjects and an inverse; unsupported claims abstained")


if __name__ == "__main__":
    main()
