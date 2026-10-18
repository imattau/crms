"""Import explicitly licensed JATS articles from a local corpus to SQLite."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from crms_research import CRMSSQLiteResearchIndex


MAX_ARTICLE_BYTES = 64 * 1024 * 1024
BLOCKS = {"abstract", "ack", "app", "body", "boxed-text", "caption",
          "disp-quote", "fig", "fn", "list", "p", "ref", "sec",
          "table-wrap", "tr"}
ALLOWED_LICENSES = {
    "cc0": "CC0",
    "cc-by": "CC BY",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(element: ET.Element) -> str:
    """Flatten readable JATS content while retaining paragraph/heading breaks."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        name = local_name(node.tag)
        if name in {"graphic", "inline-graphic", "media", "supplementary-material"}:
            return
        if name in {"td", "th"} and parts:
            parts.append(" | ")
        if name in {"title", "label", "p", "abstract", "sec", "caption", "ref"}:
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if name in {"td", "th"}:
            parts.append(" | ")
        if name in BLOCKS:
            parts.append("\n")

    walk(element)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _descendants(element: ET.Element, name: str):
    return (node for node in element.iter() if local_name(node.tag) == name)


def _article_fields(root: ET.Element) -> tuple[str, str, str, str, str] | None:
    license_node = next(_descendants(root, "license"), None)
    if license_node is None:
        return None
    license_text = element_text(license_node)
    href = next((value for key, value in license_node.attrib.items()
                 if local_name(key) in {"href", "{http://www.w3.org/1999/xlink}href"}), "")
    license_source = f"{href} {license_text}".casefold()
    restricted = re.search(r"non[ -]?commercial|no[ -]?derivatives|\bby[ -]?nc\b|\bby[ -]?nd\b|share[ -]?alike|\bby[ -]?sa\b", license_source)
    if restricted:
        return None
    if "creativecommons.org/publicdomain/zero" in license_source or re.search(r"\bcc0\b", license_source):
        license_name = ALLOWED_LICENSES["cc0"]
    elif ("creativecommons.org/licenses/by/" in license_source
          or re.search(r"\bcreative commons attribution(?:\s+4\.0)?\b", license_text, re.I)):
        license_name = ALLOWED_LICENSES["cc-by"]
    else:
        return None

    title_node = next(_descendants(root, "article-title"), None)
    title = element_text(title_node) if title_node is not None else ""
    if not title:
        return None
    authors = []
    for contrib in _descendants(root, "contrib"):
        if contrib.attrib.get("contrib-type") != "author":
            continue
        name = next(_descendants(contrib, "string-name"), None)
        if name is None:
            given = next(_descendants(contrib, "given-names"), None)
            surname = next(_descendants(contrib, "surname"), None)
            name_text = " ".join(element_text(n) for n in (given, surname) if n is not None)
        else:
            name_text = element_text(name)
        if name_text and name_text not in authors:
            authors.append(name_text)
    doi = next((element_text(n) for n in _descendants(root, "article-id")
                if n.attrib.get("pub-id-type", "").casefold() == "doi"), "")
    pmcid = next((element_text(n) for n in _descendants(root, "article-id")
                 if n.attrib.get("pub-id-type", "").casefold() in {"pmc", "pmcid"}), "")
    if pmcid.isdigit():
        pmcid = f"PMC{pmcid}"
    return title, ", ".join(authors), doi, pmcid, f"{license_name}: {license_text}"


def extract_article(path: Path) -> tuple[str, str, str, str] | None:
    if path.stat().st_size > MAX_ARTICLE_BYTES:
        raise ValueError(f"article exceeds {MAX_ARTICLE_BYTES // (1024 * 1024)} MiB limit")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"malformed JATS XML: {error}") from error
    fields = _article_fields(root)
    if fields is None:
        return None
    title, authors, doi, pmcid, license_line = fields
    body_node = next(_descendants(root, "body"), None)
    abstract_node = next(_descendants(root, "abstract"), None)
    body = element_text(body_node) if body_node is not None else ""
    abstract = element_text(abstract_node) if abstract_node is not None else ""
    if not body and not abstract:
        return None
    identity = pmcid or doi or hashlib.sha256(path.read_bytes()).hexdigest()
    location = (f"https://doi.org/{quote(doi, safe='/:')}" if doi else
                f"https://pmc.ncbi.nlm.nih.gov/articles/{quote(pmcid, safe='')}" if pmcid else path.name)
    attribution = f"Title: {title}\nAuthors: {authors or 'not specified'}\nLicense: {license_line}\nSource: {location}"
    # Preserve the source-provided abstract as a labeled field so result
    # requests can target the abstract without mistaking front-matter or body
    # text for it. The label records the JATS element; abstract wording stays
    # unchanged and remains directly citable.
    abstract_field = f"Abstract: {abstract}" if abstract else ""
    text = "\n\n".join(
        part for part in (attribution, abstract_field, body) if part)
    return f"jats:{identity}", title, text, location


def import_corpus(source: str | Path, output: str | Path, *,
                  source_notice: str | Mapping[str, str] | None = None,
                  document_ids: Mapping[str, str] | None = None
                  ) -> tuple[int, int, int]:
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if not source_path.is_dir():
        raise FileNotFoundError(f"JATS corpus directory does not exist: {source_path}")
    if output_path.exists():
        raise FileExistsError(f"output already exists: {output_path}")
    files = sorted(path for path in source_path.rglob("*.xml") if path.is_file() and not path.is_symlink())
    if not files:
        raise ValueError("JATS corpus contains no .xml files")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    accepted = rejected = errors = 0
    with tempfile.TemporaryDirectory(prefix=output_path.name + ".", dir=output_path.parent) as tmp:
        db_path = Path(tmp) / "research.sqlite"
        index = CRMSSQLiteResearchIndex(db_path)
        try:
            with index._bulk_write_context():
                for path in files:
                    try:
                        result = extract_article(path)
                        if result is None:
                            rejected += 1
                            continue
                        source_document_id, title, text, location = result
                        versioned_key = f"{source_document_id}|{path.stem}"
                        document_id = ((document_ids or {}).get(versioned_key)
                                       or (document_ids or {}).get(source_document_id)
                                       or source_document_id)
                        if index.contains_document(document_id):
                            rejected += 1
                            continue
                        notice = (source_notice.get(
                            versioned_key, source_notice.get(source_document_id))
                            if isinstance(source_notice, Mapping)
                            else source_notice)
                        if notice:
                            text = f"{notice}\n\n{text}"
                        index.add_document(document_id, title, text, location)
                        accepted += 1
                    except (OSError, ValueError) as error:
                        errors += 1
                        print(f"Skipped {path}: {error}", file=sys.stderr)
            if not accepted:
                raise ValueError("no eligible licensed JATS articles were imported")
            index.close()
            db_path.replace(output_path)
        except Exception:
            index.close()
            raise
    return accepted, rejected, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="directory of JATS .xml article files")
    parser.add_argument("--output", type=Path, required=True, help="new SQLite index to create")
    args = parser.parse_args()
    try:
        accepted, rejected, errors = import_corpus(args.corpus, args.output)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(f"Imported {accepted} licensed articles; skipped {rejected} ineligible and {errors} malformed/unreadable files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
