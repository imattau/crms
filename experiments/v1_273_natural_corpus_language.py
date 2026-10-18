"""Exercise natural corpus overview and described-paper queries on the large corpus."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import (
    _natural_corpus_topics_request,
    _natural_paper_description_request,
    _render_corpus_topics,
    _render_research_list,
)
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index_path = (Path(__file__).resolve().parents[1]
                  / "data/crms_project_model_academic.sqlite.memories/research.sqlite")
    if not index_path.exists():
        raise SystemExit(f"large corpus index not found: {index_path}")
    index = CRMSSQLiteResearchIndex.load(index_path)

    overview_question = "What research topics are represented in this model?"
    require(_natural_corpus_topics_request(overview_question),
            "corpus overview intent was not recognized")
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    resolved, clarification = dialogue._resolve_pronoun(overview_question)
    require(resolved == overview_question and clarification is None,
            "'this model' was treated as an unresolved pronoun")
    overview = _render_corpus_topics(index)
    require("Recurring terms in indexed research titles" in overview
            and "https://arxiv.org/abs/" in overview,
            "overview omitted scope or cited title examples")

    paper_question = "Tell me about the paper that studies toroidal graph cops."
    topic = _natural_paper_description_request(paper_question)
    require(topic == "toroidal graph cops",
            f"relative-clause paper topic was not extracted: {topic!r}")
    resolved, clarification = dialogue._resolve_pronoun(paper_question)
    require(resolved == paper_question and clarification is None,
            "relative-clause 'that' was treated as an entity pronoun")
    result, _documents = _render_research_list(index, topic)
    require("On the cop number of toroidal graphs" in result
            and "Some Game Theoretic Remarks" not in result,
            f"paper query did not select the title-focused source: {result}")

    print("natural corpus language diagnostic: PASS")
    print("corpus deictic and paper-relative clauses route to bounded, cited research")


if __name__ == "__main__":
    main()
