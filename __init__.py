
try:
    from .document_parser import get_parser_for_file, parse_document
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
except (ImportError, ValueError):
    from document_parser import get_parser_for_file, parse_document
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

__all__ = [
    "parse_document",
    "get_parser_for_file",
    "DocumentParser",
    "DocxParser",
    "PdfParser",
    "TxtParser",
    "CorruptedFileError",
    "DocumentParsingError",
    "DocumentSection",
    "EmptyExtractionError",
    "ExtractionMethod",
    "ParsedDocument",
    "PasswordProtectedError",
    "SourceFileType",
    "UnsupportedFileTypeError",
]