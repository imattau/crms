"""Check zero-frame surface relation suggestions remain source-review only."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    # Independent source-grounded past-tense patterns license a regular
    # predicate spelling rule used to map reviewed surface predicates to
    # canonical relation forms.
    morphology_examples = [
        ("bake", "baked", [
            ("Ada", "the Rotor", "morph-bake-a"),
            ("Bea", "the Engine", "morph-bake-b")]),
        ("admire", "admired", [
            ("Claude", "the Mural", "morph-admire-a"),
            ("Mary", "the Portrait", "morph-admire-b")]),
    ]
    for relation, predicate, rows in morphology_examples:
        for subject, obj, doc_id in rows:
            sentence = f"{subject} {predicate} {obj}."
            index.add_document(doc_id, doc_id, sentence, f"{doc_id}.txt")
            hit = next(item for item in index.search(sentence, limit=10)
                       if item.document_id == doc_id)
            kb.add_fact_from_hit(subject, relation, obj, index, hit)
            kb.teach_fact_pattern_from_hit(
                sentence, subject=subject, relation=relation, obj=obj,
                predicate_phrase=predicate, research_index=index, hit=hit)
    for doc_id, sentence in (
            ("bare-create-a", "The engineers can create reliable tools."),
            ("bare-create-b", "Researchers need to create useful models.")):
        index.add_document(doc_id, doc_id, sentence, f"{doc_id}.txt")
    baseline_facts = len(kb.facts())
    examples = [
        ("python", "Guido van Rossum created Python.",
         "Guido van Rossum", "Python"),
        ("linux", "Linus Torvalds created Linux.",
         "Linus Torvalds", "Linux"),
    ]
    accepted = []
    for doc_id, sentence, expected_subject, expected_object in examples:
        index.add_document(doc_id, "Computing history", sentence,
                           f"{doc_id}.txt")
        query = f"Who created {expected_object}?"
        result = kb.research(query, index)
        if result.status != "needs_review" or len(result.candidates or []) != 1:
            raise SystemExit(
                f"unlearned relation did not yield one review proposal: {result}")
        candidate = result.candidates[0]
        if ((candidate.subject, candidate.relation, candidate.object)
                != (expected_subject, "create", expected_object)):
            raise SystemExit(f"surface roles were not extracted as expected: {candidate}")
        if not any(item.get("kind") == "surface_relation_discovery"
                   for item in candidate.language_evidence):
            raise SystemExit("candidate omitted its heuristic discovery provenance")
        if len(kb.facts()) != baseline_facts + len(accepted):
            raise SystemExit("discovery wrote an unreviewed fact")
        rendered = kb.render_research(result)
        if ("exploratory relation proposals" not in rendered
                or candidate.source not in rendered):
            raise SystemExit("review output hid the heuristic or its citation")
        kb.accept_fact_candidate(candidate, index)
        accepted.append(candidate)
        if len(accepted) == 1:
            premature = kb.ask("Who created Linux?")
            if premature.status == "answered":
                raise SystemExit(
                    "one accepted example prematurely generalized to a new object: "
                    f"{premature}")
    if len(kb.facts()) != baseline_facts + 2:
        raise SystemExit("explicitly accepted proposals were not stored")
    learned_answer = kb.ask("Who created Python?")
    if (learned_answer.status != "answered"
            or learned_answer.answer != "Guido van Rossum"):
        raise SystemExit(
            f"reviewed claims did not induce a reusable question frame: {learned_answer}")
    if not any(accepted[0].source in item.get("sources", [])
               for item in learned_answer.evidence or []):
        raise SystemExit("induced question answer omitted source provenance")
    inverse_answer = kb.ask("What was created by Guido van Rossum?")
    if (inverse_answer.status != "answered"
            or inverse_answer.answer != "Python"):
        raise SystemExit(
            f"reviewed claims did not induce inverse role frame: {inverse_answer}")
    active_inverse = kb.ask("What did Guido van Rossum create?")
    if (active_inverse.status != "answered"
            or active_inverse.answer != "Python"):
        raise SystemExit(
            f"licensed verb morphology did not induce active inverse: {active_inverse}")

    # A teacher may align a genuinely different surface predicate with the
    # same canonical relation. Require two independently sourced examples,
    # then check transfer to an existing fact that used the original wording.
    # This exercises learned paraphrase handling without a synonym dictionary.
    alias_examples = (
        ("made-a", "Alice made Widget.", "Alice", "Widget"),
        ("made-b", "Grace made Gadget.", "Grace", "Gadget"),
    )
    for doc_id, sentence, subject, obj in alias_examples:
        index.add_document(doc_id, "Reviewed wording", sentence,
                           f"{doc_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == doc_id)
        kb.add_fact_from_hit(subject, "create", obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="create", obj=obj,
            predicate_phrase="made", research_index=index, hit=hit)
    made_answer = kb.ask("Who made Python?")
    if (made_answer.status != "answered"
            or made_answer.answer != "Guido van Rossum"):
        raise SystemExit(
            f"reviewed alternate predicate did not transfer to a known fact: "
            f"{made_answer}")
    made_research = kb.research("Who made Python?", index)
    if (made_research.status != "answered"
            or made_research.response is None
            or made_research.response.answer != "Guido van Rossum"
            or not any("Guido van Rossum created Python." in
                       row.get("text", "")
                       for row in made_research.source_sentences or [])):
        raise SystemExit(
            "reviewed alternate wording did not retrieve the cited original "
            f"source sentence: {made_research}")
    with tempfile.TemporaryDirectory(prefix="crms-made-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "research.json"
        kb.save(knowledge_path)
        index.save(index_path)
        runtime_paths = {name: root / name for name in (
            "dialogue.json", "rules.json", "rule-session.json",
            "math.json", "math-session.json", "translations.json",
            "translation-session.json")}
        chat = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(runtime_paths["dialogue.json"]),
             "--rules", str(runtime_paths["rules.json"]),
             "--rule-session", str(runtime_paths["rule-session.json"]),
             "--math", str(runtime_paths["math.json"]),
             "--math-session", str(runtime_paths["math-session.json"]),
             "--translations", str(runtime_paths["translations.json"]),
             "--translation-session",
             str(runtime_paths["translation-session.json"])],
            input="Who made Python?\n/quit\n", text=True,
            capture_output=True, check=False, timeout=30)
        if (chat.returncode != 0
                or "Guido van Rossum created Python." not in chat.stdout
                or "Source:" not in chat.stdout):
            raise SystemExit(
                "learned relation wording failed in the actual chat runtime:\n"
                f"{chat.stdout}\n{chat.stderr}")

    heldout_sentence = "Margaret Hamilton created the Apollo Software."
    index.add_document("heldout", "Computing history", heldout_sentence,
                       "heldout.txt")
    heldout_hit = index.search("Apollo Software", limit=1)[0]
    heldout_source = index.citation(heldout_hit)
    transferred = kb.propose_facts(heldout_sentence, source=heldout_source)
    if len(transferred) != 1:
        raise SystemExit(
            "two reviewed relation examples did not license held-out extraction")
    if (transferred[0].subject, transferred[0].relation,
            transferred[0].object) != (
                "Margaret Hamilton", "create", "the Apollo Software"):
        raise SystemExit(f"reviewed frame transferred incorrect roles: {transferred}")
    kb.accept_fact_candidate(transferred[0], index)
    heldout_answer = kb.ask("Who created the Apollo Software?")
    if (heldout_answer.status != "answered"
            or heldout_answer.answer != "Margaret Hamilton"):
        raise SystemExit(
            f"accepted held-out fact did not answer through the induced frame: {heldout_answer}")
    heldout_inverse = kb.ask("What was created by Margaret Hamilton?")
    if (heldout_inverse.status != "answered"
            or heldout_inverse.answer != "the Apollo Software"):
        raise SystemExit(
            f"inverse role frame did not transfer to held-out fact: {heldout_inverse}")
    with tempfile.TemporaryDirectory(prefix="crms-reviewed-frame-") as folder:
        path = Path(folder) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        after_reload = restored.propose_facts(
            heldout_sentence, source=heldout_source)
    if len(after_reload) != 1 or after_reload[0].relation != "create":
        raise SystemExit("review-induced frame did not survive persistence")
    if restored.ask("Who created the Apollo Software?").answer != "Margaret Hamilton":
        raise SystemExit("review-induced question frame did not survive persistence")
    if (restored.ask("What was created by Margaret Hamilton?").answer
            != "the Apollo Software"):
        raise SystemExit("induced inverse frame did not survive persistence")
    restored_made = restored.ask("Who made Python?")
    if (restored_made.status != "answered"
            or restored_made.answer != "Guido van Rossum"):
        raise SystemExit("reviewed alternate predicate did not survive reload")

    # A single corpus occurrence of a possible infinitive is insufficient to
    # resolve an ambiguous past-tense stem into an active do-support frame.
    cautious_index = CRMSResearchIndex()
    cautious_index.add_document(
        "one-bare-form", "One example",
        "Engineers can create reliable tools.", "one-bare-form.txt")
    cautious = kb._discover_surface_relation_candidates(
        "Dorothy Vaughan created the Calculator.",
        source="scratch:cautious", research_index=cautious_index)
    if (len(cautious) != 1 or cautious[0].relation != "created"
            or cautious[0].language_evidence[0].get("morphology_support")):
        raise SystemExit(
            "one bare-form source incorrectly resolved an ambiguous predicate")

    # Hyphens must remain attached to the predicate's textual span and an
    # unrelated prepositional attachment must not become a second relation.
    hyphenated = kb._discover_surface_relation_candidates(
        "Ken Thompson co-created Unix at Bell Labs.", source="scratch:hyphen")
    if len(hyphenated) != 1:
        raise SystemExit(f"hyphenated sentence produced noisy candidates: {hyphenated}")
    item = hyphenated[0]
    if (item.subject, item.relation, item.object) != (
            "Ken Thompson", "co-created", "Unix"):
        raise SystemExit(f"hyphenated roles were split incorrectly: {item}")

    copular = kb._discover_surface_relation_candidates(
        "The capital of France is Paris.", source="scratch:capital")
    if (len(copular) != 1 or (copular[0].subject, copular[0].relation,
                              copular[0].object) !=
            ("Paris", "capital of", "France")):
        raise SystemExit(
            f"copular nominal relation roles were not reversed: {copular}")
    if not copular[0].language_evidence[0].get("review_required"):
        raise SystemExit("copular relation proposal bypassed review")

    agentless_passive = kb._discover_surface_relation_candidates(
        "The C language was created at Bell Labs.",
        source="scratch:agentless-passive")
    if agentless_passive:
        raise SystemExit(
            "agentless passive clause was misread as a positive fact: "
            f"{agentless_passive}")

    explicit_agent_passive = kb._discover_surface_relation_candidates(
        "Python was created by Guido van Rossum.",
        source="scratch:explicit-agent-passive")
    if (len(explicit_agent_passive) != 1
            or (explicit_agent_passive[0].subject,
                explicit_agent_passive[0].relation,
                explicit_agent_passive[0].object)
            != ("Guido van Rossum", "created", "Python")):
        raise SystemExit(
            "explicit passive by-phrase did not preserve agent/patient roles: "
            f"{explicit_agent_passive}")

    lowercase_object = kb._discover_surface_relation_candidates(
        "Marie Curie discovered radium.", source="scratch:lowercase-object")
    if (len(lowercase_object) != 1
            or (lowercase_object[0].subject, lowercase_object[0].relation,
                lowercase_object[0].object)
            != ("Marie Curie", "discovered", "radium")
            or not lowercase_object[0].language_evidence[0].get("review_required")):
        raise SystemExit(
            "named subject with lowercase object was not proposed for review: "
            f"{lowercase_object}")
    class_membership = kb._discover_surface_relation_candidates(
        "Ada is a mathematician.", source="scratch:class-membership")
    if (len(class_membership) != 1
            or (class_membership[0].subject, class_membership[0].relation,
                class_membership[0].object)
            != ("Ada", "is-a", "mathematician")
            or not class_membership[0].language_evidence[0].get("review_required")):
        raise SystemExit(
            "copular class-membership sentence did not propose a reviewed is-a fact: "
            f"{class_membership}")
    negative_class = kb._discover_surface_relation_candidates(
        "Ada is not a mathematician.", source="scratch:negative-class")
    if (len(negative_class) != 1 or negative_class[0].polarity
            or (negative_class[0].subject, negative_class[0].relation,
                negative_class[0].object)
            != ("Ada", "is-a", "mathematician")
            or negative_class[0].language_evidence[0].get("polarity")
            != "negative"):
        raise SystemExit(
            "explicit negative class statement was not retained as negative: "
            f"{negative_class}")
    negative_verb = kb._discover_surface_relation_candidates(
        "Ada did not create Python.", source="scratch:negative-verb")
    if (len(negative_verb) != 1 or negative_verb[0].polarity
            or (negative_verb[0].subject, negative_verb[0].relation,
                negative_verb[0].object)
            != ("Ada", "create", "Python")
            or negative_verb[0].language_evidence[0].get("polarity")
            != "negative"):
        raise SystemExit(
            "explicit active negation was not preserved as a negative fact: "
            f"{negative_verb}")
    for sentence, expected_object in (
            ("Ada did not discover radium.", "radium"),
            ("Ada did not create New York.", "New York")):
        candidate = kb._discover_surface_relation_candidates(
            sentence, source="scratch:negative-bounded-object")
        if (len(candidate) != 1 or candidate[0].polarity
                or candidate[0].object != expected_object):
            raise SystemExit(
                f"bounded negative object was lost: {sentence}: {candidate}")
    for sentence in (
            "Ada did not create Python yesterday.",
            "Ada did not create Python because she was busy."):
        if kb._discover_surface_relation_candidates(
                sentence, source="scratch:negative-unbounded-object"):
            raise SystemExit(
                f"negative adjunct was absorbed into the object: {sentence}")
    passive_negative = kb._discover_surface_relation_candidates(
        "Python was not created by Guido van Rossum.",
        source="scratch:passive-negative")
    if (len(passive_negative) != 1 or passive_negative[0].polarity
            or (passive_negative[0].subject, passive_negative[0].relation,
                passive_negative[0].object)
            != ("Guido van Rossum", "created", "Python")
            or passive_negative[0].language_evidence[0].get("method")
            != "explicit-agent passive negation"):
        raise SystemExit(
            "explicit-agent passive negation lost role or polarity: "
            f"{passive_negative}")
    for sentence in (
            "Python was not created yesterday by Guido.",
            "Python was not created by Guido in 1991."):
        if kb._discover_surface_relation_candidates(
                sentence, source="scratch:passive-negative-attachment"):
            raise SystemExit(
                f"passive negation accepted an attached clause: {sentence}")
    passive_index = CRMSResearchIndex()
    passive_sentence = "Python was not created by Guido van Rossum."
    passive_index.add_document("passive-negative", "Negative source",
                               passive_sentence, "negative.txt")
    passive_kb = CRMSKnowledgeBase()
    reviewed = passive_kb.research("Who created Python?", passive_index)
    if (reviewed.status != "needs_review"
            or len(reviewed.candidates or []) != 1
            or reviewed.candidates[0].polarity):
        raise SystemExit(
            "passive negative did not enter the cited review path: "
            f"{reviewed}")
    passive_kb.accept_fact_candidate(reviewed.candidates[0], passive_index)
    if (passive_kb.facts() or len(passive_kb.negative_facts()) != 1
            or passive_kb.negative_facts()[0].subject != "Guido van Rossum"
            or passive_kb.negative_facts()[0].object != "Python"):
        raise SystemExit(
            "reviewed passive negation did not persist with correct roles")
    for unsafe_sentence in (
            "Ada worked at home.",
            "Ada is a member of society.",
            "Ada discovered radium and polonium.",
            "Ada did not create Python or Linux.",
            "Ada did not create Python in 1990.",
            "Marie Curie discovered radium in France."):
        if kb._discover_surface_relation_candidates(
                unsafe_sentence, source="scratch:ambiguous-lowercase"):
            raise SystemExit(
                f"ambiguous lowercase-object clause was proposed: {unsafe_sentence}")

    correction = kb._discover_surface_relation_candidates(
        "Canberra is the capital of Australia, not Sydney.",
        source="scratch:correction")
    correction_claims = {(item.subject, item.relation, item.object,
                         item.polarity) for item in correction}
    if correction_claims != {
            ("Canberra", "capital of", "Australia", True),
            ("Sydney", "capital of", "Australia", False)}:
        raise SystemExit(
            "contrastive correction did not separate positive and rejected "
            f"subject claims: {correction}")
    if any(not item.language_evidence[0].get("review_required")
           or "contrastive correction" not in item.language_evidence[0].get(
               "method", "") for item in correction):
        raise SystemExit("contrastive candidates lost their review-only analysis")
    inverse_correction = kb._discover_surface_relation_candidates(
        "The capital of France is Paris, not Lyon.",
        source="scratch:inverse-correction")
    inverse_claims = {(item.subject, item.relation, item.object, item.polarity)
                      for item in inverse_correction}
    if inverse_claims != {
            ("Paris", "capital of", "France", True),
            ("Lyon", "capital of", "France", False)}:
        raise SystemExit(
            "inverse nominal correction assigned the wrong relation roles: "
            f"{inverse_correction}")
    object_correction = kb._discover_surface_relation_candidates(
        "Guido van Rossum created Python, not Linux.",
        source="scratch:object-correction")
    object_claims = {(item.subject, item.relation, item.object, item.polarity)
                     for item in object_correction}
    if object_claims != {
            ("Guido van Rossum", "created", "Python", True),
            ("Guido van Rossum", "created", "Linux", False)}:
        raise SystemExit(
            "object-slot correction assigned incorrect roles or polarity: "
            f"{object_correction}")
    correction_index = CRMSResearchIndex()
    correction_sentence = "Canberra is the capital of Australia, not Sydney."
    correction_index.add_document(
        "contrastive-review", "Australian capitals", correction_sentence,
        "contrastive-review.txt")
    correction_kb = CRMSKnowledgeBase()
    research_result = correction_kb.research(
        "capital of Australia", correction_index)
    proposed = research_result.candidates or []
    if research_result.status != "needs_review" or {
            (item.subject, item.relation, item.object, item.polarity)
            for item in proposed} != correction_claims:
        raise SystemExit(
            "research did not surface both cited correction candidates: "
            f"{research_result}")
    for candidate in proposed:
        correction_kb.accept_fact_candidate(candidate, correction_index)
    if (len(correction_kb.facts()) != 1
            or len(correction_kb.negative_facts()) != 1):
        raise SystemExit(
            "review acceptance did not store positive and negative claims separately")
    simple_negation = kb._discover_surface_relation_candidates(
        "Sydney is not the capital of Australia.",
        source="scratch:simple-negation")
    if simple_negation:
        raise SystemExit(
            "zero-frame discovery converted a negative clause into a positive relation")

    # A learned terminal object slot must stop before a clearly attached
    # locative/date adjunct, and a hyphenated predicate prefix must not leak
    # into the subject role.
    boundary_kb = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Dennis Ritchie", "the C language", "boundary:c"),
            ("Alan Turing", "the Turing machine", "boundary:turing")):
        sentence = f"{subject} created {obj}."
        boundary_kb.add_fact(subject, "create", obj, source)
        boundary_kb.teach_fact_pattern(
            sentence, subject=subject, relation="create", obj=obj,
            source=source, predicate_phrase="created")
    augmented = boundary_kb.propose_facts(
        "Dennis Ritchie created the C language at Bell Labs.",
        source="boundary:locative")
    if (len(augmented) != 1 or augmented[0].object != "the C language"):
        raise SystemExit(f"locative adjunct contaminated the learned object: {augmented}")
    hyphenated_learned = boundary_kb.propose_facts(
        "Ken Thompson co-created Unix at Bell Labs.",
        source="boundary:hyphen")
    if any(candidate.subject == "Ken Thompson co"
           for candidate in hyphenated_learned):
        raise SystemExit(
            f"hyphenated predicate prefix leaked into subject: {hyphenated_learned}")
    numbered_entity = boundary_kb._discover_surface_relation_candidates(
        "Researcher 0133 designed the Vela instrument 0133.",
        source="boundary:numbered-entity")
    if (len(numbered_entity) != 1
            or (numbered_entity[0].subject, numbered_entity[0].relation,
                numbered_entity[0].object) !=
               ("Researcher 0133", "designed", "the Vela instrument 0133")):
        raise SystemExit(
            f"numeric identifier was split into the predicate: {numbered_entity}")
    print("reviewed surface relation discovery diagnostic: PASS")
    print("reviewed claim induction, source review, held-out QA, active/passive inverse, persistence, and guards: PASS")


if __name__ == "__main__":
    main()
