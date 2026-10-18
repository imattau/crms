"""Build a portable CRMS project corpus from source files and supplied design notes.

The resulting SQLite model embeds searchable text, so queries do not need the
original files or the temporary research index after packaging.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import (
    export_model_database, inspect_model_database,
    model_database_research_stats,
)
from crms_research import CRMSSQLiteResearchIndex


PROJECT = Path(__file__).resolve().parent
DESIGN_ATTACHMENT_IDS = (
    "96aacf6d-16f6-4b02-8f7a-22aa347c11ea",
    "a9cdd863-3eb3-45db-85d9-90b0037c6334",
    "a4c9b411-1619-4a3d-8170-42a966334d03",
    "24863ec7-0797-49d9-8996-fae2a0f71b8c",
    "63fdc7a7-f079-4f05-9c2d-d6ccd21e9ba9",
    "dfdbd851-b921-48a0-abd5-309fdeba649a",
    "a03c245b-5f18-447a-ae72-e9125249ea7f",
    "bc92feed-91c0-4934-807e-9e5d1f0b0359",
    "5e6f8835-d6f1-4814-96ad-9292ceacfe17",
    "dbae81de-246f-44c4-9abe-b8a1fc0efeac",
    "be23bc65-6efe-4310-9bb1-1597e7d36edc",
    "42f4af3b-2de3-42ae-a83f-019cc86099cb",
    "6008c201-3f00-4220-b2fc-d81aa0a7c269",
    "2a2d4dd0-bf60-46b0-aada-58e1de18e699",
    "85b9e14f-c8e9-4741-ab5c-419cae00af51",
    "65699ce5-e806-4aab-9ae5-89e352a57cb5",
)


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return re.sub(r"^#+\s*", "", line).strip()[:240] or fallback
        if line:
            return line[:240]
    return fallback


def _sources(attachments_root: Path):
    project_files = [PROJECT / "CRMS_README.md"]
    project_files.extend(sorted(PROJECT.glob("*.py")))
    project_files.extend(sorted((PROJECT / "experiments").rglob("*.py")))
    for path in project_files:
        if not path.is_file() or path.name == Path(__file__).name:
            continue
        relative = path.relative_to(PROJECT).as_posix()
        text = path.read_text(encoding="utf-8")
        yield (f"project:{relative}", _title(text, relative), text,
               f"CRMS project file: {relative}")

    curated_root = PROJECT / "data" / "curated_sources"
    for path in sorted(curated_root.rglob("*.txt")) if curated_root.is_dir() else ():
        relative = path.relative_to(curated_root).as_posix()
        text = path.read_text(encoding="utf-8")
        source_line = next((line.partition(":")[2].strip()
                            for line in text.splitlines()
                            if line.startswith("Source URL:")), "")
        if not source_line:
            raise ValueError(f"curated source is missing Source URL: {path}")
        yield (f"curated:{relative}", _title(text, relative), text,
               source_line)

    for attachment_id in DESIGN_ATTACHMENT_IDS:
        path = attachments_root / attachment_id / "Pasted text.txt"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        yield (f"conversation:{attachment_id}",
               _title(text, f"CRMS design note {attachment_id}"), text,
               f"User-provided CRMS design note: {attachment_id}")


def build(output: Path, *, attachments_root: Path, model_output: Path,
          replace: bool) -> dict[str, int]:
    output = output.expanduser().resolve()
    model_output = model_output.expanduser().resolve()
    if output == model_output:
        raise ValueError("research index and model database need different paths")
    if output.exists() and not replace:
        raise FileExistsError(f"research index already exists: {output}")
    if model_output.exists() and not replace:
        raise FileExistsError(f"model database already exists: {model_output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    model_output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    model_output.unlink(missing_ok=True)

    index = CRMSSQLiteResearchIndex(output)
    document_count = source_bytes = 0
    try:
        for document_id, title, text, location in _sources(attachments_root):
            index.add_document(document_id, title, text, location)
            document_count += 1
            source_bytes += len(text.encode("utf-8"))
    finally:
        index.close()
    if document_count == 0:
        raise ValueError("no project or explicitly supplied design sources were found")

    # The seed model keeps its source text separate from learned fact/rule
    # memories. It is ready for /teach-fact and rule learning in ordinary chat.
    memory_directory = output.parent / (output.stem + ".seed-memories")
    memory_directory.mkdir(parents=True, exist_ok=True)
    knowledge_path = memory_directory / "knowledge.json"
    rules_path = memory_directory / "rules.json"
    CRMSKnowledgeBase().save(knowledge_path)
    CRMSModel().save(rules_path)
    export_model_database(
        model_output, knowledge=knowledge_path, rules=rules_path,
        research_index=output)
    inspected = inspect_model_database(model_output)
    stats = model_database_research_stats(model_output)
    if "knowledge" not in inspected or "rules" not in inspected or not stats:
        raise ValueError("built model database failed its memory/source inspection")
    return {"documents": document_count, "source_bytes": source_bytes,
            "model_bytes": model_output.stat().st_size,
            "embedded_documents": stats["documents"],
            "embedded_source_bytes": stats["utf8_bytes"],
            "embedded_word_units": stats["word_units"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-index", type=Path, required=True,
                        help="new SQLite source index to build")
    parser.add_argument("--model-db", type=Path, required=True,
                        help="new portable SQLite model database to build")
    parser.add_argument(
        "--attachments-root", type=Path,
        default=Path("/home/lostcause/.codex/attachments"),
        help="root containing the user-supplied design-note attachments")
    parser.add_argument("--replace", action="store_true",
                        help="replace both named output files")
    args = parser.parse_args()
    try:
        stats = build(args.research_index, attachments_root=args.attachments_root,
                      model_output=args.model_db, replace=args.replace)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({
        "research_index": str(args.research_index),
        "model_database": str(args.model_db),
        **stats,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
