"""Search the current PMC AWS dataset and import licensed JATS articles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from crms_import_jats import extract_article, import_corpus
from crms_research import CRMSSQLiteResearchIndex


EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
S3_BASE = "https://pmc-oa-opendata.s3.amazonaws.com/"
S3_HOST = "pmc-oa-opendata.s3.amazonaws.com"
MAX_RESPONSE = 64 * 1024 * 1024
USER_AGENT = "CRMS research importer/1.0 (academic source indexing)"


def _fetch(url: str, *, max_bytes: int = MAX_RESPONSE,
           timeout: float = 40.0) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept-Encoding": "identity"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response exceeds {max_bytes} byte limit: {url}")
    return data


def _license_is_redistributable(code: object) -> bool:
    if not isinstance(code, str):
        return False
    normalized = " ".join(code.upper().replace("_", " ").split())
    return normalized == "CC0" or bool(re.fullmatch(r"CC BY(?: \d+(?:\.\d+)*)?", normalized))


def _license_class(code: object) -> str | None:
    if not _license_is_redistributable(code):
        return None
    normalized = " ".join(str(code).upper().replace("_", " ").split())
    return "CC0" if normalized == "CC0" else "CC BY"


def _metadata_yes(value: object) -> bool:
    return value is True or (isinstance(value, str)
                             and value.strip().casefold() in {"yes", "true", "1"})


def search_pmc(query: str, max_articles: int, *, fetch=_fetch) -> list[str]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= max_articles <= 10_000:
        raise ValueError("max_articles must be between 1 and 10000")
    term = (f"({query}) AND (cc0_license[filter] OR cc_by_license[filter]) "
            "AND (open_access[filter] OR author_manuscript[filter])")
    url = EUTILS + "?" + urlencode({"db": "pmc", "term": term,
                                     "retmode": "json", "retmax": max_articles})
    payload = json.loads(fetch(url, max_bytes=2 * 1024 * 1024).decode("utf-8"))
    ids = payload.get("esearchresult", {}).get("idlist")
    if not isinstance(ids, list):
        raise ValueError("NCBI ESearch returned an unexpected response")
    return [str(pmcid) for pmcid in ids if str(pmcid).isdigit()]


def list_article_versions(pmcid: str, *, fetch=_fetch) -> list[str]:
    prefix = f"PMC{pmcid}."
    url = S3_BASE + "?" + urlencode({"list-type": "2", "prefix": prefix,
                                     "delimiter": "/"})
    root = ET.fromstring(fetch(url, max_bytes=4 * 1024 * 1024))
    versions = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "Prefix" and element.text:
            value = element.text.strip().rstrip("/")
            if re.fullmatch(re.escape(prefix) + r"\d+", value):
                versions.append(value)
    return sorted(set(versions), key=lambda value: int(value.rsplit(".", 1)[-1]))


def _s3_object_url(url: object) -> str:
    if not isinstance(url, str):
        raise ValueError("PMC metadata is missing an object URL")
    parsed = urlsplit(url)
    if (parsed.scheme == "s3"
            and parsed.netloc == "pmc-oa-opendata"
            and parsed.path.startswith("/")
            and not parsed.fragment):
        # Current PMC metadata emits canonical S3 URIs. Translate only the
        # exact documented bucket to its public HTTPS endpoint; arbitrary S3
        # buckets and hostnames remain rejected.
        return urlunsplit(("https", S3_HOST, parsed.path, parsed.query, ""))
    if parsed.scheme != "https" or parsed.hostname != S3_HOST:
        raise ValueError("PMC metadata contains a non-dataset object URL")
    return url


def _article_metadata(prefix: str, *, fetch=_fetch) -> dict:
    metadata_url = S3_BASE + "metadata/" + prefix + ".json"
    payload = json.loads(fetch(metadata_url, max_bytes=1024 * 1024).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PMC article metadata is not an object")
    return payload


def _eligible_versions(versions: list[str], *, fetch=_fetch
                       ) -> list[tuple[str, dict]]:
    """Return every non-retracted, redistributable version without ranking it.

    PMC's current dataset documentation warns that a greater version number
    does not identify the preferred copy. Retaining each eligible version
    preserves that distinction in the CRMS document IDs and citations.
    """
    eligible = []
    for prefix in versions:
        metadata = _article_metadata(prefix, fetch=fetch)
        if _metadata_yes(metadata.get("is_retracted")):
            continue
        if not _license_is_redistributable(metadata.get("license_code")):
            continue
        eligible.append((prefix, metadata))
    return eligible


def _download_xml(metadata: dict, destination: Path, *, fetch=_fetch) -> str:
    url = _s3_object_url(metadata.get("xml_url"))
    data = fetch(url)
    expected_md5 = parse_qs(urlsplit(url).query).get("md5", [None])[0]
    if not expected_md5 or not re.fullmatch(r"[0-9a-fA-F]{32}", expected_md5):
        raise ValueError("PMC XML URL does not include the documented MD5 checksum")
    actual_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    if actual_md5.casefold() != expected_md5.casefold():
        raise ValueError("PMC XML checksum does not match its metadata URL")
    destination.write_bytes(data)
    return hashlib.sha256(data).hexdigest()[:16]


def import_pmc(query: str, output: str | Path, *, max_articles: int = 100,
               append: bool = False, fetch=_fetch
               ) -> tuple[int, int, int, int, int]:
    """Search PMC and index each eligible, non-retracted CC0/CC BY version."""
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() and not append:
        raise FileExistsError(f"output already exists: {output_path}")
    if append and output_path.exists():
        existing = CRMSSQLiteResearchIndex(output_path)
        has_sources = existing._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='source_documents'").fetchone()
        existing.close()
        if not has_sources:
            raise ValueError("--append requires an existing CRMS SQLite research index")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ids = search_pmc(query, max_articles, fetch=fetch)
    if not ids:
        raise ValueError("PMC search returned no matching articles")

    with tempfile.TemporaryDirectory(prefix=".crms-pmc-", dir=output_path.parent) as temporary:
        corpus = Path(temporary) / "articles"
        corpus.mkdir()
        staged_index_path = Path(temporary) / "staged.sqlite"
        notices: dict[str, str] = {}
        document_ids: dict[str, str] = {}
        examined = skipped = errors = 0
        for position, pmcid in enumerate(ids, start=1):
            try:
                prefixes = list_article_versions(pmcid, fetch=fetch)
                versions = _eligible_versions(prefixes, fetch=fetch)
                if not versions:
                    skipped += 1
                    continue
                for prefix, metadata in versions:
                    xml_path = corpus / f"{prefix}.xml"
                    try:
                        revision_digest = _download_xml(
                            metadata, xml_path, fetch=fetch)
                        article = extract_article(xml_path)
                        expected_license = _license_class(
                            metadata.get("license_code"))
                        if article is None:
                            raise ValueError(
                                "downloaded XML is not an eligible licensed JATS article")
                        actual_match = re.search(
                            r"^License: (CC0|CC BY):", article[2], re.M)
                        if (not actual_match
                                or actual_match.group(1) != expected_license):
                            raise ValueError(
                                "PMC JSON license code does not match article XML rights")
                        pmc_identifier = str(
                            metadata.get("pmcid") or f"PMC{pmcid}")
                        if pmc_identifier.isdigit():
                            pmc_identifier = f"PMC{pmc_identifier}"
                        source_key = f"jats:{pmc_identifier}|{prefix}"
                        notices[source_key] = (
                            "Source: NIH NLM NCBI PMC Article Datasets. "
                            f"Record {prefix}; source revision {revision_digest}. "
                            f"Redistribution license: {expected_license}. "
                            "This stored snapshot may not reflect the current or most accurate "
                            "data available from NLM; consult PMC for updates. "
                            "NLM/NIH/HHS does not endorse this model.")
                        document_ids[source_key] = (
                            f"pmc:{pmc_identifier}.v{prefix.rsplit('.', 1)[-1]}"
                            f".r{revision_digest}")
                        examined += 1
                    except (HTTPError, URLError, OSError, ValueError,
                            json.JSONDecodeError) as error:
                        errors += 1
                        xml_path.unlink(missing_ok=True)
                        print(f"Skipped {prefix}: {error}")
                if position % 25 == 0:
                    time.sleep(0.1)
            except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as error:
                errors += 1
                print(f"Skipped PMC{pmcid}: {error}")

        if not examined:
            raise ValueError("no eligible, retrievable PMC articles matched the query")
        imported, rejected, parse_errors = import_corpus(
            corpus, staged_index_path, source_notice=notices,
            document_ids=document_ids)
        errors += parse_errors
        skipped += rejected
        if not append or not output_path.exists():
            staged_index_path.replace(output_path)
            return imported, 0, skipped, errors, len(ids)

        target = CRMSSQLiteResearchIndex(output_path)
        staged = CRMSSQLiteResearchIndex(staged_index_path)
        added = updated = unchanged = 0
        try:
            cursor = staged._db.execute(
                "SELECT document_id FROM source_documents ORDER BY document_id")
            while batch := cursor.fetchmany(32):
                with target._bulk_write_context():
                    for (document_id,) in batch:
                        document = staged.document(document_id)
                        if target.contains_document(document_id):
                            current = target.document(document_id)
                            if (current.title == document.title
                                    and current.text == document.text
                                    and current.location == document.location):
                                unchanged += 1
                                continue
                            target.add_document(
                                document_id, document.title, document.text,
                                document.location, replace=True,
                                pages=document.pages)
                            updated += 1
                        else:
                            target.add_document(
                                document_id, document.title, document.text,
                                document.location, pages=document.pages)
                            added += 1
        finally:
            staged.close()
            target.close()
        return added, updated, skipped + unchanged, errors, len(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="PMC search terms (not a raw ESearch expression)")
    parser.add_argument("--output", type=Path, required=True,
                        help="new SQLite research index to create")
    parser.add_argument("--max-articles", type=int, default=100,
                        help="maximum PMC records to examine (default: 100; max: 10000)")
    parser.add_argument("--append", action="store_true",
                        help="add/update records in an existing CRMS SQLite research index")
    args = parser.parse_args()
    try:
        added, updated, skipped, errors, searched = import_pmc(
            args.query, args.output, max_articles=args.max_articles,
            append=args.append)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError,
            json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"Searched {searched} PMC records; added {added}; updated {updated}; "
          f"unchanged/ineligible {skipped}; errors {errors}; SQLite index: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
