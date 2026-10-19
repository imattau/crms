"""Small, inspectable ranker for already gate-passing source sentences.

This module is an opt-in pilot. It cannot create evidence or override the
natural-language evidence gate; callers must provide candidates that passed
``gate_passing_candidates``. The normal chat path does not load this model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from crms_nl_gate import _answer_type, _question_mentions, _stem, _tokens


VERSION = 3
WH_TYPES = ("WHO", "WHEN", "WHERE", "MEASURE", "COUNT", "DEF", "NAME")
FEATURE_NAMES = (
    "idf_weighted_question_coverage",
    "question_term_fraction",
    "ordered_proximity",
    "typed_answer_span",
    "named_mention_coverage",
    "log_sentence_length",
    "paragraph_first_sentence",
    "log_candidate_count",
    *(f"wh_type_{kind.casefold()}" for kind in WH_TYPES),
)


def _content_terms(question: str) -> list[str]:
    mentions = {word.casefold() for group in _question_mentions(question)
                for word in group}
    stop = {"a", "an", "the", "of", "in", "on", "at", "to", "for",
            "by", "is", "are", "was", "were", "be", "been", "do", "does",
            "did", "has", "have", "had", "and", "or", "who", "what",
            "when", "where", "why", "which", "how", "many", "much",
            "please", "tell", "me", "name", "about"}
    return [word.casefold() for word in _tokens(question)
            if word.casefold() not in stop | mentions]


def _typed_span(question: str, sentence: str) -> bool:
    kind = _answer_type(question)
    if kind == "WHEN":
        return bool(re.search(r"\b(?:1[0-9]{3}|20[0-9]{2})\b", sentence))
    if kind == "MEASURE":
        return bool(re.search(r"\d[\d,.]*\s*(?:metres?|meters?|km|miles?|feet|ft|"
                              r"inches?|cm|mm|kg|degrees?|years?|seconds?|minutes?|hours?)\b",
                              sentence, re.IGNORECASE))
    if kind == "COUNT":
        return bool(re.search(r"\d|\b(?:zero|one|two|three|four|five|six|seven|"
                              r"eight|nine|ten|eleven|twelve|hundred|thousand)\b",
                              sentence, re.IGNORECASE))
    if kind in {"WHO", "WHERE", "NAME"}:
        mentions = {word.casefold() for group in _question_mentions(question)
                    for word in group}
        return any(token[:1].isupper() and token.casefold() not in mentions
                   and token.casefold() not in {"the", "a", "an"}
                   for token in _tokens(sentence))
    if kind == "DEF":
        return bool(_tokens(sentence))
    return False


def _training_manifest_digest(*, version: int, feature_names: Sequence[str],
                              training_data_sha256: str,
                              training_source_ids: Sequence[str],
                              trained_on: str,
                              training_parameters: Sequence[tuple[str, float]],
                              training_method: str, threshold: float,
                              weights: Sequence[float], bias: float) -> str:
    """Bind model parameters, training provenance, and procedure in one digest."""
    payload = {
        "version": version,
        "feature_names": list(feature_names),
        "training_data_sha256": training_data_sha256,
        "training_source_ids": list(training_source_ids),
        "trained_on": trained_on,
        "training_parameters": dict(training_parameters),
        "training_method": training_method,
        "threshold": threshold,
        "weights": list(weights),
        "bias": bias,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def feature_vector(question: str, candidate: Mapping[str, Any], *,
                   candidate_count: int,
                   candidate_documents: Sequence[str] | None = None
                   ) -> tuple[float, ...]:
    """Compute the named, deterministic 15-feature representation."""
    if type(candidate_count) is not int or candidate_count < 1:
        raise ValueError("candidate_count must be a positive integer")
    sentence = str(candidate.get("text", ""))
    query_terms = _content_terms(question)
    query_stems = [_stem(term) for term in query_terms]
    sentence_words = _tokens(sentence)
    sentence_stems = [_stem(term) for term in sentence_words]
    unique_terms = sorted(set(query_stems))
    docs = candidate_documents or (sentence,)
    document_stems = [{_stem(token) for token in _tokens(text)} for text in docs]
    idfs = {term: math.log(1.0 + len(document_stems) /
                           (1.0 + sum(term in row for row in document_stems)))
            for term in unique_terms}
    matched = {term for term in unique_terms if term in sentence_stems}
    total_idf = sum(idfs.values())
    coverage = sum(idfs[term] for term in matched) / total_idf if total_idf else 0.0
    fraction = len(matched) / len(unique_terms) if unique_terms else 0.0

    proximity = 0.0
    if query_stems and sentence_stems:
        positions: dict[str, list[int]] = {}
        for index, stem in enumerate(sentence_stems):
            positions.setdefault(stem, []).append(index)
        ordered = [stem for stem in query_stems if stem in positions]
        if ordered:
            best_gap = None
            for start in positions[ordered[0]]:
                cursor = start
                for stem in ordered[1:]:
                    following = next((pos for pos in positions[stem]
                                      if pos > cursor), None)
                    if following is None:
                        break
                    cursor = following
                else:
                    gap = cursor - start - len(ordered) + 1
                    best_gap = gap if best_gap is None else min(best_gap, gap)
            if best_gap is not None:
                proximity = 1.0 / (1.0 + max(best_gap, 0))

    mentions = _question_mentions(question)
    mention_hits = 0
    for group in mentions:
        group_stems = {_stem(word) for word in group}
        if group_stems and group_stems <= set(sentence_stems):
            mention_hits += 1
    mention_coverage = mention_hits / len(mentions) if mentions else 1.0
    length = math.log1p(len(sentence_words)) / math.log1p(100.0)
    first_sentence = float(bool(candidate.get("paragraph_first_sentence", False)))
    candidate_log = math.log1p(candidate_count) / math.log1p(15.0)
    kind = _answer_type(question)
    type_flags = tuple(float(kind == value) for value in WH_TYPES)
    features = (coverage, fraction, proximity,
                float(_typed_span(question, sentence)), mention_coverage,
                length, first_sentence, candidate_log,
                *type_flags)
    if len(features) != len(FEATURE_NAMES):
        raise AssertionError("ranker feature schema is inconsistent")
    return tuple(features)


@dataclass(frozen=True)
class SentenceRanker:
    """Versioned logistic model; weights and training provenance are inspectable."""
    weights: tuple[float, ...]
    bias: float
    threshold: float
    training_examples: int
    positive_examples: int
    training_data_sha256: str
    training_manifest_sha256: str
    training_source_ids: tuple[str, ...]
    trained_on: str
    training_parameters: tuple[tuple[str, float], ...]
    training_method: str = "deterministic-batch-logistic-gradient-v1"
    version: int = VERSION

    def __post_init__(self) -> None:
        if self.version != VERSION or len(self.weights) != len(FEATURE_NAMES):
            raise ValueError("unsupported sentence-ranker schema")
        if any(not math.isfinite(value) for value in (*self.weights, self.bias)):
            raise ValueError("ranker parameters must be finite")
        if not 0.0 < self.threshold < 1.0:
            raise ValueError("ranker threshold must be between zero and one")
        if (self.training_examples < 1 or not 1 <= self.positive_examples
                <= self.training_examples):
            raise ValueError("invalid ranker training counts")
        if not re.fullmatch(r"[0-9a-f]{64}", self.training_data_sha256):
            raise ValueError("training data digest must be a SHA-256 hex digest")
        if any(not source.strip() for source in self.training_source_ids):
            raise ValueError("training source IDs must be non-empty")
        if not isinstance(self.trained_on, str):
            raise ValueError("trained_on must be an ISO calendar date")
        try:
            date.fromisoformat(self.trained_on)
        except ValueError:
            raise ValueError("trained_on must be an ISO calendar date")
        if not self.training_source_ids:
            raise ValueError("ranker training needs source provenance")
        if tuple(sorted(set(self.training_source_ids))) != self.training_source_ids:
            raise ValueError("training source IDs must be unique and sorted")
        if tuple(name for name, _value in self.training_parameters) != (
                "iterations", "learning_rate", "l2"):
            raise ValueError("ranker training parameters are incomplete or unordered")
        parameter_values = dict(self.training_parameters)
        if (any(not math.isfinite(value) for value in parameter_values.values())
                or parameter_values["iterations"] < 1
                or parameter_values["learning_rate"] <= 0
                or parameter_values["l2"] < 0):
            raise ValueError("invalid stored training parameters")
        expected_manifest = _training_manifest_digest(
            version=self.version, feature_names=FEATURE_NAMES,
            training_data_sha256=self.training_data_sha256,
            training_source_ids=self.training_source_ids,
            trained_on=self.trained_on,
            training_parameters=self.training_parameters,
            training_method=self.training_method, threshold=self.threshold,
            weights=self.weights, bias=self.bias)
        if self.training_manifest_sha256 != expected_manifest:
            raise ValueError("ranker training manifest digest does not match its record")

    def score(self, features: Sequence[float]) -> float:
        """Return the logistic score; it is not a calibrated probability."""
        if len(features) != len(self.weights):
            raise ValueError("feature vector does not match ranker schema")
        score = self.bias + sum(weight * value
                                for weight, value in zip(self.weights, features))
        if score >= 0:
            return 1.0 / (1.0 + math.exp(-min(score, 700.0)))
        exp_score = math.exp(max(score, -700.0))
        return exp_score / (1.0 + exp_score)

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "feature_names": list(FEATURE_NAMES),
                "weights": list(self.weights), "bias": self.bias,
                "threshold": self.threshold,
                "training_examples": self.training_examples,
                "positive_examples": self.positive_examples,
                "training_data_sha256": self.training_data_sha256,
                "training_manifest_sha256": self.training_manifest_sha256,
                "training_source_ids": list(self.training_source_ids),
                "trained_on": self.trained_on,
                "training_parameters": dict(self.training_parameters),
                "training_method": self.training_method}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SentenceRanker":
        if tuple(value.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError("ranker feature names or order do not match")
        return cls(tuple(float(item) for item in value["weights"]),
                   float(value["bias"]), float(value["threshold"]),
                   int(value["training_examples"]),
                   int(value["positive_examples"]),
                   str(value["training_data_sha256"]),
                   str(value["training_manifest_sha256"]),
                   tuple(str(source) for source in value["training_source_ids"]),
                   str(value["trained_on"]),
                   tuple((str(name), float(item)) for name, item in
                         value["training_parameters"].items()),
                   str(value.get("training_method", "")),
                   int(value.get("version", 0)))


def fit_ranker(rows: Iterable[tuple[Sequence[float], int]], *,
               training_source_ids: Sequence[str], trained_on: str,
               threshold: float = 0.3, iterations: int = 600,
               learning_rate: float = 0.15,
               l2: float = 0.001) -> SentenceRanker:
    """Fit a deterministic logistic ranker from labelled candidate features."""
    raw_data = list(rows)
    if any(type(label) is not int or label not in {0, 1}
           for _features, label in raw_data):
        raise ValueError("training labels must be integer zero or one")
    data = [(tuple(float(value) for value in features), label)
            for features, label in raw_data]
    if not data or any(len(features) != len(FEATURE_NAMES)
                       for features, _label in data):
        raise ValueError(
            f"training rows must contain {len(FEATURE_NAMES)} features and binary labels")
    if (not training_source_ids
            or any(not isinstance(source, str) or not source.strip()
                   for source in training_source_ids)):
        raise ValueError("training source IDs are required")
    positives = sum(label for _, label in data)
    if positives == 0 or positives == len(data):
        raise ValueError("training needs positive and negative candidates")
    if type(iterations) is not int or iterations < 1:
        raise ValueError("iterations must be positive")
    if learning_rate <= 0 or l2 < 0:
        raise ValueError("invalid optimizer parameters")
    weights = [0.0] * len(FEATURE_NAMES)
    bias = math.log(positives / (len(data) - positives))
    for _ in range(iterations):
        grad = [0.0] * len(weights)
        bias_grad = 0.0
        for features, label in data:
            score = bias + sum(weight * value
                               for weight, value in zip(weights, features))
            probability = (1.0 / (1.0 + math.exp(-min(score, 700.0)))
                           if score >= 0 else
                           math.exp(max(score, -700.0)) /
                           (1.0 + math.exp(max(score, -700.0))))
            error = probability - label
            bias_grad += error
            for index, value in enumerate(features):
                grad[index] += error * value
        scale = 1.0 / len(data)
        bias -= learning_rate * bias_grad * scale
        weights = [weight - learning_rate * (grad[index] * scale
                                              + l2 * weight)
                   for index, weight in enumerate(weights)]
    digest_payload = json.dumps(
        [[list(features), label] for features, label in data],
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    data_digest = hashlib.sha256(digest_payload).hexdigest()
    sources = tuple(sorted(set(training_source_ids)))
    parameters = (("iterations", float(iterations)),
                  ("learning_rate", float(learning_rate)),
                  ("l2", float(l2)))
    weight_tuple = tuple(weights)
    manifest_digest = _training_manifest_digest(
        version=VERSION, feature_names=FEATURE_NAMES,
        training_data_sha256=data_digest, training_source_ids=sources,
        trained_on=trained_on, training_parameters=parameters,
        training_method="deterministic-batch-logistic-gradient-v1",
        threshold=threshold, weights=weight_tuple, bias=bias)
    return SentenceRanker(weight_tuple, bias, threshold, len(data), positives,
                          data_digest, manifest_digest, sources, trained_on,
                          parameters)


def _score_candidates(question: str,
                      candidates: Sequence[Mapping[str, Any]],
                      model: SentenceRanker) -> list[dict[str, Any]]:
    texts = [str(row.get("text", "")) for row in candidates]
    scored = []
    for row in candidates:
        features = feature_vector(question, row, candidate_count=len(candidates),
                                  candidate_documents=texts)
        scored.append({**row, "ranker_score": model.score(features),
                       "ranker_features": dict(zip(FEATURE_NAMES, features))})
    scored.sort(key=lambda row: (-row["ranker_score"],
                                 str(row.get("citation", "")),
                                 str(row.get("text", "")).casefold()))
    return scored


def rank_candidates(question: str, candidates: Sequence[Mapping[str, Any]],
                    model: SentenceRanker, *,
                    licensed_predicates: list[dict[str, Any]] | None = None
                    ) -> list[dict[str, Any]]:
    """Filter through the existing evidence gate, then rank its passers."""
    from crms_nl_gate import gate_passing_candidates
    cited = [dict(row) for row in candidates
             if str(row.get("citation", "")).strip()]
    passing = gate_passing_candidates(
        question, cited, licensed_predicates=licensed_predicates)
    return _score_candidates(question, passing, model)


def select_ranked_candidate(question: str,
                            candidates: Sequence[Mapping[str, Any]],
                            model: SentenceRanker, *,
                            licensed_predicates: list[dict[str, Any]] | None = None
                            ) -> dict[str, Any] | None:
    """Gate, then choose the top candidate only above the learned threshold."""
    if not candidates:
        return None
    ranked = rank_candidates(question, candidates, model,
                             licensed_predicates=licensed_predicates)
    return (ranked[0] if ranked
            and ranked[0]["ranker_score"] >= model.threshold else None)


def rank_gated_candidates(question: str, candidates: Sequence[Mapping[str, Any]],
                          model: SentenceRanker, *,
                          licensed_predicates: list[dict[str, Any]] | None = None
                          ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Apply the existing exact gate, then return ranked passers and selection.

    The selected row is ``None`` below the model threshold. A gate rejection or
    unsupported question can therefore never become an answer through ranking.
    """
    ranked = rank_candidates(question, candidates, model,
                             licensed_predicates=licensed_predicates)
    selected = (ranked[0] if ranked
                and ranked[0]["ranker_score"] >= model.threshold else None)
    return ranked, selected
