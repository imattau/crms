"""Audit the local CC0/CC-BY arXiv index for procedure phrase fit.

This is a data audit, not a passing accuracy benchmark. It reads the local
index in read-only mode, separates full paper text from metadata/abstract
records, applies the frozen phrase extractor to exact sentence spans, and
replays the discovered metadata candidates through a fresh chat process.
Codex's case labels are diagnostic and not independent validation.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import CRMSResearchIndex, _sentence_spans
from crms_translation import CRMSTranslation


PROJECT = Path(__file__).resolve().parents[1]
INDEX_PATH = PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite"
MANUAL_LABELS = {
    "arxiv:2006.05554v1": (
        "not_a_procedure",
        "A predicted causal consequence about missing data, not an operation to perform.",
    ),
    "arxiv:2008.01532v1": (
        "wrong_subject_and_not_a_procedure",
        "The main subject is a trained DBLSTM; 'function' occurs inside an objective-function noun phrase.",
    ),
    "arxiv:2610.22210v1": (
        "administrative_future_statement",
        "A promise to release code after acceptance, not a domain operation.",
    ),
}
CHAT_QUERIES = (
    "missing value impair performance causal discovery",
    "DBLSTM CTC objective function learn",
    "code released acceptance",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(INDEX_PATH.is_file(),
            f"local corpus not found; expected read-only input at {INDEX_PATH}")
    digest = hashlib.sha256(INDEX_PATH.read_bytes()).hexdigest()
    db = sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    rows = db.execute(
        "SELECT document_id,title,location,body FROM source_documents "
        "ORDER BY document_id").fetchall()
    full_text_rows = [row for row in rows
                      if row[3].lstrip().startswith("Source: arXiv paper full text")]
    metadata_rows = [row for row in rows if row not in full_text_rows]

    candidates_by_kind: dict[str, list[tuple]] = {"full_text": [], "metadata": []}
    license_counts: dict[str, int] = {}
    for doc_id, title, location, body in rows:
        kind = ("full_text" if body.lstrip().startswith(
            "Source: arXiv paper full text") else "metadata")
        if kind == "full_text":
            match = re.search(r"^Declared license: ([^\n]+)", body, re.MULTILINE)
            require(match is not None,
                    f"full-text attribution lacks a declared license: {doc_id}")
            license_name = match.group(1).split("(", 1)[0].strip()
            license_counts[license_name] = license_counts.get(license_name, 0) + 1
        doc_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        for start, end in _sentence_spans(body):
            sentence = body[start:end]
            citation = f"{doc_id}#sha256={doc_digest}&chars={start}:{end}"
            for candidate in propose_procedure_phrase_candidates(
                    sentence, source_citation=citation):
                candidates_by_kind[kind].append(
                    (doc_id, title, location, sentence, candidate))
    db.close()

    require(len(full_text_rows) == 8,
            f"unexpected full-text record count: {len(full_text_rows)}")
    require(len(rows) == 1697,
            f"local corpus changed since this audit was scoped: {len(rows)}")
    require(not candidates_by_kind["full_text"],
            "frozen grammar now matches a full-text paper; review this case and update labels")
    require({item[0] for item in candidates_by_kind["metadata"]}
            == set(MANUAL_LABELS),
            "metadata candidate set changed; manually review before updating this audit")

    # Build an isolated text index from the three complete indexed source
    # records that produced candidates. The source index itself remains read-only.
    candidate_ids = set(MANUAL_LABELS)
    subset = CRMSResearchIndex()
    with sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True) as db:
        for doc_id, title, location, body in db.execute(
                "SELECT document_id,title,location,body FROM source_documents"):
            if doc_id in candidate_ids:
                subset.add_document(doc_id, title, body, location)

    with tempfile.TemporaryDirectory(prefix="crms-arxiv-procedure-fit-") as folder:
        root = Path(folder)
        index_path = root / "index.json"
        subset.save(index_path)
        knowledge_path = root / "knowledge.json"
        rules_path = root / "rules.json"
        math_path = root / "math.json"
        translations_path = root / "translations.json"
        CRMSKnowledgeBase().save(knowledge_path)
        CRMSModel(max_workers=1).save(rules_path)
        CRMSMath().save(math_path)
        CRMSTranslation().save(translations_path)
        chat_input = "".join(
            f"/suggest-procedure-phrases {query}\n" for query in CHAT_QUERIES
        ) + "/rules\n/quit\n"
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--math", str(math_path),
             "--rules", str(rules_path), "--translations", str(translations_path),
             "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--candidate-session", str(root / "candidates.json"),
             "--rule-session", str(root / "rule-session.json")],
            input=chat_input, text=True, capture_output=True,
            cwd=root, timeout=90, check=False)
        require(process.returncode == 0,
                f"fresh chat failed: {process.stderr}\n{process.stdout}")
        output = process.stdout
        require(output.count("Source-backed procedure phrase candidates") == 3,
                f"chat did not expose all three candidates:\n{output}")
        require("No transformation rules are committed yet." in output,
                "review-only suggestions changed the rule store")
        for doc_id, _, _, sentence, candidate in sum(
                candidates_by_kind.values(), []):
            require(sentence in output and candidate.predicate_phrase in output,
                    f"chat omitted candidate evidence for {doc_id}:\n{output}")

    print(f"Corpus SHA-256: {digest}")
    print(f"Indexed records: {len(rows)}; full paper text: {len(full_text_rows)}; "
          f"metadata/abstract records: {len(metadata_rows)}")
    print(f"Full-text licenses: {license_counts}")
    print("Frozen grammar candidates: 0/8 full-text papers; 3 metadata/abstract records")
    print("Codex review: 0/3 metadata candidates useful as procedure evidence")
    print("Fresh chat: all three remain cited, review-only; rule store unchanged")
    print("LIMIT: one arXiv corpus, only eight full-text papers, Codex labels")


if __name__ == "__main__":
    main()
