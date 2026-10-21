"""Phase 8 contract: read-only release, integrity, lineage, corrections."""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_model import CRMSModel  # noqa: E402
from crms_package import export_model_database  # noqa: E402
from crms_phase8_model import (  # noqa: E402
    build_release, open_release,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


LICENCE = {
    "document_id": "doc:1", "title": "Fixture", "source": "contract",
    "licence": "CC0 1.0", "licence_class": "public-domain",
    "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "attribution": "Contract fixture", "retrieved_at": "2026-10-21",
    "revision": "contract-v1", "body_sha256": "a" * 64,
}
DEPENDENCIES = [
    {"id": "source:doc:1", "kind": "source", "trust": "source-reviewed",
     "state": "active", "payload": {"title": "Fixture"}},
    {"id": "fact:value", "kind": "fact", "trust": "source-reviewed",
     "state": "active", "payload": {"value": 7}},
    {"id": "derived:total", "kind": "derived", "trust": "derived",
     "state": "active", "payload": {"total": 7}},
]
EDGES = [
    {"target": "fact:value", "source": "source:doc:1",
     "relation": "supports"},
    {"target": "derived:total", "source": "fact:value",
     "relation": "derived_from"},
]
CORRECTIONS = [{
    "correction_id": "correction:1", "trigger": "fact:value",
    "reason": "contract correction", "affected": [
        "fact:value", "derived:total"], "retained": [],
}]


def make_model(root: Path) -> Path:
    knowledge = root / "knowledge.json"
    rules = root / "rules.json"
    CRMSKnowledgeBase().save(knowledge)
    CRMSModel().save(rules)
    model = root / "model.sqlite"
    export_model_database(model, knowledge=knowledge, rules=rules)
    return model


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-phase8-contract-") as temporary:
        root = Path(temporary)
        model = make_model(root)
        release_path = root / "release"
        info = build_release(
            release_path, model_db=model, licences=[LICENCE],
            dependencies=DEPENDENCIES, dependency_edges=EDGES,
            corrections=CORRECTIONS)
        require(info["format"] == "crms-phase8-release",
                "release format is wrong")
        require(info["model_schema"] == 4, "model schema is not v4")
        require(info["read_only"] is True, "release is not read-only")
        require(info["licences"]["coverage"] == 1.0,
                "licence coverage is incomplete")
        require(info["dependencies"]["nodes"] == 3,
                "dependency nodes were not stored")
        require(info["dependencies"]["edges"] == 2,
                "dependency edges were not stored")
        require(info["corrections"] == 1, "correction was not stored")

        release = open_release(release_path)
        try:
            require(release.verify()["valid"], "release failed verification")
            lineage = release.lineage("derived:total")
            require(lineage["node"]["kind"] == "derived",
                    "lineage node kind is wrong")
            require([edge["source"] for edge in lineage["inputs"]]
                    == ["fact:value"], "lineage inputs are wrong")
            require(release.corrections()[0]["reason"]
                    == "contract correction", "correction history is wrong")
            require(release.evidence("doc:1")[0]["licence"] == "CC0 1.0",
                    "evidence record is wrong")
            try:
                release.phase8.execute(
                    "INSERT INTO corrections(correction_id,trigger,reason,"
                    "affected_json,retained_json,at) VALUES('x','x','x','[]','[]','x')")
            except sqlite3.OperationalError:
                pass
            else:
                raise SystemExit("read-only release accepted a write")
        finally:
            release.close()

        # Tampered model bytes must fail closed.
        tampered = root / "tampered"
        shutil.copytree(release_path, tampered)
        model_path = tampered / "model.sqlite"
        model_path.write_bytes(model_path.read_bytes() + b"x")
        try:
            open_release(tampered)
        except ValueError:
            pass
        else:
            raise SystemExit("tampered release passed verification")

        # Missing licence fields are rejected before publication.
        try:
            build_release(
                root / "bad-release", model_db=model,
                licences=[{key: value for key, value in LICENCE.items()
                           if key != "body_sha256"}])
        except ValueError:
            pass
        else:
            raise SystemExit("incomplete licence record was accepted")

    print("Phase 8 release schema, digests, and compatibility: PASS")
    print("read-only metadata, model, and tamper rejection: PASS")
    print("licence coverage, evidence, lineage, and corrections: PASS")
    print("Phase 8 model contract: PASS")


if __name__ == "__main__":
    main()
