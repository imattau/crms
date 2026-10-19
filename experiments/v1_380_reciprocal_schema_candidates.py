"""Report symmetry hypotheses without promoting open-world absences."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def source_for(index: CRMSResearchIndex, document_id: str,
               text: str, location: str) -> str:
    index.add_document(document_id, document_id, text, location)
    hit = next(hit for hit in index.search(text, limit=5)
               if hit.document_id == document_id)
    return index.citation(hit)


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()

    for number, (left, right, domain) in enumerate((
            ("Ada", "Bea", "one"),
            ("Cy", "Dee", "two"))):
        source = source_for(
            index, f"support:{number}",
            f"{left} is related to {right}. {right} is related to {left}.",
            f"https://origin-{domain}.example/relations")
        kb.add_fact(left, "related to", right, source)
        kb.add_fact(right, "related to", left, source)

    conflict_source = source_for(
        index, "conflict-on-supported-pair",
        "Bea is related to Ada. Ada is not related to Bea.",
        "https://origin-conflict.example/relations")
    kb.add_fact("Bea", "related to", "Ada", conflict_source)
    kb.add_negative_fact("Ada", "related to", "Bea", conflict_source)

    negative_source = source_for(
        index, "counterexample",
        "Eve is related to Fay. Fay is not related to Eve.",
        "https://origin-three.example/relations")
    kb.add_fact("Eve", "related to", "Fay", negative_source)
    kb.add_negative_fact("Fay", "related to", "Eve", negative_source)

    unknown_source = source_for(
        index, "unknown-reverse", "Gus is related to Hal.",
        "https://origin-four.example/relations")
    kb.add_fact("Gus", "related to", "Hal", unknown_source)

    before = tuple((fact.subject, fact.relation, fact.object)
                   for fact in kb.facts())
    discovery = kb.discover_relation_schemas(
        min_support=2, research_index=index)
    require(discovery.complete and len(discovery.candidates) == 1,
            f"expected one complete symmetry proposal: {discovery}")
    candidate = discovery.candidates[0]
    require(candidate.relation == "related to"
            and candidate.schema_type == "symmetric"
            and candidate.status == "contradicted"
            and len(candidate.positive_examples) == 2
            and len(candidate.negative_examples) == 2
            and candidate.unknown_reverse_pairs == 1
            and len(candidate.independent_sources) >= 2,
            f"candidate evidence/status was incorrect: {candidate}")
    after = tuple((fact.subject, fact.relation, fact.object)
                  for fact in kb.facts())
    require(after == before
            and not any(fact.relation == "has relation type"
                        for fact in kb.facts()),
            "report-only discovery installed or changed a schema declaration")
    rendered = kb.render_relation_schema_discovery(discovery)
    require("proposals only" in rendered
            and "unknown-reverse-pairs=1" in rendered
            and "counterexamples=2" in rendered
            and "Fay — related to → Eve" in rendered,
            f"discovery report hid open-world or negative evidence: {rendered}")

    limited = kb.discover_relation_schemas(
        min_support=2, max_expansions=1, research_index=index)
    require(not limited.complete
            and all(row.status == "incomplete" for row in limited.candidates),
            f"bounded schema discovery was reported complete: {limited}")

    with tempfile.TemporaryDirectory(prefix="crms-schema-candidates-") as folder:
        root = Path(folder)
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        restored_index = CRMSResearchIndex.load(index_path)
        round_trip = restored.discover_relation_schemas(
            min_support=2, research_index=restored_index)
        require(round_trip == discovery,
                "SQLite/JSON-independent schema candidate replay changed")
        chat = subprocess.run(
            [sys.executable,
             str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--rules", str(root / "rules.json"),
             "--dialogue-state", str(root / "dialogue.json")],
            input="/suggest-relation-schemas 2\n/inference-rules\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        require("Candidate [contradicted]: relation related to may be symmetric"
                in chat.stdout
                and "unknown-reverse-pairs=1" in chat.stdout
                and "No schema was stored." in chat.stdout
                and "related to — has relation type → symmetric"
                not in chat.stdout,
                f"interactive report proposed or stored a schema unsafely: "
                f"{chat.stdout}")

    print("reciprocal positive evidence produces a report-only schema candidate: PASS")
    print("explicit negative reverse evidence is shown; missing reverse stays unknown: PASS")
    print("candidate retains independent origins and citations across persistence: PASS")
    print("bounded search reports incompleteness and chat stores no declaration: PASS")


if __name__ == "__main__":
    main()
