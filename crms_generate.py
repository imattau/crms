#!/usr/bin/env python3
"""Generate rule-composed content from a JSON request.

Request shape:
{
  "prompt": "Explain why the sky is blue.",
  "genre": "explanation",
  "audience": "general",
  "style": "plain",
  "facts": [{"fact_id":"...", "subject":"...", "verb":"...", ...}],
  "source_documents": [{"name":"sky.txt", "text":"..."}]
}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_generation import (  # noqa: E402
    Fact, GenerationEngine, GenerationRequest,
)
from crms_generation_rules import load_rules  # noqa: E402


def request_from_mapping(raw: dict[str, Any]) -> GenerationRequest:
    facts = tuple(Fact(
        fact_id=str(row["fact_id"]), subject=str(row.get("subject", "")),
        verb=str(row.get("verb", "")), object=str(row.get("object", "")),
        complement=str(row.get("complement", "")),
        role=str(row.get("role", "claim")),
        source=str(row.get("source", "")), span=str(row.get("span", "")),
        order=int(row.get("order", 0)),
        source_text=str(row.get("source_text", "")),
        tags=tuple(str(tag) for tag in row.get("tags", ())),
    ) for row in raw.get("facts", ()))
    intake = raw.get("intake")
    if intake:
        # Phase 11: answer the listed questions from the request's own source
        # documents with relation specs; each verified match becomes a fact.
        from crms_source_intake import intake_facts
        extra, _report = intake_facts(
            list(intake.get("questions", ())),
            [(str(doc["name"]), str(doc["text"]))
             for doc in raw.get("source_documents", ())])
        facts = facts + tuple(extra)
    return GenerationRequest(
        prompt=str(raw["prompt"]), genre=str(raw["genre"]), facts=facts,
        audience=str(raw.get("audience", "general")),
        style=str(raw.get("style", "plain")),
        max_sentences=int(raw.get("max_sentences", 10)),
        source_documents=tuple(
            (str(doc["name"]), str(doc["text"]))
            for doc in raw.get("source_documents", ())),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--rule-store", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.request.read_text(encoding="utf-8"))
    if args.rule_store is not None:
        from crms_composition_memory import GenerationRuleStore
        with GenerationRuleStore(args.rule_store) as store:
            rules = store.load_rules()
    else:
        rules = load_rules(args.rules) if args.rules else load_rules()
    result = GenerationEngine(rules).generate(request_from_mapping(raw))
    payload = result.as_dict()
    output = json.dumps(payload, indent=2, ensure_ascii=False) if args.json else result.text
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    if not args.out:
        print(output)
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
