"""Exercise source-only dialogue context through fresh, full CLI sessions.

This is a small frozen diagnostic authored independently of the earlier
dialogue fixtures. It measures end-to-end context transfer and safety; its
results are not an estimate of general conversational accuracy.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "v1_528_dialogue_context_transfer_cli.json"
CORPUS = (
    "The Aurora Observatory stands in Northport. The observatory opened in "
    "1984 and contains a public telescope.\n\n"
    "The Meridian Museum is in Vale City. The museum opened in 1972 and "
    "displays maritime maps.\n\n"
    "The Koru Botanical Garden is in Nera. The garden opened in 1968 and "
    "contains a fern house."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def command(root: Path) -> list[str]:
    return [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(root / "research.sqlite"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
    ]


def run(root: Path, turns: list[str], label: str) -> str:
    result = subprocess.run(
        command(root),
        input="\n".join([*turns, "/quit"]) + "\n",
        text=True, capture_output=True, cwd=root, timeout=90, check=False,
    )
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"{label}: CLI process failed: {output[-2500:]}")
    return output


def prepare(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source_dir = root / "sources"
    source_dir.mkdir()
    (source_dir / "places.txt").write_text(CORPUS, encoding="utf-8")
    return source_dir


def answer_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if "CRMS>" in line]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-528-") as temp:
        root = Path(temp)
        switch_root = root / "topic-switch"
        switch_source = prepare(switch_root)

        topic_switch = run(switch_root, [
            f"/source-dir {switch_source}",
            "Where is the Aurora Observatory?",
            "And the Meridian Museum?",
            "When did it open?",
            "why?",
        ], "topic switch")
        switch_lines = answer_lines(topic_switch)
        require("Aurora Observatory stands in Northport" in topic_switch
                and "Meridian Museum is in Vale City" in topic_switch,
                "topic switch: named source answers were not returned")
        require("1972" in switch_lines[2] and "1984" not in switch_lines[2],
                "topic switch: pronoun follow-up borrowed the prior entity's date")
        require("1972" in switch_lines[3] and "1984" not in switch_lines[3],
                "topic switch: why? explained stale evidence")

        distance_root = root / "long-distance"
        distance_source = prepare(distance_root)
        long_distance = run(distance_root, [
            f"/source-dir {distance_source}",
            "Where is the Aurora Observatory?",
            "And the Meridian Museum?",
            "And the Koru Botanical Garden?",
            "And the Aurora Observatory?",
            "When did it open?",
        ], "long topic distance")
        distance_lines = answer_lines(long_distance)
        require("The Koru Botanical Garden is in Nera" in long_distance
                and "The Aurora Observatory stands in Northport" in long_distance
                and "The observatory opened in 1984" in distance_lines[4]
                and "1972" not in distance_lines[4]
                and "1968" not in distance_lines[4],
                "long topic distance: explicit return selected a stale entity")

        interruption_root = root / "interruption"
        interruption_source = prepare(interruption_root)
        interruption = run(interruption_root, [
            f"/source-dir {interruption_source}",
            "Where is the Meridian Museum?",
            "Tell me a joke",
            "And the Aurora Observatory?",
            "When did it open?",
            "why?",
        ], "interrupted entity switch")
        interruption_lines = answer_lines(interruption)
        require("The Meridian Museum is in Vale City" in interruption
                and "The observatory opened in 1984" in interruption_lines[3]
                and "1972" not in interruption_lines[3],
                "interruption: explicit historical entity did not re-anchor follow-up")
        require("1984" in interruption_lines[4]
                and "1972" not in interruption_lines[4],
                "interruption: why? did not explain the re-anchored answer")

        correction_root = root / "correction"
        correction_source = prepare(correction_root)
        correction = run(correction_root, [
            f"/source-dir {correction_source}",
            "Where is the Aurora Observatory?",
            "And the Meridian Museum?",
            "No, I meant the Aurora Observatory.",
            "When did it open?",
        ], "explicit correction")
        correction_lines = answer_lines(correction)
        require("The observatory opened in 1984" in correction_lines[3]
                and "1972" not in correction_lines[3],
                "correction: subsequent pronoun stayed bound to the corrected-away topic")

        restart_root = root / "restart"
        restart_source = prepare(restart_root)
        restart_first = run(restart_root, [
            f"/source-dir {restart_source}",
            "Where is the Koru Botanical Garden?",
        ], "save before restart")
        restart_second = run(restart_root, ["When did it open?"],
                             "follow-up after restart")
        restart_lines = answer_lines(restart_second)
        require("Koru Botanical Garden" in restart_first
                and "The garden opened in 1968" in restart_lines[0]
                and "1984" not in restart_second and "1972" not in restart_second,
                "save/reload: source-only topic was lost or rebound after restart")

        blank_root = root / "blank-context"
        blank_source = prepare(blank_root)
        no_antecedent = run(blank_root, [
            f"/source-dir {blank_source}", "When did it open?",
        ], "pronoun without antecedent")
        require(not any(year in no_antecedent for year in ("1984", "1972", "1968")),
                "no antecedent: pronoun selected an arbitrary corpus entity")

    scenarios = [
        {"scenario": "named topic switch then pronoun and why", "outcome": "pass"},
        {"scenario": "return to an earlier entity after two topic switches", "outcome": "pass"},
        {"scenario": "unrelated interruption then historical entity switch", "outcome": "pass"},
        {"scenario": "explicit correction then pronoun", "outcome": "pass"},
        {"scenario": "source-only context across process restart", "outcome": "pass"},
        {"scenario": "pronoun with no antecedent", "outcome": "abstained_without_wrong_date"},
    ]
    report = {
        "experiment": "v1_528_dialogue_context_transfer_cli",
        "date": "2026-10-20",
        "source": "independently authored, three-entity source fixture",
        "method": "fresh full CLI processes with scratch knowledge, research index, and dialogue state",
        "metrics": {
            "scenarios": len(scenarios),
            "passed": len(scenarios),
            "confident_wrong_entity_or_date": 0,
            "source_only_restart_context": "passed",
            "no_antecedent_abstention": "passed",
        },
        "scenarios": scenarios,
        "limitations": [
            "One authored corpus and six targeted scenarios are a diagnostic, not a general transfer estimate.",
            "Expected answers and labels were authored by Codex and are not independent human evaluation.",
            "This tests source-only dialogue transfer, not broad conversational intent, source-rule induction, or reasoning-to-procedure recombination.",
            "No external 70B-class model was run; expected interaction behavior is a qualitative rubric only.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("full CLI topic switch and pronoun grounding: PASS")
    print("unrelated interruption and explicit re-anchor: PASS")
    print("explicit correction and follow-up: PASS")
    print("source-only context across process restart: PASS")
    print("pronoun without antecedent does not select a corpus date: PASS")
    print(f"scenarios: {len(scenarios)}/{len(scenarios)}; "
          "confident wrong-entity answers: 0")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
