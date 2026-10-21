"""Phase 10 chat contract: /compose runs the rule-only generator."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "corpus" / "phase10_eval" / "fixture.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(row for row in fixture["cases"] if row["id"] == "explain-sky")
    request = {key: case[key] for key in (
        "prompt", "genre", "audience", "style", "facts", "source_documents")}
    with tempfile.TemporaryDirectory(prefix="crms-phase10-chat-") as temporary:
        root = Path(temporary)
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py")],
            cwd=root, input=f"/compose {request_path}\n/quit\n",
            text=True, capture_output=True, check=False, timeout=120)
        require(result.returncode == 0,
                f"chat /compose failed: {result.stdout}\n{result.stderr}")
        require("Rayleigh scattering" in result.stdout,
                "chat /compose lost the definition")
        require("Composition status: ok" in result.stdout,
                "chat /compose did not report success")
        require("copy ratio" in result.stdout,
                "chat /compose did not report the critic metric")
    print("Chat /compose request, generation, and critic: PASS")
    print("Phase 10 chat contract: PASS")


if __name__ == "__main__":
    main()
