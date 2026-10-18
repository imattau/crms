"""Check PDF extraction, page citations, and revision-safe offsets.

Run with pypdf or Poppler's pdftotext utility available:
    python3 experiments/v1_31_pdf_source_retrieval.py
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import CRMSResearchIndex


def make_pdf(page_text: list[str]) -> bytes:
    """Build a tiny uncompressed, searchable two-or-more-page PDF fixture."""
    if len(page_text) < 2:
        raise ValueError("fixture must contain multiple pages")
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: ("<< /Type /Pages /Kids [" + " ".join(
            f"{3 + index * 2} 0 R" for index in range(len(page_text)))
            + f"] /Count {len(page_text)} >>").encode("ascii"),
        3 + len(page_text) * 2: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    font_id = 3 + len(page_text) * 2
    for index, text in enumerate(page_text):
        page_id = 3 + index * 2
        stream_id = page_id + 1
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {stream_id} 0 R >>").encode("ascii")
        objects[stream_id] = (f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                              + stream + b"\nendstream")

    output = bytearray(b"%PDF-1.4\n%CRMS\n")
    offsets = [0] * (max(objects) + 1)
    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return bytes(output)


def main() -> None:
    pages = [
        "CRMS begins with a simple overview of symbolic rule learning.",
        "Page two contains the grounded citation phrase for retrieval.",
        "The final page records a distinct conclusion for testing page three.",
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "research.pdf"
        path.write_bytes(make_pdf(pages))
        index = CRMSResearchIndex()
        index.add_file(path, document_id="research-pdf", title="Research PDF")

        hit = index.search("grounded citation phrase", limit=1)[0]
        if hit.page_number != 2:
            raise SystemExit(f"PDF page citation is wrong: {hit}")
        document = index.document("research-pdf")
        if len(document.pages) != 3:
            raise SystemExit(f"PDF page boundaries were lost: {document.pages}")
        if document.text[hit.start:hit.end] != hit.snippet:
            raise SystemExit("PDF quote offsets do not address the extracted source")

        citation = index.citation(hit)
        if "&page=2" not in citation or index.resolve_citation(citation) != hit.snippet:
            raise SystemExit(f"PDF citation failed to resolve: {citation}")
        try:
            index.resolve_citation(citation.replace("&page=2", "&page=1"))
        except ValueError:
            pass
        else:
            raise SystemExit("citation accepted a page that does not contain the match")
        try:
            index.citation(replace(hit, page_number=1))
        except ValueError:
            pass
        else:
            raise SystemExit("search hit accepted an incorrect page number")
        rendered = index.render_hits("grounded citation phrase", [hit])
        if "page 2" not in rendered:
            raise SystemExit(f"rendered PDF result omitted its page: {rendered}")

        saved = Path(directory) / "pdf-index.json"
        index.save(saved)
        restored = CRMSResearchIndex.load(saved)
        after_load = restored.search("distinct conclusion", limit=1)[0]
        if after_load.page_number != 3:
            raise SystemExit(f"PDF page index did not survive save/load: {after_load}")

    print("PDF source retrieval diagnostic: PASS")
    print("page extraction, exact offsets, page citations, rendering, persistence: PASS")


if __name__ == "__main__":
    main()
