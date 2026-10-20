"""Answer dated events using a source-local, type-matched entity alias."""

from __future__ import annotations

import re
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_when_evidence
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
EXPECTED_SENTENCE = "The museum opened in 1972 and displays maritime maps."
EXPECTED_PRONOUN_SENTENCE = "It was completed in 80 CE."
REPORT = PROJECT / "experiments" / "reports" / "v1_527_paragraph_anchored_event_date.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def evidence_for(text: str, question: str) -> tuple[CRMSResearchIndex, dict | None]:
    folder = tempfile.TemporaryDirectory(prefix="crms-v1-527-evidence-")
    path = Path(folder.name, "guide.txt")
    path.write_text(text, encoding="utf-8")
    index = CRMSResearchIndex()
    index.add_directory(folder.name)
    # Keep the backing temporary directory alive with the index for citation
    # verification in the caller.
    index._v1_527_tempdir = folder  # type: ignore[attr-defined]
    return index, _natural_when_evidence(index, question)


def main() -> None:
    positive = (
        "The Meridian Museum is in Vale City. "
        + EXPECTED_SENTENCE
    )
    index, evidence = evidence_for(positive, "When did Meridian Museum open?")
    require(evidence is not None and evidence["text"] == EXPECTED_SENTENCE,
            f"paragraph-local class alias did not support the event date: {evidence!r}")
    require(index.resolve_citation(evidence["citation"]) == EXPECTED_SENTENCE,
            "event evidence citation did not resolve to the exact sentence")
    index._v1_527_tempdir.cleanup()  # type: ignore[attr-defined]

    pronoun_positive = (
        "The Colosseum stands in Rome. " + EXPECTED_PRONOUN_SENTENCE
    )
    pronoun_index, pronoun_evidence = evidence_for(
        pronoun_positive, "When was Colosseum completed?")
    require(pronoun_evidence is not None
            and pronoun_evidence["text"] == EXPECTED_PRONOUN_SENTENCE,
            f"same-paragraph pronoun did not support the date: {pronoun_evidence!r}")
    require(pronoun_index.resolve_citation(pronoun_evidence["citation"])
            == EXPECTED_PRONOUN_SENTENCE,
            "pronoun-led date citation did not resolve to the exact sentence")
    pronoun_index._v1_527_tempdir.cleanup()  # type: ignore[attr-defined]

    controls = [
        ("The Meridian Museum is in Vale City.\n\n"
         + EXPECTED_SENTENCE,
         "an alias from a different paragraph was accepted"),
        ("The Meridian Museum is in Vale City. "
         "The observatory opened in 1972.",
         "an entity-class mismatch was accepted"),
        ("The Meridian Museum is in Vale City. "
         "The Harbor Museum is in Eastport. The museum opened in 1972.",
         "an alias with a competing immediate antecedent was accepted"),
        ("The Meridian Museum did not open in 1972.",
         "a negated event date was accepted"),
        ("The Colosseum stands in Rome.\n\n" + EXPECTED_PRONOUN_SENTENCE,
         "a pronoun antecedent from another paragraph was accepted"),
        ("The Colosseum is in Rome. The Eiffel Tower stands in Paris. "
         + EXPECTED_PRONOUN_SENTENCE,
         "a pronoun was bound to a non-subject entity in the prior sentence"),
    ]
    control_results = []
    for source, failure in controls:
        control_index, control = evidence_for(
            source, "When did Meridian Museum open?")
        require(control is None, f"{failure}: {control!r}")
        control_results.append({"control": failure, "rejected": control is None})
        control_index._v1_527_tempdir.cleanup()  # type: ignore[attr-defined]

    with tempfile.TemporaryDirectory(prefix="crms-v1-527-chat-") as temp:
        root = Path(temp)
        source_dir = root / "source"
        source_dir.mkdir()
        (source_dir / "guide.txt").write_text(positive, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(source_dir)
        index_path = root / "index.json"
        index.save(index_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--index", str(index_path),
            "--feedback-db", str(root / "feedback.sqlite3"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command,
            input="Where is the Meridian Museum?\nWhen did it open?\nwhy?\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = result.stdout + result.stderr
        require(result.returncode == 0 and "Traceback" not in output,
                f"fresh CLI failed: {output[-2500:]}")
        require("The museum opened in 1972" in output
                and "1984" not in output,
                f"resolved pronoun did not answer from the anchored event: {output}")
        require("not an accepted fact" in output,
                "source-only date answer was mislabeled as accepted knowledge")
        citation = re.search(r"Citation: ([^\s]+#sha256=[^\s]+)", output)
        require(citation is not None,
                "why? did not expose the event sentence citation")
        require(index.resolve_citation(citation.group(1)) == EXPECTED_SENTENCE,
                "chat explanation citation does not resolve to the exact sentence")

    with tempfile.TemporaryDirectory(prefix="crms-v1-527-topic-switch-") as temp:
        root = Path(temp)
        source_dir = root / "source"
        source_dir.mkdir()
        corpus = (
            "The Eiffel Tower stands in Paris. It was completed in 1889.\n\n"
            "The Colosseum stands in Rome. It was completed in 80 CE."
        )
        (source_dir / "places.txt").write_text(corpus, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(source_dir)
        index_path = root / "index.json"
        index.save(index_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--index", str(index_path),
            "--feedback-db", str(root / "feedback.sqlite3"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command,
            input=("Where is the Eiffel Tower?\nWhat about the Colosseum?\n"
                   "When was it completed?\nwhy?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        output = result.stdout + result.stderr
        require(result.returncode == 0 and "Traceback" not in output,
                f"topic-switch CLI failed: {output[-2500:]}")
        answer_lines = [line for line in output.splitlines() if "CRMS>" in line]
        require(len(answer_lines) >= 4
                and "80 CE" in answer_lines[2]
                and "1889" not in answer_lines[2],
                f"Colosseum follow-up did not use its local date: {output}")
        require("80 CE" in answer_lines[3]
                and "1889" not in answer_lines[3],
                f"why? did not explain the current date evidence: {output}")
        citation = re.search(r"Citation: ([^\s]+#sha256=[^\s]+)", output)
        require(citation is not None
                and index.resolve_citation(citation.group(1))
                == EXPECTED_PRONOUN_SENTENCE,
                "topic-switch explanation citation does not resolve exactly")

    report = {
        "experiment": "v1_527_paragraph_anchored_event_date",
        "source": "independently authored, two-sentence paragraph",
        "success": {
            "entity_alias_same_paragraph": True,
            "pronoun_led_passive_date_same_paragraph": True,
            "resolved_followup_through_standard_effort_chat": True,
            "why_citation_resolves_exactly": True,
            "source_only_label_preserved": True,
            "eiffel_colosseum_topic_switch_uses_colosseum_date": True,
        },
        "negative_controls": control_results,
        "limitations": [
            "The date grammar accepts bounded when-did and when-was predicates with year or era-qualified dates.",
            "Pronoun binding requires the named entity to be the subject of the immediately preceding sentence in the same paragraph.",
            "This does not establish general temporal-question transfer or broad event-coreference coverage.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")

    print("paragraph-local entity-class alias: PASS")
    print("same-paragraph pronoun and passive date: PASS")
    print("separate paragraph, mismatched class, competing antecedent, and negation: PASS")
    print("fresh chat, Eiffel/Colosseum topic switch, and why? citation: PASS")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
