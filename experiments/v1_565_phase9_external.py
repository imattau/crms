"""Phase 9 contract: frozen fixture, licence inventory, comparison, raters."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "corpus" / "phase9_eval" / "fixture.json"
REPORT = PROJECT / "experiments" / "reports" / "phase9_external.json"
PACKET = PROJECT / "experiments" / "reports" / "phase9_rater_packet.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(FIXTURE.is_file(), "missing Phase 9 fixture")
    require(REPORT.is_file(), "missing Phase 9 report")
    require(PACKET.is_file(), "missing Phase 9 rater packet")
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    sidecar = FIXTURE.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
    require(digest == sidecar, "Phase 9 fixture digest does not match")

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    require(fixture["format"] == "crms-phase9-eval", "wrong fixture format")
    require(len(fixture["supported_tasks"]) == 35,
            "supported subset is not 35 tasks")
    require(len(fixture["breadth_tasks"]) == 12,
            "breadth split is not 12 tasks")
    require(len(fixture["comparison_probes"]) == 10,
            "comparison split is not 10 probes")
    require("authoring" in fixture, "missing independent-author metadata")
    require(fixture["authoring"]["breadth_model"],
            "missing breadth author model")

    source_dir = FIXTURE.parent / fixture["source_dir"]
    referenced = set()
    for group in ("supported_tasks", "breadth_tasks"):
        for task in fixture[group]:
            referenced.update(task.get("documents", ()))
    for probe in fixture["comparison_probes"]:
        referenced.update(probe.get("sources", ()))
    for name in sorted(referenced):
        require((source_dir / name).is_file(), f"missing source: {name}")

    inventory = json.loads(
        (FIXTURE.parent / "licence_inventory.json").read_text(encoding="utf-8"))
    require(len(inventory["documents"]) == 10,
            "licence inventory is not 10 documents")
    by_name = {row["path"]: row for row in inventory["documents"]}
    for name, row in by_name.items():
        path = source_dir / name
        require(path.is_file(), f"licence document missing: {name}")
        require(row["licence_class"] in {
            "public-domain", "permissive", "share-alike"},
            f"bad licence class for {name}")
        require(row["body_sha256"]
                == hashlib.sha256(path.read_bytes()).hexdigest(),
                f"licence digest mismatch: {name}")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    require(report["gate_passed"] is True, "bounded Phase 9 gate did not pass")
    require(report["external_human_gate_passed"] is False,
            "human gate must remain open for automated raters")
    require(report["full_section2_gate_passed"] is False,
            "full section 2 must not be claimed")
    supported = report["scorecard"]["supported"]
    breadth = report["scorecard"]["breadth"]
    require(supported["passed"] == 35 and supported["tasks"] == 35,
            "supported result is not 35/35")
    require(supported["unsafe_answers"] == 0,
            "supported subset has an unsafe answer")
    require(breadth["tasks"] == 12 and breadth["passed"] == 0,
            "breadth failures were not published as 0/12")
    require(report["rater_agreement"]["available"] is True,
            "rater agreement is not available")
    require(report["comparison"]["baseline"]["class"],
            "comparison baseline class is missing")
    require(len(report["comparison"]["systems"]) == 2,
            "comparison did not rate both systems")
    require(report["section2"]["met"] is False,
            "section 2 must remain open")

    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    require(len(packet["items"]) == 10, "rater packet is not 10 items")
    for item in packet["items"]:
        require(item["response_a"].strip(), "missing response A")
        require(item["response_b"].strip(), "missing response B")
        require("sources" in item, "rater packet item has no source context")

    for name in ("docs/design_phase9_external.md",
                 "docs/phase9_failure_taxonomy.md",
                 "docs/phase9_limitations.md",
                 "docs/phase9_licence_inventory.md",
                 "docs/phase9_rater_protocol.md",
                 "docs/phase9_scorecard.md"):
        require((PROJECT / name).is_file(), f"missing publication: {name}")

    print("Phase 9 frozen fixture and licence inventory: PASS")
    print("supported 35/35, breadth 0/12 published: PASS")
    print("two automated raters, agreement, and comparison: PASS")
    print("human and full section 2 gates correctly left open: PASS")
    print("Phase 9 external-validation contract: PASS")


if __name__ == "__main__":
    main()
