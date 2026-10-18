"""Check interactive source retraction and derived-case revalidation."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crms_chat
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "research.json"
        paths = [knowledge_path, index_path, root / "dialogue.json",
                 root / "rules.json", root / "session.json"]
        kb = CRMSKnowledgeBase()
        kb.add_fact("Ada", "works at", "Studio", "source:employment")
        kb.add_fact("Studio", "located in", "Paris", "source:address")
        kb.add_fact("Paris", "in country", "France", "source:old-country")
        kb.add_fact("Paris", "in country", "France", "source:backup-country")
        kb.add_inference_rule("work-location", "works at", "located in",
                              "works in")
        kb.add_inference_rule("location-country", "works in", "in country",
                              "works in country")
        if kb.practice_relation("Ada", "works in country", "France").status != "answered":
            raise SystemExit("could not create a derived result for the CLI test")
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)

        commands = [
            "/retract-fact POS|Paris|in country|France|source:old-country",
            "/derived-cases",
            "/retract-fact POS|Paris|in country|France|source:backup-country",
            "/derived-cases",
            "/infer-relation Ada|works in country|France",
            "/quit",
        ]
        cli_args = ["crms_chat.py", "--knowledge", str(paths[0]),
                    "--index", str(paths[1]), "--dialogue-state", str(paths[2]),
                    "--rules", str(paths[3]), "--rule-session", str(paths[4])]
        with patch("builtins.input", side_effect=commands), \
                patch.object(sys, "argv", cli_args), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            status = crms_chat.main()
        rendered = output.getvalue()
        if status != 0:
            raise SystemExit("terminal exited unsuccessfully")
        checks = (
            "Retracted source support; other citations remain.",
            "Derived case [verified]",
            "source:backup-country",
            "Retracted the final source support; the fact is no longer stored.",
            "Derived case [stale_or_conflicted]",
            "A rule applies, but no complete premise chain supports this conclusion.",
        )
        if any(text not in rendered for text in checks):
            raise SystemExit(f"fact correction workflow output was incomplete:\n{rendered}")
        if "source:old-country" in rendered:
            raise SystemExit("retracted citation remained in refreshed CLI lineage")

        saved = json.loads(knowledge_path.read_text(encoding="utf-8"))
        if any(fact["object"] == "France" and fact["relation"] == "in country"
               for fact in saved["facts"]):
            raise SystemExit("retracted final support remained in persisted facts")
        if saved["derived_cases"][0]["conclusion"]["object"] != "France":
            raise SystemExit("stale derived record was lost instead of marked for review")

    print("CLI fact correction diagnostic: PASS")
    print("citation-level retraction, refreshed lineage, final-support abstention, persistence: PASS")


if __name__ == "__main__":
    main()
