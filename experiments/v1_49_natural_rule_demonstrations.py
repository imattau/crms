"""Check conversational rule demonstrations in the terminal chat.

Run from the project root with:
    python3 experiments/v1_49_natural_rule_demonstrations.py
"""

from __future__ import annotations

import json
from collections import Counter
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (_natural_rule_demonstration, _natural_rule_demonstrations,
                       _natural_rule_feedback, _natural_rule_request,
                       _natural_rule_shared_phrases,
                       _natural_rule_requests)
from crms_model import CRMSModel, Step, _apply_procedure


def main() -> None:
    if CRMSModel(max_workers=1).retry("missing instruction").status != "need_examples":
        raise SystemExit("retry without stored examples should request teaching evidence")

    # One reverse example leaves many valid procedures. The follow-up should
    # use a conventional list while retaining most of the best probe's split.
    ambiguous = CRMSModel(max_workers=1).teach(
        "reverse the list", [([1, 2, 3], [3, 2, 1])])
    if (ambiguous.status != "need_more_examples"
            or ambiguous.contrastive_input is None
            or len(ambiguous.contrastive_input) > 8
            or min(ambiguous.contrastive_input) < 1
            or max(ambiguous.contrastive_input) > 8
            or len(set(ambiguous.contrastive_input))
               != len(ambiguous.contrastive_input)):
        raise SystemExit(
            f"ambiguous rule used an awkward contrastive input: {ambiguous}")
    candidates = [tuple(Step(item["operation"], item.get("parameters", {}))
                        for item in procedure)
                  for procedure in ambiguous.candidate_procedures or []]
    if not candidates:
        raise SystemExit("ambiguous rule lost its candidate procedures")
    readable_outputs = [tuple(_apply_procedure(
        procedure, ambiguous.contrastive_input)) for procedure in candidates]
    best_outputs = [tuple(_apply_procedure(procedure, [0, -1, 0]))
                    for procedure in candidates]
    readable_counts = Counter(readable_outputs)
    best_counts = Counter(best_outputs)
    if (len(readable_counts) * 5 < len(best_counts) * 4
            or max(readable_counts.values()) > 2 * max(best_counts.values())):
        raise SystemExit(
            "readable contrastive input lost too much candidate separation")

    parsed = _natural_rule_demonstration(
        "Please teach reverse the list [1, 2, 3] -> [3, 2, 1].")
    if parsed != ("reverse the list", [1, 2, 3], [3, 2, 1]):
        raise SystemExit(f"natural demonstration parsed incorrectly: {parsed}")
    natural_forms = (
        ("For input [1,2,3], reverse the list produces [3,2,1].",
         ("reverse the list", [1, 2, 3], [3, 2, 1])),
        ("Applying reverse the list to [1,2,3] yields [3,2,1].",
         ("reverse the list", [1, 2, 3], [3, 2, 1])),
        ("The result of reverse the list on [1,2,3] is [3,2,1].",
         ("reverse the list", [1, 2, 3], [3, 2, 1])),
    )
    for message, expected in natural_forms:
        if _natural_rule_demonstration(message) != expected:
            raise SystemExit(f"bounded natural example form was misparsed: {message}")
    batch = _natural_rule_demonstrations(
        "reverse the list: [1,2,3] -> [3,2,1]; [5,0,-2] -> [-2,0,5]"
    )
    if batch != ("reverse the list", [([1, 2, 3], [3, 2, 1]),
                                      ([5, 0, -2], [-2, 0, 5])]):
        raise SystemExit(f"bounded example batch was misparsed: {batch}")
    and_batch = _natural_rule_demonstrations(
        "reverse the list: [] -> [] and [4,5] -> [5,4]")
    if and_batch != ("reverse the list", [([], []), ([4, 5], [5, 4])]):
        raise SystemExit(f"and-separated example batch was misparsed: {and_batch}")
    if _natural_rule_demonstrations(
            "reverse the list: [1,,2] -> [2,1]; [3,4] -> [4,3]") is not None:
        raise SystemExit("malformed example batch was partially accepted")
    shared = _natural_rule_shared_phrases(
        'Teach both "reverse the list" and "invert the sequence" using the same '
        'examples: [1,2,3] -> [3,2,1]; [5,0,-2] -> [-2,0,5]')
    if shared != (("reverse the list", "invert the sequence"),
                  [([1, 2, 3], [3, 2, 1]), ([5, 0, -2], [-2, 0, 5])]):
        raise SystemExit(f"shared phrase teaching parsed incorrectly: {shared}")
    if _natural_rule_shared_phrases(
            'Teach both "reverse the list" and "sort the list" using the same '
            'examples: [1,2,3] -> [3,2,1]') is not None:
        raise SystemExit("one shared example incorrectly licensed a phrase group")
    if _natural_rule_demonstrations(
            "reverse the list: [1,2] -> [2,1] and then [3,4] -> [4,3]") is not None:
        raise SystemExit("unrecognized batch separator was accepted")
    if (_natural_rule_feedback("For that input, the result is [3,2,1].")
            != [3, 2, 1]
            or _natural_rule_feedback("It returns [3,2,1].") != [3, 2, 1]):
        raise SystemExit("natural output-only feedback form was not recognized")
    if _natural_rule_demonstration("reverse the list [1,,2] -> [2,1]") is not None:
        raise SystemExit("malformed integer list was accepted as a demonstration")
    if _natural_rule_request("Reverse the list []") != ("Reverse the list", []):
        raise SystemExit("empty-list prediction request was not parsed")
    if _natural_rule_requests("Reverse the list [1,2] and [3,4].") != (
            "Reverse the list", [[1, 2], [3, 4]]):
        raise SystemExit("multiple input lists were not parsed for one rule")
    if _natural_rule_request("Reverse the list [1,2] and [3,4]") is not None:
        raise SystemExit("multiple inputs were silently collapsed into one request")
    if _natural_rule_requests("Reverse the list [1,2] and sort [3,4]") is not None:
        raise SystemExit("a multi-instruction query was misread as one rule")
    if _natural_rule_request("The output is [3,2,1]") is not None:
        raise SystemExit("output-only feedback was misread as a new instruction")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        turns = [
            "reverse the list: [1,2,3] -> [3,2,1]; [5,0,-2] -> [-2,0,5]",
            "reverse the list [0,1,2,3] -> [3,2,1,0]",
            "Please teach reverse the list [] -> []",
            "Reverse the list [7,1,-4] and [2,8]",
            "Reverse the list []",
            "/rules",
            "/quit",
        ]
        rules = temp / "rules.json"
        rule_session = temp / "rule-session.json"
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--rules", str(rules),
             "--rule-session", str(rule_session),
             "--knowledge", str(temp / "knowledge.json"),
             "--index", str(temp / "index.json"),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rule-depth", "1"],
            input="\n".join(turns) + "\n", text=True,
            capture_output=True, check=True, timeout=30)
        output = result.stdout
        required = (
            "Rule learning status: learned.",
            "CRMS> [-4, 1, 7]",
            "reverse the list: reverse",
        )
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"conversational teaching missed {missing}:\n{output}")
        if output.count("CRMS> []") < 1:
            raise SystemExit(f"empty-list teaching/prediction failed:\n{output}")
        if "CRMS> [8, 2]" not in output:
            raise SystemExit(f"multi-input rule application failed:\n{output}")
        if not rules.exists():
            raise SystemExit("conversationally taught rules were not persisted")
        restored = CRMSModel(rules, max_composition_depth=1, max_workers=1)
        stored_examples = restored._examples.get("reverse the list", [])
        if (([], []) not in stored_examples
                or ([1, 2, 3], [3, 2, 1]) not in stored_examples
                or ([5, 0, -2], [-2, 0, 5]) not in stored_examples):
            raise SystemExit("batch or empty-list demonstrations did not persist")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        rules = temp / "rules.json"
        turns = (
            'Teach both "reverse the list" and "invert the sequence" using the '
            'same examples: [1,2,3] -> [3,2,1]; [5,0,-2] -> [-2,0,5]\n'
            'Invert the sequence [8,1,4]\n/quit\n')
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--rules", str(rules),
             "--knowledge", str(temp / "knowledge.json"),
             "--index", str(temp / "index.json"),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rule-depth", "1"],
            input=turns, text=True, capture_output=True,
            check=True, timeout=30)
        if ("Both phrases are grounded to the same learned procedure" not in result.stdout
                or "CRMS> [4, 1, 8]" not in result.stdout):
            raise SystemExit(f"shared phrase learning failed in chat:\n{result.stdout}")
        restored = CRMSModel(rules, max_composition_depth=1, max_workers=1)
        if (restored._procedures.get("reverse the list")
                != restored._procedures.get("invert the sequence")
                or restored.predict("invert the sequence", [7, 2]).output != [2, 7]):
            raise SystemExit("shared phrase behavior did not persist independently")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        rules = temp / "rules.json"
        baseline = CRMSModel(max_composition_depth=1, max_workers=1)
        sort_examples = [([3, 1, 2], [1, 2, 3]), ([5, 0, -2], [-2, 0, 5])]
        if baseline.teach("sort the list", sort_examples).status != "learned":
            raise SystemExit("could not establish the conflicting phrase baseline")
        baseline.save(rules)
        mismatch = (
            'Teach both "reverse the list" and "sort the list" using the same '
            'examples: [1,2,3] -> [3,2,1]; [5,0,2] -> [2,0,5]\n/quit\n')
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--rules", str(rules),
             "--knowledge", str(temp / "knowledge.json"),
             "--index", str(temp / "index.json"),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rule-depth", "1"],
            input=mismatch, text=True, capture_output=True,
            check=True, timeout=30)
        restored = CRMSModel(rules, max_composition_depth=1, max_workers=1)
        if ("no rules were changed" not in result.stdout
                or "reverse the list" in restored._procedures
                or restored._procedures.get("sort the list")
                != baseline._procedures.get("sort the list")
                or restored._examples.get("sort the list") != sort_examples):
            raise SystemExit("incompatible phrase grouping partially committed")

    # The output-only teacher reply must bind to the exact pending probe, even
    # when the chat process exits and resumes between the request and reply.
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        rules = temp / "rules.json"
        rule_session = temp / "rule-session.json"
        common_args = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rules), "--rule-session", str(rule_session),
            "--knowledge", str(temp / "knowledge.json"),
            "--index", str(temp / "index.json"),
            "--dialogue-state", str(temp / "dialogue.json"),
            "--rule-depth", "1",
        ]
        first = subprocess.run(
            common_args,
            input="reverse the list [1,2,3] -> [3,2,1]\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        if "Please provide the intended output for input [0, -1]." not in first.stdout:
            raise SystemExit(f"contrastive request was not presented:\n{first.stdout}")
        pending = json.loads(rule_session.read_text(encoding="utf-8"))
        if pending.get("input") != [0, -1]:
            raise SystemExit(f"contrastive input was not persisted: {pending}")
        first_model = CRMSModel(rules, max_workers=1)
        if "reverse the list" in first_model._procedures:
            raise SystemExit("an ambiguous first demonstration was committed")

        resumed = subprocess.run(
            common_args,
            input="What about [9,8,7]?\nFor that input, the result is [-1,0]\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        restored = CRMSModel(rules, max_workers=1)
        expected_feedback = ([0, -1], [-1, 0])
        if expected_feedback not in restored._examples.get("reverse the list", []):
            raise SystemExit("output-only reply was not bound to the pending probe")
        if ([9, 8, 7], [3, 2, 1, 0]) in restored._examples.get(
                "reverse the list", []):
            raise SystemExit("an unrelated query was mistaken for teacher feedback")
        if "Rule learning status: learned." not in resumed.stdout:
            raise SystemExit("output-only reply did not resolve active learning:\n"
                             + resumed.stdout)

    # A no-fit proposal set can still ask a grounded contrastive question.
    # Its pending input must survive a restart and the answer becomes another
    # demonstration that filters the advisory candidates.
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        values = list(range(20))
        first_output = values[7:] + values[:7]
        probe_result = CRMSModel(
            max_composition_depth=1, max_workers=1).teach(
                "rotate values", [(values, first_output)])
        probe = probe_result.contrastive_input
        if (probe_result.status != "no_fit" or probe is None
                or not probe_result.proposed_procedures):
            raise SystemExit("out-of-range rotation did not provide bounded feedback")
        expected = probe[7:] + probe[:7]
        rules = temp / "rules.json"
        rule_session = temp / "rule-session.json"
        common_args = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rules), "--rule-session", str(rule_session),
            "--knowledge", str(temp / "knowledge.json"),
            "--index", str(temp / "index.json"),
            "--dialogue-state", str(temp / "dialogue.json"),
            "--rule-depth", "1",
        ]
        first = subprocess.run(
            common_args,
            input=(f"rotate values {values} -> {first_output}\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if "Rule learning status: no_fit." not in first.stdout:
            raise SystemExit(f"out-of-range procedure was misreported:\n{first.stdout}")
        pending = json.loads(rule_session.read_text(encoding="utf-8"))
        if pending.get("input") != probe:
            raise SystemExit(f"no-fit probe was not persisted: {pending}")
        resumed = subprocess.run(
            common_args,
            input=(f"The output is {expected}\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        restored = CRMSModel(rules, max_composition_depth=1, max_workers=1)
        if (probe, expected) not in restored._examples.get("rotate values", []):
            raise SystemExit("no-fit feedback was not bound to its persisted probe")
        if "Rule learning status: no_fit." not in resumed.stdout:
            raise SystemExit("proposal feedback was incorrectly committed:\n"
                             + resumed.stdout)

    # A persisted no-fit corpus can be reopened with a wider parameter bound,
    # allowing a previously advisory modulus to enter ordinary rule search.
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        rules = temp / "rules.json"
        common_args = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rules),
            "--knowledge", str(temp / "knowledge.json"),
            "--index", str(temp / "index.json"),
            "--dialogue-state", str(temp / "dialogue.json"),
            "--rule-session", str(temp / "rule-session.json"),
            "--rule-depth", "1",
        ]
        first = subprocess.run(
            common_args,
            input=("keep multiples of seven [7,10,14,21] -> [7,14,21]\n"
                   "keep multiples of seven [28,6,35,49] -> [28,35,49]\n"
                   "/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if "Rule learning status: no_fit." not in first.stdout:
            raise SystemExit("bounded CLI did not retain the out-of-range rule examples")
        widened = subprocess.run(
            common_args + ["--rule-max-modulus", "7"],
            input=("/retry-rule keep multiples of seven\n"
                   "Keep multiples of seven [14,15,21]\n/rules\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("Rule learning status: learned." not in widened.stdout
                or "keep multiples of seven: keep_multiples_k" not in widened.stdout
                or "[14, 21]" not in widened.stdout):
            raise SystemExit(f"widened CLI search did not commit the grounded modulus:\n{widened.stdout}")
        restored = CRMSModel(rules, max_composition_depth=1,
                             max_workers=1, max_modulus=7)
        if len(restored._examples.get("keep multiples of seven", [])) != 2:
            raise SystemExit("retry duplicated or discarded saved demonstrations")

    # Incomplete-search demonstrations can likewise be reopened after raising
    # the bounded work budget.
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        rules = temp / "rules.json"
        common_args = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--rules", str(rules),
            "--knowledge", str(temp / "knowledge.json"),
            "--index", str(temp / "index.json"),
            "--dialogue-state", str(temp / "dialogue.json"),
            "--rule-session", str(temp / "rule-session.json"),
            "--rule-depth", "1", "--rule-search-expansions", "1",
        ]
        first = subprocess.run(
            common_args,
            input=("/teach-rule reverse the list|1,2,3|3,2,1\n"
                   "/teach-rule reverse the list|1,4,2|2,4,1\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if "Rule learning status: search_incomplete." not in first.stdout:
            raise SystemExit("small search budget did not preserve incomplete status")
        widened = subprocess.run(
            common_args[:-2]
            + ["--rule-search-expansions", "250000"],
            input=("/retry-rule reverse the list\n"
                   "/apply-rule reverse the list|9,2,7\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=30)
        if ("Rule learning status: learned." not in widened.stdout
                or "CRMS> [7, 2, 9]" not in widened.stdout):
            raise SystemExit(f"wider work budget did not resolve the stored search:\n{widened.stdout}")

    print("natural rule demonstrations diagnostic: PASS")
    print("evidence accumulation, persisted feedback, empty lists, prediction, widened parameter/work bounds, retry without duplicate examples: PASS")


if __name__ == "__main__":
    main()
