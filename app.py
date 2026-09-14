"""
ClauseGuard Streamlit Web Application.
AI Contract Triage Assistant powered by Strands Agents SDK and Amazon Bedrock.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent import format_markdown_report, is_aws_configured, triage_contract
from models import TriageReport

# ---------------------------------------------------------------------------
# Page Configuration & Styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ClauseGuard — AI Contract Triage",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for clean, professional contract review UI
st.markdown("""
<style>
    .main-header {
        font-size: 2.3rem;
        font-weight: 800;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .badge-pill {
        display: inline-block;
        padding: 0.25rem 0.65rem;
        font-size: 0.8rem;
        font-weight: 600;
        border-radius: 9999px;
        margin-right: 0.5rem;
    }
    .badge-aws {
        background-color: #FF9900;
        color: #FFFFFF;
    }
    .badge-strands {
        background-color: #2563EB;
        color: #FFFFFF;
    }
    .badge-agentcore {
        background-color: #10B981;
        color: #FFFFFF;
    }
    .risk-high {
        background-color: #FEE2E2;
        color: #991B1B;
        border-left: 5px solid #EF4444;
        padding: 1rem;
        border-radius: 0.375rem;
        margin-bottom: 1rem;
    }
    .risk-med {
        background-color: #FEF3C7;
        color: #92400E;
        border-left: 5px solid #F59E0B;
        padding: 1rem;
        border-radius: 0.375rem;
        margin-bottom: 1rem;
    }
    .risk-low {
        background-color: #D1FAE5;
        color: #065F46;
        border-left: 5px solid #10B981;
        padding: 1rem;
        border-radius: 0.375rem;
        margin-bottom: 1rem;
    }
    .clause-card {
        border: 1px solid #E2E8F0;
        border-radius: 0.5rem;
        padding: 1.2rem;
        margin-bottom: 1rem;
        background-color: #FFFFFF;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 1.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 1rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar: Setup, Preset Contracts, and Engine Info
# ---------------------------------------------------------------------------

SAMPLE_DIR = Path(__file__).parent / "sample_contracts"

with st.sidebar:
    st.image("https://img.icons8.com/color/96/shield.png", width=64)
    st.title("ClauseGuard")
    st.caption("Autonomous AI Contract Triage Assistant")

    st.markdown("---")
    st.subheader("⚙️ Triage Configuration")

    contract_types = [
        "Independent Contractor Agreement",
        "SaaS Subscription Agreement",
        "Commercial Lease Agreement",
        "Non-Disclosure Agreement (NDA)",
        "Vendor Procurement Agreement",
        "General Commercial Contract",
    ]
    selected_contract_type = st.selectbox(
        "Contract Type",
        options=contract_types,
        index=0,
        help="Contextualizes risk tolerance and benchmark standards",
    )

    st.markdown("---")
    st.subheader("📂 1-Click Benchmark Contracts")
    st.caption("Select a sample contract to test the triage engine:")

    benchmark_options = {
        "None": None,
        "1. Freelance Dev Agreement (4 risks)": "01_freelance_developer_agreement.txt",
        "2. SaaS Subscription (4 risks)": "02_saas_subscription_agreement.txt",
        "3. Commercial Office Lease (3 risks)": "03_commercial_office_lease.txt",
        "4. Consulting NDA (3 risks)": "04_consulting_services_nda.txt",
        "5. Standard Vendor (Safe - 0 risks)": "05_safe_standard_vendor_agreement.txt",
        "6. Test Contract (.docx)": "test_contract.docx",
    }
    selected_sample = st.selectbox(
        "Sample Contract",
        options=list(benchmark_options.keys()),
        index=0,
    )

    st.markdown("---")
    st.subheader("🧠 System Telemetry")
    aws_active = is_aws_configured()
    if aws_active:
        st.success("🟢 Amazon Bedrock: Connected")
        st.caption("Model: Claude Sonnet 4.5 via Bedrock")
    else:
        st.info("🔵 Evaluator: Calibrated Rubric Engine")
        st.caption("Deterministic offline fallback active")

    st.markdown("""
    **Frameworks:**
    - `strands-agents` >= 1.52.0
    - `strands-agents-tools`
    - `AWS Bedrock AgentCore Runtime`
    - `Curated Precedent Library` (7 Benchmarks)
    """)

    st.caption("Hackathon: AWS Agents for Humans | Track: Professional Agents")


# ---------------------------------------------------------------------------
# Main View Header
# ---------------------------------------------------------------------------

col_header_left, col_header_right = st.columns([3, 1])

with col_header_left:
    st.markdown('<div class="main-header">ClauseGuard 🛡️</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">'
        'Eliminating routine contract review busywork. Triage risky clauses, explain routine terms in plain English, and draft ready-to-send questions.'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<span class="badge-pill badge-aws">AWS Bedrock</span>'
        '<span class="badge-pill badge-strands">Strands Agents SDK</span>'
        '<span class="badge-pill badge-agentcore">AgentCore Runtime</span>',
        unsafe_allow_html=True,
    )

with col_header_right:
    st.metric(label="Core Principle", value="Triage, Never Decide", delta="Empowers Human Judgment")

st.markdown("<br>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Contract Input Selection
# ---------------------------------------------------------------------------

tab_upload, tab_text = st.tabs(["📤 Upload Contract File", "✍️ Paste Contract Text"])

target_file_path: Optional[str] = None
active_contract_type = selected_contract_type

with tab_upload:
    uploaded_file = st.file_uploader(
        "Upload contract (.docx, .pdf, .txt)",
        type=["docx", "pdf", "txt"],
        help="Upload standard text-based contracts for structural parsing and triage.",
    )

    if uploaded_file is not None:
        # Save uploaded file to temp path
        temp_dir = Path(tempfile.gettempdir()) / "clauseguard_uploads"
        temp_dir.mkdir(exist_ok=True)
        dest = temp_dir / uploaded_file.name
        dest.write_bytes(uploaded_file.getvalue())
        target_file_path = str(dest)
        st.success(f"Loaded: `{uploaded_file.name}` ({len(uploaded_file.getvalue()):,} bytes)")

    elif selected_sample and benchmark_options[selected_sample]:
        sample_rel = benchmark_options[selected_sample]
        sample_path = SAMPLE_DIR / sample_rel
        if sample_path.exists():
            target_file_path = str(sample_path)
            st.info(f"Loaded benchmark sample: `{sample_rel}`")

with tab_text:
    pasted_text = st.text_area(
        "Paste Contract Text Here",
        height=220,
        placeholder="Paste plain contract sections, terms, or clauses here...",
    )
    if pasted_text.strip() and uploaded_file is None:
        temp_dir = Path(tempfile.gettempdir()) / "clauseguard_uploads"
        temp_dir.mkdir(exist_ok=True)
        dest = temp_dir / "pasted_contract.txt"
        dest.write_text(pasted_text, encoding="utf-8")
        target_file_path = str(dest)


# ---------------------------------------------------------------------------
# Triage Execution Trigger
# ---------------------------------------------------------------------------

btn_col1, btn_col2 = st.columns([1, 4])
with btn_col1:
    triage_button = st.button("🛡️ Triage Contract", type="primary", use_container_width=True)

if triage_button:
    if not target_file_path:
        st.error("Please upload a contract file, select a sample contract from the sidebar, or paste contract text.")
    else:
        with st.spinner("Extracting clauses, evaluating 7-category risk rubric, and retrieving precedents..."):
            try:
                report: TriageReport = triage_contract(target_file_path, contract_type=active_contract_type)
                st.session_state["report"] = report
                st.session_state["report_markdown"] = format_markdown_report(report)
                st.session_state["report_json"] = report.to_json()
                st.success("Triage complete!")
            except Exception as exc:
                st.error(f"Error triaging contract: {exc}")


# ---------------------------------------------------------------------------
# Results Display
# ---------------------------------------------------------------------------

if "report" in st.session_state:
    report: TriageReport = st.session_state["report"]

    st.markdown("---")

    # High-level Metrics Row
    m1, m2, m3, m4 = st.columns(4)

    with m1:
        if report.risk_score == "HIGH":
            st.metric("Overall Risk Assessment", "🔴 HIGH RISK", delta="- Requires Human Review")
        elif report.risk_score == "MEDIUM":
            st.metric("Overall Risk Assessment", "🟡 MEDIUM RISK", delta="Needs Clarification")
        else:
            st.metric("Overall Risk Assessment", "🟢 LOW RISK", delta="Market Standard")

    with m2:
        st.metric("Total Sections Reviewed", report.total_clauses_reviewed)

    with m3:
        st.metric("Flagged for Human Judgment", report.flagged_count, delta=f"{report.flagged_count} to negotiate")

    with m4:
        st.metric("Safe Standard Clauses", report.safe_count, delta="Standard terms")

    # Executive Summary Banner
    if report.risk_score == "HIGH":
        st.markdown(f'<div class="risk-high"><strong>Summary:</strong> {report.executive_summary}</div>', unsafe_allow_html=True)
    elif report.risk_score == "MEDIUM":
        st.markdown(f'<div class="risk-med"><strong>Summary:</strong> {report.executive_summary}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="risk-low"><strong>Summary:</strong> {report.executive_summary}</div>', unsafe_allow_html=True)

    # Detailed Results Tabs
    res_tab1, res_tab2, res_tab3, res_tab4, res_tab5 = st.tabs([
        f"🚨 Flagged Clauses ({report.flagged_count})",
        f"📋 Counterparty Action List ({len(report.drafted_questions)})",
        f"📖 Safe Clauses ({report.safe_count})",
        "🔍 Structural Silences",
        "💾 Export Report",
    ])

    # Tab 1: Flagged Clauses
    with res_tab1:
        if not report.flagged_clauses:
            st.success("✅ No high-risk or asymmetric clauses detected! All examined provisions appear commercially standard.")
        else:
            st.markdown("Review clauses below that require business/legal judgment before signing:")
            for idx, c in enumerate(report.flagged_clauses, 1):
                heading = c.get("clause_heading") or f"Section {c.get('clause_id')}"
                category = c.get("risk_category", "FLAGGED")
                level = c.get("risk_level", "HIGH")
                c_id = c.get("clause_id", str(idx))

                with st.expander(f"**{idx}. Section {c_id}: {heading}** — [{level} | {category}]", expanded=(idx == 1)):
                    st.markdown(f"**What it says:** {c.get('what_it_says')}")
                    st.markdown(f"**Why it matters:** {c.get('why_it_matters')}")

                    q_col1, q_col2 = st.columns([3, 1])
                    with q_col1:
                        st.info(f"💬 **Question to ask counterparty:**\n\n_{c.get('question_to_ask')}_")
                    with q_col2:
                        st.caption("Negotiation Goal:")
                        st.write(c.get("negotiation_goal") or "Clarify & balance terms")

                    if c.get("suggested_compromise"):
                        st.markdown(f"💡 **Suggested compromise:** {c.get('suggested_compromise')}")

                    if c.get("precedent_reference"):
                        st.markdown(f"📜 **Market benchmark precedent:** `{c.get('precedent_reference')}`")
                        if c.get("precedent_text"):
                            with st.expander("View Standard Market Language"):
                                st.code(c.get("precedent_text"), language="markdown")
                                if c.get("market_standard_explanation"):
                                    st.caption(c.get("market_standard_explanation"))

    # Tab 2: Counterparty Action List
    with res_tab2:
        if not report.drafted_questions:
            st.info("No questions needed. Contract contains standard balanced terms.")
        else:
            st.markdown("### 📋 Ready-to-Send Negotiation Checklist")
            st.caption("Copy and paste these concrete questions directly into an email or redline comment for your counterparty:")

            email_body = []
            email_body.append(f"Hi team,\n\nThanks for sending over the {report.contract_type}. We reviewed the document and have a few specific questions and balanced clarifications before we can sign:\n")

            for idx, q in enumerate(report.drafted_questions, 1):
                h = f" ({q.get('clause_heading')})" if q.get("clause_heading") else ""
                item_text = f"{idx}. Section {q.get('clause_id')}{h}: {q.get('primary_question')}"
                if q.get("suggested_compromise"):
                    item_text += f"\n   *Proposed compromise:* {q.get('suggested_compromise')}"
                email_body.append(item_text)

            email_body.append("\nPlease let us know if these adjustments work for you. Looking forward to moving forward!")
            full_email_text = "\n".join(email_body)

            st.text_area("Ready-to-Send Email / Comment Draft", value=full_email_text, height=280)

            for idx, q in enumerate(report.drafted_questions, 1):
                h = f" ({q.get('clause_heading')})" if q.get("clause_heading") else ""
                with st.container():
                    st.markdown(f"**{idx}. Section {q.get('clause_id')}{h}**")
                    st.write(f"💬 *\"{q.get('primary_question')}\"*")
                    if q.get("fallback_question"):
                        st.caption(f"Fallback if pushed back: _{q.get('fallback_question')}_")
                    if q.get("suggested_compromise"):
                        st.markdown(f"💡 *Compromise:* {q.get('suggested_compromise')}")
                    st.markdown("---")

    # Tab 3: Safe Clauses Summary
    with res_tab3:
        st.markdown("### 📖 Plain-Language Summary of Routine Clauses")
        st.caption("Scan through standard commercial terms in under 30 seconds:")

        for item in report.safe_clauses:
            h = item.get("heading") or f"Section {item.get('clause_id')}"
            summary = item.get("summary") or "Standard contract provision."
            obligations = item.get("key_obligations", [])

            with st.container():
                st.markdown(f"**{h} (Section {item.get('clause_id')})**")
                st.write(summary)
                if obligations:
                    st.markdown(f"*- Key obligations:* {'; '.join(obligations)}")
                st.markdown("---")

    # Tab 4: Structural Silences
    with res_tab4:
        st.markdown("### 🔍 Missing Protections & Structural Observations")
        st.caption("ClauseGuard checks for critical missing protections (silence) such as liability caps, confidentiality, and dispute resolution:")

        for note in report.overall_notes:
            if "Silence" in note or "Missing" in note:
                st.warning(f"⚠️ {note}")
            else:
                st.info(f"ℹ️ {note}")

    # Tab 5: Export & Raw Report
    with res_tab5:
        st.markdown("### 💾 Export Triage Report")

        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            st.download_button(
                label="📥 Download Markdown Report (.md)",
                data=st.session_state["report_markdown"],
                file_name=f"clauseguard_report_{Path(report.filename).stem}.md",
                mime="text/markdown",
                use_container_width=True,
            )

        with exp_col2:
            st.download_button(
                label="📥 Download Structured JSON (.json)",
                data=st.session_state["report_json"],
                file_name=f"clauseguard_report_{Path(report.filename).stem}.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("#### Markdown Preview")
        st.markdown(st.session_state["report_markdown"])
