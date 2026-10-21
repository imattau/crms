"""Phase 3 document-learning contract: proposal-only extraction through review."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_document_learning import (  # noqa: E402
    DocumentManifest, ReviewQueue, apply_gate, extract_corpus_claims,
    load_corpus, phase3_metrics, promote_accepted,
    propose_claims_to_registry, review_with_frozen_oracle,
)
from crms_research import CRMSResearchIndex  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402

CORPUS = PROJECT / "corpus" / "phase3_eval" / "manifest.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    corpus = load_corpus(CORPUS)
    require(len(corpus.documents) == 7, "expected seven complete documents")
    require(len(corpus.publishers) == 4, "expected four publishers")
    require({document.genre for document in corpus.documents}
            == {"technical-reference", "prose"},
            "expected technical and prose genres")
    require(len(corpus.labels) == 16 and len(corpus.controls) == 7,
            "frozen labels/controls changed")

    # A manifest hash mismatch or an unapproved licence must fail closed.
    first = corpus.documents[0]
    try:
        DocumentManifest(**{**first.__dict__, "sha256": "0" * 64}).validate(
            root=corpus.root)
    except ValueError:
        pass
    else:
        raise SystemExit("tampered document hash was accepted")
    try:
        DocumentManifest(**{**first.__dict__, "licence_class": "unknown"}).validate(
            root=corpus.root)
    except ValueError:
        pass
    else:
        raise SystemExit("unapproved licence class was accepted")

    claims = extract_corpus_claims(corpus)
    eligible = [claim for claim in claims if claim.proposal_eligible]
    require(len(claims) == 20 and len(eligible) == 16,
            f"unexpected extraction counts: {len(claims)}/{len(eligible)}")
    require(any(claim.antecedent == "Mira"
                and claim.subject == "Mira"
                and claim.object == "the Lantern Archive"
                for claim in claims),
            "pronoun antecedent was not preserved")
    require(any(claim.conditions == ("before: If the input is empty",)
                for claim in claims),
            "condition scope was not preserved")
    require(any("table_row" in dict(claim.roles) for claim in claims),
            "structured table roles were not preserved")
    require(all(not claim.proposal_eligible
                for claim in claims
                if claim.status in {"negated", "quoted", "uncertain",
                                    "attributed", "denied"}),
            "a non-asserted control became proposal-eligible")

    with tempfile.TemporaryDirectory(prefix="crms-phase3-") as folder:
        root = Path(folder)
        registry = RuleRegistry()
        proposed = propose_claims_to_registry(claims, registry)
        require(len(proposed) == 16, "not every eligible claim was proposed")
        require(not registry.records(state="active"),
                "a document claim activated before review")

        queue = ReviewQueue(root / "review.sqlite")
        try:
            require(queue.add(claims) == 16, "review queue lost claims")
            require(len(queue.pending()) == 16, "pending queue is wrong")
            review_with_frozen_oracle(queue, corpus)
            metrics = queue.metrics()
            require(metrics["accepted"] == 15 and metrics["rejected"] == 1,
                    f"review decisions are wrong: {metrics}")
            require(abs(metrics["precision"] - 15 / 16) < 1e-9,
                    "precision is not measured over reviewed proposals")
            require(metrics["false_positive_taxonomy"] == {"wrong_role": 1},
                    f"false-positive taxonomy is wrong: {metrics}")
            require(metrics["review_minutes_per_claim"] < 2.0,
                    "review time exceeds the gate")
            promotion = promote_accepted(queue, registry)
            require(promotion["active_phase3_rules"] == 15,
                    f"promotion did not activate accepted rules: {promotion}")
            retired = [record for record in registry.records(state="retired")
                       if record.id.startswith("phase3-")]
            require(len(retired) == 1
                    and retired[0].payload["object"] == "Guido van Rossum",
                    "rejected wrong-role proposal was not retired")
        finally:
            queue.close()

        # The ledger and registry survive reload.
        queue = ReviewQueue(root / "review.sqlite")
        try:
            require(queue.metrics()["reviewed"] == 16,
                    "review ledger did not persist")
        finally:
            queue.close()
        registry.save(root / "registry.sqlite")
        reloaded = RuleRegistry.load(root / "registry.sqlite")
        require(len(reloaded.records(state="active")) == 15,
                "active rules did not survive reload")

        index = CRMSResearchIndex()
        for document in corpus.documents:
            index.add_document(
                document.id, document.title, document.text, document.url)
        reopened = _Reopened(root / "review.sqlite")
        try:
            metrics = phase3_metrics(
                corpus, reopened, reloaded, claims,
                learning_publisher="northwind-docs", index=index)
            metrics = apply_gate(metrics)
        finally:
            reopened.close()
        require(metrics["gate_passed"], f"Phase 3 gate failed: {metrics['gate']}")
        require(metrics["transfer"]["coverage"] == 1.0
                and metrics["transfer"]["heldout_labels"] == 4,
                f"second-publisher transfer is wrong: {metrics['transfer']}")
        require(metrics["retention"]["retention"] == 1.0
                and metrics["retention"]["citations_resolved"] == 15,
                f"retention after 100 documents failed: {metrics['retention']}")
        require(metrics["proposal_to_active"] == 1.0,
                "proposal-to-active conversion is wrong")

    print("licence and hash audit fails closed: PASS")
    print("clause, condition, antecedent, table, and control boundaries: PASS")
    print("all eligible candidates enter the registry as proposed/inert: PASS")
    print("frozen review raises precision and a wrong-role proposal is retired: PASS")
    print("second-publisher transfer and 100-document retention: PASS")
    print("Phase 3 document-learning gate: PASS")


class _Reopened:
    """Small context wrapper so the metrics call cannot close the ledger."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.queue = ReviewQueue(path)

    def metrics(self):
        return self.queue.metrics()

    def accepted(self):
        return self.queue.accepted()

    def reviewed(self):
        return self.queue.reviewed()

    def close(self) -> None:
        self.queue.close()


if __name__ == "__main__":
    main()
