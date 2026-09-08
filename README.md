# ClauseGuard 🛡️

> **AI Contract Triage Assistant powered by Strands Agents SDK and Amazon Bedrock**  
> *AWS "Agents for Humans" Hackathon — Professional Agents Track*

ClauseGuard is an autonomous AI agent designed to eliminate routine, repetitive contract review busywork for professionals, freelancers, and small business owners. Instead of forcing you to read dense legal boilerplate or blindly signing risky agreements, ClauseGuard runs quietly as a triage layer: it flags dangerous clauses that require human judgment, summarises everyday standard provisions in plain English, and drafts ready-to-send questions for counterparties.

ClauseGuard operates under a strict principle: **Triage, never decide.** It never tells the user "sign this" or "reject this"—it equips the user with what they need to decide for themselves.

---

## 🏗️ Architecture at a Glance

ClauseGuard is built on a modular five-layer architecture:

1. **Input & Document Parser**: Pure structural extraction for `.docx`, `.pdf`, and `.txt` contracts. Normalizes whitespace, strips header/footer artifacts, and chunks into numbered sections without data loss.
2. **Strands Agent Core**: Orchestrated with the AWS **Strands Agents SDK**. Uses a triage system prompt and custom Strands tools.
3. **Reasoning Engine**: **Amazon Bedrock** (Claude Sonnet 3.5 / 4.5) for per-clause semantic risk analysis and question drafting.
4. **Structured Output**: 4-part Markdown or JSON report:
   - **Executive Summary** (contract parties & core deal)
   - **Flagged Clauses** (requires human judgment: what it says, why it matters, questions to ask)
   - **Plain-Language Summary** (standard safe provisions)
   - **Overall Notes** (structural anomalies and absent protections / silence)
5. **Runtime & Integrations**: Support for Model Context Protocol (MCP) via `strands-agents-mcp-server` and future AWS Bedrock AgentCore runtime deployment.

```
                  ┌───────────────────────────────┐
                  │    Uploaded Contract File     │
                  │      (.docx, .pdf, .txt)      │
                  └──────────────┬────────────────┘
                                 │
                                 ▼
                  ┌───────────────────────────────┐
                  │       Document Parser         │
                  │ (Text Extraction & Chunking)  │
                  └──────────────┬────────────────┘
                                 │
                                 ▼
                  ┌───────────────────────────────┐
                  │      Strands Agents Core      │
                  │   ├── extract_clauses         │
                  │   └── flag_risky_clause       │
                  └───────┬───────────────▲───────┘
                          │               │
        Rubric Evaluation │               │ Inferences
                          ▼               │
                  ┌───────────────────────────────┐
                  │    Amazon Bedrock (Claude)    │
                  │  (7-Category Risk Evaluation) │
                  └───────────────────────────────┘
                                 │
                                 ▼
                  ┌───────────────────────────────┐
                  │   ClauseGuard Triage Report   │
                  │ (Summary, Flags, Qs, Notes)   │
                  └───────────────────────────────┘
```

---

## ⚖️ The 7-Category Risk Rubric

ClauseGuard flags clauses requiring human judgment based on:

1. **Financial Exposure**: Uncapped liability, unilateral indemnity, early termination penalties, unnotified renewal price increases.
2. **IP & Rights**: Broad pre-existing IP assignment, moral rights waivers, non-competes, exclusivity, broad non-solicits.
3. **Termination & Lock-in**: Asymmetric cancellation rights, long notice periods (>60 days), accelerated liquidated damages.
4. **Dispute Resolution**: Mandatory binding arbitration, waiver of jury trial, waiver of class actions, distant exclusive venues.
5. **Unilateral Modification**: Unilateral rights to alter terms, features, or fees without affirmative consent.
6. **Asymmetric Obligations**: Obligations or warranties imposed solely on one party without reciprocal protection.
7. **Silence & Omissions**: Crucial missing protections (no liability cap, no confidentiality, no breach cure period).

---

## 🚀 Quickstart & Usage

### 1. Installation & Environment Setup

Clone the repository and activate your Python 3.12+ virtual environment:

```bash
git clone https://github.com/letlotlo-modiba/ClauseGuard.git
cd ClauseGuard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # or: pip install strands-agents strands-agents-tools python-docx pdfplumber boto3 python-dotenv pytest
```

### 2. Configure AWS Bedrock (Optional for Local Mode)

Copy `.env.example` to `.env` and enter your AWS credentials:

```bash
cp .env.example .env
```

ClauseGuard includes an intelligent fallback evaluator: if AWS credentials are active, it invokes Bedrock Claude; if running offline or in unit tests, it evaluates deterministically using the rubric engine.

### 3. Run Contract Triage from CLI

Analyze any contract file (.docx, .pdf, or .txt):

```bash
# Markdown report to terminal
python agent.py sample_contracts/01_freelance_developer_agreement.txt --type "Freelance Developer Agreement"

# Save report to a markdown file
python agent.py sample_contracts/02_saas_subscription_agreement.txt -o saas_report.md

# Output structured JSON
python agent.py sample_contracts/03_commercial_office_lease.txt --json
```

---

## 🧪 Benchmark Test Suite

ClauseGuard includes 5 fictional benchmark contracts with ground-truth answer keys in `sample_contracts/`:

| Test Contract | Contract Type | Tested Risks | Expected Flags |
|---|---|---|---|
| `01_freelance_developer_agreement.txt` | Freelance Agreement | IP assignment over prior work, uncapped indemnity, 18-mo non-compete, invoice forfeiture | 4 flags |
| `02_saas_subscription_agreement.txt` | SaaS Terms | Auto-renewal +25% price hike, unilateral terms modification, $0 liability cap, mandatory arbitration | 4 flags |
| `03_commercial_office_lease.txt` | Office Lease | Uncapped capital improvement pass-throughs, 100% accelerated rent penalty, unannounced entry | 4 flags |
| `04_consulting_services_nda.txt` | NDA | Shifted evidentiary burden on public info, perpetual duration + non-solicit, unilateral fee-shifting | 3 flags |
| `05_safe_standard_vendor_agreement.txt` | Standard Vendor Agreement | Balanced mutual terms, capped liability (12 mo fees), mutual indemnity | 0 flags (Negative Control) |

Run all tests via pytest:

```bash
pytest test_week1.py -v
```

---

## 🛠️ MCP Server Integration

ClauseGuard tools are compatible with the Strands Model Context Protocol (MCP) server. Configure `.vscode/mcp.json`:

```json
{
  "servers": {
    "strands-agents": {
      "command": "uvx",
      "args": ["strands-agents-mcp-server"]
    }
  }
}
```

Once started, `extract_clauses` and `flag_risky_clause` are automatically discovered by MCP-enabled IDEs and tools.

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.