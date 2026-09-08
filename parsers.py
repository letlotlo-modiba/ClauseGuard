"""
Format-specific parsers. Each one only knows how to extract raw text/pages
from its own file format - normalisation and clause-chuncking happen in
text_processing.py, on unified output.
"""

from abc import ABC , abstractmethod
from pathlib import Path

import docx
import pdfplumber
from docx.opc.exceptions import PackageNotFoundError

try:
    from .models import (
        CorruptedFileError,
        DocumentSection,
        EmptyExtractionError,
        ExtractionMethod,
        ParsedDocument,
        PasswordProtectedError,
        SourceFileType,
    )
except (ImportError, ValueError):
    from models import (
        CorruptedFileError,
        DocumentSection,
        EmptyExtractionError,
        ExtractionMethod,
        ParsedDocument,
        PasswordProtectedError,
        SourceFileType,
    )

class DocumentParser(ABC):
    """Base interface every format-specific parser implements."""

    
    @abstractmethod
    def parse(self, file_path: Path) -> ParsedDocument:
        ...

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Cheap check based on extension before attempting a full parse."""
        ...


class DocxParser(DocumentParser):
    """Extracts text from .docx files using python-docx."""

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".docx"

    def parse(self, file_path: Path) -> ParsedDocument:
        try:
            document = docx.Document(str(file_path))
        except PackageNotFoundError as exc:
            raise CorruptedFileError(f"Could not open file{file_path.name}: not a valid .docx file") from exc

        warnings: list[str] = []
        sections: list[DocumentSection] = []
        raw_text_parts: list[str] = []

        current_heading: str | None = None
        para_counter = 0

        for para in document.paragraphs:
            text = para.text.strip()
            if not text: 
                continue

            style_name = (para.style.name or "").lower() if para.style else ""
            is_heading = style_name.startswith("heading") or style_name == "title"

            if is_heading: 
                current_heading = text

            para_counter += 1
            raw_text_parts.append(text)
            sections.append(
                DocumentSection(
                    text=text,
                    section_id=f"para_{para_counter}",
                    page_number=None,
                    heading=current_heading,
                    is_table=False
                )
            )

        # Tables (e.g fee schedules, signature blocks) are walked separately
        for table_idx, table in enumerate(document.tables, start=1):
            table_text_rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                table_text_rows.append(" | ".join(cells))
            table_text = "\n".join(table_text_rows)

            if table_text.strip():
                raw_text_parts.append(table_text)
                sections.append(
                    DocumentSection(
                        text=table_text,
                        section_id=f"table_{table_idx}",
                        page_number=None,
                        heading=current_heading,
                        is_table=True,
                    )
                )

        raw_text = "\n\n".join(raw_text_parts)

        if not raw_text.strip():
            raise EmptyExtractionError(
                file_path.name, likely_cause="file may be empty or contain no readable paragraphs"
            )

        return ParsedDocument(
            raw_text=raw_text,
            sections=sections,
            source_file_type=SourceFileType.DOCX,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            page_count=None,
            filename=file_path.name,
            warnings=warnings,
        )


class PdfParser(DocumentParser):
    """
    Extracts text from .pdf files using pdfplumber.
 
    Handles the common contract-PDF failure modes explicitly rather than
    letting them fail silently downstream:
      - scanned/image-only PDFs (no text layer) -> EmptyExtractionError
      - password-protected PDFs                 -> PasswordProtectedError
      - corrupted/unreadable PDFs                -> CorruptedFileError
 
    OCR is intentionally NOT implemented here. If a scanned PDF is detected,
    I raise a clear error
    """
 
    # If extracted text per page falls below this character count while the
    # page clearly has content (non-trivial height/width), treat it as a
    # signal the page is likely scanned rather than truly blank.
    MIN_CHARS_PER_NONBLANK_PAGE = 10

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".pdf"

    def parse(self, file_path: Path) -> ParsedDocument:
        try:
            pdf = pdfplumber.open(str(file_path))
        except Exception as exc: #pdfplumber wraps several underlying libraries
            if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
                raise PasswordProtectedError(file_path.name) from exc
            raise CorruptedFileError(file_path.name, original_exception=exc) from exc

        Warnings: list[str] = []
        sections: list[DocumentSection] = []
        raw_text_parts: list[str] = []
        blank_like_pages: list[int] = []

        with pdf:
            page_count = len(pdf.pages)

            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = (page.extract_text() or "").strip()

                if len(page_text) < self.MIN_CHARS_PER_NONBLANK_PAGE:
                    blank_like_pages.append(page_number)
                    continue

                raw_text_parts.append(page_text)

                # Split page text into paragraph-level sections. Finer clause
                # detection (numbered headings) happens later in
                # text_processing.detect_sections on the normalised text —
                # this is just a page-scoped first pass so page_number is
                # preserved per chunk.
                for para_idx, para_text in enumerate(
                    (p for p in page_text.split("\n\n") if p.strip()), start=1):
                    sections.append(
                        DocumentSection(
                            text=para_text.strip(),
                            section_id=f"p{page_number}_para_{para_idx}",
                            page_number=page_number,
                            heading=None,
                            is_table=False,
                        )
                    )

                # Tables (fee schedules, rent tables, etc.) extracted separately
                for table_idx, table in enumerate(page.extract_tables(), start=1):
                    table_text = "\n".join(" | ".join(cell or "" for cell in row) for row in table)
                    if table_text.strip():
                        sections.append(
                            DocumentSection(
                                text=table_text,
                                section_id=f"p{page_number}_table_{table_idx}",
                                page_number=page_number,
                                heading=None,
                                is_table=True,
                            )
                        )

        raw_text = "\n\n".join(raw_text_parts)

        # Entire document came back empty/near-empty -> almost certainly scanned.
        if not raw_text.strip():
            raise EmptyExtractionError(
                file_path.name,
                likely_cause="possibly a scanned/image-only PDF; OCR is not currently supported",
            )

        # Some page were partially blank but not all
        if blank_like_pages:
            Warnings.append(
                f"Pages {blank_like_pages} returned little or no text and were skipped "
                f"(possibly scanned images embedded in an otherwise text-based PDF)"
                )

        return ParsedDocument(
            raw_text=raw_text,
            sections=sections,
            source_file_type=SourceFileType.PDF,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            page_count=page_count,
            filename=file_path.name,
            warnings=Warnings,
        )


class TxtParser(DocumentParser):
    """Extracts text from plain-text (.txt) contract files."""

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".txt"

    def parse(self, file_path: Path) -> ParsedDocument:
        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw_text = file_path.read_text(encoding="latin-1")
            except Exception as exc:
                raise CorruptedFileError(file_path.name, original_exception=exc) from exc
        except Exception as exc:
            raise CorruptedFileError(file_path.name, original_exception=exc) from exc

        if not raw_text.strip():
            raise EmptyExtractionError(
                file_path.name,
                likely_cause="file is empty or contains only whitespace",
            )

        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        sections = [
            DocumentSection(
                text=para,
                section_id=f"para_{i}",
                page_number=1,
                heading=None,
                is_table=False,
            )
            for i, para in enumerate(paragraphs, start=1)
        ]

        return ParsedDocument(
            raw_text=raw_text,
            sections=sections,
            source_file_type=SourceFileType.TXT,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            page_count=1,
            filename=file_path.name,
            warnings=[],
        )