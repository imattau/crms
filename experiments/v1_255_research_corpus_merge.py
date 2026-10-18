"""Check lossless merging and resumable combination of local research indexes."""

from __future__ import annotations

import sys
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_merge_research import merge_research_indexes
from crms_package import (
    export_model_database, install_model_database,
    model_database_research_stats,
)
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-research-merge-") as folder:
        root = Path(folder)
        left_path = root / "left.sqlite"
        right_path = root / "right.sqlite"
        output_path = root / "combined.sqlite"
        left = CRMSSQLiteResearchIndex(left_path)
        right = CRMSSQLiteResearchIndex(right_path)
        pages = ("Alexander Hamilton wrote the report.",
                 "The report was adopted in 1787.")
        try:
            left.add_document("shared", "Report", "\n\f\n".join(pages),
                              "archive://report", pages=pages)
            left.add_document("left-only", "Left", "Ada studied logic.",
                              "left.txt")
            right.add_document("shared", "Report", "\n\f\n".join(pages),
                               "archive://report", pages=pages)
            right.add_document("right-only", "Right", "Grace designed a compiler.",
                               "right.txt")
        finally:
            left.close()
            right.close()

        result = merge_research_indexes(
            [left_path, right_path], output_path, batch_size=1)
        if (result["added"] != 3 or result["identical_duplicates"] != 1
                or result["documents"] != 3):
            raise SystemExit(f"merge counts are incorrect: {result}")
        merged = CRMSSQLiteResearchIndex(output_path)
        try:
            hit = merged.search("Who wrote the report?", limit=5)[0]
            if hit.document_id != "shared" or "Hamilton" not in hit.snippet:
                raise SystemExit(f"merged search missed the shared source: {hit}")
            citation = merged.citation(hit)
            if "Hamilton" not in merged.resolve_citation(citation):
                raise SystemExit("merged citation did not resolve")
            if merged.document("shared").pages != pages:
                raise SystemExit("page boundaries were lost during the merge")
        finally:
            merged.close()

        resumed = merge_research_indexes(
            [right_path], output_path, append=True, batch_size=2)
        if (resumed["documents"] != 3
                or resumed["identical_duplicates"] != 2):
            raise SystemExit(f"append was not idempotent: {resumed}")

        conflict_path = root / "conflict.sqlite"
        conflict = CRMSSQLiteResearchIndex(conflict_path)
        try:
            conflict.add_document("shared", "Changed", "Different text.",
                                  "new.txt")
        finally:
            conflict.close()
        try:
            merge_research_indexes([conflict_path], output_path, append=True)
        except ValueError as error:
            if "conflicting document ID" not in str(error):
                raise
        else:
            raise SystemExit("conflicting source ID silently overwrote data")
        preserved = CRMSSQLiteResearchIndex(output_path)
        try:
            if preserved.document("shared").text != "\n\f\n".join(pages):
                raise SystemExit("failed merge changed the existing output")
        finally:
            preserved.close()

        replaced = merge_research_indexes(
            [conflict_path], output_path, append=True,
            conflict="replace-later")
        if replaced["replaced"] != 1:
            raise SystemExit(f"explicit replacement was not recorded: {replaced}")
        final = CRMSSQLiteResearchIndex(output_path)
        try:
            if final.document("shared").text != "Different text.":
                raise SystemExit("replace-later did not install the new source")
        finally:
            final.close()

        knowledge_path, rules_path = root / "knowledge.json", root / "rules.json"
        knowledge_path.write_text(json.dumps({"facts": []}), encoding="utf-8")
        rules_path.write_text(json.dumps({"rules": []}), encoding="utf-8")
        model_path = root / "crms-model.sqlite"
        export_model_database(
            model_path, knowledge=knowledge_path, rules=rules_path,
            research_index=output_path)
        stats = model_database_research_stats(model_path)
        if not stats or stats["documents"] != 3:
            raise SystemExit(f"merged corpus was not packaged: {stats}")
        installed_dir = root / "installed"
        install_model_database(model_path, installed_dir)
        installed_index = CRMSSQLiteResearchIndex(
            installed_dir / "research.sqlite")
        try:
            if installed_index.document_count() != 3:
                raise SystemExit("installed model lost merged documents")
            installed_hit = installed_index.search("Ada logic", limit=3)[0]
            if installed_hit.document_id != "left-only":
                raise SystemExit(
                    "installed portable model cannot search merged sources")
        finally:
            installed_index.close()

    print("research corpus merge diagnostic: PASS")
    print("multi-source merge, provenance, exact citations, page retention, "
          "idempotent append, conflict refusal, explicit replacement, "
          "portable packaging and installation: PASS")


if __name__ == "__main__":
    main()
