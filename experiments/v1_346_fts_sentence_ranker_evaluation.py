"""Evaluate a self-trained sentence ranker on FTS-supplied SimpleWiki evidence.

Training and evaluation questions are generated from disjoint document windows.
The ranker sees only the top FTS result sentences and candidates that pass the
existing quoted-evidence gate. This remains an opt-in benchmark; it never
changes chat or writes to the source index.

Run with:
    python3 experiments/v1_346_fts_sentence_ranker_evaluation.py
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_nl_gate import gate_passing_candidates, gate_quoted_evidence
from crms_research import (
    CRMSSQLiteResearchIndex, SearchHit, _sentence_context_kind,
    _sentence_spans,
)
from crms_sentence_ranker import (
    SentenceRanker, feature_vector, fit_ranker, rank_candidates,
)
from crms_text import tokens as normalized_tokens


_LEADING_SUBJECT = re.compile(
    r"^\s*(?P<subject>(?:The\s+)?[A-Z][\w’'-]*(?:\s+[A-Z][\w’'-]*){0,4})"
    r"\s+(?P<verb>[a-z][\w’'-]{1,18})\s+(?P<rest>[^.!?]{2,180})[.!?]?$"
)
_SKIP_SUBJECTS = {"it", "this", "that", "these", "those", "he", "she",
                  "they", "we", "i", "there", "the", "a", "an"}
_SKIP_VERBS = {"is", "are", "was", "were", "has", "have", "had", "be",
               "been", "being", "seems", "became"}
_DROP_WORDS = {"a", "an", "the", "and", "or", "but", "of", "in", "on",
               "at", "to", "for", "by", "with", "from", "as", "that",
               "which", "who", "whom", "whose", "this", "these", "those"}


def _question_and_answer(sentence: str) -> tuple[str, str] | None:
    match = _LEADING_SUBJECT.fullmatch(sentence.strip())
    if match is None:
        return None
    subject = match.group("subject").strip()
    answer = re.sub(r"^The\s+", "", subject, flags=re.IGNORECASE)
    answer_tokens = normalized_tokens(answer)
    if (not answer_tokens or answer.casefold() in _SKIP_SUBJECTS
            or answer_tokens[0] in _SKIP_SUBJECTS):
        return None
    verb = match.group("verb")
    if verb.casefold() in _SKIP_VERBS:
        return None
    rest = match.group("rest").strip()
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9’'-]*", rest)
    # Keep the relation cue and a deterministic partial set of object words.
    # The target subject is absent, making it a self-generated WHO cloze.
    kept = [word for index, word in enumerate(words)
            if word.casefold() not in _DROP_WORDS and (index % 3 != 1)]
    if not kept:
        kept = words[:]
    question = f"Who {verb} {' '.join(kept)}?"
    return question, answer


def _phrase_present(answer: str, sentence: str) -> bool:
    answer_tokens = normalized_tokens(answer)
    sentence_tokens = normalized_tokens(sentence)
    if not answer_tokens or len(answer_tokens) > len(sentence_tokens):
        return False
    width = len(answer_tokens)
    return any(sentence_tokens[index:index + width] == answer_tokens
               for index in range(len(sentence_tokens) - width + 1))


def _paragraph_first(document_text: str, sentence_start: int) -> bool:
    previous_break = max(document_text.rfind("\n\n", 0, sentence_start),
                         document_text.rfind("\f", 0, sentence_start))
    prefix = document_text[previous_break + 1:sentence_start]
    return not any(sentence.strip() for sentence in re.split(r"[.!?]+", prefix))


def _fts_candidates(index: CRMSSQLiteResearchIndex, question: str,
                    *, limit: int = 12,
                    excluded_source_ids: set[str] | None = None
                    ) -> list[dict[str, object]]:
    found: dict[tuple[str, str], dict[str, object]] = {}
    fts_limit = 100 if excluded_source_ids else limit
    selected_documents = set()
    for hit in index.search(question, limit=fts_limit, context_chars=520):
        if excluded_source_ids and hit.document_id in excluded_source_ids:
            continue
        if hit.document_id not in selected_documents:
            if len(selected_documents) >= limit:
                break
            selected_documents.add(hit.document_id)
        document = index.verify_hit(hit)
        for local_start, local_end in _sentence_spans(hit.snippet):
            start, end = hit.start + local_start, hit.start + local_end
            sentence = document.text[start:end]
            if _sentence_context_kind(sentence, document.text, start) != "assertion":
                continue
            sentence_hit = SearchHit(
                hit.document_id, hit.title, hit.location, hit.score, sentence,
                start, end, hit.matched_terms)
            row = {
                "text": sentence,
                "citation": index.citation(sentence_hit),
                "document_id": hit.document_id,
                "title": hit.title,
                "paragraph_first_sentence": _paragraph_first(document.text, start),
                "fts_score": hit.score,
            }
            found.setdefault((hit.document_id, sentence.casefold()), row)
    return list(found.values())


def _examples_from_window(index: CRMSSQLiteResearchIndex, *, offset: int,
                          max_docs: int, max_examples: int,
                          excluded_candidate_source_ids: set[str] | None = None
                          ) -> list[dict[str, object]]:
    examples = []
    for document_id, _title, location in index.source_list(
            limit=max_docs, offset=offset):
        if location and location.casefold().endswith((".py", ".js", ".java", ".c",
                                                     ".cpp", ".rs", ".go", ".sql")):
            continue
        document = index.document(document_id)
        for start, end in _sentence_spans(document.text):
            sentence = document.text[start:end]
            if len(sentence) > 360 or _sentence_context_kind(
                    sentence, document.text, start) != "assertion":
                continue
            generated = _question_and_answer(sentence)
            if generated is None:
                continue
            question, answer = generated
            if len(normalized_tokens(question)) < 4:
                continue
            candidates = _fts_candidates(
                index, question,
                excluded_source_ids=excluded_candidate_source_ids)
            if not candidates:
                continue
            passing = gate_passing_candidates(question, candidates)
            if not any(_phrase_present(answer, str(row["text"]))
                       for row in passing):
                continue
            examples.append({
                "question": question,
                "answer": answer,
                "target_sentence": sentence,
                "target_source": document_id,
                "candidates": passing,
            })
            if len(examples) >= max_examples:
                return examples
    return examples


def _training_rows(examples: list[dict[str, object]]):
    rows = []
    sources = set()
    for example in examples:
        candidates = example["candidates"]
        if len(candidates) < 2:
            continue
        texts = [str(row["text"]) for row in candidates]
        positives = 0
        example_rows = []
        for candidate in candidates:
            label = int(_phrase_present(
                str(example["answer"]), str(candidate["text"])))
            positives += label
            features = feature_vector(
                str(example["question"]), candidate,
                candidate_count=len(candidates), candidate_documents=texts)
            example_rows.append((features, label, str(candidate["document_id"])))
        if positives == 0 or positives == len(candidates):
            continue
        rows.extend((features, label) for features, label, _source in example_rows)
        sources.add(str(example["target_source"]))
        sources.update(source for _features, _label, source in example_rows)
    return rows, tuple(sorted(sources))


def _evaluate(index: CRMSSQLiteResearchIndex,
              examples: list[dict[str, object]], model: SentenceRanker
              ) -> dict[str, object]:
    counts = Counter()
    error_samples = []
    latencies = []
    gate_latencies = []
    for example in examples:
        candidates = example["candidates"]
        answer = str(example["answer"])
        question = str(example["question"])
        counts["total_questions"] += 1
        if len(candidates) < 2:
            counts["fewer_than_two_gate_candidates"] += 1
        else:
            counts["eligible_questions"] += 1
        baseline_start = time.perf_counter()
        baseline = gate_quoted_evidence(question, candidates)
        baseline_seconds = time.perf_counter() - baseline_start
        gate_latencies.append(baseline_seconds)
        if baseline["status"] != "accepted":
            counts["gate_abstained_or_ambiguous"] += 1
            if len(candidates) >= 2:
                counts["gate_multi_abstained_or_ambiguous"] += 1
        elif _phrase_present(answer, str(baseline["evidence"]["text"])):
            counts["gate_correct"] += 1
            if len(candidates) >= 2:
                counts["gate_multi_correct"] += 1
        else:
            counts["gate_wrong"] += 1
            if len(candidates) >= 2:
                counts["gate_multi_wrong"] += 1
        rank_start = time.perf_counter()
        ranked = rank_candidates(question, candidates, model)
        rank_seconds = time.perf_counter() - rank_start
        latencies.append(rank_seconds)

        selected = (ranked[0] if ranked and ranked[0]["ranker_score"]
                    >= model.threshold else None)
        if selected is None:
            counts["ranker_abstained"] += 1
            if len(candidates) >= 2:
                counts["ranker_multi_abstained"] += 1
            continue
        if _phrase_present(answer, str(selected["text"])):
            counts["ranker_correct"] += 1
            if len(candidates) >= 2:
                counts["ranker_multi_correct"] += 1
        else:
            counts["ranker_wrong"] += 1
            if len(candidates) >= 2:
                counts["ranker_multi_wrong"] += 1
            if len(error_samples) < 8:
                error_samples.append({
                    "question": question,
                    "gold_answer": answer,
                    "selected_sentence": selected["text"],
                    "citation": selected["citation"],
                    "score": selected["ranker_score"],
                    "source": selected["document_id"],
                })

        target_source = str(example["target_source"])
        other_sources = [row for row in candidates
                         if str(row["document_id"]) != target_source]
        if other_sources:
            wrong_article = rank_candidates(question, other_sources, model)
            wrong_choice = (wrong_article[0]
                            if wrong_article and wrong_article[0]["ranker_score"]
                            >= model.threshold else None)
            if wrong_choice is not None:
                if _phrase_present(answer, str(wrong_choice["text"])):
                    counts["other_source_corroborated"] += 1
                else:
                    counts["other_source_wrong_answer"] += 1
            else:
                counts["other_source_abstained"] += 1
        else:
            counts["no_other_source_candidate"] += 1

    denominator = counts["eligible_questions"]
    answered = counts["ranker_correct"] + counts["ranker_wrong"]
    multi_answered = (counts["ranker_multi_correct"]
                      + counts["ranker_multi_wrong"])
    gate_multi_answered = (counts["gate_multi_correct"]
                           + counts["gate_multi_wrong"])
    all_questions = counts["total_questions"]
    gate_answered = counts["gate_correct"] + counts["gate_wrong"]
    return {
        "counts": dict(sorted(counts.items())),
        "ranker_answer_precision": (counts["ranker_correct"] / answered
                                    if answered else None),
        "ranker_coverage_all_test_questions": (
            answered / all_questions if all_questions else None),
        "ranker_coverage_on_multi_candidate_questions": (
            multi_answered / denominator if denominator else None),
        "ranker_precision_on_multi_candidate_questions": (
            counts["ranker_multi_correct"] / multi_answered
            if multi_answered else None),
        "gate_coverage_on_multi_candidate_questions": (
            gate_multi_answered / denominator if denominator else None),
        "gate_precision_on_multi_candidate_questions": (
            counts["gate_multi_correct"] / gate_multi_answered
            if gate_multi_answered else None),
        "gate_coverage_all_test_questions": (
            gate_answered / all_questions if all_questions else None),
        "gate_answer_precision": (
            counts["gate_correct"] /
            (counts["gate_correct"] + counts["gate_wrong"])
            if counts["gate_correct"] + counts["gate_wrong"] else None),
        "median_ranker_milliseconds": (
            sorted(latencies)[len(latencies) // 2] * 1000
            if latencies else None),
        "median_gate_milliseconds": (
            sorted(gate_latencies)[len(gate_latencies) // 2] * 1000
            if gate_latencies else None),
        "ranker_wrong_examples": error_samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path,
                        default=PROJECT / "data/crms_simplewiki_research.sqlite")
    parser.add_argument("--train-offset", type=int, default=20_000)
    parser.add_argument("--test-offset", type=int, default=220_000)
    parser.add_argument("--docs-per-window", type=int, default=600)
    parser.add_argument("--train-examples", type=int, default=120)
    parser.add_argument("--test-examples", type=int, default=120)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if args.train_offset == args.test_offset:
        parser.error("train and test windows must be disjoint")

    index = CRMSSQLiteResearchIndex(args.index, read_only=True)
    try:
        started = time.perf_counter()
        training_doc_ids = {
            document_id for document_id, _title, _location
            in index.source_list(limit=args.docs_per_window,
                                 offset=args.train_offset)}
        test_doc_ids = {
            document_id for document_id, _title, _location
            in index.source_list(limit=args.docs_per_window,
                                 offset=args.test_offset)}
        if training_doc_ids & test_doc_ids:
            raise SystemExit("training and test source windows overlap")
        train = _examples_from_window(
            index, offset=args.train_offset, max_docs=args.docs_per_window,
            max_examples=args.train_examples,
            excluded_candidate_source_ids=test_doc_ids)
        test = _examples_from_window(
            index, offset=args.test_offset, max_docs=args.docs_per_window,
            max_examples=args.test_examples)
        training_rows, training_sources = _training_rows(train)
        if set(training_sources) & test_doc_ids:
            raise SystemExit("training candidates leaked into the test source window")
        if not training_rows or not test:
            raise SystemExit(
                f"insufficient FTS/gate examples: train={len(train)}, "
                f"rows={len(training_rows)}, test={len(test)}")
        model = fit_ranker(
            training_rows, training_source_ids=training_sources,
            trained_on=date.today().isoformat(), threshold=0.3)
        evaluation = _evaluate(index, test, model)
        result = {
            "benchmark": "crms-sentence-ranker-fts-self-cloze-v1",
            "index": str(args.index),
            "index_documents": index.document_count(),
            "train_window": {"offset": args.train_offset,
                             "documents": args.docs_per_window,
                             "document_ids_sha256": hashlib.sha256(
                                 "\n".join(sorted(training_doc_ids)).encode()
                             ).hexdigest()},
            "test_window": {"offset": args.test_offset,
                            "documents": args.docs_per_window,
                            "document_ids_sha256": hashlib.sha256(
                                "\n".join(sorted(test_doc_ids)).encode()
                            ).hexdigest()},
            "train_questions": len(train),
            "train_candidate_rows": len(training_rows),
            "train_positive_rows": model.positive_examples,
            "training_source_count": len(training_sources),
            "test_questions": len(test),
            "threshold": model.threshold,
            "model": model.as_dict(),
            "evaluation": evaluation,
            "elapsed_seconds": time.perf_counter() - started,
            "limitations": [
                "Self-generated WHO questions from leading-subject sentences only.",
                "The answer-span labels are weak labels from the source sentence.",
                "Question source windows are disjoint; test-window documents are excluded from training candidates.",
                "Only gate-passing FTS candidates are ranked; production chat is unchanged.",
            ],
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
    finally:
        index.close()


if __name__ == "__main__":
    main()
