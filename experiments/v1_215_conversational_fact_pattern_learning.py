"""Check source-backed conversational fact-pattern acquisition in the CLI."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        index = CRMSResearchIndex()
        sentences = (
            ("ada", "Ada Lovelace developed the Analytical Engine."),
            ("grace", "Grace Hopper developed the Compiler."),
            ("mary", "Mary Jackson developed the flight equations."),
            ("katherine", "Katherine Johnson developed the trajectory table."),
        )
        for document_id, sentence in sentences:
            index.add_document(document_id, document_id, sentence,
                               f"research/{document_id}.txt")
        index.save(index_path)
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--knowledge", str(knowledge_path), "--index", str(index_path),
                   "--dialogue-state", str(root / "dialogue.json")]

        invalid = (
            'Teach a sourced fact pattern from examples: '
            '"Ada Lovelace developed the Analytical Engine." => '
            '"Ada Lovelace" | "designed" | "the Analytical Engine" '
            '["Ada Lovelace" | "developed" | "the Analytical Engine"]; '
            '"An unindexed person designed an unknown device." => '
            '"An unindexed person" | "designed" | "an unknown device"')
        mixed_relations = (
            'Teach a sourced fact pattern from examples: '
            '"Ada Lovelace developed the Analytical Engine." => '
            '"Ada Lovelace" | "designed" | "the Analytical Engine" '
            '["Ada Lovelace" | "developed" | "the Analytical Engine"]; '
            '"Grace Hopper developed the Compiler." => '
            '"Grace Hopper" | "constructed" | "the Compiler" '
            '["Grace Hopper" | "developed" | "the Compiler"]')
        teach = (
            'Teach a sourced fact pattern from examples: '
            '"Ada Lovelace developed the Analytical Engine." => '
            '"Ada Lovelace" | "designed" | "the Analytical Engine" '
            '["Ada Lovelace" | "developed" | "the Analytical Engine"]; '
            '"Grace Hopper developed the Compiler." => '
            '"Grace Hopper" | "designed" | "the Compiler" '
            '["Grace Hopper" | "developed" | "the Compiler"]; '
            '"Mary Jackson developed the flight equations." => '
            '"Mary Jackson" | "designed" | "the flight equations" '
            '["Mary Jackson" | "developed" | "the flight equations"]')
        teach_question = (
            'Teach a question frame from examples: '
            '"Who designed the Analytical Engine?" => "Ada Lovelace"; '
            '"Who designed the Compiler?" => "Grace Hopper"; '
            '"Who designed the flight equations?" => "Mary Jackson"')
        output = subprocess.run(
            command,
            input="\n".join((invalid, mixed_relations, "/facts", teach,
                              "/facts", teach_question,
                              "Who developed the Analytical Engine?",
                              "Who developed the Compiler?",
                              "Who developed the trajectory table?", "/accept 1",
                              "/write-about Katherine Johnson", "/quit")) + "\n",
            text=True, capture_output=True, check=True, timeout=20).stdout
        if "each example must match one unique indexed source sentence exactly" not in output:
            raise SystemExit(f"unindexed example was not rejected:\n{output}")
        if "same canonical relation and polarity; no change was saved" not in output:
            raise SystemExit(f"mixed-relation batch was not rejected:\n{output}")
        if "No facts are stored yet." not in output:
            raise SystemExit(f"failed batch changed knowledge before commit:\n{output}")
        if "Sourced fact pattern licensed from 3 examples." not in output:
            raise SystemExit(f"valid examples did not license a pattern:\n{output}")
        if ("Question frame licensed from 3 fact-backed examples" not in output
                or "Answer: Ada Lovelace." not in output
                or "Answer: Grace Hopper." not in output
                or "Katherine Johnson — designed → the trajectory table" not in output
                or "Review candidate 1 (positive)" not in output
                or "Accepted positive fact: Katherine Johnson — designed → the trajectory table." not in output
                or "Katherine Johnson developed the trajectory table." not in output):
            raise SystemExit(f"learned predicate wording did not transfer to QA:\n{output}")

        stored = CRMSKnowledgeBase.load(knowledge_path)
        if len(stored.facts()) != 4:
            raise SystemExit(f"expected three taught facts plus one accepted fact, got {stored.facts()}")
        for document_id, sentence in sentences[:3]:
            hit = index.search(sentence, limit=1)[0]
            citation = index.citation(hit)
            if citation not in output or citation not in {
                    source for fact in stored.facts() for source in fact.sources}:
                raise SystemExit(f"source provenance was not retained for {document_id}")

        holdout_id, holdout_sentence = sentences[3]
        holdout_hit = index.search(holdout_sentence, limit=1)[0]
        holdout_citation = index.citation(holdout_hit)
        proposals = stored.propose_facts(holdout_sentence, source=holdout_citation)
        matching = [item for item in proposals if (
            item.subject, item.relation, item.object
        ) == ("Katherine Johnson", "designed", "the trajectory table")]
        if len(matching) != 1:
            raise SystemExit(f"licensed frame failed on held-out sentence: {proposals}")
        if len(stored.facts()) != 4:
            raise SystemExit("held-out extraction changed the post-review fact store")

        # Retracting the three teaching sources must remove the lexical frame;
        # the separately accepted holdout fact remains, but cannot keep the
        # source-learned predicate or writing template alive by itself.
        for document_id, sentence, subject, relation, obj in (
                ("ada", sentences[0][1], "Ada Lovelace", "designed",
                 "the Analytical Engine"),
                ("grace", sentences[1][1], "Grace Hopper", "designed",
                 "the Compiler"),
                ("mary", sentences[2][1], "Mary Jackson", "designed",
                 "the flight equations")):
            hit = index.search(sentence, limit=1)[0]
            citation = index.citation(hit)
            if not stored.remove_fact(subject, relation, obj, citation):
                raise SystemExit(f"failed to retract teaching source {document_id}")
        if stored.ask("Who developed the trajectory table?").status != "unknown":
            raise SystemExit("retracted predicate alignment remained active in QA")
        if stored.propose_facts(holdout_sentence, source=holdout_citation):
            raise SystemExit("retracted training frames still propose held-out facts")
        if stored.write_about("Katherine Johnson").status != "no_licensed_frame":
            raise SystemExit("retracted training frames still licensed generated writing")
        if len(stored.facts()) != 1:
            raise SystemExit("retracting teaching sources removed the independently accepted fact")

        # The optional span labels let the sentence's wording differ from the
        # canonical fact labels without hiding that mapping from the teacher.
        aligned_index = CRMSResearchIndex()
        aligned_examples = (
            ("a", "A. Lovelace developed the engine.", "Ada Lovelace",
             "Analytical Engine", "A. Lovelace", "the engine"),
            ("g", "G. Hopper developed the compiler.", "Grace Hopper",
             "Compiler", "G. Hopper", "the compiler"),
            ("k", "K. Johnson developed the trajectory table.", "Katherine Johnson",
             "trajectory table", "K. Johnson", "the trajectory table"),
        )
        for document_id, sentence, _subject, _obj, _surface_subject, _surface_obj in aligned_examples:
            aligned_index.add_document(document_id, document_id, sentence)
        aligned_index_path = root / "aligned-index.json"
        aligned_index.save(aligned_index_path)
        aligned_knowledge_path = root / "aligned-knowledge.json"
        aligned_command = [sys.executable, str(PROJECT / "crms_chat.py"),
                           "--knowledge", str(aligned_knowledge_path),
                           "--index", str(aligned_index_path),
                           "--dialogue-state", str(root / "aligned-dialogue.json")]

        def aligned_pair(item):
            _document_id, sentence, subject, obj, subject_surface, object_surface = item
            return (f'"{sentence}" => "{subject}" | "designed" | "{obj}" '
                    f'["{subject_surface}" | "developed" | "{object_surface}"]')

        aligned_teach = ("Teach a sourced fact pattern from examples: "
                         + "; ".join(aligned_pair(item)
                                     for item in aligned_examples[:2]))
        aligned_output = subprocess.run(
            aligned_command,
            input=aligned_teach + "\n/quit\n", text=True, capture_output=True,
            check=True, timeout=20).stdout
        if "Sourced fact pattern licensed from 2 examples." not in aligned_output:
            raise SystemExit(f"explicit span labels did not license frame:\n{aligned_output}")
        aligned_stored = CRMSKnowledgeBase.load(aligned_knowledge_path)
        held_out = aligned_examples[2]
        held_out_hit = aligned_index.search(held_out[1], limit=1)[0]
        aligned_proposals = aligned_stored.propose_facts(
            held_out[1], source=aligned_index.citation(held_out_hit))
        aligned_match = [item for item in aligned_proposals if (
            item.subject, item.relation, item.object
        ) == (held_out[4], "designed", held_out[5])]
        if len(aligned_match) != 1:
            raise SystemExit(f"aligned surface phrases did not transfer: {aligned_proposals}")

    print("conversational sourced fact-pattern diagnostic: PASS")
    print("three-example licensing, explicit surface alignment, exact-source "
          "requirement, transactional rejection, citation retention, held-out "
          "QA and research, explicit fact acceptance, sourced writing transfer, "
          "source retraction and lexical invalidation: PASS")


if __name__ == "__main__":
    main()
