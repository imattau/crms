"""Keep weak copular parses out of self-discovered language frames."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-frame-quality-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "research.sqlite")
        rows = (
            ("weak-1", "Alaskan king crab fishing is a famous example."),
            ("weak-2", "Arctic king crab fishing is a notable example."),
            ("coord-1", "April is a spring month and an autumn month."),
            ("coord-2", "June is a summer month and a winter month."),
            ("pronoun-1", "Now it is a Beppyo shrine."),
            ("pronoun-2", "Then it is a local temple."),
            ("exist-1", "There is a festival on May 3rd."),
            ("exist-2", "There is a ceremony on June 4th."),
            ("valid-1", "Allarmont is a commune."),
            ("valid-2", "Ambacourt is a commune."),
            ("valid-3", "Paris is a city."),
            ("valid-4", "Rome is a city."),
            ("bad-join-1", "Ravi joined Northwave Records and began touring."),
            ("bad-join-2", "Mira joined Southline Records and started recording."),
            ("bad-connect-1", "The Canal connects the east coast with the west coast."),
            ("bad-connect-2", "The Road connects the north shore with the south shore."),
            ("bad-discourse-1", "Militarily the battle was a draw."),
            ("bad-discourse-2", "Militarily the contest was a victory."),
            ("bad-relative-1", "Van Dine was a writer who wrote detective novels."),
            ("bad-relative-2", "Ada was a scientist who studied chemistry."),
            ("bad-clipped-1", "Luxembourg is a small country located in Europe."),
            ("bad-clipped-2", "The association is an independent charity based in London."),
            ("bad-title-1", '"Layered Magnetic Structures: evidence for Fe-layers across Cr-interlayers."'),
            ("bad-title-2", '"Important Structures: coupling across Nu-interlayers."'),
            ("bad-passive-1", "2007 – The Declaration is adopted by the Assembly."),
            ("bad-passive-2", "2008 – The Agreement is approved by the Council."),
            ("bad-boundary-1", "Four Soviet armies attacked the northern group."),
            ("bad-boundary-2", "Five Soviet armies advanced toward the city."),
            ("bad-versus-1", "Team A debuted versus Hungary."),
            ("bad-versus-2", "Team B debuted versus France."),
            ("bad-years-1", "About 3000 years before, the Polynesians settled in Tongatapu."),
            ("bad-years-2", "About 4000 years before, the people settled in Fiji."),
            ("bad-long-relation-1", "The Bats played at a stadium called Cardinal Stadium."),
            ("bad-long-relation-2", "The Owls played at a stadium called Forest Park."),
            ("bad-number-noun-1", "Approximately 900 species have been found."),
            ("bad-number-noun-2", "Nearly 1200 species have been found."),
            ("bad-copula-boundary-1", "Burkholderia species are gram-negative bacteria."),
            ("bad-copula-boundary-2", "Methanobacteria species are methane-producing microbes."),
            ("bad-preposition-boundary-1", "The Kamo River flows along its eastern border."),
            ("bad-preposition-boundary-2", "The River Vartry flows through the town."),
            ("bad-prep-subject-1", "A campus in Silicon Valley called Apple Campus 3."),
            ("bad-prep-subject-2", "An office in Nacre City called Meridian Tower."),
            ("bad-ordinal-relation-1", "Calhoun becomes the first Vice President to resign."),
            ("bad-ordinal-relation-2", "Sullivan becomes the first American woman to perform a spacewalk."),
            ("bad-clipped-object-1", "Eisenhower becomes Supreme Commander of NATO Europe."),
            ("bad-clipped-object-2", "Nimitz becomes Fleet Admiral of the Navy."),
            ("verb-1", "Mara designed Engine."),
            ("verb-2", "Nema designed Bridge."),
        )
        for document_id, sentence in rows:
            index.add_document(document_id, document_id, sentence,
                               f"{document_id}.txt")
        # Article titles may be useful for quoted retrieval, but a sentence
        # whose grammatical subject is only a pronoun must not license a
        # reusable corpus relation frame from title substitution alone.
        index.add_document(
            "page-pronoun-1", "Mara Vell", "She is a scientist.",
            "page-pronoun-1.txt")
        index.add_document(
            "page-pronoun-2", "Nera Vell", "She is a scientist.",
            "page-pronoun-2.txt")
        proposals = CRMSKnowledgeBase().propose_corpus_relation_frames(
            index, minimum_examples=2, maximum_documents=100,
            maximum_sentences=200, maximum_proposals=20)
        commune = next((proposal for proposal in proposals
                       if proposal["relation"] == "is-a"
                       and any(item["object"] == "commune"
                               for item in proposal["support"])), None)
        require(commune is not None,
                f"valid repeated type frame was lost: {proposals}")
        designed = next((proposal for proposal in proposals
                         if proposal["relation"] == "designed"), None)
        require(designed is not None,
                f"valid action frame was lost: {proposals}")
        rejected_relations = {
            "across", "armies", "adopted", "approved", "versus", "years",
            "played at a stadium called", "species", "flows", "becomes the first",
            "called",
        }
        require(not any(proposal["relation"] in rejected_relations
                        for proposal in proposals),
                f"quoted, timeline, passive, or noun-boundary noise entered rules: {proposals}")
        require(not any(
            support["sentence"] == "She is a scientist."
            for proposal in proposals for support in proposal["support"]),
            "page-title pronouns were treated as stated relation subjects")
        learned_objects = {
            (support["sentence"], support["object"])
            for proposal in proposals for support in proposal["support"]}
        require(("Eisenhower becomes Supreme Commander of NATO Europe.",
                 "Supreme Commander of NATO Europe") in learned_objects,
                f"the of-complement was not retained in the object: {learned_objects}")
        require(("Nimitz becomes Fleet Admiral of the Navy.",
                 "Fleet Admiral of the Navy") in learned_objects,
                f"the second of-complement was not retained: {learned_objects}")
        bad_subjects = {"now it", "there", "then it"}
        for proposal in proposals:
            for support in proposal["support"]:
                require(support["subject"].casefold() not in bad_subjects,
                        f"pronoun/existential subject entered a frame: {support}")
                require(support["object"].casefold() not in {
                    "famous example", "notable example"},
                    f"dangling example complement entered a frame: {support}")
                require(not any(token in support["object"].casefold().split()
                                for token in {"who", "which", "that"}),
                        f"relative clause entered a class phrase: {support}")
                require(support["object"].casefold().split()[-1] not in {
                    "located", "based", "called", "known", "named",
                    "described", "considered", "used",
                }, f"clipped postmodifier entered a class phrase: {support}")
                require(support["subject"].casefold().split()[0]
                        not in {"militarily", "finally", "however", "therefore"},
                        f"discourse modifier entered a subject: {support}")
                require(" and " not in support["sentence"].casefold()
                        and " or " not in support["sentence"].casefold(),
                        f"coordinated sentence entered a flat frame: {support}")
                if support["relation"] in {"connect", "connects", "connected"}:
                    require(" with " not in support["sentence"].casefold(),
                            f"two-endpoint connection was reduced to one object: {support}")
        index.close()

    print("corpus relation-frame quality gates: PASS")
    print("dangling, coordinated, quoted, timeline, passive-role and noun-boundary noise rejected; valid frames retained: PASS")


if __name__ == "__main__":
    main()
