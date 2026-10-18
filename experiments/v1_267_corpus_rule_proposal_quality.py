"""Keep weak sentence openings and metadata out of corpus rule proposals."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    learner = CRMSKnowledgeBase()
    rejected = (
        "Such edits are the common case.",
        "Both methods are theoretically well-founded.",
        "There is a fair amount of noise in the sample.",
        "First was a brute force attack using either bit vector.",
        "By using the mechanism, symmetry breaking can be realized dynamically.",
        "The rest of the paper is structured as follows.",
        "X is the R module generated from the input graph.",
        "Title: Discrete Diffusion Models are Minimax Optimal Under Sparsity",
    )
    for sentence in rejected:
        if learner._discover_surface_relation_candidates(sentence, source="fixture"):
            raise SystemExit(f"weak subject or title produced a fact proposal: {sentence}")

    valid = "Abstraction is a single-level grammar extension."
    candidates = learner._discover_surface_relation_candidates(valid, source="fixture")
    if (len(candidates) != 1
            or (candidates[0].subject, candidates[0].relation,
                candidates[0].object) !=
               ("Abstraction", "is-a", "single-level grammar extension")):
        raise SystemExit(f"bounded class-membership claim was lost: {candidates}")
    common_noun = learner._discover_surface_relation_candidates(
        "The parser is a tokenizer.", source="fixture")
    if (len(common_noun) != 1
            or (common_noun[0].subject, common_noun[0].relation,
                common_noun[0].object) != ("parser", "is-a", "tokenizer")):
        raise SystemExit(f"bounded common-noun classification was lost: {common_noun}")
    clipped_common_noun = learner._discover_surface_relation_candidates(
        "modality possess is an open research problem.", source="fixture")
    if clipped_common_noun:
        raise SystemExit(f"lowercase source fragment became a class claim: {clipped_common_noun}")

    index = CRMSResearchIndex()
    for document_id, sentence in (
            ("authored-a", "Ada authored Engine."),
            ("authored-b", "Bea authored Compiler."),
            ("weak-a", rejected[0]),
            ("weak-b", rejected[1]),
            ("title-a", rejected[2]),
            ("comma-quality-a",
             "Finally, the quality of the body image produced by the network is evaluated."),
            ("comma-quality-b",
             "However, the quality of automatic parses can vary greatly."),
            ("comma-most-a",
             "Finally, most of our interviewees do not report high enjoyment."),
            ("comma-most-b",
             "However, most of them either focus on ranked list evaluation."),
            ("comma-class-a",
             "Interestingly, a class of butterfly matrices belongs to this category."),
            ("comma-set-a",
             "In this paper, we introduce DR-Tools Suite, a set of lightweight tools.")):
        index.add_document(document_id, "Corpus fixture", sentence,
                           f"{document_id}.txt")
    proposals = learner.propose_corpus_relation_frames(index)
    authored = [proposal for proposal in proposals
                if proposal["relation"] == "authored"]
    if len(authored) != 1 or len(authored[0]["support"]) != 2:
        raise SystemExit(f"valid corpus pattern did not survive filtering: {proposals}")
    if any(proposal["relation"] in {"edits", "methods", "are"}
           for proposal in proposals):
        raise SystemExit(f"weak or title-derived relation remained: {proposals}")
    comma_artifacts = {"quality of", "most of", "a class of", "a set of"}
    if comma_artifacts & {proposal["relation"] for proposal in proposals}:
        raise SystemExit(
            f"comma-bearing discourse/appositive text became a corpus rule: {proposals}")
    if learner.facts():
        raise SystemExit("proposal quality check mutated accepted knowledge")
    negative = learner._discover_surface_relation_candidates(
        "CRMS is not a language model.", source="fixture")
    if (len(negative) != 1 or negative[0].polarity
            or negative[0].subject != "CRMS"):
        raise SystemExit(f"explicit named-subject negation was lost: {negative}")
    clipped = learner._discover_surface_relation_candidates(
        "coverage is not a success if unsupported conclusions are returned.",
        source="fixture")
    if clipped:
        raise SystemExit(f"lowercase continuation became a named negative fact: {clipped}")
    print("corpus rule proposal quality diagnostic: PASS")
    print("weak pronoun/demonstrative subjects and title metadata rejected; "
          "valid copular class and repeated authored frame retained for review")


if __name__ == "__main__":
    main()
