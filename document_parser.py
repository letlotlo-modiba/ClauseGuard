"""
Top-level entry point. This is the ONLY module the rest of ClauseGuard
(Strands tools, Bedrock calls, Streamlit UI) should import from.

Nothing downstream should reach into parsers.py directly — that's what
keeps this swappable (e.g. adding OCR or a .txt parser later) without
touching agent logic.
"""

from pathlib import Path

try:
    from .models import (
        CorruptedFileError,
        DocumentParsingError,
        DocumentSection,
        EmptyExtractionError,
        ExtractionMethod,
        ParsedDocument,
        PasswordProtectedError,
        SourceFileType,
        UnsupportedFileTypeError,
    )
    from .parsers import DocumentParser, DocxParser, PdfParser, TxtParser
    from .text_processing import detect_sections, normalise_text
except (ImportError, ValueError):
    from models import (
        CorruptedFileError,
        DocumentParsingError,
        DocumentSection,
        EmptyExtractionError,
        ExtractionMethod,
        ParsedDocument,
        PasswordProtectedError,
        SourceFileType,
        UnsupportedFileTypeError,
    )
    from parsers import DocumentParser, DocxParser, PdfParser, TxtParser
    from text_processing import detect_sections, normalise_text

# Registered in order; get_parser_for_file returns the first match.
_PARSERS: list[DocumentParser] = [DocxParser(), PdfParser(), TxtParser()]


def get_parser_for_file(file_path: Path) -> DocumentParser:
    """Selects the right parser based on file extension.

    Raises UnsupportedFileTypeError if no registered parser matches.
    """
    for parser in _PARSERS:
        if parser.can_handle(file_path):
            return parser

    raise UnsupportedFileTypeError(file_path.name, file_path.suffix)


def parse_document(file_path: str | Path, rechunk: bool = True) -> ParsedDocument:
    """
    Parses a contract file end-to-end: extraction -> validation -> normalisation
    -> clause chunking.

    Args:
        file_path: path to a .docx or .pdf file.
        rechunk: if True (default), re-runs detect_sections() on the fully
            normalised raw_text and replaces `sections` with that result.
            Set to False if you want to keep the parser's original
            page-scoped sections (e.g. PdfParser's page-numbered chunks)
            instead of the flattened numbered-heading chunks.

    Returns:
        ParsedDocument — the unified structure every downstream component uses.

    Raises:
        UnsupportedFileTypeError, EmptyExtractionError, CorruptedFileError, PasswordProtectedError
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")

    parser = get_parser_for_file(path)
    parsed = parser.parse(path)

    normalised_text = normalise_text(parsed.raw_text)

    if not normalised_text.strip():
        # Defensive: parser-level extraction already checks this, but
        # normalisation could theoretically strip everything as "footer noise" on a pathological input.
        raise EmptyExtractionError(path.name, likely_cause="no usable text remaining after normalisation")

    parsed.raw_text = normalised_text

    if rechunk:
        parsed.sections = detect_sections(normalised_text)

    return parsed