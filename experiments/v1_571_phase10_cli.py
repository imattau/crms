"""Phase 10 CLI contract: JSON request, generated text, JSON result."""
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
    with tempfile.TemporaryDirectory(prefix="crms-phase10-cli-") as temporary:
        root = Path(temporary)
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        text = subprocess.run(
            [sys.executable, str(PROJECT / "crms_generate.py"),
             "--request", str(request_path)],
            cwd=PROJECT, text=True, capture_output=True, check=False)
        require(text.returncode == 0, f"text CLI failed: {text.stderr}")
        require("Rayleigh scattering" in text.stdout,
                "text CLI lost the definition")
        structured = subprocess.run(
            [sys.executable, str(PROJECT / "crms_generate.py"),
             "--request", str(request_path), "--json"],
            cwd=PROJECT, text=True, capture_output=True, check=False)
        require(structured.returncode == 0,
                f"JSON CLI failed: {structured.stderr}")
        payload = json.loads(structured.stdout)
        require(payload["status"] == "ok", "CLI result is not ok")
        require(payload["evidence"], "CLI result lost evidence")
        require(payload["critique"]["passed"], "CLI critic failed")
        require("Rayleigh scattering" in payload["text"],
                "JSON CLI text lost the definition")
    print("Phase 10 CLI text and JSON output: PASS")
    print("Evidence and critic survive the CLI: PASS")
    print("Phase 10 CLI contract: PASS")


if __name__ == "__main__":
    main()
