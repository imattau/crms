"""Phase 12: route-first wiring of the learned relation specs in the chat.

``--relation-first agent`` tries the agent-family relation specs (Who directed /
produced / wrote X?) before the quote route and falls back to the existing route
when they return nothing. The switch is a family name, never a global flag.

Run with: python3 experiments/v1_585_relation_first_route.py
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import crms_chat  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


def ask(folder: Path, index: Path, question: str, *flags: str) -> str:
    command = [sys.executable, str(PROJECT / "crms_chat.py"), "--index", str(index), *flags]
    for name in ("dialogue-state", "candidate-session", "rule-session", "math-session"):
        command += [f"--{name}", str(folder / f"{name}.json")]
    command += ["--feedback-db", str(folder / "feedback.sqlite3")]
    out = subprocess.run(command, input=question + "\n/quit\n", text=True,
                         capture_output=True, timeout=180, cwd=folder).stdout
    return out.split("CRMS> ", 1)[1].split("CRMS state saved")[0] if "CRMS> " in out else ""


def main() -> None:
    require(set(crms_chat.RELATION_FAMILIES) == {"agent"}, "one family per change")
    require(crms_chat.RELATION_FIRST_DEFAULT in {"off", *crms_chat.RELATION_FAMILIES},
            "the default names a known family or off")
    with tempfile.TemporaryDirectory(prefix="crms-relfirst-") as raw:
        folder = Path(raw)
        index_path = folder / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "doc-1", "Titanic 666",
            "Titanic 666 is a 2022 horror film. Titanic 666 was produced by The Asylum. "
            "The film was shot in California.")
        index.save() if hasattr(index, "save") else None
        engine = crms_chat._relation_first_engine(index, "agent")
        require(engine is not None and engine.allowed == {"work_by_artist", "agent_transformed"},
                "engine is limited to the agent family")
        require(crms_chat._relation_first_engine(index, "off") is None, "off builds no engine")
        answer = engine.ask("Who produced Titanic 666?")
        require(answer is not None and "Asylum" in answer.answer, answer)
        require(engine.ask("Where was Titanic 666 filmed?") is None,
                "other families are not asked")

        on = ask(folder, index_path, "Who produced Titanic 666?", "--relation-first", "agent")
        # When the existing route already holds a reviewable claim it renders
        # that claim; relation-first answers only where the old route has none.
        require("The Asylum" in on, on)
        off = ask(folder, index_path, "Who produced Titanic 666?", "--relation-first", "off")
        require("relation " not in off, off)
        unknown = ask(folder, index_path, "Who produced Nonexistent Picture?", "--relation-first", "agent")
        require("relation " not in unknown, unknown)   # falls back to the existing route
    print("Phase 12 relation-first route passed")


if __name__ == "__main__":
    main()
