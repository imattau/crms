"""Build a large isolated corpus, drive terminal chat, and score language retrieval.

This fixture uses fictional entities and explicitly generated claims. It tests
corpus scale and natural-language routing without adding synthetic knowledge to
any project or user model store.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT / "experiments" / "reports" / "large_corpus_chat_audit.json"
sys.path.insert(0, str(PROJECT))
from crms_package import (  # noqa: E402
    export_model_database, model_database_research_stats)
from crms_model import CRMSModel  # noqa: E402


def response_chunks(output: str, turns: list[str]) -> list[str]:
    # input() prints the prompt but subprocess pipes do not echo typed input.
    # Associate each prompt-delimited response with the known input sequence.
    chunks = output.split("you> ")[1:]
    if len(chunks) != len(turns):
        raise SystemExit(
            f"chat emitted {len(chunks)} prompt responses for {len(turns)} turns")
    return [chunk.strip() for chunk in chunks]


def corpus_rows(count: int = 1_200):
    people = [f"Researcher {index:04d}" for index in range(count)]
    objects = [f"Vela instrument {index:04d}" for index in range(count)]
    cities = [f"Nacre City {index:04d}" for index in range(count)]
    rivers = [f"Serein River {index:04d}" for index in range(count)]
    topics = [f"quartz field {index:04d}" for index in range(count)]
    institutes = [f"Meridian Institute {index:04d}" for index in range(count)]
    rows = []
    for i in range(count):
        # Every document mixes relation types and nearby distractors; the
        # target is deliberately not always the first sentence.
        sentences = [
            f"The {rivers[i]} flows through {cities[i]}.",
            f"{people[i]} designed the {objects[i]}.",
            f"Researchers at the {institutes[i]} studied {topics[i]}.",
            f"{people[(i + 37) % count]} studied {topics[i]} in 204{i % 10}.",
            f"The {objects[i]} was designed by {people[i]}.",
            f"{cities[i]} is crossed by {rivers[i]}.",
        ]
        rows.append((f"doc-{i:04d}", f"Fictional Research Record {i:04d}",
                     "\n".join(sentences)))
    return rows


def classify_unknown_reply(reply: str) -> str:
    """Separate refusals, evidence-only context, clarifications, and answers."""
    lowered = reply.casefold()
    if "which meaning should i look up?" in lowered:
        return "clarification"
    refusal_markers = (
        "couldn't find", "don't know", "can't answer", "won't guess",
        "i do not know", "i don't have a grounded answer",
        "does not support a grounded answer", "does not establish",
    )
    if not any(marker in lowered for marker in refusal_markers):
        return "other"
    if ("closest source sentence:" in lowered
            or "closest related source says:" in lowered):
        return "abstained_with_related_evidence"
    return "abstained"


def target_queries(count: int = 1_200):
    queries = []
    # Query a spread of the indexed corpus: enough turns to test varied
    # language while keeping the end-to-end CLI run useful as a development
    # diagnostic rather than turning it into a throughput benchmark.
    for i in sorted({round(index * (count - 1) / 9) for index in range(10)}):
        # Exact and structurally varied forms share terms with the source.
        queries.extend((
            (f"Which river flows through Nacre City {i:04d}?",
             f"The Serein River {i:04d} flows through Nacre City {i:04d}."),
            (f"Who designed the Vela instrument {i:04d}?",
             f"Researcher {i:04d} designed the Vela instrument {i:04d}."),
            (f"What did researchers at the Meridian Institute {i:04d} study?",
             f"Researchers at the Meridian Institute {i:04d} studied quartz field {i:04d}."),
        ))
    return queries


def main() -> None:
    if classify_unknown_reply(
            "I won't guess.\nClosest source sentence: nearby evidence") != (
                "abstained_with_related_evidence"):
        raise SystemExit("related-evidence abstention was misclassified")
    if classify_unknown_reply("Which meaning should I look up?") != "clarification":
        raise SystemExit("clarification was incorrectly counted as an abstention")
    if classify_unknown_reply("The answer is 42.") != "other":
        raise SystemExit("a direct answer was misclassified as an abstention")
    with tempfile.TemporaryDirectory(prefix="crms-large-corpus-") as folder:
        root = Path(folder)
        sources = root / "sources"
        sources.mkdir()
        for document_id, title, text in corpus_rows():
            (sources / f"{document_id}.txt").write_text(
                f"{title}\n{text}\n", encoding="utf-8")

        knowledge = root / "knowledge.json"
        index = root / "research.sqlite"
        turns = [f"/source-dir {sources}"]
        expected = target_queries()
        turns.extend(question for question, _ in expected)
        gap_queries = [
            "Who was the designer of the Vela instrument 0000?",
            "Which stream passes through Nacre City 0133?",
            "What research happened at Meridian Institute 0266?",
            # These probes hold the entity constant while changing the
            # relation wording or question structure. They are diagnostic,
            # not pass/fail requirements: evidence retrieval alone must not be
            # counted as a natural-language answer.
            "Who was responsible for designing the Vela instrument 0133?",
            "Who is credited with designing the Vela instrument 0133?",
            "Who created the Vela instrument 0133?",
            "Which waterway runs through Nacre City 0133?",
            "What body of water crosses Nacre City 0133?",
            "Where does the Serein River 0133 run?",
            "What did the Meridian Institute 0266 investigate?",
            "What topic was studied by the Meridian Institute 0266?",
            "At which institute did researchers study quartz field 0266?",
            "Who was responsible for orchestrating the Vela instrument 0133?",
            "What did researchers at the Meridian Institute 0266 invent?",
        ]
        natural_language_targets = {
            gap_queries[0]: "Researcher 0000 designed the Vela instrument 0000.",
            gap_queries[1]: "The Serein River 0133 flows through Nacre City 0133.",
            gap_queries[2]: "Researchers at the Meridian Institute 0266 studied quartz field 0266.",
            gap_queries[3]: "Researcher 0133 designed the Vela instrument 0133.",
            gap_queries[4]: "Researcher 0133 designed the Vela instrument 0133.",
            gap_queries[5]: "Researcher 0133 designed the Vela instrument 0133.",
            gap_queries[6]: "The Serein River 0133 flows through Nacre City 0133.",
            # This query asks for the subject of the passive ``is crossed by``
            # clause, not for the separate ``flows through`` sentence in the
            # same record. Score the answer realization entailed by that
            # clause rather than requiring an unrelated source sentence.
            gap_queries[7]: "Serein River 0133 crosses Nacre City 0133.",
            gap_queries[8]: "The Serein River 0133 flows through Nacre City 0133.",
            gap_queries[9]: "Researchers at the Meridian Institute 0266 studied quartz field 0266.",
            gap_queries[10]: "Researchers at the Meridian Institute 0266 studied quartz field 0266.",
            gap_queries[11]: "Researchers at the Meridian Institute 0266 studied quartz field 0266.",
            gap_queries[12]: "Researcher 0133 designed the Vela instrument 0133.",
            gap_queries[13]: "Researchers at the Meridian Institute 0266 studied quartz field 0266.",
        }
        expected_probe_hits = {question: True for question in gap_queries}
        # "Create" is not licensed by a source that only says "designed";
        # this is a relation-conflict control, not a positive paraphrase.
        expected_probe_hits[gap_queries[5]] = False
        expected_probe_hits[gap_queries[12]] = False
        expected_probe_hits[gap_queries[13]] = False
        # Text overlap is only a retrieval diagnostic. These authored task
        # outcomes distinguish a real answer from a relevant sentence shown
        # with an explicit limitation, and from a correct abstention.
        expected_probe_outcomes = {
            gap_queries[0]: "answer",
            gap_queries[1]: "answer",
            gap_queries[2]: "related_evidence_only",
            gap_queries[3]: "answer",
            gap_queries[4]: "answer",
            gap_queries[5]: "abstain",
            gap_queries[6]: "answer",
            gap_queries[7]: "answer",
            gap_queries[8]: "answer",
            gap_queries[9]: "answer",
            gap_queries[10]: "answer",
            gap_queries[11]: "answer",
            gap_queries[12]: "abstain",
            gap_queries[13]: "abstain",
        }
        turns.extend(gap_queries)
        unknown_queries = [
            "Who invented the Zorblax engine?",
            "What is the population of Nacre City 9999?",
        ]
        turns.extend(unknown_queries)
        turns.append("/quit")
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge), "--index", str(index),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--math-session", str(root / "math-session.json"),
            "--translations", str(root / "translations.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        run = subprocess.run(command, input="\n".join(turns) + "\n",
                             text=True, capture_output=True, cwd=root,
                             timeout=180, check=False)
        if run.returncode:
            raise SystemExit(f"chat process failed ({run.returncode}):\n{run.stderr}")
        output = run.stdout
        responses = response_chunks(output, turns)
        response_by_turn = dict(zip(turns, responses))
        failures = [(question, wanted) for question, wanted in expected
                    if wanted not in response_by_turn[question]]
        event_nominal_question = "What research happened at Meridian Institute 0266?"
        event_nominal_target = (
            "Researchers at the Meridian Institute 0266 studied quartz field 0266.")
        event_nominal_response = response_by_turn[event_nominal_question]
        event_nominal_evidence_only = (
            event_nominal_target in event_nominal_response
            and "does not establish the requested relation" in event_nominal_response
            and "quoted evidence, not an answer to that relation" in event_nominal_response)
        if not event_nominal_evidence_only:
            raise SystemExit(
                "event-nominal wording should show the related sentence and its limit: "
                f"{event_nominal_response}")
        candidate_reply_question = "Who designed the Vela instrument 0000?"
        candidate_reply_sentence = (
            "Researcher 0000 designed the Vela instrument 0000.")
        candidate_reply = response_by_turn[candidate_reply_question]
        candidate_reply_is_sentence = (
            candidate_reply_sentence in candidate_reply
            and "source claim awaiting review" in candidate_reply
            and "not yet an accepted fact" in candidate_reply
            and "Researcher 0000 — designed →" not in candidate_reply
            and "Evidence:" not in candidate_reply)
        if not candidate_reply_is_sentence:
            raise SystemExit(
                "unaccepted source candidate should be presented as its cited "
                "sentence with a clear review status: "
                f"{candidate_reply}")
        report = {
            "documents": len(corpus_rows()),
            "sentences": len(corpus_rows()) * 6,
            "queries": len(expected),
            "expected_answer_sentences_seen": len(expected) - len(failures),
            "misses": failures[:30],
            "baseline_query_results": {
                question: {
                    "expected_sentence": wanted,
                    "response": response_by_turn[question],
                    "expected_sentence_found": wanted in response_by_turn[question],
                }
                for question, wanted in expected
            },
            "indexed_confirmation": next(
                (line for line in output.splitlines() if "Indexed " in line), ""),
            "paraphrase_probes": gap_queries,
            "event_nominal_related_evidence_only": {
                "question": event_nominal_question,
                "response": event_nominal_response,
                "evidence_shown_with_limit": event_nominal_evidence_only,
                "counts_as_answered_paraphrase": False,
            },
            "review_candidate_sentence_reply": {
                "question": candidate_reply_question,
                "response": candidate_reply,
                "sentence_with_explicit_review_status": candidate_reply_is_sentence,
            },
            "paraphrase_sentence_hits": sum(
                1 for question in gap_queries
                if expected_probe_hits[question]
                and natural_language_targets[question]
                    in response_by_turn[question]),
            "positive_paraphrase_related_evidence_only_count": int(
                event_nominal_evidence_only),
            "positive_paraphrase_probe_count": sum(
                1 for question in gap_queries
                if expected_probe_hits[question]),
            "negative_relation_control_count": sum(
                1 for question in gap_queries
                if not expected_probe_hits[question]),
            "natural_language_probe_results": {
                question: {
                    "response": response_by_turn[question],
                    "expected_sentence_found":
                        natural_language_targets[question]
                        in response_by_turn[question],
                    "should_find_expected_sentence":
                        expected_probe_hits[question],
                }
                for question in gap_queries
            },
            "natural_language_task_outcomes": {},
            "unknown_query_examples": unknown_queries,
            "unknown_reply_classifications": {
                question: classify_unknown_reply(response_by_turn[question])
                for question in unknown_queries
            },
            "unknown_reply_classification_counts": {},
            "unknown_abstention_count": sum(
                classify_unknown_reply(response_by_turn[question])
                in {"abstained", "abstained_with_related_evidence"}
                for question in unknown_queries),
            "pending_state_probe": {
                question: response_by_turn[question]
                for question in gap_queries
            },
        }
        for question in gap_queries:
            response = response_by_turn[question]
            lowered = response.casefold()
            target_found = (natural_language_targets[question]
                            in response)
            if any(marker in lowered for marker in (
                    "does not establish the requested relation",
                    "does not support a grounded answer",
                    "closest source sentence:",
                    "closest related source says:")):
                observed = "related_evidence_only"
            elif any(marker in lowered for marker in (
                    "i couldn't find", "i can't answer", "i won't guess")):
                observed = "abstain"
            elif target_found:
                observed = ("source_answer" if any(marker in lowered for marker in (
                    "quoted evidence", "awaiting review", "not yet an accepted fact"))
                    else "answer")
            else:
                observed = "other"
            expected_outcome = expected_probe_outcomes[question]
            accepted_observations = {
                "answer": {"answer", "source_answer"},
                "related_evidence_only": {"related_evidence_only"},
                "abstain": {"abstain"},
            }[expected_outcome]
            report["natural_language_task_outcomes"][question] = {
                "expected": expected_outcome,
                "observed": observed,
                "pass": observed in accepted_observations,
            }
        report["task_outcome_counts"] = {
            outcome: sum(
                item["observed"] == outcome
                for item in report["natural_language_task_outcomes"].values())
            for outcome in ("answer", "source_answer",
                            "related_evidence_only", "abstain", "other")
        }
        report["task_outcome_pass_count"] = sum(
            item["pass"]
            for item in report["natural_language_task_outcomes"].values())
        classification_counts: dict[str, int] = {}
        for classification in report["unknown_reply_classifications"].values():
            classification_counts[classification] = (
                classification_counts.get(classification, 0) + 1)
        report["unknown_reply_classification_counts"] = classification_counts
        report["unknown_reply_count"] = sum(
            classification_counts.get(kind, 0)
            for kind in ("abstained", "abstained_with_related_evidence"))
        report["unknown_abstention_gate"] = (
            report["unknown_abstention_count"] == len(unknown_queries))
        if not report["unknown_abstention_gate"]:
            raise SystemExit(
                "an unsupported query was not clearly abstained: "
                f"{report['unknown_reply_classifications']}")
        report_path = root / "report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if report["expected_answer_sentences_seen"] != report["queries"]:
            report["exact_answer_gate"] = "FAIL"
        else:
            report["exact_answer_gate"] = "PASS"
        if "Indexed 1200 source file(s)" not in report["indexed_confirmation"]:
            raise SystemExit("chat did not index the complete generated corpus")

        # Now teach from two cited examples and ask the chat to transfer the
        # pattern to an indexed but previously unseen pair.
        learning_turns = [
            "/teach-fact Researcher 0000|designed|the Vela instrument 0000|Researcher 0000 designed the Vela instrument 0000|designed|positive",
            "/teach-fact Researcher 0001|designed|the Vela instrument 0001|Researcher 0001 designed the Vela instrument 0001|designed|positive",
            "/teach-question Who designed the Vela instrument 0000?|designed|subject|the Vela instrument 0000|Researcher 0000",
            "/teach-question Who designed the Vela instrument 0001?|designed|subject|the Vela instrument 0001|Researcher 0001",
            "Who designed the Vela instrument 0133?",
            "/accept 1",
            "Who designed the Vela instrument 0133?",
            "What did Researcher 0133 design?",
            "Who was the designer of the Vela instrument 0133?",
            "/quit",
        ]
        learning_command = list(command)
        review_flag = learning_command.index("--candidate-session")
        learning_command[review_flag + 1] = str(root / "learning-candidates.json")
        learned = subprocess.run(
            learning_command, input="\n".join(learning_turns) + "\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        if learned.returncode:
            raise SystemExit(f"learned-pattern chat failed: {learned.stderr}")
        learned_responses = response_chunks(learned.stdout, learning_turns)
        learned_by_turn = dict(zip(learning_turns, learned_responses))
        report["learned_transfer_answer"] = (
            "Researcher 0133 designed the Vela instrument 0133."
            in learned.stdout)
        report["learned_transfer_candidate_reviewed"] = (
            "Accepted positive fact: Researcher 0133 — designed → "
            "the Vela instrument 0133." in learned.stdout)
        nominal_reply = learned_by_turn[
            "Who was the designer of the Vela instrument 0133?"]
        inverse_reply = learned_by_turn[
            "What did Researcher 0133 design?"]
        report["inverse_question_returns_accepted_answer"] = (
            "CRMS> Researcher 0133 designed the Vela instrument 0133."
            in inverse_reply)
        report["unlicensed_nominal_paraphrase_review_candidate"] = (
            "Researcher 0133 — designed → the Vela instrument 0133"
            in nominal_reply)
        report["nominal_paraphrase_returns_quoted_evidence"] = (
            "Source text: Researcher 0133 designed the Vela instrument 0133."
            in nominal_reply)
        report["nominal_paraphrase_returns_accepted_answer"] = (
            "CRMS> Researcher 0133 designed the Vela instrument 0133."
            in nominal_reply)
        if not report["learned_transfer_answer"]:
            raise SystemExit("two cited examples failed to transfer to a reviewed held-out fact")
        if report["paraphrase_sentence_hits"] < 3:
            raise SystemExit("baseline evidence retrieval probes regressed")
        incorrect_probe_results = {
            question: detail for question, detail in
            report["natural_language_probe_results"].items()
            if detail["expected_sentence_found"]
            != detail["should_find_expected_sentence"]
        }
        report["unexpected_probe_results"] = incorrect_probe_results
        institute_record_question = gap_queries[11]
        report["numbered_record_disambiguation_gate"] = (
            natural_language_targets[institute_record_question]
            in response_by_turn[institute_record_question])
        if not report["numbered_record_disambiguation_gate"]:
            raise SystemExit(
                "numbered corpus query did not select its matching record: "
                f"{response_by_turn[institute_record_question]}")
        report["learned_transfer_gate"] = bool(report["learned_transfer_answer"])
        report["unknown_abstention_gate"] = (
            report["unknown_abstention_count"] == len(unknown_queries))
        report["negative_relation_controls_abstained"] = sum(
            1 for question, detail in
            report["natural_language_probe_results"].items()
            if not detail["should_find_expected_sentence"]
            and not detail["expected_sentence_found"])
        report["agent_noun_transfer_gate"] = bool(
            report["nominal_paraphrase_returns_accepted_answer"])
        report["inverse_question_transfer_gate"] = bool(
            report["inverse_question_returns_accepted_answer"])
        # Package the learned store and all indexed text into one portable
        # model database, then query it with the original corpus and index
        # paths unavailable. This checks distributability at corpus scale.
        rule_memory = root / "rules.json"
        if not rule_memory.exists():
            CRMSModel().save(rule_memory)
        model_database = root / "portable-model.sqlite"
        export_model_database(
            model_database, knowledge=knowledge,
            rules=rule_memory, research_index=index)
        research_stats = model_database_research_stats(model_database)
        report["portable_model_documents"] = (
            research_stats["documents"] if research_stats else 0)
        (root / "sources").rename(root / "sources-offline")
        index.rename(root / "research-offline.sqlite")
        portable_turns = [
            "Which river flows through Nacre City 0000?", "/quit"]
        portable_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(model_database),
            "--dialogue-state", str(root / "portable-dialogue.json"),
            "--rule-session", str(root / "portable-rule-session.json"),
            "--candidate-session", str(root / "portable-candidate-session.json"),
        ]
        portable = subprocess.run(
            portable_command, input="\n".join(portable_turns) + "\n",
            text=True, capture_output=True, cwd=root, timeout=180, check=False)
        if portable.returncode:
            raise SystemExit(
                f"portable model chat failed ({portable.returncode}):\n"
                f"{portable.stderr}")
        portable_responses = response_chunks(portable.stdout, portable_turns)
        report["portable_model_retrieves_embedded_source"] = (
            "The Serein River 0000 flows through Nacre City 0000."
            in portable_responses[0])
        report["portable_model_gate"] = (
            report["portable_model_documents"] == 1_200
            and report["portable_model_retrieves_embedded_source"])
        report["portable_model_reply"] = portable_responses[0]
        report["unrelated_pending_queue_notices"] = sum(
            "candidate(s) remain pending" in response
            for response in report["pending_state_probe"].values())
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if report["unrelated_pending_queue_notices"]:
            raise SystemExit(
                "existing review-queue counts leaked into question replies")
        print("\nLEARNED CHAT PHASE")
        print(learned.stdout[-5000:])
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("\nCORPUS CHAT REPORT")
        print(json.dumps(report, indent=2))
        print(f"\nPersistent report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
