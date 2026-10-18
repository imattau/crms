"""Check typed object questions using only explicit type and relation facts.

Run from the project root with:
    python3 experiments/v1_258_typed_object_did_questions.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "designed", "the Vela instrument", "design:ada")
    kb.add_fact("the Vela instrument", "is-a", "instrument", "type:vela")
    result = kb.ask("Which instrument did Ada design?")
    if result.status != "answered" or result.answer != "the Vela instrument":
        raise SystemExit(f"typed object question failed: {result}")
    if "Ada designed the Vela instrument." not in kb.render_brief(result):
        raise SystemExit("object answer did not realize its grounded fact sentence")
    if len(result.evidence or []) != 2:
        raise SystemExit("answer omitted relation or explicit type evidence")
    with tempfile.TemporaryDirectory(prefix="crms-typed-object-chat-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        run = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json"),
             "--rule-session", str(root / "rule-session.json")],
            input="Which instrument did Ada design?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        if "Ada designed the Vela instrument." not in run.stdout:
            raise SystemExit(f"chat did not route the typed object question:\n{run.stdout}")

    unsupported = kb.ask("Which machine did Ada design?")
    if unsupported.status != "unknown" or unsupported.answer is not None:
        raise SystemExit("question inferred an unsupported object type")

    ambiguous = CRMSKnowledgeBase()
    for obj, source in (("the Vela instrument", "vela"),
                        ("the Lyra instrument", "lyra")):
        ambiguous.add_fact("Ada", "designed", obj, f"design:{source}")
        ambiguous.add_fact(obj, "is-a", "instrument", f"type:{source}")
    multiple = ambiguous.ask("Which instrument did Ada design?")
    if (multiple.status != "ambiguous"
            or set(multiple.candidates or []) != {
                "the Vela instrument", "the Lyra instrument"}):
        raise SystemExit("multiple typed objects were not reported as ambiguous")

    conflict = CRMSKnowledgeBase()
    conflict.add_fact("Ada", "designed", "the Vela instrument", "design:yes")
    conflict.add_negative_fact("Ada", "designed", "the Vela instrument",
                               "design:no")
    conflict.add_fact("the Vela instrument", "is-a", "instrument", "type:yes")
    contradicted = conflict.ask("Which instrument did Ada design?")
    if contradicted.status != "ambiguous":
        raise SystemExit("contradictory relation evidence was hidden")

    print("typed object question diagnostic: PASS")
    print("regular did-support, explicit type gate, sentence realization, "
          "CLI routing, ambiguity and conflict handling: PASS")


if __name__ == "__main__":
    main()
