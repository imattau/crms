"""Measure exact, staged compression of learned rule observations.

This is a storage/structure diagnostic only. Encodings must reconstruct every
example and procedure exactly; semantic procedure sharing is permitted only
when CRMS's exact canonicalizer groups them.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _procedure_dict, _semantic_key


TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]+", flags=re.UNICODE)


def encoded_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def deduplicate(records: list[dict]) -> list[dict]:
    unique = {}
    for record in records:
        key = json.dumps(record, sort_keys=True, ensure_ascii=False)
        unique.setdefault(key, record)
    return list(unique.values())


def grouped_records(records: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    order = []
    for record in records:
        index = len(grouped[record["instruction"]])
        grouped[record["instruction"]].append({
            "input": record["input"], "output": record["output"]})
        order.append([record["instruction"], index])
    return {"groups": dict(sorted(grouped.items())), "order": order}


def decode_grouped(grouped: dict) -> list[dict]:
    return [{"instruction": instruction,
             **grouped["groups"][instruction][index]}
            for instruction, index in grouped["order"]]


def semantic_procedure_encoding(procedures: dict[str, list[dict]]) -> dict:
    groups: dict[tuple, list[str]] = defaultdict(list)
    for phrase, payload in procedures.items():
        procedure = tuple(Step(step["operation"], step.get("parameters", {}))
                          for step in payload)
        groups[_semantic_key(procedure)].append(phrase)

    classes = []
    assignments = []
    for group_id, (_behavior, phrases) in enumerate(
            sorted(groups.items(), key=lambda item: min(item[1]))):
        phrases = sorted(phrases)
        representative = phrases[0]
        representative_procedure = procedures[representative]
        rep_steps = tuple(Step(step["operation"], step.get("parameters", {}))
                          for step in representative_procedure)
        test_inputs = [[], [1], [0, -2, 5], [3, 2, -1, 8], [-7, 4, 4, 0]]
        for phrase in phrases:
            candidate_steps = tuple(Step(step["operation"], step.get("parameters", {}))
                                    for step in procedures[phrase])
            if any(_apply_procedure(rep_steps, values)
                   != _apply_procedure(candidate_steps, values)
                   for values in test_inputs):
                raise SystemExit("semantic canonicalizer merged differing probe behavior")
            residual = (None if procedures[phrase] == representative_procedure
                        else procedures[phrase])
            assignments.append([phrase, group_id, residual])
        classes.append(representative_procedure)
    return {"classes": classes, "assignments": assignments}


def decode_semantic_procedures(encoded: dict) -> dict[str, list[dict]]:
    decoded = {}
    for phrase, class_id, residual in encoded["assignments"]:
        decoded[phrase] = (encoded["classes"][class_id]
                           if residual is None else residual)
    return dict(sorted(decoded.items()))


def factor_phrases(bundle: dict) -> tuple[dict, list[str]]:
    phrases = sorted({record["instruction"] for record in bundle["examples"]}
                     | set(bundle["procedures"]))
    tokenized = {phrase: TOKEN_RE.findall(phrase) for phrase in phrases}

    # Select repeated token sequences only when the actual JSON encoding gets
    # smaller. The residual token stream preserves all whitespace and symbols.
    candidates = set()
    for tokens in tokenized.values():
        for start in range(len(tokens)):
            for end in range(start + 2, len(tokens) + 1):
                candidates.add(tuple(tokens[start:end]))
    candidates = [candidate for candidate in candidates
                  if sum(any(tokens[i:i + len(candidate)] == list(candidate)
                             for i in range(len(tokens) - len(candidate) + 1))
                         for tokens in tokenized.values()) >= 2]
    candidates.sort(key=lambda candidate: (-len("".join(candidate)), candidate))

    accepted: list[tuple[str, ...]] = []

    def serialized(patterns: list[tuple[str, ...]]) -> dict:
        encoded_streams = []
        for phrase in phrases:
            tokens = tokenized[phrase]
            output = []
            i = 0
            while i < len(tokens):
                matches = [(len(pattern), index) for index, pattern in enumerate(patterns)
                           if tuple(tokens[i:i + len(pattern)]) == pattern]
                if matches:
                    length, index = max(matches)
                    output.append({"ref": index})
                    i += length
                else:
                    output.append({"text": tokens[i]})
                    i += 1
            encoded_streams.append({"tokens": output})
        return {"dictionary": [list(pattern) for pattern in patterns],
                "phrases": encoded_streams}

    for candidate in candidates:
        before = encoded_size(serialized(accepted))
        trial = accepted + [candidate]
        if encoded_size(serialized(trial)) < before:
            accepted = trial

    encoded = serialized(accepted)
    return encoded, phrases


def decode_phrases(encoded: dict, phrases: list[str]) -> dict[str, str]:
    return dict(zip(phrases, decode_phrase_values(encoded)))


def decode_phrase_values(encoded: dict) -> list[str]:
    dictionary = encoded["dictionary"]
    decoded = []
    for item in encoded["phrases"]:
        parts = []
        for part in item["tokens"]:
            parts.extend(dictionary[part["ref"]] if "ref" in part else [part["text"]])
        decoded.append("".join(parts))
    return decoded


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = {
        "reverse the list": [([1, 4, 2], [2, 4, 1]), ([8, -1, 3], [3, -1, 8])],
        "reverse each sequence": [([1, 4, 2], [2, 4, 1]), ([8, -1, 3], [3, -1, 8])],
        "double each value": [([1, 3], [2, 6]), ([-2, 4], [-4, 8])],
        "scale every number by two": [([1, 3], [2, 6]), ([-2, 4], [-4, 8])],
    }
    for phrase, rows in examples.items():
        result = model.teach(phrase, rows)
        if result.status != "learned":
            raise SystemExit(f"could not learn diagnostic procedure for {phrase}: {result}")
    # Add repeated observations deliberately so the first compression stage is
    # measured on raw records rather than an already deduplicated set.
    model.teach("reverse the list", [examples["reverse the list"][0]])
    model.teach("double each value", [examples["double each value"][0]])

    raw_records = [
        {"instruction": phrase, "input": list(values), "output": list(output)}
        for phrase, rows in model._examples.items()
        for values, output in rows
    ]
    exact_procedures = {
        phrase: _procedure_dict(procedure)
        for phrase, procedure in sorted(model._procedures.items())
    }
    baseline = {"examples": raw_records, "procedures": exact_procedures}
    unique = deduplicate(raw_records)
    grouped = grouped_records(unique)
    grouped_decoded = decode_grouped(grouped)
    if grouped_decoded != unique:
        raise SystemExit("instruction grouping did not reconstruct the exact unique examples")

    semantic_encoded = semantic_procedure_encoding(exact_procedures)
    semantic_decoded = decode_semantic_procedures(semantic_encoded)
    if semantic_decoded != exact_procedures:
        raise SystemExit("semantic grouping/residuals did not reconstruct exact procedures")

    factored, phrase_order = factor_phrases({
        "examples": unique, "procedures": exact_procedures})
    phrase_decoded = decode_phrases(factored, phrase_order)
    if phrase_decoded != {phrase: phrase for phrase in phrase_order}:
        raise SystemExit("phrase dictionary did not reconstruct exact instruction text")

    phrase_ids = {phrase: index for index, phrase in enumerate(phrase_order)}
    indexed_examples = {
        "groups": [grouped["groups"].get(phrase, []) for phrase in phrase_order],
        "order": [[phrase_ids[phrase], index]
                  for phrase, index in grouped["order"]],
    }
    indexed_procedures = {
        "classes": semantic_encoded["classes"],
        "assignments": [[phrase_ids[phrase], class_id, residual]
                        for phrase, class_id, residual
                        in semantic_encoded["assignments"]],
    }
    factored_bundle = {"instruction_tokens": factored,
                       "examples": indexed_examples,
                       "procedures": indexed_procedures}
    decoded_phrases = decode_phrase_values(factored_bundle["instruction_tokens"])
    reconstructed_records = [
        {"instruction": decoded_phrases[phrase_id],
         **indexed_examples["groups"][phrase_id][example_id]}
        for phrase_id, example_id in indexed_examples["order"]
    ]
    reconstructed_procedures = {}
    for phrase_id, class_id, residual in indexed_procedures["assignments"]:
        reconstructed_procedures[decoded_phrases[phrase_id]] = (
            indexed_procedures["classes"][class_id] if residual is None else residual)
    if reconstructed_records != unique:
        raise SystemExit("factored bundle did not reconstruct the exact unique examples")
    if dict(sorted(reconstructed_procedures.items())) != exact_procedures:
        raise SystemExit("factored bundle did not reconstruct exact procedures")

    stage_sizes = {
        "raw observations + procedures": encoded_size(baseline),
        "deduplicated observations": encoded_size({"examples": unique,
                                                     "procedures": exact_procedures}),
        "grouped by instruction": encoded_size({"examples": grouped,
                                                  "procedures": exact_procedures}),
        "grouped observations + semantic procedure groups": encoded_size(
            {"examples": grouped, "procedures": semantic_encoded}),
        "factored phrases + grouped observations + semantic procedures":
            encoded_size(factored_bundle),
    }
    print("lossless rule compression diagnostic: PASS")
    print(f"observations: {len(raw_records)} raw, {len(unique)} unique; "
          f"duplicate cases removed: {len(raw_records) - len(unique)}")
    print(f"procedures: {len(exact_procedures)} phrases, "
          f"{len(semantic_encoded['classes'])} proven behavior groups")
    print(f"exact syntax residuals retained: "
          f"{sum(residual is not None for _, _, residual in semantic_encoded['assignments'])}")
    print(f"shared phrase patterns retained: "
          f"{len(factored['dictionary'])}")
    print("encoded bytes by representation:")
    for label, size in stage_sizes.items():
        change = (100 * (1 - size / stage_sizes["raw observations + procedures"]))
        print(f"  {label}: {size} bytes ({change:+.1f}% vs raw)")
    print("exact example, instruction, and procedure reconstruction: PASS")
    print("semantic grouping held-out probes: PASS")


if __name__ == "__main__":
    main()
