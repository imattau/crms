"""Check rule validation label coverage and noisy-counterexample tolerance."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_inference import discover_rule_candidates, validate_rule_candidate
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def fact(subject: str, relation: str, obj: str, source: str,
         polarity: str = "positive") -> dict:
    return {"subject": subject, "relation": relation, "object": obj,
            "sources": [source], "qualifiers": (), "polarity": polarity}


def add_chain(rows: list[dict], number: int, label: str | None,
              index: CRMSResearchIndex) -> None:
    subject, middle, target = f"A{number}", f"M{number}", f"Z{number}"
    text = f"{subject} is parent of {middle}. {middle} is parent of {target}."
    if label == "positive":
        text += f" {subject} is ancestor of {target}."
    elif label == "negative":
        text += f" {subject} is not ancestor of {target}."
    document = f"validation-case-{number}"
    index.add_document(document, document, text,
                       f"https://publisher-{number}.example/case")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source = f"{document}#sha256={digest}&chars=0:{len(text)}"
    rows.append(fact(subject, "parent", middle, source))
    rows.append(fact(middle, "parent", target, source))
    if label == "positive":
        rows.append(fact(subject, "ancestor", target, source))
    elif label == "negative":
        rows.append(fact(subject, "ancestor", target, source, "negative"))


def candidate_for(training_positive: list[dict],
                  training_negative: list[dict], index: CRMSResearchIndex):
    result = discover_rule_candidates(
        training_positive, negative_facts=training_negative, min_support=2,
        research_index=index)
    return next(candidate for candidate in result.candidates
                if (candidate.first_relation, candidate.second_relation,
                    candidate.conclusion_relation)
                == ("parent", "parent", "ancestor"))


def validate(candidate, training_positive, training_negative,
             validation_positive, validation_negative, *, index):
    return validate_rule_candidate(
        candidate, training_facts=training_positive,
        training_negative_facts=training_negative,
        validation_facts=validation_positive,
        validation_negative_facts=validation_negative,
        research_index=index)


def main() -> None:
    index = CRMSResearchIndex()
    training_positive: list[dict] = []
    for number in range(4):
        add_chain(training_positive, number, "positive", index)
    candidate = candidate_for(training_positive, [], index)

    sparse_holdout: list[dict] = []
    for number in range(100, 600):
        add_chain(sparse_holdout, number,
                  "positive" if number in {100, 101} else None, index)
    sparse = validate(candidate, training_positive, [], sparse_holdout, [],
                      index=index)
    require(sparse.status == "low-coverage"
            and sparse.unknown_endpoint_pairs == 498
            and sparse.label_coverage is not None
            and sparse.label_coverage < 0.01,
            f"sparse labels did not block validation: {sparse}")

    noisy_training = list(training_positive)
    add_chain(noisy_training, 4, "negative", index)
    noisy_candidate = candidate_for(
        [row for row in noisy_training if row["polarity"] != "negative"],
        [row for row in noisy_training if row["polarity"] == "negative"], index)
    noisy_holdout: list[dict] = []
    for number in range(700, 712):
        label = ("negative" if number == 700 else
                 None if number == 711 else "positive")
        add_chain(noisy_holdout, number, label, index)
    tolerated = validate(
        noisy_candidate,
        [row for row in noisy_training if row["polarity"] != "negative"],
        [row for row in noisy_training if row["polarity"] == "negative"],
        [row for row in noisy_holdout if row["polarity"] != "negative"],
        [row for row in noisy_holdout if row["polarity"] == "negative"],
        index=index)
    require(tolerated.status == "validated"
            and tolerated.negative_examples
            and tolerated.precision_lower_bound is not None
            and tolerated.precision_lower_bound >= 0.25
            and tolerated.training_precision_lower_bound is not None
            and tolerated.training_precision_lower_bound >= 0.25,
            f"strong support did not tolerate isolated counterevidence: {tolerated}")

    weak_holdout: list[dict] = []
    for number in range(800, 804):
        add_chain(weak_holdout, number,
                  "positive" if number < 802 else "negative", index)
    weak = validate(
        candidate, training_positive, [],
        [row for row in weak_holdout if row["polarity"] != "negative"],
        [row for row in weak_holdout if row["polarity"] == "negative"],
        index=index)
    require(weak.status == "low-confidence"
            and weak.precision_lower_bound is not None
            and weak.precision_lower_bound < 0.25,
            f"balanced positive and negative evidence was over-trusted: {weak}")

    print("sparse holdout coverage, Wilson precision bound, and noisy "
          "counterexample tolerance: PASS")


if __name__ == "__main__":
    main()
