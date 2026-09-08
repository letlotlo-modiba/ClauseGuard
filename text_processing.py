"""Text normalisation and clause-boundary chunking. Both functions take plain text/sections in and return plain text/sections"""

import re

try:
    from .models import DocumentSection
except (ImportError, ValueError):
    from models import DocumentSection


_HEADING_WORD = r"[A-Z][A-Z0-9\-'/]*(?![a-z])"
_CLAUSE_HEADING_PATTERN = re.compile(
    rf"^\s*((?:[Ss]ection\s+)?\d+(?:\.\d+)*\.?)\s+"
    rf"((?:{_HEADING_WORD}\s+)*{_HEADING_WORD})"
    rf"(.*)$"
)

# Common repeating footer/header noise in contract PDFs, e.g.
# "Confidential — Page 3 of 12", "Page 3 of 12", or just a bare "Page 3"
# (the "of N" part is optional since many footers omit the total).
_PAGE_FOOTER_PATTERN = re.compile(
    r"^\s*(confidential\s*[-—]?\s*)?page\s+\d+(\s+of\s+\d+)?\s*$",
    re.IGNORECASE,
)


def normalise_text(raw_text: str) -> str:
    """
    Cleans raw extracted text before chunking:
      - strips repeated page-footer/header noise (e.g. "Page 3 of 12")
      - collapses runs of blank lines down to a single blank line
      - trims trailing whitespace on each line

    Intentionally conservative: this should never remove content a human
    would consider part of the contract, only extraction artifacts.
    """
    lines = raw_text.splitlines()
    cleaned_lines = [
        line.rstrip()
        for line in lines
        if not _PAGE_FOOTER_PATTERN.match(line.strip())
    ]

    text = "\n".join(cleaned_lines)
    
    # collapse 3+ consecutive newlines down to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_sections(normalised_text: str) -> list[DocumentSection]:
    """
    Splits normalised text into clause-level DocumentSections using
    numbered-heading detection (e.g. "1.", "2.1", "Section 3").

    Chunking is LINE-based, not blank-line/paragraph-based: I scan every
    line, and whenever a line matches the heading pattern on its own, I
    start a new section that accumulates every following line (heading
    included) up until the next heading match. This is deliberate —
    neither docx (one paragraph per line, headings and bodies as separate
    paragraphs) nor pdfplumber (joins wrapped lines with single "\\n",
    often with no blank line between clauses) reliably produce blank-line
    gaps between clauses. Scanning line-by-line for headings works
    regardless of how the source paragraphs/lines are grouped.

    Any text before the first detected heading (e.g. a title/preamble
    paragraph) becomes a single "preamble" section rather than being
    dropped.

    If NO heading is matched anywhere in the document, I fall back to
    blank-line paragraph splitting so unstructured documents still get
    chunked into something usable, just without clause-level section IDs.
    Callers can treat a document with zero numbered sections as a signal
    to try LLM-based semantic segmentation instead.

    page_number and is_table are not set here since this operates on
    already-flattened text; page-scoped sections from PdfParser carry
    their own page numbers and should be preferred when available.
    """
    lines = normalised_text.split("\n")

    sections: list[DocumentSection] = []
    preamble_lines: list[str] = []
    current_id: str | None = None
    current_heading: str | None = None
    current_lines: list[str] = []
    found_first_heading = False


    def flush_current() -> None:
        if current_id is None:
            return
        text = " ".join(l for l in current_lines if l).strip()
        text = re.sub(r"\s{2,}", " ", text)
        if text:
            sections.append(
                DocumentSection(
                    text=text,
                    section_id=current_id,
                    page_number=None,
                    heading=current_heading,
                    is_table=False,
                )
            )

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue  # blank lines are just spacing, not clause boundaries

        match = _CLAUSE_HEADING_PATTERN.match(stripped)

        if match:
            flush_current()
            current_id = match.group(1).rstrip(".")
            current_heading = match.group(2).strip()

            # group(3) is whatever followed the heading on the same physical line. Keep the full stripped line in current_lines so flush_current() still reconstructs complete body text.
            current_lines = [stripped]
            found_first_heading = True
        elif found_first_heading:
            current_lines.append(stripped)
        else:
            
            preamble_lines.append(stripped)

    flush_current()

    if not found_first_heading:
        # No numbering pattern detected anywhere -> fall back to paragraph
        # splitting so the document still gets chunked into something,
        # rather than returning zero sections.
        return _fallback_paragraph_split(normalised_text)

    result: list[DocumentSection] = []
    if preamble_lines:
        preamble_text = re.sub(r"\s{2,}", " ", " ".join(preamble_lines)).strip()
        if preamble_text:
            result.append(
                DocumentSection(
                    text=preamble_text,
                    section_id="preamble",
                    page_number=None,
                    heading=None,
                    is_table=False,
                )
            )
    result.extend(sections)
    return result


def _fallback_paragraph_split(normalised_text: str) -> list[DocumentSection]:
    """Used only when no numbered heading was found anywhere in the
    document. Splits on blank lines as a last resort."""
    paragraphs = [p.strip() for p in normalised_text.split("\n\n") if p.strip()]
    return [
        DocumentSection(
            text=para,
            section_id=f"unnumbered_{i}",
            page_number=None,
            heading=None,
            is_table=False,
        )
        for i, para in enumerate(paragraphs, start=1)
    ]