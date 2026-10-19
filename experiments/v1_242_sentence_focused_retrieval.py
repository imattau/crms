"""Check content-word ranking and exact sentence citations in both indexes."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import (
    CRMSSQLiteResearchIndex, CRMSResearchIndex,
    _research_query_focus_terms, _research_query_terms, _sentence_context_kind,
    _sentence_span_at, _sentence_spans,
)
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    quoted_sentences = _sentence_spans(
        '“Guido created Python.” Agentless passives remain unassigned.')
    if [
            '“Guido created Python.” Agentless passives remain unassigned.'[
                start:end]
            for start, end in quoted_sentences
    ] != ['“Guido created Python.”', 'Agentless passives remain unassigned.']:
        raise SystemExit(
            f"sentence splitter crossed a closing quote: {quoted_sentences}")
    abbreviated = "Thompson was born in St. Petersburg. Dr. Ada Lovelace replied."
    if [abbreviated[start:end]
            for start, end in _sentence_spans(abbreviated)] != [
                "Thompson was born in St. Petersburg.",
                "Dr. Ada Lovelace replied."]:
        raise SystemExit("sentence splitting broke a place or title abbreviation")
    local_span = _sentence_span_at(
        abbreviated, abbreviated.index("Petersburg"))
    if abbreviated[slice(*local_span)] != "Thompson was born in St. Petersburg.":
        raise SystemExit("local sentence lookup split a place abbreviation")
    if "can" in _research_query_terms(
            "How can source text be included in a model?"):
        raise SystemExit("a common auxiliary was retained as a content term")
    if "that" in _research_query_terms(
            "Does the word count prove that CRMS knows more?"):
        raise SystemExit("a complementizer was retained as a content term")
    if _research_query_focus_terms(
            "What can the induced question frames generalize?") != {"generalize"}:
        raise SystemExit("object-wh modal question lost its predicate focus")
    corpus = {
        "computing": ("Computing", "Python was created by Guido van Rossum. "
                      "The C language was created at Bell Labs."),
        "geography": ("Geography", "The capital of France is Paris. "
                     "The Seine flows through Paris."),
        "science": ("Science", "Marie Curie conducted pioneering research "
                    "on radioactivity. She won two Nobel Prizes."),
    }
    with tempfile.TemporaryDirectory(prefix="crms-retrieval-") as directory:
        indexes = [CRMSResearchIndex(),
                   CRMSSQLiteResearchIndex(Path(directory) / "research.sqlite")]
        try:
            for index in indexes:
                for doc_id, (title, text) in corpus.items():
                    index.add_document(doc_id, title, text, f"{doc_id}.txt")
                hits = index.search("Who created the C language?", limit=3)
                if not hits or hits[0].document_id != "computing":
                    raise SystemExit(f"content terms did not rank computing first: {hits}")
                if hits[0].snippet != "The C language was created at Bell Labs.":
                    raise SystemExit(f"retrieval did not return one exact sentence: {hits[0]}")
                citation = index.citation(hits[0])
                if index.resolve_citation(citation) != hits[0].snippet:
                    raise SystemExit("sentence citation does not resolve exactly")

                # A rare entity identifier can occur in an unrelated sentence
                # inside a document that otherwise matches common query words.
                # The snippet picker must select the identifier-bearing
                # sentence rather than the document's more generic design line.
                target = "Researcher 0133 designed the Vela instrument 0133."
                index.add_document(
                    "numbered-target", "Numbered target", target,
                    "numbered-target.txt")
                index.add_document(
                    "numbered-distractor", "Numbered distractor",
                    "Researcher 0002 designed the Vela instrument 0002. "
                    "Researcher 0133 studied quartz field 0096 in 2046.",
                    "numbered-distractor.txt")
                numbered = index.search(
                    "Who was the designer of the Vela instrument 0133?", limit=5)
                distractor = next(
                    (hit for hit in numbered
                     if hit.document_id == "numbered-distractor"), None)
                if distractor is None or "Researcher 0133" not in distractor.snippet:
                    raise SystemExit(
                        "sentence ranking ignored the rare entity identifier: "
                        f"{numbered}")

                turing_sentence = "Alan Turing worked at Bletchley Park."
                index.add_document(
                    "turing-work", "Alan Turing biography",
                    "Alan Turing proposed the Turing machine. "
                    + turing_sentence,
                    "turing-work.txt")
                index.add_document(
                    "lovelace-work", "Ada Lovelace biography",
                    "Ada Lovelace worked at Babbage House.",
                    "lovelace-work.txt")
                location_kb = CRMSKnowledgeBase()
                result = location_kb.research(
                    "Where does Alan Turing work?", index)
                if (not result.source_sentences
                        or result.source_sentences[0]["text"] != turing_sentence):
                    raise SystemExit(
                        "regular verb inflection did not find the answer-bearing "
                        f"sentence: {result.source_sentences}")
                if not any(item.get("kind") ==
                           "regular_question_verb_inflection"
                           for item in result.query_expansions or []):
                    raise SystemExit(
                        "retrieval omitted its mechanical morphology explanation")
                if (result.status != "needs_review"
                        or len(result.candidates or []) != 1
                        or (result.candidates[0].subject,
                            result.candidates[0].relation,
                            result.candidates[0].object) !=
                           ("Alan Turing", "worked at", "Bletchley Park")):
                    raise SystemExit(
                        "locative sentence did not yield one review-only relation: "
                        f"{result.candidates}")
                location_kb.accept_fact_candidate(result.candidates[0], index)
                second = location_kb.research(
                    "Where does Ada Lovelace work?", index)
                if second.status != "needs_review" or not second.candidates:
                    raise SystemExit(
                        "second locative example was not held for review")
                location_kb.accept_fact_candidate(second.candidates[0], index)
                answer = location_kb.ask("Where does Alan Turing work?")
                if (answer.status != "answered"
                        or answer.answer != "Bletchley Park"
                        or not answer.evidence):
                    raise SystemExit(
                        "two reviewed locative examples did not license a "
                        f"where-question: {answer}")
        finally:
            indexes[1].close()
    # A contrastive correction is not safely representable by a flat
    # positive fact frame; it must never leak the rejected entity into the
    # accepted object slot.
    knowledge = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Paris", "France", "capital-a"),
            ("Canberra", "Australia", "capital-b")):
        knowledge.add_fact(subject, "capital of", obj, source)
        knowledge.teach_fact_pattern(
            f"{subject} is the capital of {obj}.", subject=subject,
            relation="capital of", obj=obj, source=source)
    if knowledge.propose_facts(
            "Canberra is the capital of Australia, not Sydney.",
            source="contrastive-correction"):
        raise SystemExit("contrastive correction was flattened into a positive fact")

    # A single accepted fact is enough for a transparent agent-noun question
    # grammar; no question frame is taught. The derivation must not answer an
    # unrelated noun that does not share the stored relation's stem.
    nominal = CRMSKnowledgeBase()
    nominal.add_fact("Ada Lovelace", "designed", "Analytical Engine",
                     "teacher:accepted-fact")
    nominal_answer = nominal.ask(
        "Who was the designer of the Analytical Engine?")
    if (nominal_answer.status != "answered"
            or nominal_answer.answer != "Ada Lovelace"):
        raise SystemExit(
            f"grounded agent-noun question failed without a taught frame: "
            f"{nominal_answer}")
    unrelated_nominal = nominal.ask(
        "Who was the curator of the Analytical Engine?")
    if unrelated_nominal.status != "unknown":
        raise SystemExit(
            "agent-noun derivation crossed to an unrelated stored relation: "
            f"{unrelated_nominal}")
    wrapped_index = CRMSResearchIndex()
    wrapped_sentence = (
        "In this open-world store,\n"
        "the absence of a proposition is unknown, not a negative example.")
    wrapped_index.add_document(
        "wrapped-readme", "CRMS README",
        wrapped_sentence + "\n\nA separate paragraph follows.",
        "CRMS_README.md")
    wrapped_summary = wrapped_index.summarize(
        "What does a missing proposition mean in the open-world store?",
        limit=1)
    if (not wrapped_summary.sentences
            or wrapped_summary.sentences[0].text != wrapped_sentence):
        raise SystemExit(
            "sentence retrieval split a soft-wrapped source line: "
            f"{wrapped_summary.sentences}")

    focus_index = CRMSResearchIndex()
    focus_index.add_document(
        "focus", "Question frames",
        "An induced question frame supports one unique parse. "
        "These forms do not generalize to arbitrary paraphrases.",
        "focus.txt")
    focused = focus_index.summarize(
        "What can the induced question frames generalize?", limit=1)
    if (not focused.sentences
            or focused.sentences[0].text
            != "These forms do not generalize to arbitrary paraphrases."):
        raise SystemExit(
            "predicate focus lost to a subject-heavy neighboring sentence: "
            f"{focused.sentences}")

    # SQLite ranks a representative chunk for each document. Put the
    # answer-bearing predicate in a later chunk so selecting only terms from
    # that representative chunk cannot hide it from sentence scoring.
    chunked_focus_text = (
        "Licensed induced question frames also guide research retrieval. "
        + "A neutral corpus sentence describes the surrounding material. "
        * 230
        + "These forms do not generalize to arbitrary paraphrases.")
    with tempfile.TemporaryDirectory(prefix="crms-focus-chunks-") as directory:
        chunk_indexes = [
            CRMSResearchIndex(),
            CRMSSQLiteResearchIndex(Path(directory) / "focus.sqlite"),
        ]
        try:
            for index in chunk_indexes:
                index.add_document("focus", "Question frames",
                                   chunked_focus_text, "focus.txt")
                chunked = index.summarize(
                    "What can the induced question frames generalize?",
                    limit=1)
                if (not chunked.sentences
                        or chunked.sentences[0].text
                        != "These forms do not generalize to arbitrary paraphrases."):
                    raise SystemExit(
                        "chunk-level ranking hid a focused sentence: "
                        f"{type(index).__name__}: {chunked.sentences}")
        finally:
            chunk_indexes[1].close()

    complementizer_index = CRMSResearchIndex()
    complementizer_index.add_document(
        "complementizer", "Model measure",
        "Other probes prove that remaining candidates are uncertain. "
        "Word units are not an LLM tokenizer count and do not "
        "establish knowledge equivalence to a model by parameter count.",
        "complementizer.txt")
    focused_measure = complementizer_index.summarize(
        "Does the word count prove that CRMS knows as much as a "
        "large model?", limit=1)
    if (not focused_measure.sentences
            or "word units are not an llm tokenizer count"
            not in focused_measure.sentences[0].text.casefold()):
        raise SystemExit(
            "complementizer/prove noise outranked the word-count evidence: "
            f"{focused_measure.sentences}")
    search_count = 0
    original_search = wrapped_index.search

    def counted_search(*args, **kwargs):
        nonlocal search_count
        search_count += 1
        return original_search(*args, **kwargs)

    wrapped_index.search = counted_search
    CRMSKnowledgeBase().research(
        "What does a missing proposition mean in the open-world store?",
        wrapped_index)
    if search_count != 1:
        raise SystemExit(
            f"one research turn ran the same search {search_count} times")
    inverse = CRMSKnowledgeBase()
    inverse.add_fact("Ada Lovelace", "designed", "Analytical Engine",
                     "teacher:accepted-fact")
    inverse_answer = inverse.ask("What did Ada Lovelace design?")
    if (inverse_answer.status != "answered"
            or inverse_answer.answer != "Analytical Engine"):
        raise SystemExit(
            f"do-support inverse question required a taught frame: "
            f"{inverse_answer}")
    synonym_guess = inverse.ask("What did Ada Lovelace invent?")
    if synonym_guess.status != "unknown":
        raise SystemExit(
            "stored-relation parsing guessed an unobserved synonym: "
            f"{synonym_guess}")
    regular_forms = CRMSKnowledgeBase()
    for relation, verb, obj in (
            ("created", "create", "Analytical Engine"),
            ("stopped", "stop", "Runaway carriage")):
        regular_forms.add_fact("Ada Lovelace", relation, obj,
                               f"teacher:{relation}")
        result = regular_forms.ask(f"What did Ada Lovelace {verb}?")
        if result.status != "answered" or result.answer != obj:
            raise SystemExit(
                f"regular do-support morphology failed for {relation}: {result}")
    subject_question = CRMSKnowledgeBase()
    subject_question.add_fact(
        "Ada Lovelace", "designed", "Analytical Engine",
        "teacher:accepted-fact")
    subject_answer = subject_question.ask(
        "Who designed the Analytical Engine?")
    if (subject_answer.status != "answered"
            or subject_answer.answer != "Ada Lovelace"):
        raise SystemExit(
            f"grounded subject question required a taught frame: {subject_answer}")
    subject_reply = subject_question.render_brief(subject_answer)
    if not subject_reply.startswith(
            "Ada Lovelace designed Analytical Engine."):
        raise SystemExit(
            f"grounded answer was not realized as a sentence: {subject_reply}")
    invented_guess = subject_question.ask(
        "Who invented the Analytical Engine?")
    if invented_guess.status != "unknown":
        raise SystemExit(
            "stored-relation subject parser guessed an unobserved synonym: "
            f"{invented_guess}")
    subject_question.add_fact(
        "Charles Babbage", "designed", "Analytical Engine",
        "teacher:second-subject")
    multiple_subjects = subject_question.ask(
        "Who designed the Analytical Engine?")
    if multiple_subjects.status != "ambiguous":
        raise SystemExit(
            "multiple accepted subjects were not reported as ambiguous: "
            f"{multiple_subjects}")
    code_index = CRMSResearchIndex()
    code_index.add_document(
        "code-fixture", "Python test fixture",
        'assert result == ("Mira Sol", "founded", "Moonbase Institute")',
        "fixture.py")
    code_index.add_document(
        "biography", "Mira Sol biography",
        "Mira Sol founded the Moonbase Institute.", "biography.txt")
    person_hits = code_index.search(
        "Who founded the Moonbase Institute?", limit=5)
    if (not person_hits or person_hits[0].document_id != "biography"
            or any(hit.document_id == "code-fixture" for hit in person_hits)):
        raise SystemExit(
            "person question did not prefer prose evidence over code: "
            f"{person_hits}")
    code_result = CRMSKnowledgeBase().research(
        "Who founded the Moonbase Institute?", code_index)
    if any("fixture.py" in candidate.source
           for candidate in code_result.candidates or []):
        raise SystemExit(
            "Python test syntax was proposed as a natural-language fact: "
            f"{code_result.candidates}")
    code_index.add_document(
        "concept-code", "feedback_loop function implementation",
        "def feedback_loop(): retry_counter = 0; return retry_counter",
        "feedback_loop.py")
    code_index.add_document(
        "concept-prose", "Feedback design",
        "The feedback loop retrieves cases, overlays their contributions, "
        "verifies the result, then stores a derived case.", "design.txt")
    code_index.add_document(
        "concept-lexical-prose", "Feedback API note",
        "The feedback_loop function work is tracked in this API design note.",
        "api-design.md")
    conceptual_hits = code_index.search(
        "How does the feedback loop work?", limit=5)
    if (not conceptual_hits
            or any(hit.document_id == "concept-code"
                   for hit in conceptual_hits)):
        raise SystemExit(
            "conceptual question retrieved a source-code fixture: "
            f"{conceptual_hits}")
    natural_function_hits = code_index.search(
        "What is the function of a feedback loop?", limit=5)
    if (not natural_function_hits
            or any(hit.document_id == "concept-code"
                   for hit in natural_function_hits)):
        raise SystemExit(
            "a natural question about a function was misrouted to code: "
            f"{natural_function_hits}")
    programming_hits = code_index.search(
        "How does the feedback_loop function work?", limit=5)
    if (not programming_hits
            or programming_hits[0].document_id != "concept-code"):
        raise SystemExit(
            "explicit programming question did not rank implementation code first: "
            f"{programming_hits}")
    example_index = CRMSResearchIndex()
    example_index.add_document(
        "readme-example", "Parser example",
        "### Python API\n\nThe zero-frame parser normalizes a bounded explicit-agent passive "
        "form such as “Python was created by Guido” into the same "
        "agent/relation/patient slots as “Guido created Python.” "
        "Agentless passives remain unassigned.", "CRMS_README.md")
    example_summary = example_index.summarize(
        "Who created Python?", limit=1)
    if (not example_summary.sentences
            or example_summary.sentences[0].context_kind != "example"):
        raise SystemExit(
            "source index lost the illustrative context label: "
            f"{example_summary.sentences}")
    example_result = CRMSKnowledgeBase().research(
        "Who created Python?", example_index)
    if (example_result.candidates or example_result.source_sentences
            or example_result.passages or example_result.status != "unknown"):
        raise SystemExit(
            "an illustrative parser example was presented as factual answer evidence: "
            f"{example_result}")
    explicit_example = CRMSKnowledgeBase().research(
        "What example illustrates the passive form?", example_index)
    if (explicit_example.status != "sources_found"
            or not explicit_example.source_sentences
            or explicit_example.source_sentences[0]["context_kind"] != "example"):
        raise SystemExit(
            "an explicit example request could not retrieve its illustration: "
            f"{explicit_example}")
    if _sentence_context_kind(
            "Ada Lovelace founded the Analytical Engine Society.",
            "Ada Lovelace founded the Analytical Engine Society.", 0) != "assertion":
        raise SystemExit("a direct declarative was mislabeled as an example")
    structured_index = CRMSResearchIndex()
    structured_line = '=> "Ada Lovelace" | "designed" | "Analytical Engine"'
    structured_index.add_document(
        "parser-output", "Parser output example",
        structured_line, "CRMS_README.md")
    structured_result = CRMSKnowledgeBase().research(
        "Who designed the Analytical Engine?", structured_index)
    if structured_result.candidates:
        raise SystemExit(
            "structured parser output became a natural-language fact: "
            f"{structured_result.candidates}")
    if _sentence_context_kind(structured_line, structured_line, 0) != "example":
        raise SystemExit("structured output was not labeled as an example")
    relation_note = (
        '2. **Relation synonyms by shared frame.** If "designed" and '
        '"built" both appear in `Who ___ the Engine?` with the same answer '
        'set, propose them as interchangeable in that frame.')
    if _sentence_context_kind(relation_note, relation_note, 0) != "example":
        raise SystemExit("a numbered design-note example was not recognized")
    with tempfile.TemporaryDirectory(prefix="crms-person-source-") as folder:
        sqlite_person_index = CRMSSQLiteResearchIndex(
            Path(folder) / "research.sqlite")
        try:
            sqlite_person_index.add_document(
                "code-fixture", "Python test fixture",
                'assert result == ("Mira Sol", "founded", "Moonbase Institute")',
                "fixture.py")
            sqlite_person_index.add_document(
                "biography", "Mira Sol biography",
                "Mira Sol founded the Moonbase Institute.", "biography.txt")
            sqlite_person_hits = sqlite_person_index.search(
                "Who founded the Moonbase Institute?", limit=5)
            if (not sqlite_person_hits
                    or sqlite_person_hits[0].document_id != "biography"
                    or any(hit.document_id == "code-fixture"
                           for hit in sqlite_person_hits)):
                raise SystemExit(
                    "SQLite person retrieval did not filter code sources: "
                    f"{sqlite_person_hits}")
            sqlite_person_index.add_document(
                "concept-code", "feedback_loop function implementation",
                "def feedback_loop(): retry_counter = 0; return retry_counter",
                "feedback_loop.py")
            sqlite_person_index.add_document(
                "concept-prose", "Feedback design",
                "The feedback loop retrieves cases and stores a verified derived case.",
                "design.txt")
            sqlite_person_index.add_document(
                "concept-lexical-prose", "Feedback API note",
                "The feedback_loop function work is tracked in this API design note.",
                "api-design.md")
            conceptual_sqlite_hits = sqlite_person_index.search(
                "How does the feedback loop work?", limit=5)
            natural_function_sqlite_hits = sqlite_person_index.search(
                "What is the function of a feedback loop?", limit=5)
            programming_sqlite_hits = sqlite_person_index.search(
                "How does the feedback_loop function work?", limit=5)
            if (any(hit.document_id == "concept-code"
                    for hit in conceptual_sqlite_hits)
                    or any(hit.document_id == "concept-code"
                           for hit in natural_function_sqlite_hits)
                    or not programming_sqlite_hits
                    or programming_sqlite_hits[0].document_id != "concept-code"):
                raise SystemExit(
                    "SQLite source-type routing failed for prose/code queries")
        finally:
            sqlite_person_index.close()
    print("sentence-focused retrieval diagnostic: PASS")
    print("stopword filtering, sentence citations, backend parity, regular-verb retrieval, "
          "reviewed locative learning and QA, contrastive guard, grounded "
          "agent-noun parsing, stored-relation do-support, subject questions, "
          "and code-source fact-extraction guard: PASS")


if __name__ == "__main__":
    main()
