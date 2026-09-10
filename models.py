

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from typing import Any, Optional

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


# -----------------------------------------------------------------------
# Triage Output Models & Structured Formats (Week 2)
# -----------------------------------------------------------------------

class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class RiskCategory(str, Enum):
    FINANCIAL_EXPOSURE = "FINANCIAL_EXPOSURE"
    IP_AND_RIGHTS = "IP_AND_RIGHTS"
    TERMINATION_AND_LOCKIN = "TERMINATION_AND_LOCKIN"
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"
    UNILATERAL_MODIFICATION = "UNILATERAL_MODIFICATION"
    ASYMMETRIC_OBLIGATIONS = "ASYMMETRIC_OBLIGATIONS"
    SILENCE_OR_AMBIGUITY = "SILENCE_OR_AMBIGUITY"


@dataclass
class FlaggedClause:
    """Detailed risk assessment of a clause requiring human judgment."""
    clause_id: str
    risk_category: str
    risk_level: str = "HIGH"
    clause_heading: Optional[str] = None
    what_it_says: str = ""
    why_it_matters: str = ""
    question_to_ask: str = ""
    suggested_compromise: Optional[str] = None
    precedent_reference: Optional[str] = None
    raw_text: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "clause_heading": self.clause_heading or "",
            "flagged": True,
            "risk_category": self.risk_category,
            "risk_level": self.risk_level,
            "what_it_says": self.what_it_says,
            "why_it_matters": self.why_it_matters,
            "question_to_ask": self.question_to_ask,
            "suggested_compromise": self.suggested_compromise or "",
            "precedent_reference": self.precedent_reference or "",
        }


@dataclass
class SafeClauseSummary:
    """Concise plain-language translation of a routine/safe contract clause."""
    clause_id: str
    heading: Optional[str] = None
    summary: str = ""
    key_obligations: list[str] = field(default_factory=list)
    is_standard: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "heading": self.heading or f"Section {self.clause_id}",
            "summary": self.summary,
            "key_obligations": self.key_obligations,
            "is_standard": self.is_standard,
        }


@dataclass
class DraftedQuestion:
    """Specific questions and compromise proposals drafted for counterparties."""
    clause_id: str
    primary_question: str
    clause_heading: Optional[str] = None
    risk_category: Optional[str] = None
    fallback_question: Optional[str] = None
    suggested_compromise: Optional[str] = None
    negotiation_goal: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "clause_heading": self.clause_heading or "",
            "risk_category": self.risk_category or "",
            "primary_question": self.primary_question,
            "fallback_question": self.fallback_question or "",
            "suggested_compromise": self.suggested_compromise or "",
            "negotiation_goal": self.negotiation_goal or "",
        }


@dataclass
class PrecedentResult:
    """Market-standard benchmark clause or precedent retrieved for comparison."""
    found: bool
    precedent_title: str
    standard_clause_text: str
    market_standard_explanation: str
    source: str = "curated_precedent_library"
    risk_category: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "precedent_title": self.precedent_title,
            "standard_clause_text": self.standard_clause_text,
            "market_standard_explanation": self.market_standard_explanation,
            "source": self.source,
            "risk_category": self.risk_category or "",
        }


@dataclass
class TriageReport:
    """
    Complete end-to-end ClauseGuard Triage Report.
    Conforms to the 4-part structure (Summary, Flagged Clauses, Plain-Language Summary, Overall Notes)
    and supports both Markdown export and UI-ready structured JSON.
    """
    filename: str
    contract_type: str
    total_clauses_reviewed: int
    flagged_count: int
    safe_count: int
    risk_score: str = "LOW"
    executive_summary: str = ""
    flagged_clauses: list[dict[str, Any]] = field(default_factory=list)
    safe_clauses: list[dict[str, Any]] = field(default_factory=list)
    drafted_questions: list[dict[str, Any]] = field(default_factory=list)
    overall_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "contract_type": self.contract_type,
            "risk_score": self.risk_score,
            "executive_summary": self.executive_summary,
            "total_clauses_reviewed": self.total_clauses_reviewed,
            "flagged_count": self.flagged_count,
            "safe_count": self.safe_count,
            "flagged_clauses": self.flagged_clauses,
            "safe_clauses": self.safe_clauses,
            "drafted_questions": self.drafted_questions,
            "overall_notes": self.overall_notes,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        md = []
        badge = f"[{self.risk_score} RISK]"
        md.append(f"# ClauseGuard Triage Report: {self.filename}")
        md.append(
            f"**Contract Type:** {self.contract_type} | "
            f"**Overall Assessment:** {badge} | "
            f"**Reviewed Sections:** {self.total_clauses_reviewed} | "
            f"**Flagged for Human Review:** {self.flagged_count}\n"
        )
        md.append("> [!IMPORTANT]")
        md.append(
            "> **ClauseGuard is an AI triage assistant, not legal counsel.** "
            "The flagged provisions below require human business or legal judgment before signing.\n"
        )

        # Part 1: Summary
        md.append("## 1. Summary")
        if self.executive_summary:
            md.append(f"{self.executive_summary}\n")
        else:
            md.append(
                f"This document is a **{self.contract_type}** ({self.filename}) containing {self.total_clauses_reviewed} sections. "
                f"ClauseGuard evaluated the terms against the 7-category risk rubric and identified **{self.flagged_count} clause(s)** "
                "requiring human judgment and counterparty clarification.\n"
            )

        # Part 2: Flagged Clauses (Requires Human Judgment)
        md.append("## 2. Flagged Clauses (Requires Human Judgment)")
        if not self.flagged_clauses:
            md.append("✅ *No high-risk or asymmetric clauses were flagged. All examined clauses appear standard for this document type.*\n")
        else:
            for idx, clause in enumerate(self.flagged_clauses, 1):
                heading_info = f" — {clause.get('clause_heading')}" if clause.get("clause_heading") else ""
                c_id = clause.get("clause_id", f"Section {idx}")
                level = clause.get("risk_level", "HIGH")
                category = clause.get("risk_category", "FLAGGED")

                risk_badge = f"**[{level} RISK | {category}]**"
                md.append(f"### {idx}. Section {c_id}{heading_info} {risk_badge}")
                md.append(f"- **What it says:** {clause.get('what_it_says')}")
                md.append(f"- **Why it matters:** {clause.get('why_it_matters')}")
                md.append(f"- **Question to ask counterparty:** 💬 *\"{clause.get('question_to_ask')}\"*")
                if clause.get("suggested_compromise"):
                    md.append(f"- **Suggested compromise:** 💡 {clause.get('suggested_compromise')}")
                if clause.get("precedent_reference"):
                    md.append(f"- **Standard precedent reference:** 📜 {clause.get('precedent_reference')}")
                md.append("")

        # Action Checklist: Questions to Send Counterparty
        if self.drafted_questions:
            md.append("### 📋 Ready-to-Send Counterparty Questions")
            md.append("Copy and paste these questions directly to your counterparty:")
            for q in self.drafted_questions:
                h = f" ({q.get('clause_heading')})" if q.get("clause_heading") else ""
                md.append(f"- **Section {q.get('clause_id')}{h}:** {q.get('primary_question')}")
                if q.get("suggested_compromise"):
                    md.append(f"  *Proposed compromise:* {q.get('suggested_compromise')}")
            md.append("")

        # Part 3: Plain-Language Summary (Everything Else)
        md.append("## 3. Plain-Language Summary (Everything Else)")
        if not self.safe_clauses:
            md.append("*No additional sections to summarize.*\n")
        else:
            for item in self.safe_clauses:
                h = item.get("heading") or f"Section {item.get('clause_id')}"
                summary_text = item.get("summary") or "Standard contract provision."
                md.append(f"- **{h} (Section {item.get('clause_id')}):** {summary_text}")
                if item.get("key_obligations"):
                    obs = "; ".join(item["key_obligations"])
                    md.append(f"  *Key obligations:* {obs}")
            md.append("")

        # Part 4: Overall Notes & Structural Observations
        md.append("## 4. Overall Notes & Structural Observations")
        if self.overall_notes:
            for note in self.overall_notes:
                md.append(f"- {note}")
        else:
            md.append("- No unusual structural anomalies or omissions detected.")
        md.append("")

        return "\n".join(md)

    # Dict-like interface for backward compatibility with existing tests
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def __iter__(self):
        return iter(self.to_dict())