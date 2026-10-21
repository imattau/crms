"""Phase 10 clean-room contract: copied rules and fixture, no project imports."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from run_phase10_eval import FIXTURE, REPORT, evaluate_fixture  # noqa: E402

MODULES = ("crms_generation.py", "crms_generation_rules.py",
           "run_phase10_eval.py")
RULES = PROJECT / "crms_generation_rules.json"
CLEAN_REPORT = PROJECT / "experiments" / "reports" / "phase10_clean_room.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    baseline = evaluate_fixture(FIXTURE)
    baseline_text = {row["id"]: row["text"] for row in baseline["cases"]}
    source = "\n".join((PROJECT / name).read_text(encoding="utf-8")
                       for name in MODULES)
    for forbidden in ("requests", "urllib", "http://", "https://",
                      "openai", "anthropic"):
        require(forbidden not in source,
                f"generation path contains forbidden dependency: {forbidden}")

    with tempfile.TemporaryDirectory(prefix="crms-phase10-clean-") as temporary:
        root = Path(temporary)
        for name in MODULES:
            shutil.copy2(PROJECT / name, root / name)
        shutil.copy2(RULES, root / RULES.name)
        fixture_dir = root / "corpus" / "phase10_eval"
        fixture_dir.mkdir(parents=True)
        shutil.copy2(FIXTURE, fixture_dir / "fixture.json")
        shutil.copy2(FIXTURE.with_suffix(".sha256"),
                     fixture_dir / "fixture.sha256")
        result = subprocess.run(
            [sys.executable, "run_phase10_eval.py", "--out", "report.json"],
            cwd=root, text=True, capture_output=True, check=False,
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"},
        )
        require(result.returncode == 0,
                f"clean-room run failed: {result.stdout}\n{result.stderr}")
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        require(report["gate_passed"], "clean-room first-slice gate failed")
        clean_text = {row["id"]: row["text"] for row in report["cases"]}
        require(clean_text == baseline_text,
                "clean-room output differs from the project checkout")
        require(report["rule_sha256"] == baseline["rule_sha256"],
                "clean-room rule digest changed")
        require(report["fixture_sha256"] == baseline["fixture_sha256"],
                "clean-room fixture digest changed")

    payload = {
        "format": "crms-phase10-clean-room",
        "version": 1,
        "cases": len(baseline_text),
        "identical_outputs": True,
        "no_llm_or_network_imports": True,
        "rule_sha256": baseline["rule_sha256"],
        "fixture_sha256": baseline["fixture_sha256"],
        "gate_passed": True,
    }
    CLEAN_REPORT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    print("Clean-room copied modules, rules, and fixture: PASS")
    print("12/12 outputs identical, no LLM/network imports: PASS")
    print(f"Report: {CLEAN_REPORT.relative_to(PROJECT)}")
    print("Phase 10 clean-room contract: PASS")


if __name__ == "__main__":
    main()
