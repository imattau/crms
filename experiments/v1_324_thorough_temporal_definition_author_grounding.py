"""Ground date, definition, and writer answers in explicit source evidence."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import (
    _exact_title_definition,
    _natural_when_evidence,
    _natural_when_question,
    _natural_who_structured_field_evidence,
)
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-thorough-evidence-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "research.sqlite")
        index.add_document("war", "World War II", "World War II ended in 1945.", "war.txt")
        index.add_document("noise", "Other war", "The war began in 1945.", "noise.txt")
        index.add_document("pacific", "Pacific Ocean",
                           "The Pacific Ocean is the largest ocean.", "pacific.txt")
        index.add_document("hamlet", "Hamlet",
                           "Infobox play\nname = Hamlet\nwriter = William Shakespeare\n\n"
                           "Hamlet was written between 1600 and 1602.", "hamlet.txt")

        require(_natural_when_question("When did World War II end?")
                == ("World War II", "end"), "date question parser failed")
        when = _natural_when_evidence(index, "When did World War II end?")
        require(when is not None and when["text"] == "World War II ended in 1945.",
                f"temporal evidence did not require matching entity/action/date: {when}")
        require(_exact_title_definition(index, "Pacific Ocean")["text"]
                == "The Pacific Ocean is the largest ocean.",
                "definition lead with 'The' was not accepted")
        writer = _natural_who_structured_field_evidence(index, "Who wrote Hamlet?")
        require(writer is not None
                and writer["realized_answer"]["text"]
                == "William Shakespeare is listed as the writer of Hamlet.",
                f"writer infobox field was not realized: {writer}")
        index.close()

    print("thorough temporal, definition and writer evidence: PASS")
    print("subject/action/date alignment, definite article and writer metadata: PASS")


if __name__ == "__main__":
    main()
