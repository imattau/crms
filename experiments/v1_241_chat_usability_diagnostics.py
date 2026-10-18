"""Check chat guidance, abstention reasons, articles, and pending rule state.

Run from the project root with:
    python3 experiments/v1_241_chat_usability_diagnostics.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    for subject, obj, source in (("Alice", "tea", "a.txt"),
                                 ("Bob", "coffee", "b.txt")):
        kb.add_fact(subject, "likes", obj, source)
        kb.teach_question(
            f"Who likes {obj}?", relation="likes", answer_field="subject",
            bound_entity=obj, answer=subject)

    missing_fact = kb.ask("Who likes water?")
    require("frame" in (missing_fact.request or "")
            and "no matching fact" in (missing_fact.request or ""),
            f"known frame did not explain the missing fact: {missing_fact}")
    near_miss = kb.ask("Who loves tea?")
    require("closest taught frame" in (near_miss.request or "")
            and "Who likes {object}?" in (near_miss.request or ""),
            f"unsupported wording did not identify its nearest frame: {near_miss}")
    article = kb.ask("Who likes the tea?")
    require(article.status == "answered" and article.answer == "Alice",
            f"leading article prevented a known entity match: {article}")
    bare = kb.ask("Who likes tea?")
    require(article.matched_templates == bare.matched_templates
            and article.matched_templates == ["who likes {object}"],
            "article surface variation changed the matched question frame")
    require(not any(item.get("kind") == "optional_question_word"
                    for item in article.language_evidence or []),
            "article normalization was misreported as learned optional-word evidence")
    dangling_article = kb.ask("Who likes the?")
    require(dangling_article.status != "answered",
            f"article without a grounded entity produced an answer: {dangling_article}")
    unknown_article_entity = kb.ask("Who likes the water?")
    require(unknown_article_entity.status == "unknown",
            f"article normalization invented an entity: {unknown_article_entity}")

    optional_kb = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Alice", "tea", "optional:tea"),
            ("Bob", "coffee", "optional:coffee"),
            ("Mira", "water", "optional:water")):
        optional_kb.add_fact(subject, "likes", obj, source)
        if subject != "Mira":
            for question in (f"Who likes {obj}?", f"Who likes the {obj}?",
                             f"Who likes {obj} please?",
                             f"Please who likes {obj}?"):
                optional_kb.teach_question(
                    question, relation="likes", answer_field="subject",
                    bound_entity=obj, answer=subject)
    optional = optional_kb.ask("Who likes the water?")
    optional_trace = next((item for item in optional.language_evidence or []
                           if item.get("kind") == "optional_question_word"), None)
    require(optional.status == "answered" and optional.answer == "Mira"
            and optional_trace is not None
            and optional_trace.get("word") == "the"
            and len(optional_trace.get("support", [])) >= 2,
            f"paired grounded examples did not license and trace optional word: {optional}")
    optional_render = optional_kb.render(optional)
    require("Learned optional question word: 'the'" in optional_render
            and "optional:tea" in optional_render
            and "optional:coffee" in optional_render,
            f"optional-word trace was not rendered with its sources: {optional_render}")
    optional_turn = CRMSDialogue(optional_kb).turn("Who likes the water?")
    require(optional_turn.status == "answered"
            and "Learned optional question word: 'the'" in optional_turn.text,
            f"chat did not expose the learned optional-word trace: {optional_turn}")
    polite = optional_kb.ask("Who likes water please?")
    require(polite.status == "answered" and polite.answer == "Mira"
            and any(item.get("kind") == "optional_question_word"
                    and item.get("word") == "please"
                    for item in polite.language_evidence or []),
            f"learned optional trailing token did not transfer: {polite}")
    composed_optional = optional_kb.ask("Please who likes the water?")
    composed_words = {item.get("word") for item in
                      composed_optional.language_evidence or []
                      if item.get("kind") == "optional_question_word"}
    require(composed_optional.status == "answered"
            and composed_optional.answer == "Mira"
            and "please who likes the {object}"
            in (composed_optional.matched_templates or [])
            and {"please", "the"}.issubset(composed_words),
            f"independently learned optional tokens did not compose: {composed_optional}")
    with tempfile.TemporaryDirectory() as folder:
        persisted = Path(folder) / "optional-language.json"
        optional_kb.save(persisted)
        restored = CRMSKnowledgeBase.load(persisted).ask("Who likes the water?")
        require(restored.status == "answered"
                and any(item.get("kind") == "optional_question_word"
                        for item in restored.language_evidence or []),
                f"learned optional-word evidence did not reconstruct after load: {restored}")
    swapped_relation = optional_kb.ask("Who hates the water?")
    require(swapped_relation.status != "answered",
            f"optional-word evidence changed the relation: {swapped_relation}")
    require(optional_kb.remove_fact("Alice", "likes", "tea", "optional:tea"),
            "could not retract one optional-word support fact")
    after_retraction = optional_kb.ask("Who likes the water?")
    require(not any(item.get("kind") == "optional_question_word"
                    for item in after_retraction.language_evidence or []),
            f"optional-word trace survived retraction below its support threshold: {after_retraction}")

    phrase_kb = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Alice", "tea", "phrase:tea"),
            ("Bob", "coffee", "phrase:coffee"),
            ("Mira", "water", "phrase:water")):
        phrase_kb.add_fact(subject, "likes", obj, source)
        phrase_kb.teach_question(
            f"Who likes {obj}?", relation="likes", answer_field="subject",
            bound_entity=obj, answer=subject)
        if subject != "Mira":
            phrase_kb.teach_question(
                f"Please tell me who likes {obj}?", relation="likes",
                answer_field="subject", bound_entity=obj, answer=subject)
            phrase_kb.teach_question(
                f"Who likes {obj} in particular?", relation="likes",
                answer_field="subject", bound_entity=obj, answer=subject)
    composed_phrase_question = (
        "Please tell me who likes water in particular?")
    phrase_answer = phrase_kb.ask(composed_phrase_question)
    phrase_traces = [item for item in phrase_answer.language_evidence or []
                     if item.get("kind") == "optional_question_phrase"]
    require(phrase_answer.status == "answered"
            and phrase_answer.answer == "Mira"
            and {item.get("word") for item in phrase_traces}
            >= {"please tell me", "in particular"}
            and all(len(item.get("support", [])) >= 2
                    for item in phrase_traces),
            f"independent phrase examples did not compose for a held-out entity: {phrase_answer}")
    phrase_render = phrase_kb.render(phrase_answer)
    phrase_turn = CRMSDialogue(phrase_kb).turn(composed_phrase_question)
    require("Learned optional question phrase: 'please tell me'" in phrase_render
            and "Learned optional question phrase: 'in particular'" in phrase_turn.text,
            f"phrase-learning provenance was not shown in natural dialogue: {phrase_turn}")
    phrase_near_miss = phrase_kb.ask(
        "Tell me please who likes water in particular?")
    require(phrase_near_miss.status != "answered",
            f"the learned phrase ignored its observed word order: {phrase_near_miss}")
    with tempfile.TemporaryDirectory() as folder:
        persisted = Path(folder) / "optional-phrase-language.json"
        phrase_kb.save(persisted)
        restored = CRMSKnowledgeBase.load(persisted).ask(
            composed_phrase_question)
        require(restored.status == "answered"
                and {item.get("word") for item in restored.language_evidence or []
                     if item.get("kind") == "optional_question_phrase"}
                >= {"please tell me", "in particular"},
                f"optional phrase evidence did not reconstruct after load: {restored}")
    intersection = kb.ask("Who likes tea and coffee?")
    require("No answer is supported by every clause" in
            (intersection.request or ""),
            f"empty intersection did not explain the result: {intersection}")
    greeting = CRMSDialogue(kb).turn("Hi, how are you?")
    require("supplied sources and learned facts" in greeting.text,
            f"greeting did not return the scope statement: {greeting}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--knowledge", str(root / "knowledge.json"),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json"),
                   "--rules", str(root / "rules.json"),
                   "--rule-session", str(root / "rule-session.json"),
                   "--math", str(root / "math.json"),
                   "--translations", str(root / "translations.json")]
        output = subprocess.run(
            command,
            input=("reverse the list [1,2] -> [2,1]\n"
                   "What is 2 + 3?\n/cancel-rule\n/help\n/help all\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30).stdout
        require("type /help for a quick start" in output
                and "Use /help all for the complete command reference." in output,
                "startup or short help did not show the onboarding path")
        require("still waiting for the output" in output
                and "this input will be handled separately" in output
                and "CRMS> 5 (exact arithmetic" in output,
                f"pending rule blocked or hid unrelated input: {output}")
        require("/teach-counterfactual-path-question" in output,
                "full help was not available through /help all")

    print("chat usability diagnostics: PASS")
    print("specific abstention, nearest frame, guarded article normalization, "
          "evidence-learned optional word and composed phrase with trace/persistence, "
          "relation guard, "
          "conservative intersection, small-talk scope, pending-state visibility, "
          "and help: PASS")


if __name__ == "__main__":
    main()
