"""
Unit and Integration Tests for ClauseGuard Week 2 Implementation.
Validates:
1. summarize_clause tool (plain language, key obligations, boilerplate detection)
2. draft_questions tool (primary question, fallback, compromise, negotiation goal)
3. retrieve_precedent tool (curated library lookup, benchmark clause retrieval)
4. Calibration & anti-overflagging (lease premises indemnity, custom IP, standard terms)
5. Ground truth benchmark validation against answer_key.json (all 5 contracts)
6. Structured TriageReport output formats (JSON serialization and Markdown rendering)
7. Strands Agent integration with all 5 tools registered
"""

import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import (
    DraftedQuestion,
    FlaggedClause,
    PrecedentResult,
    RiskCategory,
    RiskLevel,
    SafeClauseSummary,
    TriageReport,
)
from clause_tools import (
    draft_questions,
    extract_clauses,
    flag_risky_clause,
    retrieve_precedent,
    summarize_clause,
)
from agent import (
    create_clauseguard_agent,
    format_markdown_report,
    triage_contract,
)

SAMPLE_DIR = Path(__file__).parent / "sample_contracts"


class TestSummarizeClauseTool:
    def test_summarize_payment_clause(self):
        text = "Client shall pay Contractor an hourly rate of $120.00. Invoices shall be paid within thirty (30) days of receipt."
        result = summarize_clause(text, clause_id="2", clause_heading="PAYMENT")
        assert result["status"] == "success"
        assert result["clause_id"] == "2"
        assert "compensation" in result["summary"].lower() or "payment" in result["summary"].lower()
        assert len(result["key_obligations"]) > 0
        assert result["is_standard"] is True

    def test_summarize_confidentiality_clause(self):
        text = "Each party agrees to hold the other party's Confidential Information in strict confidence for two (2) years."
        result = summarize_clause(text, clause_id="5", clause_heading="CONFIDENTIALITY")
        assert result["status"] == "success"
        assert "confidential" in result["summary"].lower()
        assert len(result["key_obligations"]) > 0

    def test_summarize_lease_premises_indemnity_clause(self):
        text = "Tenant shall maintain commercial general liability insurance of $2,000,000 and indemnify Landlord against any liability occurring on the premises."
        result = summarize_clause(text, clause_id="9", clause_heading="INSURANCE AND INDEMNITY")
        assert result["status"] == "success"
        assert "insurance" in result["summary"].lower() or "liability" in result["summary"].lower()
        assert len(result["key_obligations"]) > 0

    def test_summarize_empty_clause(self):
        result = summarize_clause("", clause_id="0")
        assert result["status"] == "success"
        assert "empty" in result["summary"].lower()


class TestDraftQuestionsTool:
    def test_draft_questions_unilateral_indemnity(self):
        text = "Contractor shall defend, indemnify, and hold harmless Company from all losses. No reciprocal obligation."
        result = draft_questions(
            clause_text=text,
            clause_id="7",
            clause_heading="INDEMNIFICATION",
            risk_category="FINANCIAL_EXPOSURE",
            risk_level="HIGH",
        )
        assert result["status"] == "success"
        assert "mutual" in result["primary_question"].lower()
        assert "suggested_compromise" in result
        assert len(result["suggested_compromise"]) > 0
        assert "negotiation_goal" in result

    def test_draft_questions_ip_grab(self):
        text = "Contractor assigns all inventions and background IP developed prior to the effective date."
        result = draft_questions(
            clause_text=text,
            clause_id="4",
            clause_heading="INTELLECTUAL PROPERTY",
            risk_category="IP_AND_RIGHTS",
            risk_level="HIGH",
        )
        assert result["status"] == "success"
        assert "pre-existing" in result["primary_question"].lower() or "carve out" in result["primary_question"].lower()
        assert len(result["fallback_question"]) > 0

    def test_draft_questions_unilateral_modification(self):
        text = "Provider reserves the right to modify subscription terms and pricing at any time."
        result = draft_questions(
            clause_text=text,
            clause_id="6",
            clause_heading="MODIFICATION OF TERMS",
            risk_category="UNILATERAL_MODIFICATION",
            risk_level="HIGH",
        )
        assert result["status"] == "success"
        assert "notice" in result["primary_question"].lower() or "written" in result["primary_question"].lower()

    def test_draft_questions_empty_clause(self):
        result = draft_questions("", clause_id="0")
        assert result["status"] == "success"
        assert len(result["primary_question"]) > 0


class TestRetrievePrecedentTool:
    def test_retrieve_indemnity_precedent(self):
        result = retrieve_precedent("unilateral indemnification defense", risk_category="FINANCIAL_EXPOSURE")
        assert result["status"] == "success"
        assert result["found"] is True
        assert "Indemnification" in result["precedent_title"]
        assert len(result["standard_clause_text"]) > 0
        assert len(result["market_standard_explanation"]) > 0

    def test_retrieve_ip_carveout_precedent(self):
        result = retrieve_precedent("pre-existing IP background inventions", risk_category="IP_AND_RIGHTS")
        assert result["status"] == "success"
        assert result["found"] is True
        assert "IP" in result["precedent_title"] or "Work Product" in result["precedent_title"]

    def test_retrieve_termination_precedent(self):
        result = retrieve_precedent("termination for convenience notice forfeiture", risk_category="TERMINATION_AND_LOCKIN")
        assert result["status"] == "success"
        assert result["found"] is True
        assert "Termination" in result["precedent_title"]

    def test_retrieve_operating_expenses_precedent(self):
        result = retrieve_precedent("capital improvements operating expenses pass-throughs", risk_category="FINANCIAL_EXPOSURE")
        assert result["status"] == "success"
        assert result["found"] is True
        assert "Operating Expenses" in result["precedent_title"] or "Lease" in result["precedent_title"]


class TestCalibrationAgainstSampleContracts:
    @classmethod
    def setup_class(cls):
        with open(SAMPLE_DIR / "answer_key.json", "r", encoding="utf-8") as f:
            cls.answer_key = json.load(f)

    def test_all_five_contracts_match_answer_key(self):
        """Validate that all 5 benchmark contracts strictly match ground truth expected flag counts."""
        for entry in self.answer_key["contracts"]:
            filename = entry["filename"]
            contract_type = entry["contract_type"]
            expected_flags = entry["expected_flag_count"]
            file_path = SAMPLE_DIR / filename

            report = triage_contract(str(file_path), contract_type=contract_type)

            assert report.flagged_count == expected_flags, (
                f"{filename}: expected {expected_flags} flags, got {report.flagged_count}"
            )

            # Check that expected flagged section IDs match
            if expected_flags > 0:
                expected_ids = {c["clause_id"] for c in entry["flagged_clauses"]}
                actual_ids = {c["clause_id"] for c in report.flagged_clauses}
                assert actual_ids == expected_ids, (
                    f"{filename}: expected flagged IDs {expected_ids}, got {actual_ids}"
                )

    def test_negative_control_safe_vendor_produces_low_risk(self):
        report = triage_contract(
            str(SAMPLE_DIR / "05_safe_standard_vendor_agreement.txt"),
            contract_type="Procurement Agreement",
        )
        assert report.flagged_count == 0
        assert report.risk_score == "LOW"
        assert len(report.safe_clauses) > 0
        assert len(report.drafted_questions) == 0


class TestStructuredTriageReport:
    @classmethod
    def setup_class(cls):
        cls.report = triage_contract(
            str(SAMPLE_DIR / "01_freelance_developer_agreement.txt"),
            contract_type="Independent Contractor Agreement",
        )

    def test_report_object_attributes(self):
        assert isinstance(self.report, TriageReport)
        assert self.report.filename == "01_freelance_developer_agreement.txt"
        assert self.report.contract_type == "Independent Contractor Agreement"
        assert self.report.risk_score == "HIGH"
        assert len(self.report.executive_summary) > 0
        assert self.report.flagged_count == 4
        assert len(self.report.drafted_questions) == 4
        assert len(self.report.safe_clauses) > 0

    def test_report_backward_compatibility_dict_access(self):
        # Existing callers can treat TriageReport like a dict
        assert self.report["flagged_count"] == 4
        assert "safe_clauses" in self.report
        assert self.report.get("contract_type") == "Independent Contractor Agreement"
        assert "filename" in list(self.report.keys())
        d = dict(self.report)
        assert d["flagged_count"] == 4

    def test_report_to_json_valid(self):
        json_str = self.report.to_json(indent=2)
        parsed = json.loads(json_str)
        assert parsed["filename"] == "01_freelance_developer_agreement.txt"
        assert parsed["risk_score"] == "HIGH"
        assert len(parsed["flagged_clauses"]) == 4
        assert len(parsed["drafted_questions"]) == 4
        assert len(parsed["safe_clauses"]) > 0

    def test_report_to_markdown_conforms_to_spec(self):
        md = self.report.to_markdown()

        # Check required 4 major sections
        assert "## 1. Summary" in md
        assert "## 2. Flagged Clauses (Requires Human Judgment)" in md
        assert "## 3. Plain-Language Summary (Everything Else)" in md
        assert "## 4. Overall Notes & Structural Observations" in md

        # Check ready-to-send questions checklist
        assert "Ready-to-Send Counterparty Questions" in md

        # Check flagged clause details
        assert "What it says:" in md
        assert "Why it matters:" in md
        assert "Question to ask counterparty:" in md
        assert "Suggested compromise:" in md
        assert "Standard precedent reference:" in md


class TestStrandsAgentWeek2Integration:
    def test_agent_registered_all_week2_tools(self):
        agent = create_clauseguard_agent()
        tool_names = agent.tool_names
        expected_tools = [
            "extract_clauses",
            "flag_risky_clause",
            "summarize_clause",
            "draft_questions",
            "retrieve_precedent",
        ]
        for t in expected_tools:
            assert t in tool_names, f"Tool {t} missing from Agent.tool_names: {tool_names}"

    def test_agent_system_prompt_present(self):
        agent = create_clauseguard_agent()
        assert agent.system_prompt is not None
        assert "ClauseGuard" in agent.system_prompt
        assert "Flag" in agent.system_prompt
        assert "Summarize" in agent.system_prompt
        assert "Question" in agent.system_prompt
