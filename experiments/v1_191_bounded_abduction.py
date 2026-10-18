"""Check bounded abduction over cited pending facts without committing them."""

from __future__ import annotations

from dataclasses import asdict, replace
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase, FactCandidate, FactEvidence
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    sentences = {
        "pending-bc": "Bea is parent of Cal.",
        "pending-cd": "Cal is parent of Dee.",
        "pending-noise": "Eve is parent of Fox.",
        "pending-direct": "Ada is ancestor of Dee.",
    }
    candidates = {}
    for document_id, sentence in sentences.items():
        index.add_document(document_id, document_id, sentence,
                           f"https://research.test/{document_id}")
        hit = index.search(sentence, limit=1)[0]
        subject, obj = {
            "pending-bc": ("Bea", "Cal"),
            "pending-cd": ("Cal", "Dee"),
            "pending-noise": ("Eve", "Fox"),
            "pending-direct": ("Ada", "Dee"),
        }[document_id]
        relation = "ancestor" if document_id == "pending-direct" else "parent"
        candidates[document_id] = FactCandidate(
            subject, relation, obj, index.citation(hit), "fixture", sentence)

    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "parent", "Bea", "teacher:ab")
    kb.add_fact("Grace", "parent", "Hopper", "frame:parent")
    kb.teach_fact_pattern(
        "Ada is parent of Bea.", subject="Ada", relation="parent", obj="Bea",
        source="teacher:ab", predicate_phrase="is parent of")
    kb.teach_fact_pattern(
        "Grace is parent of Hopper.", subject="Grace", relation="parent",
        obj="Hopper", source="frame:parent", predicate_phrase="is parent of")
    parsed_parent = kb.propose_facts(
        "Cal is parent of Dee.", source="heldout:parent")
    require(len(parsed_parent) == 1
            and (parsed_parent[0].subject, parsed_parent[0].relation,
                 parsed_parent[0].object) == ("Cal", "parent", "Dee"),
            f"licensed predicate words leaked into entity spans: {parsed_parent}")
    for subject, obj, source in (("Iris", "Jules", "frame:ancestor-1"),
                                 ("Mira", "Noel", "frame:ancestor-2")):
        kb.add_fact(subject, "ancestor", obj, source)
        kb.teach_fact_pattern(
            f"{subject} is ancestor of {obj}.", subject=subject,
            relation="ancestor", obj=obj, source=source,
            predicate_phrase="is ancestor of")

    for document_id, candidate in list(candidates.items()):
        proposed = kb.propose_facts(candidate.sentence, source=candidate.source)
        match = next((item for item in proposed
                      if (item.subject, item.relation, item.object)
                      == (candidate.subject, candidate.relation, candidate.object)),
                     None)
        if match is None:
            raise SystemExit(f"fixture sentence was not learned: {document_id}")
        candidates[document_id] = match

    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    kb.add_inference_rule("ancestor-chain", "parent", "ancestor", "ancestor")
    before_facts = kb.facts()

    result = kb.abduce_relation(
        "Ada", "ancestor", "Dee",
        candidates=[candidates["pending-bc"], candidates["pending-cd"],
                    candidates["pending-noise"]],
        research_index=index, max_hypothesis_size=2)
    require(result.status == "hypotheses" and result.complete
            and len(result.hypotheses) == 1,
            f"bounded abduction did not find the minimal two-fact set: {result}")
    hypothesis = result.hypotheses[0]
    require(hypothesis.minimal
            and {candidate.source.split("#sha256=")[0]
                 for candidate in hypothesis.candidates}
            == {"pending-bc", "pending-cd"},
            "hypothesis omitted its minimal cited candidate set")
    facts = [asdict(fact) for fact in before_facts]
    for candidate in hypothesis.candidates:
        facts.append(asdict(FactEvidence(
            candidate.subject, candidate.relation, candidate.object,
            (candidate.source,), candidate.qualifiers)))
    for proof in hypothesis.result.proofs:
        check = verify_inference_proof(
            proof, facts, [asdict(rule) for rule in kb._inference_rules.values()],
            expected_conclusion=hypothesis.result.conclusion)
        require(check.valid, f"independent verifier rejected abduced proof: {check}")
    require(kb.facts() == before_facts
            and kb.infer_relation("Ada", "ancestor", "Dee").status == "unknown"
            and kb.retrieve_derived_case("Ada", "ancestor", "Dee") is None,
            "abduction committed a pending candidate or derived case")

    # Exercise the user-facing flow: a research query fills the pending set,
    # then the explicit command presents a hypothetical result without commit.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json",
            "rule-session.json", "candidate-session.json")}
        kb.save(paths["knowledge.json"])
        index.save(paths["index.json"])
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(paths["knowledge.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(paths["dialogue.json"]),
             "--rules", str(paths["rules.json"]),
             "--rule-session", str(paths["rule-session.json"]),
             "--candidate-session", str(paths["candidate-session.json"])],
            input="parent Cal\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(process.returncode == 0
                and paths["candidate-session.json"].exists(),
                f"terminal did not persist its pending review queue:\n"
                f"{process.stdout}\n{process.stderr}")
        resumed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(paths["knowledge.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(paths["dialogue.json"]),
             "--rules", str(paths["rules.json"]),
             "--rule-session", str(paths["rule-session.json"]),
             "--candidate-session", str(paths["candidate-session.json"])],
            input="/pending-candidates\n/abduce Ada|ancestor|Dee\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(resumed.returncode == 0
                and "Restored " in resumed.stdout
                and "Minimal cited hypotheses:" in resumed.stdout
                and "pending-bc#sha256=" in resumed.stdout
                and "pending-cd#sha256=" in resumed.stdout
                and "Nothing was accepted." in resumed.stdout,
                f"terminal abduction flow failed:\n{resumed.stdout}\n{resumed.stderr}")
        reloaded = CRMSKnowledgeBase.load(paths["knowledge.json"])
        require(len(reloaded.facts()) == len(before_facts)
                and reloaded.infer_relation("Ada", "ancestor", "Dee").status == "unknown",
                "terminal abduction changed the persisted knowledge store")
        changed_index = CRMSResearchIndex.load(paths["index.json"])
        changed_index.add_document(
            "pending-bc", "pending-bc", "This source was revised.",
            "https://research.test/pending-bc", replace=True)
        changed_index.save(paths["index.json"])
        stale_check = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(paths["knowledge.json"]),
             "--index", str(paths["index.json"]),
             "--dialogue-state", str(paths["dialogue.json"]),
             "--rules", str(paths["rules.json"]),
             "--rule-session", str(paths["rule-session.json"]),
             "--candidate-session", str(paths["candidate-session.json"])],
            input="/pending-candidates\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(stale_check.returncode == 0
                and "Restored " in stale_check.stdout
                and "invalidated candidate record(s)" in stale_check.stdout
                and "pending-bc#sha256=" not in stale_check.stdout
                and "pending-cd#sha256=" in stale_check.stdout,
                f"stale research evidence was not removed on reload:\n"
                f"{stale_check.stdout}\n{stale_check.stderr}")

    limited = kb.abduce_relation(
        "Ada", "ancestor", "Dee",
        candidates=[candidates["pending-direct"], candidates["pending-noise"]],
        research_index=index, max_hypothesis_size=2, max_subsets=1)
    require(limited.status == "incomplete" and not limited.complete
            and limited.hypotheses
            and not any(item.minimal for item in limited.hypotheses),
            "bounded search exhaustion claimed complete minimal hypotheses")

    invalid = replace(candidates["pending-bc"], sentence="unsupported sentence")
    try:
        kb.abduce_relation("Ada", "ancestor", "Cal", candidates=[invalid],
                           research_index=index)
    except ValueError as error:
        require("citation" in str(error),
                "stale candidate citation failed for an unexpected reason")
    else:
        raise SystemExit("abduction accepted a candidate detached from its citation")

    print("bounded research-candidate abduction diagnostic: PASS")
    print("minimal cited hypotheses, proof verification, bound abstention, and no write-back: PASS")


if __name__ == "__main__":
    main()
