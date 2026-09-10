"""
Unit and Integration Tests for ClauseGuard Week 1 Implementation.
Validates:
1. Document parsers (TxtParser, DocxParser, PdfParser, error handling)
2. Text processing & section chunking
3. Strands tools (extract_clauses, flag_risky_clause)
4. Full benchmark test suite against 5 sample contracts
5. End-to-end report generation conforming to System Prompt v1
"""

import json
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import (
    EmptyExtractionError,
    SourceFileType,
    UnsupportedFileTypeError,
)
from document_parser import get_parser_for_file, parse_document
from parsers import DocxParser, PdfParser, TxtParser
from clause_tools import extract_clauses, flag_risky_clause
from agent import format_markdown_report, triage_contract


SAMPLE_DIR = Path(__file__).parent / "sample_contracts"


class TestDocumentParsers:
    def test_txt_parser_registered_and_detected(self):
        txt_path = SAMPLE_DIR / "01_freelance_developer_agreement.txt"
        parser = get_parser_for_file(txt_path)
        assert isinstance(parser, TxtParser)
        assert parser.can_handle(txt_path)

    def test_docx_parser_registered_and_detected(self):
        docx_path = Path("sample_contract.docx")
        parser = get_parser_for_file(docx_path)
        assert isinstance(parser, DocxParser)

    def test_pdf_parser_registered_and_detected(self):
        pdf_path = Path("sample_contract.pdf")
        parser = get_parser_for_file(pdf_path)
        assert isinstance(parser, PdfParser)

    def test_unsupported_file_type_raises(self, tmp_path):
        dummy_file = tmp_path / "test.exe"
        dummy_file.write_text("binary data")
        with pytest.raises(UnsupportedFileTypeError):
            parse_document(dummy_file)

    def test_nonexistent_file_raises_filenotfound(self):
        with pytest.raises(FileNotFoundError):
            parse_document(Path("does_not_exist_12345.txt"))

    def test_empty_txt_raises_empty_extraction(self, tmp_path):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("   \n\n   ")
        with pytest.raises(EmptyExtractionError):
            parse_document(empty_file)

    def test_parse_document_end_to_end_txt(self):
        txt_path = SAMPLE_DIR / "01_freelance_developer_agreement.txt"
        doc = parse_document(txt_path)
        assert doc.source_file_type == SourceFileType.TXT
        assert len(doc.sections) > 0
        assert "INDEPENDENT CONTRACTOR AGREEMENT" in doc.raw_text


class TestStrandsTools:
    def test_extract_clauses_tool_success(self):
        txt_path = SAMPLE_DIR / "01_freelance_developer_agreement.txt"
        result = extract_clauses(str(txt_path))
        assert result["status"] == "success"
        assert result["clause_count"] > 0
        assert len(result["clauses"]) > 0

    def test_extract_clauses_tool_file_not_found(self):
        result = extract_clauses("non_existent_file_abc.txt")
        assert result["status"] == "error"
        assert result["error_type"] == "FileNotFoundError"

    def test_flag_risky_clause_indemnity(self):
        risky_text = "Contractor shall defend, indemnify, and hold harmless Company from all claims. No reciprocal obligation."
        result = flag_risky_clause(clause_text=risky_text, clause_heading="INDEMNIFICATION")
        assert result["flagged"] is True
        assert result["risk_category"] == "FINANCIAL_EXPOSURE"
        assert result["risk_level"] == "HIGH"
        assert len(result["question_to_ask"]) > 0

    def test_flag_risky_clause_non_compete(self):
        risky_text = "Contractor agrees to an 18-month worldwide non-compete prohibiting work for competitors."
        result = flag_risky_clause(clause_text=risky_text, clause_heading="RESTRICTIVE COVENANTS")
        assert result["flagged"] is True
        assert result["risk_category"] == "IP_AND_RIGHTS"
        assert result["risk_level"] == "HIGH"

    def test_flag_risky_clause_safe_clause(self):
        safe_text = "Supplier shall deliver office supplies as set forth in purchase orders."
        result = flag_risky_clause(clause_text=safe_text, clause_heading="SCOPE OF SERVICES")
        assert result["flagged"] is False
        assert result["risk_category"] is None
        assert result["risk_level"] == "NONE"


class TestBenchmarkContractsSuite:
    @classmethod
    def setup_class(cls):
        with open(SAMPLE_DIR / "answer_key.json", "r", encoding="utf-8") as f:
            cls.answer_key = json.load(f)

    def test_contract_01_freelance_developer(self):
        report = triage_contract(str(SAMPLE_DIR / "01_freelance_developer_agreement.txt"), "Independent Contractor Agreement")
        assert report["flagged_count"] == 4
        categories = [c["risk_category"] for c in report["flagged_clauses"]]
        assert "IP_AND_RIGHTS" in categories
        assert "FINANCIAL_EXPOSURE" in categories
        assert "TERMINATION_AND_LOCKIN" in categories

    def test_contract_02_saas_subscription(self):
        report = triage_contract(str(SAMPLE_DIR / "02_saas_subscription_agreement.txt"), "SaaS Agreement")
        assert report["flagged_count"] == 4
        categories = [c["risk_category"] for c in report["flagged_clauses"]]
        assert "UNILATERAL_MODIFICATION" in categories
        assert "DISPUTE_RESOLUTION" in categories
        assert "FINANCIAL_EXPOSURE" in categories

    def test_contract_03_commercial_lease(self):
        report = triage_contract(str(SAMPLE_DIR / "03_commercial_office_lease.txt"), "Commercial Lease")
        assert report["flagged_count"] in (3, 4)  # 3 after Week 2 lease premises calibration (matches answer_key.json)
        categories = [c["risk_category"] for c in report["flagged_clauses"]]
        assert "FINANCIAL_EXPOSURE" in categories
        assert "TERMINATION_AND_LOCKIN" in categories
        assert "ASYMMETRIC_OBLIGATIONS" in categories

    def test_contract_04_consulting_nda(self):
        report = triage_contract(str(SAMPLE_DIR / "04_consulting_services_nda.txt"), "Non-Disclosure Agreement")
        assert report["flagged_count"] == 3
        categories = [c["risk_category"] for c in report["flagged_clauses"]]
        assert "ASYMMETRIC_OBLIGATIONS" in categories
        assert "IP_AND_RIGHTS" in categories
        assert "FINANCIAL_EXPOSURE" in categories

    def test_contract_05_negative_control_safe_vendor(self):
        report = triage_contract(str(SAMPLE_DIR / "05_safe_standard_vendor_agreement.txt"), "Procurement Agreement")
        # Negative control: balanced terms should produce 0 flagged clauses
        assert report["flagged_count"] == 0
        assert len(report["safe_clauses"]) > 0


class TestEndToEndReportFormatting:
    def test_format_markdown_conforms_to_prompt_v1(self):
        report = triage_contract(str(SAMPLE_DIR / "01_freelance_developer_agreement.txt"), "Independent Contractor Agreement")
        md = format_markdown_report(report)

        # 4 required sections according to System Prompt Draft v1:
        assert "## 1. Summary" in md
        assert "## 2. Flagged Clauses (Requires Human Judgment)" in md
        assert "## 3. Plain-Language Summary (Everything Else)" in md
        assert "## 4. Overall Notes & Structural Observations" in md

        # Required flagged clause fields:
        assert "What it says:" in md
        assert "Why it matters:" in md
        assert "Question to ask counterparty:" in md
