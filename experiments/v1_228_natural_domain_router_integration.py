"""Exercise the natural-language domain router in one CRMS runtime session."""

from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-natural-router-") as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "rules.json", "math.json", "translations.json",
            "index.json", "dialogue.json", "rule-session.json")}

        kb = CRMSKnowledgeBase()
        for subject, obj, source in (("Alice", "tea", "alice"),
                                     ("Bob", "coffee", "bob")):
            kb.add_fact(subject, "likes", obj, source)
            kb.teach_fact_pattern(
                f"{subject} likes {obj}.", subject=subject,
                relation="likes", obj=obj, source=source,
                predicate_phrase="likes")
            kb.teach_question(
                f"What does {subject} like?", relation="likes",
                answer_field="object", bound_entity=subject, answer=obj)
            kb.teach_about_frame(f"Tell me about {subject}", entity=subject)
        for subject, relation, obj, source in (
                ("Ada", "founded", "Acme", "frame:ada-founded"),
                ("Grace", "founded", "Lab", "frame:grace-founded"),
                ("Ada", "launched", "Widget", "frame:ada-launched"),
                ("Bob", "launched", "Device", "frame:bob-launched")):
            kb.add_fact(subject, relation, obj, source)
            kb.teach_fact_pattern(
                f"{subject} {relation} {obj}.", subject=subject,
                relation=relation, obj=obj, source=source,
                predicate_phrase=relation)
        kb.add_fact("Ada", "founded", "Acme", "event:2012",
                    qualifiers={"year": "2012"})
        kb.add_fact("Ada", "launched", "Widget", "event:2010",
                    qualifiers={"year": "2010"})
        timeline = kb.write_timeline("Ada")
        require(timeline.status == "written"
                and timeline.text.index("In 2010") < timeline.text.index("In 2012"),
                f"explicit chronology was not written in order: {timeline}")
        conflict_timeline_kb = copy.deepcopy(kb)
        conflict_timeline_kb.add_negative_fact(
            "Ada", "founded", "Acme", "event:negative-2012",
            qualifiers={"year": "2012"})
        conflict_timeline = conflict_timeline_kb.write_timeline("Ada")
        require(conflict_timeline.conflicts
                and not any("founded Acme" in item["sentence"]
                            for item in conflict_timeline.statements),
                f"timeline stated an event with conflicting evidence: "
                f"{conflict_timeline}")
        mixed_precision_kb = copy.deepcopy(kb)
        mixed_precision_kb.add_fact(
            "Ada", "designed", "Bridge", "event:full-date",
            qualifiers={"year": "2012-06-01"})
        mixed_precision = mixed_precision_kb.write_timeline("Ada")
        require(not mixed_precision.statements
                and any(item.get("reason") == "mixed year and full-date precision"
                        for item in mixed_precision.omitted),
                f"timeline ranked incomparable date precision: {mixed_precision}")
        kb.save(paths["knowledge.json"])

        rules = CRMSModel(max_composition_depth=1, max_workers=1)
        learned = rules.teach(
            "reverse the list",
            [([1, 2, 3], [3, 2, 1]), ([4, -1, 7], [7, -1, 4])])
        require(learned.status == "learned", f"coding fixture failed: {learned}")
        rules.save(paths["rules.json"])

        math = CRMSMath()
        require(math.teach("What is 2 plus 3?", "5").status
                == "needs_more_examples", "math fixture licensed too early")
        require(math.teach("What is 5 plus 3?", "8").status == "licensed",
                "math fixture did not license the operator")
        math.save(paths["math.json"])

        translations = CRMSTranslation()
        translations.teach(
            "English", "French", "formal", "Hello, {name}.",
            "Bonjour, {name}.",
            [("Hello, Ada.", "Bonjour, Ada."),
             ("Hello, Malik.", "Bonjour, Malik.")])
        translations.save(paths["translations.json"])

        index = CRMSResearchIndex()
        index.add_document(
            "mars", "Mars Pathfinder",
            "Mars Pathfinder landed on Mars in 1997. "
            "The mission used the Sojourner rover to study rocks.",
            "book:mars")
        index.save(paths["index.json"])

        command = [sys.executable, str(ROOT / "crms_chat.py"),
                   "--knowledge", str(paths["knowledge.json"]),
                   "--rules", str(paths["rules.json"]),
                   "--math", str(paths["math.json"]),
                   "--translations", str(paths["translations.json"]),
                   "--index", str(paths["index.json"]),
                   "--dialogue-state", str(paths["dialogue.json"]),
                   "--rule-session", str(paths["rule-session.json"])]
        requests = (
            'Teach a fact pattern from labeled examples: "Ada mentors Bo." => '
            '"Ada" | "mentors" | "Bo"; "Cara mentors Dee." => '
            '"Cara" | "mentors" | "Dee"',
            'Remember that "Eli mentors Fay." as a fact from source '
            '"teacher:conversation".',
            "Can you write Python code to reverse the list?",
            "Can you reverse the list in Python?",
            "What is 17 plus -6?",
            "Translate from English to French in formal register: Hello, Rowan.",
            "How would I say Hello, Rowan. in French?",
            'Remember that "Alice likes tea." as a fact from source '
            '"teacher:conversation".',
            "What does Alice like?",
            "Why?",
            "Tell me the story of Ada ordered by year.",
            "Tell me about Alice.",
            "Summarize the Mars rover mission.",
            'Retract the positive fact "Alice likes tea." from source '
            '"teacher:conversation".',
            "What does Alice like?",
            "Why?",
            'Retract the positive fact "Alice likes tea." from source "alice".',
            "What does Alice like?",
            "Why?",
            "Tell me the story of Ada ordered by year.",
            "Why?",
            "/quit",
        )
        run = subprocess.run(
            command, input="\n".join(requests) + "\n", text=True,
            capture_output=True, cwd=root, timeout=30)
        require(run.returncode == 0,
                f"integrated CRMS session failed:\n{run.stdout}\n{run.stderr}")
        for expected in (
                "Stored 2 teacher-labeled positive facts",
                "The fact pattern is licensed.",
                "Stored positive fact: Eli — mentors → Fay "
                "[source: teacher:conversation].",
                "Generated Python for 'reverse the list'",
                "11 (learned 'plus' as exact add",
                "Bonjour, Rowan.",
                "Stored positive fact: Alice — likes → tea "
                "[source: teacher:conversation].",
                "Answer: tea.", "Alice likes tea.",
                "Timeline for Ada, ordered by year:",
                "In 2010, Ada launched Widget.",
                "In 2012, Ada founded Acme.",
                "The mission used the Sojourner rover to study rocks.",
                "Retracted that source's support; other citations remain.",
                "Retracted the final source support; the fact is no longer stored.",
                "I don't know this from the sources and facts I have. "
                "Add a source or teach the fact.",
                "There is no previous grounded answer to explain yet."):
            require(expected in run.stdout,
                    f"natural-language route missed {expected!r}:\n{run.stdout}")
        require(run.stdout.count("Answer: tea.") == 2,
                "Why? reused an answer after its final source was retracted")
        require(run.stdout.count("Generated Python for 'reverse the list'") == 2,
                "explicit Python task wording did not reach grounded code generation")
        require(run.stdout.count("Bonjour, Rowan.") >= 2,
                "both explicit and conversational translation wording must use the learned frame")
        require(run.stdout.count("In 2010, Ada launched Widget.") == 3,
                "timeline follow-up did not recompute and explain the grounded timeline")
        restored_timeline = subprocess.run(
            command, input="Why?\n/quit\n", text=True, capture_output=True,
            cwd=root, timeout=30)
        require(restored_timeline.returncode == 0
                and "Timeline for Ada, ordered by year:" in restored_timeline.stdout
                and "In 2010, Ada launched Widget." in restored_timeline.stdout
                and "In 2012, Ada founded Acme." in restored_timeline.stdout,
                f"timeline follow-up did not survive restart:\n"
                f"{restored_timeline.stdout}\n{restored_timeline.stderr}")
        learned_knowledge = CRMSKnowledgeBase.load(paths["knowledge.json"])
        require(any(fact.subject == "Eli" and fact.relation == "mentors"
                    and fact.object == "Fay"
                    and "teacher:conversation" in fact.sources
                    for fact in learned_knowledge.facts()),
                "natural teacher examples did not license reusable fact learning")

        scoped = CRMSKnowledgeBase()
        scoped.add_fact("Alice", "likes", "tea", "shared",
                        qualifiers={"year": "2024"})
        scoped.add_fact("Alice", "likes", "tea", "shared",
                        qualifiers={"year": "2025"})
        scoped.add_fact("Alice", "likes", "tea", "frame:alice")
        scoped.add_fact("Bob", "likes", "coffee", "other")
        scoped.teach_fact_pattern(
            "Alice likes tea.", subject="Alice", relation="likes",
            obj="tea", source="frame:alice", predicate_phrase="likes")
        scoped.teach_fact_pattern(
            "Bob likes coffee.", subject="Bob", relation="likes",
            obj="coffee", source="other", predicate_phrase="likes")
        scoped_path = root / "scoped-knowledge.json"
        scoped.save(scoped_path)
        scoped_run = subprocess.run(
            [sys.executable, str(ROOT / "crms_chat.py"),
             "--knowledge", str(scoped_path),
             "--rules", str(paths["rules.json"]),
             "--math", str(paths["math.json"]),
             "--translations", str(paths["translations.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(root / "scoped-dialogue.json"),
             "--rule-session", str(root / "scoped-rule-session.json")],
            input=('Retract the positive fact "Alice likes tea." from source '
                   '"shared".\n'
                   'Retract the positive fact "Alice likes tea." from source '
                   '"shared" in context "year=2024".\n/quit\n'),
            text=True, capture_output=True, cwd=root, timeout=30)
        require(scoped_run.returncode == 0
                and "multiple scoped facts" in scoped_run.stdout
                and "Retracted the final source support" in scoped_run.stdout,
                f"natural scoped retraction failed:\n{scoped_run.stdout}\n"
                f"{scoped_run.stderr}")
        restored_scoped = CRMSKnowledgeBase.load(scoped_path)
        remaining_years = {
            dict(fact.qualifiers).get("year")
            for fact in restored_scoped.facts()
            if fact.subject == "Alice" and fact.relation == "likes"
            and fact.object == "tea"}
        require(remaining_years == {None, "2025"},
                f"scoped retraction removed the wrong context: {remaining_years}")

        conflicting = CRMSKnowledgeBase()
        conflicting.add_fact("Alice", "likes", "tea", "existing:positive")
        conflicting_path = root / "conflicting-knowledge.json"
        conflicting.save(conflicting_path)
        conflict_batch = (
            'Teach a fact pattern from labeled examples: '
            '"Alice does not like tea." => "Alice" | "likes" | "tea" | "negative"; '
            '"Bob does not like coffee." => "Bob" | "likes" | "coffee" | "negative"')
        conflict_run = subprocess.run(
            [sys.executable, str(ROOT / "crms_chat.py"),
             "--knowledge", str(conflicting_path),
             "--rules", str(paths["rules.json"]),
             "--math", str(paths["math.json"]),
             "--translations", str(paths["translations.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(root / "conflict-dialogue.json"),
             "--rule-session", str(root / "conflict-rule-session.json")],
            input=conflict_batch + "\n/quit\n", text=True,
            capture_output=True, cwd=root, timeout=30)
        require(conflict_run.returncode == 0
                and "nothing was saved" in conflict_run.stdout,
                f"conflicting teacher batch was not rejected:\n{conflict_run.stdout}")
        unchanged = CRMSKnowledgeBase.load(conflicting_path)
        require(len(unchanged.facts()) == 1 and not unchanged.negative_facts(),
                "rejected teacher batch partially changed stored facts")
        print("natural-language domain router integration: PASS")
        print("coding, mathematics, translation, factual QA, grounded writing, and "
              "source-cited research routed in one terminal session")


if __name__ == "__main__":
    main()
