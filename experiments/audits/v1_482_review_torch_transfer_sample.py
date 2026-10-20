"""Apply a frozen Codex review to the v1_481 PyTorch sample.

Run with:
    python3 experiments/audits/v1_482_review_torch_transfer_sample.py

The v1_481 manifest is immutable and committed before this review. Labels are
unblinded, single-rater diagnostics, not independent validation or accuracy
estimates. The source text and extracted fields are preserved with the review.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]

# Label: (review category, explanation).
CANDIDATE_LABELS = {
    "00e1c03326e4": ("reviewable", "The LSTM projection condition and selected behavior are explicit."),
    "027b49c1fa02": ("boundary_error", "The sentence is a truncated code-example line; the predicate ends at 'first'."),
    "02d01684f840": ("boundary_error", "The reduction list alternatives are merged into one candidate."),
    "0548e78011f1": ("boundary_error", "The subject absorbs a neighboring note and the ceil_mode condition."),
    "06a495d081bb": ("reviewable", "The plural values subject and replication behavior are explicit, with its condition retained."),
    "0755ee3df6e8": ("context_needed", "return_indices is a condition; the action subject is implicit in the API operation."),
    "07ced4a10017": ("boundary_error", "Default and parameter-description text are absorbed into the subject."),
    "07f1f870e63e": ("boundary_error", "Two coordinated norm claims are combined into one predicate."),
    "08620d9d51cc": ("context_needed", "This behavior depends on an antecedent outside the cited sentence."),
    "08dfdc0b574f": ("reviewable", "The Parameter remains an explicit subject and the no_grad qualification is preserved."),
    "0c0fa6c4b136": ("reviewable", "The worker-process subject and num_workers condition are explicit."),
    "0d3ca6b7c341": ("boundary_error", "The comparative Whereas clause is extracted as subject and the contrasting claim is merged."),
    "1063d842f4b7": ("boundary_error", "The source excerpt is an incomplete sentence ending at 'described in'."),
    "10a03256ea51": ("boundary_error", "The note and deprecated-argument context are absorbed into the subject."),
    "10a4a6be8cd8": ("boundary_error", "Device and dtype conditions are incorrectly part of the subject."),
    "110a4c443d84": ("boundary_error", "The reduction alternatives are merged, as in the analogous NLLLoss case."),
    "1135c4d0a021": ("reviewable", "embed_dim is the explicit subject; 'Note that' is harmless framing."),
    "1138eb48745d": ("boundary_error", "The padding declaration contaminates the zero-padding subject."),
    "117b4264a51b": ("reviewable", "The computed output size and interpolation behavior are explicit."),
    "12545053821e": ("boundary_error", "A footnote/link fragment contaminates the subject and the URL is absorbed into the predicate."),
}

NON_CANDIDATE_LABELS = {
    "04511538307e": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "313a55ea2be5": ("missed_conditional_behavior", "The decoupled-weight-decay condition contains an explicit negative behavior claim."),
    "51cada2e47eb": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "5537164ae957": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "5eab9c3d15bb": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "702bbe34dcea": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "779c8a7c7a37": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "86128aaa0171": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "8bacf4fd4ef3": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "94b6f9230739": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "97eec7bb4911": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "a28521df12a2": ("incomplete_source_fragment", "The cited span ends at 'the shape will be' and does not contain a recoverable predicate."),
    "a2db2639614e": ("missed_shared_subject", "The coordinated 'will be visible' clause inherits Tensors from the preceding clause."),
    "b0ab7dce41fc": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "c068f2e472a9": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "d091fb6e12d8": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "e252a8ed06ec": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "eadd6cdac8fa": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
    "f562110aea30": ("missed_conditional_behavior", "The bias option's condition and the layer's behavior are stated, but the parser abstains."),
}


def label_rows(rows: list[dict[str, object]], labels: dict[str, tuple[str, str]],
               group: str) -> list[dict[str, object]]:
    result = []
    seen = set()
    for row in rows:
        prefix = str(row["sample_key"])[:12]
        if prefix not in labels or prefix in seen:
            raise SystemExit(f"unexpected {group} sample key: {prefix}")
        seen.add(prefix)
        label, note = labels[prefix]
        result.append({**row, "codex_review_label": label,
                       "review_note": note})
    if seen != set(labels):
        raise SystemExit(f"{group} label keys no longer match frozen manifest")
    return result


def main() -> None:
    manifest_path = PROJECT / "experiments/reports/v1_481_torch_publisher_transfer_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = label_rows(
        manifest["candidate_sample"], CANDIDATE_LABELS, "candidate")
    non_candidates = label_rows(
        manifest["non_candidate_sample"], NON_CANDIDATE_LABELS,
        "non-candidate")
    report = {
        "audit": "v1_482_review_torch_transfer_sample",
        "manifest": "v1_481_torch_publisher_transfer_manifest.json",
        "source_version": manifest["source"]["version"],
        "corpus_sha256": manifest["source"]["corpus_sha256"],
        "label_protocol": (
            "One unblinded Codex pass over the frozen exact source sentences "
            "and candidate fields. These categories diagnose extraction; "
            "they are not a probability-sample accuracy or precision estimate."),
        "candidate_sample": candidates,
        "candidate_label_counts": dict(sorted(Counter(
            row["codex_review_label"] for row in candidates).items())),
        "non_candidate_sample": non_candidates,
        "non_candidate_label_counts": dict(sorted(Counter(
            row["codex_review_label"] for row in non_candidates).items())),
        "limits": manifest["limits"] + [
            "The selected non-candidate rows contain repeated bias-option boilerplate, so they are not 19 independent linguistic patterns.",
            "No parser change was made from this review; use the findings to design a new sample or a new general extraction method, not to retrofit these rows.",
        ],
    }
    output = PROJECT / "experiments/reports/v1_482_torch_transfer_review.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(f"Wrote {output.relative_to(PROJECT)}")
    print(json.dumps({
        "candidate": report["candidate_label_counts"],
        "non_candidate": report["non_candidate_label_counts"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
