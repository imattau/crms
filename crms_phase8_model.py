"""Phase 8 portable release: model, licence manifest, lineage, corrections.

A release is a directory:

```text
phase8_release/
  model.sqlite      chat-compatible learned model and embedded sources
  phase8.sqlite     licences, dependency graph, registry, corrections, integrity
  release.json      format, compatibility, file digests, counts
```

The chat CLI loads ``model.sqlite`` with ``--model-db``. The release layer is
read-only: verification, lineage, corrections, and licence evidence never write
to the release. Learning continues in the chat's neighboring sidecar and can be
repacked into a new release with ``crms_package.py repack``.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from crms_package import (
    inspect_model_database, model_database_has_research,
    model_database_research_stats,
)

FORMAT = "crms-phase8-release"
VERSION = 1
MODEL_SCHEMA_VERSION = 4
MODEL_FILE = "model.sqlite"
PHASE8_FILE = "phase8.sqlite"
RELEASE_FILE = "release.json"
COMPATIBILITY = (
    "crms-learned-model 1",
    "crms-learned-model 2",
    "crms-learned-model 3",
    "crms-learned-model 4",
    "crms-learned-model 5",
)

_PHASE8_SCHEMA = """
CREATE TABLE release_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE licences (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    licence TEXT NOT NULL,
    licence_class TEXT NOT NULL,
    licence_url TEXT NOT NULL,
    attribution TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    revision TEXT NOT NULL,
    body_sha256 TEXT NOT NULL
);
CREATE TABLE dependencies (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    trust TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE dependency_edges (
    target TEXT NOT NULL,
    source TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY(target, source, relation)
);
CREATE TABLE registry_rules (
    id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE registry_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    action TEXT NOT NULL,
    at TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    before_json TEXT
);
CREATE TABLE corrections (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id TEXT NOT NULL UNIQUE,
    trigger TEXT NOT NULL,
    reason TEXT NOT NULL,
    affected_json TEXT NOT NULL,
    retained_json TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE integrity (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    role TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while batch := stream.read(1024 * 1024):
            digest.update(batch)
    return digest.hexdigest()


def _coverage(licences: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    allowed = frozenset({"public-domain", "permissive", "share-alike"})
    by_class: dict[str, int] = {}
    complete = 0
    for row in licences:
        licence_class = str(row.get("licence_class", "unknown"))
        by_class[licence_class] = by_class.get(licence_class, 0) + 1
        if (licence_class in allowed
                and str(row.get("licence", "")).strip()
                and str(row.get("attribution", "")).strip()
                and str(row.get("licence_url", "")).strip()
                and str(row.get("retrieved_at", "")).strip()
                and str(row.get("revision", "")).strip()):
            complete += 1
    total = len(licences)
    return {
        "documents": total,
        "complete_documents": complete,
        "coverage": complete / total if total else 0.0,
        "by_class": dict(sorted(by_class.items())),
    }


def build_release(output: str | Path, *, model_db: str | Path,
                  licences: Iterable[Mapping[str, Any]],
                  dependencies: Iterable[Mapping[str, Any]] = (),
                  dependency_edges: Iterable[Mapping[str, Any]] = (),
                  registry_db: str | Path | None = None,
                  corrections: Iterable[Mapping[str, Any]] = (),
                  replace: bool = False) -> dict[str, Any]:
    """Publish a validated, read-only Phase 8 release directory."""
    destination = Path(output).expanduser().resolve()
    source_model = Path(model_db).expanduser().resolve()
    if not source_model.is_file():
        raise FileNotFoundError(f"model database does not exist: {source_model}")
    if destination.exists() and not replace:
        raise FileExistsError(f"release directory already exists: {destination}")
    if destination.exists():
        shutil.rmtree(destination)

    licence_rows = [dict(row) for row in licences]
    allowed_classes = {"public-domain", "permissive", "share-alike"}
    for row in licence_rows:
        for field in ("document_id", "title", "source", "licence",
                      "licence_class", "licence_url", "attribution",
                      "retrieved_at", "revision", "body_sha256"):
            if not str(row.get(field, "")).strip():
                raise ValueError(f"licence record is missing {field}: {row}")
        if row["licence_class"] not in allowed_classes:
            raise ValueError(
                f"licence class is not redistributable: {row['licence_class']}")
        if len(str(row["body_sha256"])) != 64:
            raise ValueError(
                f"body_sha256 must be a 64-character digest: {row['document_id']}")
    dependency_rows = [dict(row) for row in dependencies]
    edge_rows = [dict(row) for row in dependency_edges]
    correction_rows = [dict(row) for row in corrections]

    # Validate the chat model before publishing anything. This also rejects a
    # model from a newer incompatible package schema.
    memories = inspect_model_database(source_model)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix=destination.name + ".", dir=destination.parent) as temporary:
        staging = Path(temporary)
        model_path = staging / MODEL_FILE
        shutil.copy2(source_model, model_path)
        phase8_path = staging / PHASE8_FILE
        connection = sqlite3.connect(phase8_path)
        try:
            connection.executescript(_PHASE8_SCHEMA)
            connection.executemany(
                "INSERT INTO licences VALUES(?,?,?,?,?,?,?,?,?,?)",
                ((row["document_id"], row["title"], row["source"],
                  row["licence"], row["licence_class"], row["licence_url"],
                  row["attribution"], row["retrieved_at"], row["revision"],
                  row["body_sha256"]) for row in licence_rows))
            connection.executemany(
                "INSERT INTO dependencies VALUES(?,?,?,?,?,?,?)",
                ((row["id"], row["kind"], row.get("trust", "derived"),
                  row.get("state", "active"),
                  json.dumps(row.get("payload", {}), sort_keys=True),
                  row.get("created_at", _now()), row.get("updated_at", _now()))
                 for row in dependency_rows))
            connection.executemany(
                "INSERT INTO dependency_edges VALUES(?,?,?)",
                ((row["target"], row["source"],
                  row.get("relation", "derived_from")) for row in edge_rows))
            if registry_db is not None:
                registry_path = Path(registry_db).expanduser().resolve()
                if not registry_path.is_file():
                    raise FileNotFoundError(
                        f"rule registry does not exist: {registry_path}")
                registry = sqlite3.connect(
                    registry_path.as_uri() + "?mode=ro", uri=True)
                try:
                    connection.executemany(
                        "INSERT INTO registry_rules VALUES(?,?,?,?,?)",
                        registry.execute(
                            "SELECT id,family,state,payload,updated_at "
                            "FROM rules ORDER BY id").fetchall())
                    connection.executemany(
                        "INSERT INTO registry_history"
                        "(rule_id,action,at,detail_json,before_json) "
                        "VALUES(?,?,?,?,?)",
                        registry.execute(
                            "SELECT rule_id,action,at,detail,before "
                            "FROM history ORDER BY seq").fetchall())
                finally:
                    registry.close()
            connection.executemany(
                "INSERT INTO corrections(correction_id,trigger,reason,"
                "affected_json,retained_json,at) VALUES(?,?,?,?,?,?)",
                ((row["correction_id"], row["trigger"], row["reason"],
                  json.dumps(list(row.get("affected", ())), sort_keys=True),
                  json.dumps(list(row.get("retained", ())), sort_keys=True),
                  row.get("at", _now())) for row in correction_rows))
            model_sha = _sha256(model_path)
            model_bytes = model_path.stat().st_size
            connection.execute(
                "INSERT INTO integrity VALUES(?,?,?,?)",
                (MODEL_FILE, model_sha, model_bytes, "chat-model"))
            coverage = _coverage(licence_rows)
            metadata = {
                "format": FORMAT,
                "version": str(VERSION),
                "model_schema": str(MODEL_SCHEMA_VERSION),
                "created_at": _now(),
                "read_only": "true",
                "licence_coverage": json.dumps(coverage, sort_keys=True),
                "source_documents": str(len(licence_rows)),
                "dependency_nodes": str(len(dependency_rows)),
                "dependency_edges": str(len(edge_rows)),
                "corrections": str(len(correction_rows)),
            }
            connection.executemany(
                "INSERT INTO release_meta VALUES(?,?)",
                sorted(metadata.items()))
            connection.commit()
        finally:
            connection.close()

        phase8_sha = _sha256(phase8_path)
        phase8_bytes = phase8_path.stat().st_size
        research = model_database_research_stats(model_path) if (
            model_database_has_research(model_path, validate=False)) else None
        files = [
            {"path": MODEL_FILE, "sha256": model_sha, "bytes": model_bytes,
             "role": "chat-model"},
            {"path": PHASE8_FILE, "sha256": phase8_sha, "bytes": phase8_bytes,
             "role": "phase8-metadata"},
        ]
        release = {
            "format": FORMAT,
            "version": VERSION,
            "model_schema": MODEL_SCHEMA_VERSION,
            "created_at": metadata["created_at"],
            "read_only": True,
            "compatibility": list(COMPATIBILITY),
            "model": {
                "memories": sorted(memories),
                "has_research": research is not None,
                "source_documents": research["documents"] if research else 0,
                "source_bytes": research["utf8_bytes"] if research else 0,
                "source_words": research["word_units"] if research else 0,
            },
            "licences": coverage,
            "dependencies": {
                "nodes": len(dependency_rows),
                "edges": len(edge_rows),
            },
            "registry_rules": None,
            "corrections": len(correction_rows),
            "files": files,
            "total_bytes": model_bytes + phase8_bytes,
        }
        # Re-open the staged metadata for accurate registry counts.
        check = sqlite3.connect(phase8_path.as_uri() + "?mode=ro", uri=True)
        try:
            release["registry_rules"] = int(check.execute(
                "SELECT count(*) FROM registry_rules").fetchone()[0])
            release["licences"] = json.loads(check.execute(
                "SELECT value FROM release_meta WHERE key='licence_coverage'"
            ).fetchone()[0])
        finally:
            check.close()
        (staging / RELEASE_FILE).write_text(
            json.dumps(release, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        # Verify the staged release before publishing it.
        verify_release(staging)
        staging.rename(destination)
    release = open_release(destination)
    try:
        return release.inspect()
    finally:
        release.close()


@dataclass
class Release:
    path: Path
    manifest: dict[str, Any]
    phase8: sqlite3.Connection

    @property
    def model_path(self) -> Path:
        return self.path / MODEL_FILE

    @property
    def phase8_path(self) -> Path:
        return self.path / PHASE8_FILE

    def _scalar(self, query: str, parameters: Sequence[Any] = ()) -> int:
        return int(self.phase8.execute(query, parameters).fetchone()[0])

    def inspect(self) -> dict[str, Any]:
        model = inspect_model_database(self.model_path)
        research = model_database_research_stats(
            self.model_path, validate=False) or {
                "documents": 0, "utf8_bytes": 0, "word_units": 0,
            }
        memory_sizes = {
            name: int(detail.get("bytes", 0))
            for name, detail in model.items()
        }
        release_meta = dict(self.phase8.execute(
            "SELECT key,value FROM release_meta"))
        return {
            "path": str(self.path),
            "format": self.manifest["format"],
            "version": self.manifest["version"],
            "model_schema": self.manifest["model_schema"],
            "read_only": bool(self.manifest.get("read_only")),
            "compatibility": self.manifest.get("compatibility", []),
            "total_bytes": self.manifest["total_bytes"],
            "model_bytes": self.model_path.stat().st_size,
            "metadata_bytes": self.phase8_path.stat().st_size,
            "memories": sorted(model),
            "memory_bytes": memory_sizes,
            "research": research,
            "licences": self.manifest.get("licences", {}),
            "dependencies": {
                "nodes": self._scalar("SELECT count(*) FROM dependencies"),
                "edges": self._scalar("SELECT count(*) FROM dependency_edges"),
                "by_kind": {
                    row[0]: int(row[1]) for row in self.phase8.execute(
                        "SELECT kind,count(*) FROM dependencies GROUP BY kind")},
                "by_state": {
                    row[0]: int(row[1]) for row in self.phase8.execute(
                        "SELECT state,count(*) FROM dependencies GROUP BY state")},
            },
            "registry": {
                "rules": self._scalar("SELECT count(*) FROM registry_rules"),
                "by_family": {
                    row[0]: int(row[1]) for row in self.phase8.execute(
                        "SELECT family,count(*) FROM registry_rules GROUP BY family")},
                "by_state": {
                    row[0]: int(row[1]) for row in self.phase8.execute(
                        "SELECT state,count(*) FROM registry_rules GROUP BY state")},
            },
            "corrections": self._scalar("SELECT count(*) FROM corrections"),
            "release_meta": release_meta,
        }

    def lineage(self, node_id: str) -> dict[str, Any]:
        row = self.phase8.execute(
            "SELECT id,kind,trust,state,payload_json,created_at,updated_at "
            "FROM dependencies WHERE id=?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown dependency node: {node_id!r}")
        inputs = [
            {"target": target, "source": source, "relation": relation}
            for target, source, relation in self.phase8.execute(
                "SELECT target,source,relation FROM dependency_edges "
                "WHERE target=? ORDER BY source,relation", (node_id,))]
        dependents = [
            {"target": target, "source": source, "relation": relation}
            for target, source, relation in self.phase8.execute(
                "SELECT target,source,relation FROM dependency_edges "
                "WHERE source=? ORDER BY target,relation", (node_id,))]
        return {
            "node": {
                "id": row[0], "kind": row[1], "trust": row[2],
                "state": row[3], "payload": json.loads(row[4]),
                "created_at": row[5], "updated_at": row[6],
            },
            "inputs": inputs,
            "dependents": dependents,
        }

    def corrections(self) -> list[dict[str, Any]]:
        return [
            {
                "correction_id": row[0], "trigger": row[1], "reason": row[2],
                "affected": json.loads(row[3]), "retained": json.loads(row[4]),
                "at": row[5],
            }
            for row in self.phase8.execute(
                "SELECT correction_id,trigger,reason,affected_json,retained_json,at "
                "FROM corrections ORDER BY seq")
        ]

    def evidence(self, document_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT document_id,title,source,licence,licence_class,licence_url,"
            "attribution,retrieved_at,revision,body_sha256 FROM licences")
        parameters: tuple[Any, ...] = ()
        if document_id is not None:
            query += " WHERE document_id=?"
            parameters = (document_id,)
        query += " ORDER BY document_id"
        rows = self.phase8.execute(query, parameters).fetchall()
        if document_id is not None and not rows:
            raise KeyError(f"unknown evidence document: {document_id!r}")
        return [
            {
                "document_id": row[0], "title": row[1], "source": row[2],
                "licence": row[3], "licence_class": row[4],
                "licence_url": row[5], "attribution": row[6],
                "retrieved_at": row[7], "revision": row[8],
                "body_sha256": row[9],
            }
            for row in rows
        ]

    def verify(self) -> dict[str, Any]:
        errors: list[str] = []
        for item in self.manifest.get("files", ()):
            path = self.path / item["path"]
            if not path.is_file():
                errors.append(f"missing release file: {item['path']}")
                continue
            if path.stat().st_size != int(item["bytes"]):
                errors.append(f"size mismatch: {item['path']}")
            if _sha256(path) != item["sha256"]:
                errors.append(f"digest mismatch: {item['path']}")
        try:
            inspect_model_database(self.model_path)
        except Exception as error:
            errors.append(f"model validation failed: {error}")
        try:
            rows = dict(self.phase8.execute(
                "SELECT path,sha256 FROM integrity"))
            if rows.get(MODEL_FILE) != self.manifest["files"][0]["sha256"]:
                errors.append("integrity table does not match the model digest")
        except sqlite3.DatabaseError as error:
            errors.append(f"metadata integrity read failed: {error}")
        return {
            "valid": not errors,
            "errors": errors,
            "files": len(self.manifest.get("files", ())),
            "total_bytes": self.manifest.get("total_bytes", 0),
        }

    def close(self) -> None:
        self.phase8.close()


def open_release(path: str | Path) -> Release:
    root = Path(path).expanduser().resolve()
    manifest_path = root / RELEASE_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(f"not a CRMS Phase 8 release: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise ValueError("unsupported Phase 8 release format")
    if manifest.get("version") != VERSION:
        raise ValueError("unsupported Phase 8 release version")
    model_path = root / MODEL_FILE
    phase8_path = root / PHASE8_FILE
    if not model_path.is_file() or not phase8_path.is_file():
        raise ValueError("Phase 8 release is missing a required file")
    connection = sqlite3.connect(phase8_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    release = Release(root, manifest, connection)
    verification = release.verify()
    if not verification["valid"]:
        release.close()
        raise ValueError(
            "Phase 8 release failed verification: "
            + "; ".join(verification["errors"]))
    return release


def migrate_model(source: str | Path, output: str | Path) -> Path:
    """Repack an older chat model into the current package schema.

    The installer materializes normalized knowledge/rules and embedded research
    from the source without reading original input files. The result can then
    be published with :func:`build_release`.
    """
    from crms_package import export_model_database, install_model_database
    source_path = Path(source).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"migration output already exists: {destination}")
    with tempfile.TemporaryDirectory(prefix="crms-phase8-migrate-") as temporary:
        staging = Path(temporary)
        installed = install_model_database(source_path, staging)
        knowledge = installed["knowledge"]
        rules = installed["rules"]
        math = installed.get("math")
        translations = installed.get("translations")
        dialogue = installed.get("dialogue")
        research = installed.get("research_index")
        export_model_database(
            destination, knowledge=knowledge, rules=rules, math=math,
            translations=translations, dialogue=dialogue,
            research_index=research)
    return destination


def verify_release(path: str | Path) -> dict[str, Any]:
    release = open_release(path)
    try:
        return release.verify()
    finally:
        release.close()


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="show release contents and counts")
    inspect.add_argument("--release", type=Path, required=True)
    inspect.add_argument("--json", action="store_true")

    migrate = sub.add_parser("migrate", help="migrate an older chat model")
    migrate.add_argument("--model-db", type=Path, required=True)
    migrate.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify", help="verify file digests and model schema")
    verify.add_argument("--release", type=Path, required=True)

    lineage = sub.add_parser("lineage", help="inspect one dependency node")
    lineage.add_argument("--release", type=Path, required=True)
    lineage.add_argument("node")

    corrections = sub.add_parser("corrections", help="inspect correction history")
    corrections.add_argument("--release", type=Path, required=True)

    evidence = sub.add_parser("evidence", help="inspect per-document licences")
    evidence.add_argument("--release", type=Path, required=True)
    evidence.add_argument("document_id", nargs="?")

    args = parser.parse_args(argv)
    if args.command == "migrate":
        try:
            destination = migrate_model(args.model_db, args.output)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        _print_json({"migrated": str(destination),
                     "bytes": destination.stat().st_size})
        return 0
    release = open_release(args.release)
    try:
        if args.command == "inspect":
            result = release.inspect()
            if args.json:
                _print_json(result)
            else:
                print(f"Release: {result['path']}")
                print(f"Format: {result['format']} v{result['version']} "
                      f"(model schema {result['model_schema']})")
                print(f"Read-only: {result['read_only']}")
                print(f"Size: {result['total_bytes']:,} bytes "
                      f"({result['model_bytes']:,} model + "
                      f"{result['metadata_bytes']:,} metadata)")
                print(f"Memories: {', '.join(result['memories'])}")
                print(f"Sources: {result['research']['documents']:,}; "
                      f"words: {result['research']['word_units']:,}")
                print(f"Licence coverage: "
                      f"{result['licences']['coverage']:.1%}")
                print(f"Dependencies: {result['dependencies']['nodes']} nodes, "
                      f"{result['dependencies']['edges']} edges")
                print(f"Registry rules: {result['registry']['rules']}; "
                      f"corrections: {result['corrections']}")
            return 0
        if args.command == "verify":
            _print_json(release.verify())
            return 0
        if args.command == "lineage":
            _print_json(release.lineage(args.node))
            return 0
        if args.command == "corrections":
            _print_json(release.corrections())
            return 0
        _print_json(release.evidence(args.document_id))
        return 0
    finally:
        release.close()


if __name__ == "__main__":
    raise SystemExit(main())
