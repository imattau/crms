"""Check source-separated corpus frame discovery and explicit acceptance."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex, CRMSResearchIndex


def seed(index) -> None:
    for document_id, sentence in (
            ("created-python", "Guido van Rossum created Python."),
            ("created-linux", "Linus Torvalds created Linux."),
            ("created-ruby", "Yukihiro Matsumoto created Ruby."),
            ("noise", "The C language was created at Bell Labs.")):
        index.add_document(document_id, "Computing", sentence,
                           f"{document_id}.txt")


def check_index(index) -> None:
    seed(index)
    kb = CRMSKnowledgeBase()
    proposals = kb.propose_corpus_relation_frames(index)
    proposal = next((item for item in proposals
                     if item["relation"] == "created"), None)
    if proposal is None:
        raise SystemExit(f"repeated zero-frame relation was not found: {proposals}")
    if (proposal["distinct_subjects"] < 2
            or proposal["distinct_objects"] < 2
            or proposal["independent_documents"] < 2
            or not proposal["review_required"]):
        raise SystemExit(f"proposal lacks varied independent evidence: {proposal}")
    if kb.facts() or kb.ask("Who created Python?").status == "answered":
        raise SystemExit("report-only corpus discovery mutated usable knowledge")
    if any(row["document_id"] == "noise" for row in proposal["support"]):
        raise SystemExit("agentless passive was included as an agent relation")

    accepted = kb.accept_corpus_relation_frame(proposal["proposal_id"], index)
    if len(accepted["support"]) < 2 or len(kb.facts()) < 2:
        raise SystemExit("explicit frame acceptance did not store cited examples")
    for question, expected in (
            ("Who created Python?", "Guido van Rossum"),
            ("Who created Linux?", "Linus Torvalds"),
            ("Who created Ruby?", "Yukihiro Matsumoto")):
        answer = kb.ask(question)
        if answer.status != "answered" or answer.answer != expected:
            raise SystemExit(f"accepted frame did not answer {question}: {answer}")
        evidence_sources = {source for item in answer.evidence or []
                            for source in item.get("sources", [])}
        if not evidence_sources:
            raise SystemExit(f"answer lost source provenance: {answer}")


def check_morphology_aware_discovery() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()

    def teach(relation: str, predicate: str, prefix: str) -> None:
        for number, (subject, obj) in enumerate(
                (("Ada", "Engine"), ("Bea", "Compiler")), start=1):
            sentence = f"{subject} {predicate} {obj}."
            document_id = f"{prefix}-{number}"
            index.add_document(document_id, "Grounded morphology example",
                               sentence, f"{document_id}.txt")
            hit = next(item for item in index.search(sentence, limit=10)
                       if item.document_id == document_id)
            kb.add_fact_from_hit(subject, relation, obj, index, hit)
            kb.teach_fact_pattern_from_hit(
                sentence, subject=subject, relation=relation, obj=obj,
                predicate_phrase=predicate, research_index=index, hit=hit)
            if relation == "create":
                kb.teach_question(
                    f"Who created {obj}?", relation="create",
                    answer_field="subject", bound_entity=obj, answer=subject)

    # Independent relation families license the -ed and final-e + -es
    # spelling classes; the base infinitive also needs source-context support.
    teach("create", "created", "morph-create")
    teach("manage", "managed", "morph-manage")
    teach("bake", "bakes", "morph-bake")
    teach("make", "makes", "morph-make")
    index.add_document("base-create-1", "Infinitive context",
                       "Engineers can create useful tools.", "base-create-1.txt")
    index.add_document("base-create-2", "Infinitive context",
                       "Researchers need to create reliable models.",
                       "base-create-2.txt")
    index.add_document("target-created", "Inflected source",
                       "Ava created Quill.", "target-created.txt")
    index.add_document("target-creates", "Inflected source",
                       "Bea creates Loom.", "target-creates.txt")
    index.add_document("target-passive", "Passive source",
                       "Archive was created by Cal.", "target-passive.txt")

    support_lookups: dict[str, int] = {}
    original_support_lookup = kb._corpus_bare_predicate_support

    def counted_support_lookup(research_index, base, *, limit=40):
        support_lookups[base] = support_lookups.get(base, 0) + 1
        return original_support_lookup(research_index, base, limit=limit)

    kb._corpus_bare_predicate_support = counted_support_lookup
    proposals = kb.propose_corpus_relation_frames(index)
    if any(count > 1 for count in support_lookups.values()):
        raise SystemExit("corpus scan repeated a cached base-form evidence search")
    proposal = next((item for item in proposals
                     if item["relation"] == "create"
                     and {row["document_id"] for row in item["support"]}
                     >= {"target-created", "target-creates", "target-passive"}), None)
    if proposal is None:
        raise SystemExit(
            f"licensed inflections were not grouped under the relation: {proposals}")
    if not all(row.get("morphology_support") for row in proposal["support"]
               if row["document_id"] in {
                   "target-created", "target-creates", "target-passive"}):
        raise SystemExit("inflection merge omitted its independent morphology evidence")
    passive_row = next(row for row in proposal["support"]
                       if row["document_id"] == "target-passive")
    if ((passive_row["subject"], passive_row["relation"],
         passive_row["object"]) != ("Cal", "create", "Archive")):
        raise SystemExit(f"passive by-phrase roles were not normalized: {passive_row}")
    if not any(item.get("method") == "passive by-phrase role normalization"
               for item in kb._discover_surface_relation_candidates(
                   "Archive was created by Cal.", source="test",
                   research_index=index)[0].language_evidence):
        raise SystemExit("passive parse did not retain its role-analysis evidence")
    with tempfile.TemporaryDirectory(prefix="crms-morph-frame-cli-") as folder:
        root = Path(folder)
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        cli = subprocess.run(
            command, input="/suggest-corpus-frames\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        if ("Morphology alignment: created → create" not in cli.stdout
                or "rule sources:" not in cli.stdout
                or "base-form sources:" not in cli.stdout):
            raise SystemExit(
                f"chat review hid inflection evidence: {cli.stdout}")
    accepted = kb.accept_corpus_relation_frame(proposal["proposal_id"], index)
    if (not accepted or kb._facts.get(kb._fact_key("Ava", "create", "Quill")) is None
            or kb._facts.get(kb._fact_key("Bea", "create", "Loom")) is None
            or kb._facts.get(kb._fact_key("Cal", "create", "Archive")) is None):
        raise SystemExit("reviewed inflected proposals did not store canonical facts")
    for question, expected in (("Who created Quill?", "Ava"),
                               ("Who creates Loom?", "Bea"),
                               ("What was created by Cal?", "Archive")):
        answer = kb.ask(question)
        if answer.status != "answered" or answer.answer != expected:
            raise SystemExit(
                f"licensed inflection did not transfer through QA: {question}: {answer}")


def check_lowercase_objects() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    for document_id, sentence in (
            ("curie-radium", "Marie Curie discovered radium."),
            ("rutherford-polonium", "Ernest Rutherford discovered polonium.")):
        index.add_document(document_id, "Science history", sentence,
                           f"{document_id}.txt")
    proposal = next((item for item in kb.propose_corpus_relation_frames(index)
                     if item["relation"] == "discovered"), None)
    if proposal is None or {row["object"] for row in proposal["support"]} != {
            "radium", "polonium"}:
        raise SystemExit(
            f"lowercase objects did not form a reviewed relation frame: {proposal}")
    kb.accept_corpus_relation_frame(proposal["proposal_id"], index)
    for question, expected in (("Who discovered radium?", "Marie Curie"),
                               ("Who discovered polonium?", "Ernest Rutherford")):
        answer = kb.ask(question)
        if answer.status != "answered" or answer.answer != expected:
            raise SystemExit(
                f"accepted lowercase-object fact did not answer {question}: {answer}")


def check_typed_question_requires_type_evidence() -> None:
    index = CRMSResearchIndex()
    for document_id, sentence in (
            ("seine-flow", "The Seine flows through Paris."),
            ("thames-flow", "The Thames flows through London."),
            ("seine-type", "The Seine is a river."),
            ("thames-type", "The Thames is a river.")):
        index.add_document(document_id, "Geography", sentence,
                           f"{document_id}.txt")
    kb = CRMSKnowledgeBase()
    flow = next((proposal for proposal in
                 kb.propose_corpus_relation_frames(index)
                 if proposal["relation"] == "flows through"), None)
    if flow is None:
        raise SystemExit("river-flow sources did not yield a reviewed frame")
    kb.accept_corpus_relation_frame(flow["proposal_id"], index)
    present_yes = kb.ask("Does the Seine flow through Paris?")
    present_unknown = kb.ask("Does the Seine flow through Rome?")
    if (present_yes.status != "answered" or present_yes.answer != "Yes"
            or present_unknown.status != "unknown"):
        raise SystemExit(
            "source-licensed does-support failed or inferred absence: "
            f"{present_yes}; {present_unknown}")
    object_wh = kb.ask("What does the Seine flow through?")
    if object_wh.status != "answered" or object_wh.answer != "Paris":
        raise SystemExit(
            f"inverse do-support question did not use its reviewed frame: "
            f"{object_wh}")
    unsupported_type = kb.ask("Which river flows through Paris?")
    if unsupported_type.status != "unknown":
        raise SystemExit(
            "relation evidence alone was treated as proof of river type: "
            f"{unsupported_type}")
    untyped = kb.ask("What flows through Paris?")
    if untyped.status != "answered" or untyped.answer != "The Seine":
        raise SystemExit(
            f"untyped subject question did not use its source frame: {untyped}")
    wrong_type = kb.ask("Which city flows through Paris?")
    if wrong_type.status != "unknown":
        raise SystemExit(
            f"typed query ignored its unsupported requested class: {wrong_type}")
    what_typed = kb.ask("What river flows through Paris?")
    if what_typed.status != "unknown":
        raise SystemExit(
            f"what + class query bypassed the type evidence gate: {what_typed}")

    for document_id, sentence in (
            ("seine-type", "The Seine is a river."),
            ("thames-type", "The Thames is a river.")):
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        proposals = kb._discover_surface_relation_candidates(
            sentence, source=index.citation(hit))
        if (len(proposals) != 1 or proposals[0].relation != "is-a"
                or proposals[0].object != "river"):
            raise SystemExit(
                f"source type claim was not reviewable: {proposals}")
        kb.accept_fact_candidate(proposals[0], index)
    answer = kb.ask("Which river flows through Paris?")
    if (answer.status != "answered" or answer.answer != "The Seine"
            or {item["relation"] for item in answer.evidence or []}
            != {"flows through", "is-a"}):
        raise SystemExit(
            f"typed answer lacks relation and class evidence: {answer}")
    with tempfile.TemporaryDirectory(prefix="crms-typed-chat-") as folder:
        root = Path(folder)
        memory_path = root / "knowledge.json"
        index_path = root / "research.json"
        index.save(index_path)
        kb.save(memory_path)
        chat = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(memory_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "rule-session.json")],
            input=("Which river flows through Paris?\n"
                   "What flows through Paris?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30)
        if (chat.returncode != 0
                or chat.stdout.count("The Seine flows through Paris.") != 2
                or "Source: Geography; accepted fact" not in chat.stdout
                or "CRMS state saved. Goodbye." not in chat.stdout):
            raise SystemExit(
                f"typed relation query failed through terminal chat:\n"
                f"{chat.stdout}\n{chat.stderr}")
    with tempfile.TemporaryDirectory(prefix="crms-typed-question-") as folder:
        memory_path = Path(folder) / "knowledge.json"
        fact_path = Path(folder) / "facts.sqlite"
        kb.save(memory_path)
        indexed_kb = CRMSKnowledgeBase.load(memory_path, fact_db=fact_path)
        try:
            indexed_answer = indexed_kb.ask(
                "Which river flows through Paris?")
            if (indexed_answer.status != "answered"
                    or indexed_answer.answer != "The Seine"):
                raise SystemExit(
                    "SQLite relation/type indexes failed typed QA: "
                    f"{indexed_answer}")
        finally:
            indexed_kb.close()

    contradiction = "The Seine is not a river."
    index.add_document("seine-not-river", "Contradictory source",
                       contradiction, "seine-not-river.txt")
    hit = next(item for item in index.search(contradiction, limit=10)
               if item.document_id == "seine-not-river")
    negative_type = kb._discover_surface_relation_candidates(
        contradiction, source=index.citation(hit))
    if len(negative_type) != 1 or negative_type[0].polarity:
        raise SystemExit("negative type evidence was not reviewable")
    kb.accept_fact_candidate(negative_type[0], index)
    conflicted = kb.ask("Which river flows through Paris?")
    if conflicted.status != "ambiguous":
        raise SystemExit(
            f"contradictory type evidence did not block typed answer: {conflicted}")


def check_repeated_passive_negative_discovery() -> None:
    index = CRMSResearchIndex()
    for document_id, sentence in (
            ("negative-python",
             "Python was not created by Guido van Rossum."),
            ("negative-unix",
             "Unix was not created by Ken Thompson.")):
        index.add_document(document_id, "Negative history claims", sentence,
                           f"{document_id}.txt")
    kb = CRMSKnowledgeBase()
    proposals = kb.propose_corpus_relation_frames(index)
    matching = [proposal for proposal in proposals
                if proposal["relation"] == "created"
                and proposal["polarity"] is False]
    if len(matching) != 1:
        raise SystemExit(
            f"repeated passive negatives did not form one review proposal: "
            f"{proposals}")
    proposal = matching[0]
    if (proposal["distinct_subjects"] != 2
            or proposal["distinct_objects"] != 2
            or proposal["independent_documents"] != 2
            or kb.facts() or kb.negative_facts()):
        raise SystemExit(
            "negative corpus discovery lacked source diversity or wrote early")
    accepted = kb.accept_corpus_relation_frame(
        proposal["proposal_id"], index)
    if (len(accepted["support"]) != 2 or kb.facts()
            or len(kb.negative_facts()) != 2
            or {(fact.subject, fact.relation, fact.object)
                for fact in kb.negative_facts()}
            != {("Guido van Rossum", "created", "Python"),
                ("Ken Thompson", "created", "Unix")}):
        raise SystemExit(
            "reviewed passive negative frame lost polarity or participant roles")
    kb.add_fact("Guido van Rossum", "created", "Python",
                "independent-positive-source")
    conflict = kb.infer_relation("Guido van Rossum", "created", "Python")
    if conflict.status != "ambiguous":
        raise SystemExit(
            "positive evidence overrode an accepted passive negative: "
            f"{conflict}")


def check_source_types_feed_typed_rules() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    for document_id, sentence in (
            ("engine-type", "Engine is a machine."),
            ("rotor-type", "Rotor is a component."),
            ("engine-not-type", "Engine is not a machine."),
            ("rotor-not-type", "Rotor is not a component.")):
        index.add_document(document_id, "Engineering types", sentence,
                           f"{document_id}.txt")
    proposal = next((item for item in kb.propose_corpus_relation_frames(index)
                     if item["relation"] == "is-a" and item["polarity"]), None)
    if proposal is None:
        raise SystemExit("source text did not propose an is-a frame")
    kb.accept_corpus_relation_frame(proposal["proposal_id"], index)
    kb.add_fact("Ada", "owns", "Engine", "chain:owns")
    kb.add_fact("Engine", "has-part", "Rotor", "chain:part")
    kb.add_fact("Rotor", "located-in", "Lab", "chain:location")
    kb.add_inference_rule(
        "owned-machine-part-location", "owns", "has-part", "can-access",
        third_relation="located-in", middle_kind="machine",
        second_middle_kind="component")
    result = kb.infer_relation("Ada", "can-access", "Lab")
    if (result.status != "answered" or not result.proofs
            or not any(leaf.get("relation") == "is-a"
                       and leaf.get("object") == "machine"
                       for proof in result.proofs
                       for leaf in kb._inference_fact_leaves(proof))
            or not any(leaf.get("relation") == "is-a"
                       and leaf.get("object") == "component"
                       for proof in result.proofs
                       for leaf in kb._inference_fact_leaves(proof))):
        raise SystemExit(
            f"source-learned type facts did not ground typed inference: {result}")
    negative_proposal = next((item for item in
                              kb.propose_corpus_relation_frames(index)
                              if item["relation"] == "is-a"
                              and not item["polarity"]), None)
    if negative_proposal is None:
        raise SystemExit("explicit negative type sources were not proposed")
    kb.accept_corpus_relation_frame(negative_proposal["proposal_id"], index)
    contradiction = kb.infer_relation("Engine", "is-a", "machine")
    if contradiction.status != "ambiguous":
        raise SystemExit(
            f"accepted negative type evidence did not conflict with its positive: {contradiction}")


def check_example_and_code_context_gates() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "quoted-example", "Parser guide",
        'The parser accepts examples such as “Mira designed Atlas.”',
        "guide.md")
    index.add_document(
        "structured-output", "Parser output",
        '=> "Ravi" | "created" | "Beacon Engine"', "output.md")
    index.add_document(
        "code-fixture", "Python fixture",
        'assert result == ("Nia", "designed", "Compiler")', "fixture.py")
    direct = "Ada Lovelace designed the Analytical Engine."
    index.add_document("direct-claim", "Biography", direct, "bio.txt")

    kb = CRMSKnowledgeBase()
    inspected: list[str] = []

    def capture(sentence: str, **_kwargs):
        inspected.append(sentence)
        return []

    kb._discover_surface_relation_candidates = capture
    kb.propose_corpus_relation_frames(index)
    if direct not in inspected:
        raise SystemExit("direct natural-language source was skipped")
    if any(sentence != direct for sentence in inspected):
        raise SystemExit(
            "code or illustrative source entered relation induction: "
            f"{inspected}")


def main() -> None:
    check_example_and_code_context_gates()
    check_lowercase_objects()
    check_typed_question_requires_type_evidence()
    check_repeated_passive_negative_discovery()
    check_source_types_feed_typed_rules()
    check_morphology_aware_discovery()
    memory_index = CRMSResearchIndex()
    check_index(memory_index)
    with tempfile.TemporaryDirectory(prefix="crms-corpus-frame-") as folder:
        path = Path(folder) / "index.sqlite"
        sqlite_index = CRMSSQLiteResearchIndex(path)
        try:
            check_index(sqlite_index)
        finally:
            sqlite_index.close()

    # Later sources must remain discoverable after the bounded first page.
    paged_index = CRMSResearchIndex()
    for number in range(1000):
        document_id = f"a-noise-{number:04}"
        paged_index.add_document(
            document_id, "Unrelated catalog entry",
            f"Unrelated catalog note {number}.", f"{document_id}.txt")
    paged_index.add_document("z-created-a", "Later source",
                             "Ada created Quill.", "z-created-a.txt")
    paged_index.add_document("z-created-b", "Later source",
                             "Bea created Loom.", "z-created-b.txt")
    paged_kb = CRMSKnowledgeBase()
    first_page = paged_kb.propose_corpus_relation_frames(paged_index)
    later_page = paged_kb.propose_corpus_relation_frames(
        paged_index, document_offset=1000)
    if any(item["relation"] == "created" for item in first_page):
        raise SystemExit("first corpus page unexpectedly saw later source records")
    later_proposal = next((item for item in later_page
                           if item["relation"] == "created"), None)
    if later_proposal is None:
        raise SystemExit("corpus frame discovery did not reach the later document page")
    accepted_page = paged_kb.accept_corpus_relation_frame(
        later_proposal["proposal_id"], paged_index, document_offset=1000)
    if not accepted_page or paged_kb.ask("Who created Quill?").answer != "Ada":
        raise SystemExit("paged corpus proposal did not revalidate and transfer")

    with tempfile.TemporaryDirectory(prefix="crms-paged-corpus-cli-") as folder:
        root = Path(folder)
        cli_index = CRMSResearchIndex()
        for number in range(1000):
            document_id = f"a-noise-{number:04}"
            cli_index.add_document(
                document_id, "Unrelated catalog entry",
                f"Unrelated catalog note {number}.", f"{document_id}.txt")
        cli_index.add_document("z-created-a", "Later source",
                               "Ada created Quill.", "z-created-a.txt")
        cli_index.add_document("z-created-b", "Later source",
                               "Bea created Loom.", "z-created-b.txt")
        cli_kb = CRMSKnowledgeBase()
        cli_proposal = next(item for item in
                            cli_kb.propose_corpus_relation_frames(
                                cli_index, document_offset=1000)
                            if item["relation"] == "created")
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        cli_kb.save(knowledge_path)
        cli_index.save(index_path)
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        cli = subprocess.run(
            command,
            input=("/suggest-corpus-frames 1000\n"
                   f"/accept-corpus-frame {cli_proposal['proposal_id']}|1000\n"
                   "Who created Quill?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("Accepted 'created'" not in cli.stdout
                or "Ada" not in cli.stdout):
            raise SystemExit(f"paged corpus CLI flow failed: {cli.stdout}")

    stale_index = CRMSResearchIndex()
    stale_index.add_document("stale-a", "Computing",
                             "Mira created the Atlas Engine.", "stale-a.txt")
    stale_index.add_document("stale-b", "Computing",
                             "Ravi created the Beacon Engine.", "stale-b.txt")
    stale_kb = CRMSKnowledgeBase()
    stale_proposal = next(item for item in
                          stale_kb.propose_corpus_relation_frames(stale_index)
                          if item["relation"] == "created")
    stale_index.add_document("stale-a", "Computing",
                             "Mira maintains the Atlas Engine.", "stale-a.txt",
                             replace=True)
    try:
        stale_kb.accept_corpus_relation_frame(
            stale_proposal["proposal_id"], stale_index)
    except ValueError:
        pass
    else:
        raise SystemExit("stale corpus-frame proposal was accepted")
    if stale_kb.facts():
        raise SystemExit("failed stale acceptance partially mutated knowledge")

    with tempfile.TemporaryDirectory(prefix="crms-corpus-frame-cli-") as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        seed(index)
        kb = CRMSKnowledgeBase()
        proposal = next(item for item in kb.propose_corpus_relation_frames(index)
                        if item["relation"] == "created")
        knowledge_path, index_path = root / "knowledge.json", root / "index.json"
        kb.save(knowledge_path)
        index.save(index_path)
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        cli = subprocess.run(
            command,
            input=("/suggest-corpus-frames\n"
                   f"/accept-corpus-frame {proposal['proposal_id']}\n"
                   "Who created Python?\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("Report only: no facts or frames changed" not in cli.stdout
                or "Accepted 'created'" not in cli.stdout
                or "Guido van Rossum" not in cli.stdout):
            raise SystemExit(f"interactive corpus-frame flow failed: {cli.stdout}")

    print("zero-frame corpus learning diagnostic: PASS")
    print("source-separated discovery, review gate, transactional acceptance, "
          "lowercase objects, inflection/passive grouping, paging, provenance, "
          "passive negative relation grouping, source-learned type "
          "guards/conflicts, typed question answer gating, "
          "terminal typed/untyped QA, in-memory/SQLite parity, "
          "CLI path: PASS")


if __name__ == "__main__":
    main()
