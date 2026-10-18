"""Offline runtime diagnostic for the current PMC AWS dataset adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_import_pmc import import_pmc
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def article(pmcid: str, license_href: str, license_text: str, phrase: str,
            fact_sentence: str | None = None) -> bytes:
    body_sentence = fact_sentence or f"Distinct PMC result: {phrase} supports local research."
    return f'''<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<article-id pub-id-type="pmc">{pmcid}</article-id><article-id pub-id-type="doi">10.1234/{pmcid.lower()}</article-id>
<title-group><article-title>PMC {phrase}</article-title></title-group>
<contrib-group><contrib contrib-type="author"><string-name>Grace Hopper</string-name></contrib></contrib-group>
<permissions><license xlink:href="{license_href}"><license-p>{license_text}</license-p></license></permissions>
<abstract><p>Abstract for {phrase}.</p></abstract></article-meta></front>
<body><sec><title>Results</title><p>{body_sentence}</p></sec></body></article>'''.encode()


def main() -> None:
    blobs: dict[str, bytes] = {}
    metadata: dict[str, dict] = {}

    def add(prefix: str, *, license_code: str, manuscript: object = "no",
            retracted: object = "no", xml_license: str | None = None,
            fact_sentence: str | None = None) -> None:
        pmcid = prefix.split(".")[0]
        href = ("https://creativecommons.org/publicdomain/zero/1.0/"
                if xml_license == "CC0" else
                "https://creativecommons.org/licenses/by-nc/4.0/"
                if xml_license == "NC" else
                "https://creativecommons.org/licenses/by/4.0/")
        label = ("CC0 1.0" if xml_license == "CC0" else
                 "CC BY-NC 4.0" if xml_license == "NC" else "CC BY 4.0")
        payload = article(pmcid, href, label, prefix, fact_sentence)
        digest = hashlib.md5(payload, usedforsecurity=False).hexdigest()
        xml_url = ("s3://pmc-oa-opendata/" + prefix + "/" +
                   prefix + ".xml?md5=" + digest)
        https_xml_url = ("https://pmc-oa-opendata.s3.amazonaws.com/" +
                         prefix + "/" + prefix + ".xml?md5=" + digest)
        metadata[prefix] = {
            "pmcid": pmcid, "version": prefix.rsplit(".", 1)[-1],
            "doi": f"10.1234/{pmcid.lower()}", "title": prefix,
            "license_code": license_code, "is_manuscript": manuscript,
            "is_retracted": retracted, "xml_url": xml_url,
        }
        blobs[https_xml_url] = payload

    add("PMC101.1", license_code="CC BY 4.0", manuscript="yes")
    add("PMC101.2", license_code="CC0", manuscript="no", xml_license="CC0")
    add("PMC102.1", license_code="CC BY-NC 4.0")
    add("PMC103.1", license_code="CC BY 4.0", retracted="yes")
    add("PMC104.1", license_code="CC BY 4.0", xml_license="NC")
    add("PMC105.1", license_code="CC0", xml_license="CC BY 4.0")
    add("PMC106.1", license_code="CC BY 4.0",
        fact_sentence="Ada Lovelace designed the Analytical Engine.")
    add("PMC107.1", license_code="CC BY 4.0",
        fact_sentence="Grace Hopper designed the Compiler.")
    add("PMC108.1", license_code="CC BY 4.0",
        fact_sentence="Katherine Johnson designed the trajectory table.")

    def fetch(url: str, *, max_bytes: int = 64 * 1024 * 1024, timeout: float = 40.0) -> bytes:
        parsed = urlsplit(url)
        if parsed.path.endswith("esearch.fcgi"):
            query = parse_qs(parsed.query)
            assert "cc0_license[filter]" in query["term"][0]
            assert "cc_by_license[filter]" in query["term"][0]
            return json.dumps({"esearchresult": {"idlist": ["101", "102", "103", "104", "105", "106", "107", "108"]}}).encode()
        if parsed.path == "/":
            from urllib.parse import parse_qs as parse
            prefix = parse(parsed.query).get("prefix", [""])[0]
            rows = sorted(key.rsplit("/", 1)[0] for key in metadata if key.startswith(prefix))
            tags = "".join(f"<CommonPrefixes><Prefix>{item}/</Prefix></CommonPrefixes>" for item in rows)
            return f"<ListBucketResult>{tags}</ListBucketResult>".encode()
        if "/metadata/" in parsed.path:
            return json.dumps(metadata[Path(parsed.path).stem]).encode()
        if url in blobs:
            return blobs[url]
        raise AssertionError(f"unexpected URL {url}")

    with tempfile.TemporaryDirectory(prefix="crms-pmc-test-") as temporary:
        output = Path(temporary) / "pmc.sqlite"
        added, updated, skipped, errors, searched = import_pmc(
            "symbolic reasoning", output, max_articles=20, fetch=fetch)
        assert (added, updated, skipped, errors, searched) == (5, 0, 2, 2, 8)
        index = CRMSSQLiteResearchIndex(output)
        hits = index.search("Distinct PMC result PMC101.2", limit=5)
        assert hits and "Distinct PMC result: PMC101.2" in hits[0].snippet
        old_hit = hits[0]
        old_citation = index.citation(old_hit)
        docs = index.documents()
        assert len(docs) == 5, [(document.document_id, document.title) for document in docs]
        text = next(document.text for document in docs
                    if document.document_id.startswith("pmc:PMC101.v2."))
        assert "PMC101.2" in text and "source revision" in text
        assert "may not reflect the current" in text
        assert "NLM/NIH/HHS does not endorse" in text
        assert "CC0: CC0 1.0" in text
        assert "PMC101.1" not in text
        assert any(document.document_id.startswith("pmc:PMC101.v1.")
                   for document in docs), "eligible alternate version was discarded"

        # Academic source text can license a learned sentence frame, but only
        # after two source-backed examples; new extraction remains review-only.
        kb = CRMSKnowledgeBase()
        examples = [
            ("Ada Lovelace designed the Analytical Engine.",
             "Ada Lovelace", "the Analytical Engine"),
            ("Grace Hopper designed the Compiler.",
             "Grace Hopper", "the Compiler"),
        ]
        example_hits = []
        for sentence, subject, obj in examples:
            hit = index.search(sentence, limit=5)[0]
            citation = index.citation(hit)
            kb.add_fact(subject, "designed", obj, citation)
            example_hits.append((sentence, subject, obj, hit))
        frame_results = [kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=obj,
            research_index=index, hit=hit)
            for sentence, subject, obj, hit in example_hits]
        assert frame_results == [False, True], frame_results
        kb.teach_question("Who designed the Analytical Engine?", relation="designed",
                          answer_field="subject", bound_entity="the Analytical Engine",
                          answer="Ada Lovelace")
        kb.teach_question("Who designed the Compiler?", relation="designed",
                          answer_field="subject", bound_entity="the Compiler",
                          answer="Grace Hopper")
        new_sentence = "Katherine Johnson designed the trajectory table."
        new_hit = index.search(new_sentence, limit=5)[0]
        candidates = kb.propose_facts_from_hit(
            new_sentence, research_index=index, hit=new_hit)
        assert len(candidates) == 1 and candidates[0].subject == "Katherine Johnson"
        assert len(kb.facts()) == 2, "source extraction committed without review"
        kb.accept_fact_candidate(candidates[0], index)
        answer = kb.ask("Who designed the trajectory table?")
        assert answer.status == "answered" and answer.answer == "Katherine Johnson"
        assert candidates[0].source in (answer.evidence or [])[0]["sources"]
        index.close()

        # Repeated queries update the same version in place and don't duplicate
        # unchanged records; the version stays part of the document identity.
        added, updated, skipped, errors, searched = import_pmc(
            "symbolic reasoning", output, max_articles=20,
            append=True, fetch=fetch)
        assert (added, updated, skipped, errors, searched) == (0, 0, 7, 2, 8)
        add("PMC101.2", license_code="CC0", manuscript="no", xml_license="CC0",
            fact_sentence="Refreshed PMC article verifies current import.")
        added, updated, skipped, errors, searched = import_pmc(
            "symbolic reasoning", output, max_articles=20,
            append=True, fetch=fetch)
        assert (added, updated, skipped, errors, searched) == (1, 0, 6, 2, 8)
        refreshed = CRMSSQLiteResearchIndex(output)
        revisions = [document for document in refreshed.documents()
                     if document.document_id.startswith("pmc:PMC101.v2.")]
        assert len(revisions) == 2
        assert any("Refreshed PMC article verifies current import." in item.text
                   for item in revisions)
        assert refreshed.resolve_citation(old_citation) == old_hit.snippet
        refreshed.close()
    print("PMC AWS dataset import diagnostic: PASS")
    print("bounded NCBI query, license filters, every eligible version retained, retraction exclusion, metadata/XML license agreement, MD5 verification, source freshness notice, citation retrieval, learned fact-frame extraction, reviewed acceptance, cited QA, append deduplication, immutable revision snapshots, and historical citation preservation: PASS")


if __name__ == "__main__":
    main()
