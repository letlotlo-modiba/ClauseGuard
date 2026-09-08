"""
ClauseGuard Agent - AI Contract Triage Assistant.
Built with Strands Agents SDK and Amazon Bedrock.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
import strands
from strands import Agent

load_dotenv()

try:
    from .clause_tools import extract_clauses, flag_risky_clause
    from .prompts import CLAUSEGUARD_SYSTEM_PROMPT
except (ImportError, ValueError):
    from clause_tools import extract_clauses, flag_risky_clause
    from prompts import CLAUSEGUARD_SYSTEM_PROMPT


def is_aws_configured() -> bool:
    """Check if AWS credentials and region appear available."""
    has_keys = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(os.environ.get("AWS_SECRET_ACCESS_KEY"))
    has_profile = bool(os.environ.get("AWS_PROFILE"))
    has_aws_file = Path("~/.aws/credentials").expanduser().exists()
    return has_keys or has_profile or has_aws_file


def create_clauseguard_agent(
    model_id: Optional[str] = None,
    region_name: Optional[str] = None,
) -> Agent:
    """
    Constructs a Strands Agent configured with ClauseGuard's system prompt,
    custom tools (extract_clauses, flag_risky_clause), and Amazon Bedrock model.
    """
    model_id = model_id or os.environ.get(
        "BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    region_name = region_name or os.environ.get(
        "AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1")
    )

    tools = [extract_clauses, flag_risky_clause]

    if is_aws_configured():
        from strands.models import BedrockModel

        model = BedrockModel(model_id=model_id, region_name=region_name)
        return Agent(
            model=model,
            tools=tools,
            system_prompt=CLAUSEGUARD_SYSTEM_PROMPT,
            name="ClauseGuard",
            description="AI Contract Triage Assistant powered by Strands Agents and Amazon Bedrock.",
        )
    else:
        # Without AWS credentials, return agent configured with tools and prompt
        return Agent(
            tools=tools,
            system_prompt=CLAUSEGUARD_SYSTEM_PROMPT,
            name="ClauseGuard-Local",
            description="AI Contract Triage Assistant (Local Evaluation Mode).",
        )


def triage_contract(
    document_path: str,
    contract_type: str = "General Contract",
) -> dict[str, Any]:
    """
    Core end-to-end triage loop:
    1. Parse and extract clauses using extract_clauses tool.
    2. Evaluate each clause using flag_risky_clause tool.
    3. Generate structured triage report conforming to Draft v1 system prompt.
    """
    path = Path(document_path)
    if not path.exists():
        raise FileNotFoundError(f"Contract file not found: {document_path}")

    # Step 1: Structural extraction via Strands tool
    # Tool call returns dict or tool result
    extract_result = extract_clauses(str(path))
    if extract_result.get("status") != "success":
        error_msg = extract_result.get("message", "Failed to extract clauses")
        raise RuntimeError(f"Document parsing error: {error_msg}")

    clauses = extract_result.get("clauses", [])
    filename = extract_result.get("filename", path.name)

    # Step 2: Per-clause evaluation via Strands tool
    flagged_clauses = []
    safe_clauses = []

    for item in clauses:
        clause_id = item.get("clause_id", "")
        clause_heading = item.get("heading") or ""
        clause_text = item.get("text", "").strip()

        if not clause_text or clause_id == "preamble":
            continue

        eval_result = flag_risky_clause(
            clause_text=clause_text,
            clause_id=clause_id,
            clause_heading=clause_heading,
            contract_type=contract_type,
        )

        if eval_result.get("flagged", False):
            flagged_clauses.append(eval_result)
        else:
            safe_clauses.append({
                "clause_id": clause_id,
                "heading": clause_heading,
                "summary": eval_result.get("what_it_says", "Standard clause."),
            })

    # Step 3: Compile 4-part structured report
    report = {
        "filename": filename,
        "contract_type": contract_type,
        "total_clauses_reviewed": len(clauses),
        "flagged_count": len(flagged_clauses),
        "safe_count": len(safe_clauses),
        "flagged_clauses": flagged_clauses,
        "safe_clauses": safe_clauses,
        "overall_notes": _generate_overall_notes(flagged_clauses, clauses),
    }

    return report


def _generate_overall_notes(flagged_clauses: list[dict], all_clauses: list[dict]) -> list[str]:
    """Identify structural anomalies or missing protections (silence)."""
    notes = []
    all_text = " ".join(c.get("text", "") for c in all_clauses).lower()

    # Check silence on standard protections
    if "liability" not in all_text or "limitation of liability" not in all_text:
        notes.append("Silence on Liability Cap: No express limitation of liability clause detected in the document.")
    if "confidential" not in all_text:
        notes.append("Silence on Confidentiality: No confidentiality or non-disclosure protections found.")
    if "dispute" not in all_text and "governing law" not in all_text:
        notes.append("Missing Dispute Resolution: No explicit governing law or dispute resolution clause specified.")

    if not flagged_clauses:
        notes.append("Standard bilateral agreement: No severe asymmetric liabilities or unusual restrictions detected.")
    else:
        notes.append(f"{len(flagged_clauses)} clause(s) require human judgment prior to signing.")

    return notes


def format_markdown_report(report: dict[str, Any]) -> str:
    """Format structured triage output into user-facing Markdown report."""
    md = []
    md.append(f"# ClauseGuard Triage Report: {report['filename']}")
    md.append(f"**Contract Type:** {report['contract_type']} | **Reviewed Clauses:** {report['total_clauses_reviewed']} | **Flagged for Human Review:** {report['flagged_count']}\n")
    md.append("> [!IMPORTANT]")
    md.append("> **ClauseGuard is a triage assistant, not legal counsel.** The items below require human business/legal judgment before signing.\n")

    # Part 1: Summary
    md.append("## 1. Summary")
    md.append(
        f"This document is a **{report['contract_type']}** ({report['filename']}) containing {report['total_clauses_reviewed']} sections. "
        f"ClauseGuard reviewed the terms against the 7-category risk rubric and identified **{report['flagged_count']} clause(s)** "
        "requiring human judgment and counterparty clarification.\n"
    )

    # Part 2: Flagged Clauses
    md.append("## 2. Flagged Clauses (Requires Human Judgment)")
    if not report["flagged_clauses"]:
        md.append("✅ *No high-risk or asymmetric clauses were flagged. All examined clauses appear standard for this document type.*\n")
    else:
        for idx, clause in enumerate(report["flagged_clauses"], 1):
            heading_info = f" — {clause.get('clause_heading')}" if clause.get("clause_heading") else ""
            c_id = clause.get("clause_id", f"Section {idx}")
            level = clause.get("risk_level", "HIGH")
            category = clause.get("risk_category", "FLAGGED")

            badge = f"**[{level} RISK | {category}]**"
            md.append(f"### {idx}. Section {c_id}{heading_info} {badge}")
            md.append(f"- **What it says:** {clause.get('what_it_says')}")
            md.append(f"- **Why it matters:** {clause.get('why_it_matters')}")
            md.append(f"- **Question to ask counterparty:** 💬 *\"{clause.get('question_to_ask')}\"*\n")

    # Part 3: Plain-Language Summary
    md.append("## 3. Plain-Language Summary (Everything Else)")
    if not report["safe_clauses"]:
        md.append("*No additional sections to summarize.*\n")
    else:
        for item in report["safe_clauses"]:
            h = item.get("heading") or f"Section {item.get('clause_id')}"
            md.append(f"- **{h} (Section {item.get('clause_id')}):** {item.get('summary')}")
        md.append("")

    # Part 4: Overall Notes
    md.append("## 4. Overall Notes & Structural Observations")
    for note in report.get("overall_notes", []):
        md.append(f"- {note}")
    md.append("")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(
        description="ClauseGuard: AI Contract Triage Assistant built with Strands Agents."
    )
    parser.add_argument("contract_path", help="Path to the contract file (.docx, .pdf, .txt)")
    parser.add_argument(
        "--type",
        dest="contract_type",
        default="General Contract",
        help="Type of contract (e.g., 'Freelance Agreement', 'SaaS Agreement', 'Commercial Lease')",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted Markdown",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Optional file path to save the output report",
    )

    args = parser.parse_args()

    try:
        report = triage_contract(args.contract_path, contract_type=args.contract_type)
        if args.json:
            output_text = json.dumps(report, indent=2)
        else:
            output_text = format_markdown_report(report)

        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
            print(f"Report saved to {args.output}")
        else:
            print(output_text)

    except Exception as exc:
        print(f"Error processing contract: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
