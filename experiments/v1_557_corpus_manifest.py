"""Contract tests for the tiered corpus manifest.

The manifest is a licence and size inventory, not proof of ingestion. These
checks keep tiers, domain targets, licences, and exclusions internally coherent.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_corpus_manifest import (  # noqa: E402
    DOMAINS, load_manifest, summarize_manifest, validate_manifest,
)

MANIFEST = PROJECT / "corpus" / "manifest_v0.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    payload = load_manifest(MANIFEST)
    errors = validate_manifest(payload)
    require(not errors, "manifest validation failed:\n" + "\n".join(errors))
    summary = summarize_manifest(payload)

    require(summary["total_sources"] == 20,
            f"expected 20 candidate sources, got {summary['total_sources']}")
    require(summary["excluded_sources"] == 4,
            f"expected 4 documented exclusions, got {summary['excluded_sources']}")
    require(50_000_000 <= summary["core_estimated_words"] <= 100_000_000,
            "core estimate is outside the 50M-100M word target: "
            f"{summary['core_estimated_words']}")
    require(set(summary["by_tier"]) == {"core", "extended", "research"},
            "manifest does not cover all three tiers")
    require(summary["by_tier"]["core"]["sources"] >= 8,
            "core tier has too few independent source groups")
    require(sum(payload["domain_targets"].values()) == 100,
            "domain targets do not sum to 100")
    require(set(payload["domain_targets"]) == set(DOMAINS),
            "domain target keys do not match the known domains")
    require(summary["by_status"].get("restricted", 0) == 4,
            "restricted sources are not counted correctly")
    for source in payload["sources"]:
        if source["tier"] == "core":
            require(source["packaged_ok"] is True,
                    f"core source is not packaged: {source['id']}")
            require(source["licence_class"] != "unknown",
                    f"core source has unknown licence: {source['id']}")
        else:
            require(source["packaged_ok"] is False,
                    f"non-core source is packaged: {source['id']}")

    def expect_error(mutator, label: str) -> None:
        broken = copy.deepcopy(payload)
        mutator(broken)
        require(bool(validate_manifest(broken)),
                f"invalid manifest passed validation: {label}")

    expect_error(lambda item: item["domain_targets"].__setitem__(
        "reference", item["domain_targets"]["reference"] + 1),
        "domain targets no longer sum to 100")
    expect_error(lambda item: item["sources"][1].__setitem__(
        "id", item["sources"][0]["id"]), "duplicate source id")
    expect_error(lambda item: item["sources"][0].__setitem__(
        "packaged_ok", False), "core source outside the package")
    expect_error(lambda item: item["sources"][0].__setitem__(
        "licence_class", "unknown"), "unknown core licence")
    expect_error(lambda item: item["sources"][0].pop("estimated_words"),
                 "core source without a word estimate")
    expect_error(lambda item: item["excluded"][0].__setitem__(
        "id", item["sources"][0]["id"]), "excluded/source id collision")

    print("corpus manifest schema, tiers, and licences: PASS")
    print("domain targets sum to 100: PASS")
    print(f"core estimate: {summary['core_estimated_words']:,} words; "
          f"{summary['by_tier']['core']['sources']} source groups")
    print(f"extended known estimate: "
          f"{summary['by_tier']['extended']['known_words']:,} words; "
          f"research sources: {summary['by_tier']['research']['sources']}")
    print("invalid tier, licence, estimate, and id mutations are refused: PASS")


if __name__ == "__main__":
    main()
