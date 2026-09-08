"""
Strands tools for ClauseGuard.

extract_clauses   - pure structural extraction (.docx, .pdf, .txt) via document_parser.
flag_risky_clause - per-clause risk evaluation against the 7-category ClauseGuard rubric.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from strands import tool

load_dotenv()

try:
    from .document_parser import DocumentParsingError, parse_document
    from .prompts import CLAUSE_FLAGGING_RUBRIC
except (ImportError, ValueError):
    from document_parser import DocumentParsingError, parse_document
    from prompts import CLAUSE_FLAGGING_RUBRIC


@tool
def extract_clauses(document_path: str) -> dict:
    """
    Parse a contract file (.docx, .pdf, or .txt) into a flat list of clauses
    ready for per-clause review.
    """
    path = Path(document_path)

    try:
        parsed = parse_document(path)
    except DocumentParsingError as exc:
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": exc.user_message,
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error_type": "FileNotFoundError",
            "message": f"Could not find '{path.name}' — please check the file was uploaded correctly.",
        }

    clauses = [
        {
            "clause_id": section.section_id,
            "text": section.text,
            "heading": section.heading,
            "page_number": section.page_number,
        }
        for section in parsed.sections
    ]

    return {
        "status": "success",
        "filename": parsed.filename,
        "source_file_type": parsed.source_file_type.value,
        "clause_count": len(clauses),
        "clauses": clauses,
        "warnings": parsed.warnings,
    }


def _heuristic_flag_clause(clause_text: str, clause_heading: Optional[str] = None) -> dict[str, Any]:
    """
    Fallback deterministic heuristic evaluator for contract clauses against
    the ClauseGuard rubric when Bedrock is unavailable or during local testing.
    """
    text_lower = clause_text.lower()
    heading_lower = (clause_heading or "").lower()
    combined = f"{heading_lower} {text_lower}"

    # 1. Financial Exposure & Indemnification
    has_indemnity = any(k in combined for k in ["indemnif", "hold harmless", "defend and hold"])
    is_negated_reciprocal = any(
        k in text_lower
        for k in ["no reciprocal", "not reciprocal", "without reciprocal", "no reciprocal indemnification"]
    )
    is_mutual_indemnity = (
        ("mutual" in text_lower or "each party shall indemnify" in text_lower or "defend and indemnify each other" in text_lower)
        and not is_negated_reciprocal
    )

    if has_indemnity and not is_mutual_indemnity:
        return {
            "flagged": True,
            "risk_category": "FINANCIAL_EXPOSURE",
            "risk_level": "HIGH",
            "what_it_says": "Requires one party to indemnify and hold harmless the other party against claims, losses, and damages without balanced mutual protection.",
            "why_it_matters": "Creates potentially uncapped financial liability for third-party claims or legal defense fees.",
            "question_to_ask": "Can we make the indemnification mutual, and cap the total indemnification exposure to the fees paid under this agreement?",
        }

    if any(
        k in text_lower
        for k in ["uncapped liability", "unlimited liability", "exceed zero dollars", "zero dollars ($0.00)", "zero dollars ($0)", "shall not exceed zero"]
    ) or ("liability" in combined and any(k in text_lower for k in ["shall not be limited", "uncapped"])):
        return {
            "flagged": True,
            "risk_category": "FINANCIAL_EXPOSURE",
            "risk_level": "HIGH",
            "what_it_says": "Creates an extreme asymmetry or complete disclaimer of one party's liability while leaving the other party exposed or uncapped.",
            "why_it_matters": "Exposes the signing party to potentially catastrophic damages far exceeding the contract value with zero accountability from the counterparty.",
            "question_to_ask": "Can we include a mutual aggregate liability cap tied to 12 months of contract fees?",
        }

    if any(k in combined for k in ["pass-through", "capital improvement", "structural replacement"]):
        if any(k in text_lower for k in ["sole discretion", "without limitation", "uncapped", "without amortiz"]):
            return {
                "flagged": True,
                "risk_category": "FINANCIAL_EXPOSURE",
                "risk_level": "HIGH",
                "what_it_says": "Passes through unlimited or un-amortized capital improvement and structural repair costs to tenant at landlord's discretion.",
                "why_it_matters": "Creates unpredictable, potentially massive financial exposure for building infrastructure outside tenant's control.",
                "question_to_ask": "Can capital expenditures be excluded from operating expenses or amortized over their useful life with an annual percentage cap?",
            }

    if any(k in combined for k in ["attorney fees", "legal expenses", "remedies and legal"]):
        if any(k in text_lower for k in ["regardless of the outcome", "regardless of outcome", "without posting bond", "solely responsible for all legal"]):
            return {
                "flagged": True,
                "risk_category": "FINANCIAL_EXPOSURE",
                "risk_level": "HIGH",
                "what_it_says": "Requires you to pay the counterparty's legal expenses regardless of the outcome of a dispute.",
                "why_it_matters": "Eliminates counterparty risk in litigation, encouraging frivolous or aggressive legal maneuvers.",
                "question_to_ask": "Can fee recovery follow the standard prevailing-party rule, where only the winning party recovers fees?",
            }

    if "auto-renew" in combined or "automatically renew" in combined:
        if any(k in text_lower for k in ["increase", "rate change", "without notice", "discretion"]):
            return {
                "flagged": True,
                "risk_category": "FINANCIAL_EXPOSURE",
                "risk_level": "MEDIUM",
                "what_it_says": "The contract automatically renews and permits price increases without required prior notice or caps.",
                "why_it_matters": "Risk of being locked into higher rates automatically unless canceled well in advance.",
                "question_to_ask": "Will you provide at least 30 days written notice prior to any renewal price adjustment, with the right to cancel?",
            }

    # 2. IP and Rights
    if any(k in combined for k in ["intellectual property", "ownership", "inventions", "work product"]):
        if any(k in text_lower for k in ["all right, title", "exclusive property", "assigns all", "pre-existing", "moral rights"]):
            return {
                "flagged": True,
                "risk_category": "IP_AND_RIGHTS",
                "risk_level": "HIGH",
                "what_it_says": "Broadly assigns intellectual property rights, potentially encompassing pre-existing tools, background IP, or work created outside the scope.",
                "why_it_matters": "You may lose ownership of your own proprietary tooling, background IP, or pre-existing methodologies.",
                "question_to_ask": "Can we explicitly carve out pre-existing intellectual property and limit the assignment strictly to custom deliverables created under this scope?",
            }

    if any(k in combined for k in ["non-compete", "covenant not to compete", "exclusivity"]):
        return {
            "flagged": True,
            "risk_category": "IP_AND_RIGHTS",
            "risk_level": "HIGH",
            "what_it_says": "Restricts you from working with competitors or offering similar services to other clients during or after the term.",
            "why_it_matters": "Directly constrains your ability to earn a livelihood or take on other commercial clients.",
            "question_to_ask": "Can this non-compete clause be removed, or narrowed strictly to direct misuse of confidential information?",
        }

    # 3. Confidentiality and Restrictive Covenants
    if "confidential" in combined:
        if any(k in text_lower for k in ["clear and convincing", "proves by clear and convincing"]):
            return {
                "flagged": True,
                "risk_category": "ASYMMETRIC_OBLIGATIONS",
                "risk_level": "MEDIUM",
                "what_it_says": "Places an unusually high evidentiary burden (clear and convincing evidence) to prove information is public or non-confidential.",
                "why_it_matters": "Increases legal vulnerability and costs if standard commercial discussions are contested.",
                "question_to_ask": "Can standard exceptions to confidentiality apply based on general public availability without heightened evidentiary burdens?",
            }
        if any(k in text_lower for k in ["perpetuity", "in perpetuity", "perpetual confidentiality"]):
            return {
                "flagged": True,
                "risk_category": "IP_AND_RIGHTS",
                "risk_level": "HIGH",
                "what_it_says": "Imposes perpetual non-disclosure obligations without expiration.",
                "why_it_matters": "Indefinite liability requires tracking and safeguarding materials forever.",
                "question_to_ask": "Can confidentiality obligations be limited to a standard term of two to three years?",
            }

    if any(k in combined for k in ["non-solicitation", "solicit company employees", "solicit any employee", "solicit, or engage"]):
        if any(k in text_lower for k in ["two (2) years", "2 years", "vendor, or customer", "customers of disclosing"]):
            return {
                "flagged": True,
                "risk_category": "IP_AND_RIGHTS",
                "risk_level": "MEDIUM",
                "what_it_says": "Restricts hiring or engaging employees, contractors, or customers for an extended period.",
                "why_it_matters": "Constrains normal commercial hiring and networking across industry contacts.",
                "question_to_ask": "Can the non-solicit be narrowed strictly to key personnel directly involved in this specific engagement?",
            }

    # 4. Termination and Lock-in
    if any(k in combined for k in ["termination", "term and termination"]):
        if any(k in text_lower for k in ["sole discretion", "without cause", "convenience"]) and not (
            "either party" in text_lower or "mutual" in text_lower
        ):
            return {
                "flagged": True,
                "risk_category": "TERMINATION_AND_LOCKIN",
                "risk_level": "MEDIUM",
                "what_it_says": "Allows one party to terminate at will for convenience while denying the other party an equivalent right.",
                "why_it_matters": "Asymmetric cancellation risk leaves you vulnerable to sudden termination without recourse.",
                "question_to_ask": "Can both parties be granted equal rights to terminate for convenience with 30 days written notice?",
            }
        if any(k in text_lower for k in ["penalty", "early termination fee", "liquidated damages", "remaining balance of the unexpired"]):
            return {
                "flagged": True,
                "risk_category": "TERMINATION_AND_LOCKIN",
                "risk_level": "HIGH",
                "what_it_says": "Imposes severe financial penalties or accelerated rent liquidated damages for ending the agreement early.",
                "why_it_matters": "Creates financial lock-in, penalizing exit even if business circumstances change.",
                "question_to_ask": "Can early termination fees be capped reasonably (e.g. 2-3 months), allowing exit upon notice without accelerating the entire contract?",
            }

    # 5. Landlord Access / Right of Entry
    if any(k in combined for k in ["access and entry", "landlord access", "right of entry"]):
        if any(k in text_lower for k in ["at any hour", "without prior notice", "without notice"]):
            return {
                "flagged": True,
                "risk_category": "ASYMMETRIC_OBLIGATIONS",
                "risk_level": "MEDIUM",
                "what_it_says": "Permits unannounced entry to the premises at any hour without advance notice.",
                "why_it_matters": "Disrupts business operations and creates security and privacy concerns.",
                "question_to_ask": "Can landlord entry be conditioned on 24 hours advance written notice, except in bona fide emergencies?",
            }

    # 6. Dispute Resolution
    if any(k in combined for k in ["arbitration", "jury trial", "class action"]):
        if any(k in text_lower for k in ["binding arbitration", "waives any right to a jury", "class action waiver"]):
            return {
                "flagged": True,
                "risk_category": "DISPUTE_RESOLUTION",
                "risk_level": "MEDIUM",
                "what_it_says": "Requires mandatory binding arbitration and waives the constitutional right to a jury trial or class action.",
                "why_it_matters": "Eliminates access to public courts and limits appeal rights if a dispute arises.",
                "question_to_ask": "Is the counterparty open to standard court jurisdiction or mutual mediation prior to arbitration?",
            }

    # 7. Unilateral Modification
    if any(k in text_lower for k in ["unilaterally modify", "reserve the right to modify", "modify these terms at any time", "sole discretion to change"]):
        return {
            "flagged": True,
            "risk_category": "UNILATERAL_MODIFICATION",
            "risk_level": "HIGH",
            "what_it_says": "Permits one party to unilaterally alter the terms, pricing, or scope of the agreement at any time.",
            "why_it_matters": "The agreement can change beneath you without your affirmative consent.",
            "question_to_ask": "Can any changes to the terms require mutual written agreement by both parties?",
        }

    # 6. Safe / Standard Clause
    return {
        "flagged": False,
        "risk_category": None,
        "risk_level": "NONE",
        "what_it_says": "Standard commercial contract provision.",
        "why_it_matters": "No asymmetric financial exposure, IP forfeiture, or unusual risk detected.",
        "question_to_ask": "",
    }


@tool
def flag_risky_clause(
    clause_text: str,
    clause_id: str = "",
    clause_heading: str = "",
    contract_type: str = "General Contract",
) -> dict:
    """
    Evaluate a single contract clause against the 7-category ClauseGuard risk rubric.
    Returns structured JSON specifying whether human judgment is required, the risk category,
    explanation of what it says, why it matters, and a drafted question for the counterparty.
    """
    if not clause_text or not clause_text.strip():
        return {
            "clause_id": clause_id,
            "flagged": False,
            "risk_category": None,
            "risk_level": "NONE",
            "what_it_says": "Empty clause.",
            "why_it_matters": "No content to evaluate.",
            "question_to_ask": "",
        }

    # Attempt Bedrock Claude invocation if AWS credentials are active
    model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0")
    region = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))

    has_credentials = (
        bool(os.environ.get("AWS_ACCESS_KEY_ID"))
        or bool(os.environ.get("AWS_PROFILE"))
        or Path("~/.aws/credentials").expanduser().exists()
    )

    if has_credentials:
        try:
            import boto3

            client = boto3.client("bedrock-runtime", region_name=region)
            user_prompt = f"""{CLAUSE_FLAGGING_RUBRIC}

Contract Type: {contract_type}
Clause ID: {clause_id}
Clause Heading: {clause_heading}

Clause Text:
\"\"\"{clause_text}\"\"\"

Respond ONLY with valid JSON matching this schema:
{{
  "flagged": true | false,
  "risk_category": "FINANCIAL_EXPOSURE" | "IP_AND_RIGHTS" | "TERMINATION_AND_LOCKIN" | "DISPUTE_RESOLUTION" | "UNILATERAL_MODIFICATION" | "ASYMMETRIC_OBLIGATIONS" | "SILENCE_OR_AMBIGUITY" | null,
  "risk_level": "HIGH" | "MEDIUM" | "LOW" | "NONE",
  "what_it_says": "concise plain-language paraphrase (max 2 sentences, no verbatim copy)",
  "why_it_matters": "specific risk or asymmetry in 1-2 sentences",
  "question_to_ask": "crisp, ready-to-send question for counterparty"
}}"""

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "temperature": 0.0,
                "messages": [{"role": "user", "content": user_prompt}],
            })

            response = client.invoke_model(modelId=model_id, body=body)
            response_body = json.loads(response["body"].read().decode("utf-8"))
            content_text = response_body["content"][0]["text"].strip()

            # Clean any markdown code blocks if the model wrapped in ```json
            if content_text.startswith("```"):
                content_text = re.sub(r"^```(?:json)?\n?", "", content_text)
                content_text = re.sub(r"\n?```$", "", content_text).strip()

            parsed_result = json.loads(content_text)
            parsed_result["clause_id"] = clause_id
            parsed_result["clause_heading"] = clause_heading
            return parsed_result
        except Exception:
            # Fall back to heuristic evaluator on any AWS / network / parse error
            pass

    # Fallback to deterministic rubric evaluation
    result = _heuristic_flag_clause(clause_text, clause_heading)
    result["clause_id"] = clause_id
    result["clause_heading"] = clause_heading
    return result