

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class SourceFileType(Enum):

    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"

class ExtractionMethod(Enum):

    NATIVE_TEXT = "native_text" # normal text-layer extraction
    OCR_FALLBACK = "ocr_fallback"   # for scanned documents and not implemented for now
    TABLE_EXTRACTION = "table_extraction"

@dataclass
class DocumentSection():
    """One structural chunk of the document — a clause, heading, or paragraph."""
    text: str
    section_id: str # "1", "2.1", or "para_14" if no numbering found
    page_number: Optional[int]
    heading: Optional[str]  # nearest heading/section title, if detected
    is_table: bool = False

@dataclass
class ParsedDocument():
    """Unified output every downstream component consumes."""
    raw_text: str
    sections: list[DocumentSection]
    source_file_type: SourceFileType
    extraction_method: ExtractionMethod
    page_count: Optional[int]
    filename: str
    warnings: list[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# Exception Handling - specific so callers can react differently to each.
# -----------------------------------------------------------------------

class DocumentParsingError(Exception):
    """Base class for all parsing failures"""
    def __init__(self, message: str, *, filename: Optional[str] = None, user_message: Optional[str] = None):
        self.filename = filename
        self.user_message = user_message or message
        super().__init__(message)

    def __str__(self) -> str:
        if self.filename:
            return f"[{self.filename}] {super().__str__()}"
        return super().__str__()


class UnsupportedFileTypeError(DocumentParsingError):
    """Raised when the file extension isn't .docx, .pdf, or .txt."""
    def __init__(self, filename: str, extension: str, supported_extensions: tuple[str, ...] = (".docx", ".pdf", ".txt")):
        self.extension = extension
        self.supported_extensions = supported_extensions
        message = (
            f"Unsupported file type '{extension}' for {filename} "
            f"(supported: {', '.join(supported_extensions)})"
        )
        user_message = (
            f"ClauseGuard can't read '{extension}' files yet. "
            f"Please upload a {' or '.join(supported_extensions)} files instead."
        )
        super().__init__(message, filename=filename, user_message=user_message)


class EmptyExtractionError(DocumentParsingError):
    """Raised when extraction yields ~0 usable text.

    Most commonly a scanned/image-only PDF with no text layer, but can also
    fire on a genuinely empty file or one that's all header/footer noise.
    """

    def __init__(self, filename: str, likely_cause: Optional[str] = None):
        self.likely_cause = likely_cause
        detail = f"({likely_cause})" if likely_cause else ""
        message = f"No extractable text found in {filename}{detail}"

        if likely_cause and "scanned" in likely_cause.lower():
            user_message = (
                f"'{filename}' appears to be a scanned document with no readable text layer. "
                f"ClauseGuard doesn't support OCR yet, so scanned documents can't be processed — "
                f"please upload a text-based version if you have one."
            )
        else:
            user_message = f"'{filename}' appears to be empty or has no readable text."
        super().__init__(message, filename=filename, user_message=user_message)


class CorruptedFileError(DocumentParsingError):
    """Raised when the underlying library can't open/parse the file at all."""

    def __init__(self, filename: str, original_exception: Optional[Exception] = None):
        self.original_exception = original_exception
        detail = f": {original_exception}" if original_exception else ""
        message = f"Could not open {filename} — file may be corrupted{detail}"
        user_message = (
            f"'{filename}' couldn't be opened. It may be corrupted, or not actually "
            f"a valid file of its type — try re-saving or re-exporting it."
        )
        super().__init__(message, filename=filename, user_message=user_message)


class PasswordProtectedError(DocumentParsingError):
    """Raised when a PDF is encrypted and can't be read without a password."""

    def __init__(self, filename: str):
        message = f"'{filename}' is password-protected and cannot be read"
        user_message = (
            f"'{filename}' is password-protected. Please upload an unlocked version — "
            f"ClauseGuard can't prompt for a password."
        )
        super().__init__(message, filename=filename, user_message=user_message)