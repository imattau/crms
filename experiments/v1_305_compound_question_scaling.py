"""Profile composed-question latency against increasing SQLite fact stores."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_text import tokens


def insert_facts(path: Path, count: int) -> None:
    CRMSKnowledgeBase().save(path)
    with sqlite3.connect(path) as db:
        batch = []

        def row(subject: str, relation: str, obj: str, source: str):
            subject_key = json.dumps(tokens(subject), ensure_ascii=False,
                                     separators=(",", ":"))
            relation_key = json.dumps(tokens(relation), ensure_ascii=False,
                                      separators=(",", ":"))
            object_key = json.dumps(tokens(obj), ensure_ascii=False,
                                    separators=(",", ":"))
            key = json.dumps((tokens(subject), tokens(relation), tokens(obj)),
                             ensure_ascii=False, separators=(",", ":"))
            payload = json.dumps({
                "subject": subject, "relation": relation, "object": obj,
                "sources": [source], "qualifiers": [],
            }, ensure_ascii=False, separators=(",", ":"))
            return key, relation_key, subject_key, object_key, payload

        for start in range(0, count, 10_000):
            end = min(count, start + 10_000)
            batch = [row(f"Entity{i}", "recorded", f"Value{i}",
                         f"source:filler:{i}") for i in range(start, end)]
            db.executemany("INSERT INTO positive_facts VALUES (?,?,?,?,?)", batch)
        db.executemany("INSERT INTO positive_facts VALUES (?,?,?,?,?)", [
            row("Ada", "design", "Engine", "source:design"),
            row("Ada", "build", "Loom", "source:build"),
        ])


def profile(count: int, folder: Path) -> tuple[float, int]:
    path = folder / f"knowledge-{count}.sqlite"
    insert_facts(path, count)
    knowledge = CRMSKnowledgeBase.load(path)
    query = "Did Ada design Engine and build Loom?"
    durations = []
    expected = None
    for _ in range(4):
        started = time.perf_counter()
        result = knowledge.ask(query)
        durations.append(time.perf_counter() - started)
        signature = (result.status, result.answer, result.truth,
                     tuple(sorted(source for item in result.evidence or []
                                  for source in item["sources"])))
        if expected is None:
            expected = signature
        elif signature != expected:
            raise SystemExit(f"non-deterministic answer at {count} facts: {signature}")
    if expected != ("answered", "Yes", True,
                    ("source:build", "source:design")):
        raise SystemExit(f"wrong composed result at {count} facts: {expected}")
    knowledge.close()
    return statistics.median(durations[1:]) * 1000, count + 2


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-compound-scale-") as folder:
        root = Path(folder)
        print("SQLite facts | median composed-answer latency (3 warm runs)")
        for count in (1_000, 100_000, 1_000_000):
            print(f"starting {count:,}-fact case", flush=True)
            milliseconds, total = profile(count, root)
            print(f"{total:>12,} | {milliseconds:>8.2f} ms", flush=True)


if __name__ == "__main__":
    main()
