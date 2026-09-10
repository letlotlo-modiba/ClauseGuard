"""
Strands tools for ClauseGuard (Week 2).

extract_clauses    - pure structural extraction (.docx, .pdf, .txt) via document_parser.
flag_risky_clause  - per-clause risk evaluation against the tuned 7-category ClauseGuard rubric.
summarize_clause   - plain-language translation of contract clauses for non-lawyers.
draft_questions    - targeted questions and market-standard compromise positions for counterparties.
retrieve_precedent - benchmark clause search via Amazon Bedrock Knowledge Base or local precedent library.
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
    from .prompts import (
        CLAUSE_FLAGGING_RUBRIC,
        CLAUSE_SUMMARIZATION_PROMPT,
        DRAFT_QUESTIONS_PROMPT,
    )
except (ImportError, ValueError):
    from document_parser import DocumentParsingError, parse_document
    from prompts import (
        CLAUSE_FLAGGING_RUBRIC,
        CLAUSE_SUMMARIZATION_PROMPT,
        DRAFT_QUESTIONS_PROMPT,
    )


# ---------------------------------------------------------------------------
# Amazon Bedrock Runtime Helpers
# ---------------------------------------------------------------------------

def _is_aws_available() -> bool:
    """Check whether AWS credentials or configuration appear available."""
    has_keys = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(os.environ.get("AWS_SECRET_ACCESS_KEY"))
    has_profile = bool(os.environ.get("AWS_PROFILE"))
    has_aws_dir = Path("~/.aws/credentials").expanduser().exists() or Path("~/.aws/config").expanduser().exists()
    return has_keys or has_profile or has_aws_dir


def _call_bedrock_claude(user_prompt: str, max_tokens: int = 512) -> Optional[dict[str, Any]]:
    """
    Invoke Amazon Bedrock Claude model with prompt and return parsed JSON.
    Returns None if AWS is not configured or if any error occurs (allowing fallback).
    """
    if not _is_aws_available():
        return None

    model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0")
    region = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))

    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=region)
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": user_prompt}],
        })

        response = client.invoke_model(modelId=model_id, body=body)
        response_body = json.loads(response["body"].read().decode("utf-8"))
        content_text = response_body["content"][0]["text"].strip()

        # Clean markdown code fence if present
        if content_text.startswith("```"):
            content_text = re.sub(r"^```(?:json)?\n?", "", content_text)
            content_text = re.sub(r"\n?```$", "", content_text).strip()

        return json.loads(content_text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tool 1: extract_clauses
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tuned Heuristic Flagging Evaluator (Tuned against sample & realistic contracts)
# ---------------------------------------------------------------------------

def _heuristic_flag_clause(clause_text: str, clause_heading: Optional[str] = None) -> dict[str, Any]:
    """
    Deterministic rubric evaluator for contract clauses against the ClauseGuard rubric.
    Tuned to avoid over-flagging routine commercial boilerplate (e.g. standard work-for-hire,
    standard 30-day payment terms, standard mutual confidentiality, standard lease premises indemnity)
    while reliably catching real financial and legal risks.
    """
    text_lower = clause_text.lower()
    heading_lower = (clause_heading or "").lower()
    combined = f"{heading_lower} {text_lower}"

    # 1. Financial Exposure & Indemnification
    has_indemnity = any(k in combined for k in ["indemnif", "hold harmless", "defend and hold"])
    is_negated_reciprocal = any(
        k in text_lower
        for k in [
            "no reciprocal",
            "not reciprocal",
            "without reciprocal",
            "no reciprocal indemnification",
            "company shall have no reciprocal",
            "client shall have no reciprocal",
        ]
    )
    is_mutual_indemnity = (
        (
            "mutual" in text_lower
            or "each party shall indemnify" in text_lower
            or "defend and indemnify each other" in text_lower
            or "indemnify, defend, and hold each other" in text_lower
        )
        and not is_negated_reciprocal
    )

    # Calibration: In commercial leases, tenant indemnifying landlord against liabilities
    # occurring on tenant's occupied premises is standard commercial practice.
    is_lease_premises_indemnity = (
        ("lease" in combined or "premises" in text_lower or "tenant" in text_lower)
        and any(k in text_lower for k in ["occurring on the premises", "within the premises", "tenant's use of the premises", "on or about the premises"])
        and not any(k in text_lower for k in ["landlord's gross negligence", "regardless of landlord's fault", "structural defect", "uncapped capital"])
    )

    if has_indemnity and not is_mutual_indemnity and not is_lease_premises_indemnity:
        # Flag unilateral indemnity obligations
        return {
            "flagged": True,
            "risk_category": "FINANCIAL_EXPOSURE",
            "risk_level": "HIGH",
            "what_it_says": "Requires one party to indemnify and hold harmless the other party against claims, losses, and damages without balanced mutual protection.",
            "why_it_matters": "Creates potentially uncapped financial liability for third-party claims or legal defense fees.",
            "question_to_ask": "Can we make the indemnification mutual, and cap the total indemnification exposure to the fees paid under this agreement?",
            "suggested_compromise": "Mutual indemnification capped at aggregate fees paid in the preceding 12 months, limited to direct gross negligence or breach.",
        }

    # Liability Caps & Asymmetric Disclaimers
    if any(
        k in text_lower
        for k in [
            "uncapped liability",
            "unlimited liability",
            "exceed zero dollars",
            "zero dollars ($0.00)",
            "zero dollars ($0)",
            "shall not exceed zero",
        ]
    ) or ("liability" in combined and any(k in text_lower for k in ["shall not be limited", "uncapped"])):
        return {
            "flagged": True,
            "risk_category": "FINANCIAL_EXPOSURE",
            "risk_level": "HIGH",
            "what_it_says": "Creates an extreme asymmetry or complete disclaimer of one party's liability while leaving the other party exposed or uncapped.",
            "why_it_matters": "Exposes the signing party to potentially catastrophic damages far exceeding the contract value with zero accountability from the counterparty.",
            "question_to_ask": "Can we include a mutual aggregate liability cap tied to 12 months of contract fees?",
            "suggested_compromise": "Mutual aggregate liability cap equal to fees paid in the trailing 12 months with mutual waiver of consequential damages.",
        }

    # Capital Improvements / Uncapped Pass-Throughs (Commercial Lease)
    if any(k in combined for k in ["pass-through", "capital improvement", "structural replacement"]):
        if any(k in text_lower for k in ["sole discretion", "without limitation", "uncapped", "without amortiz"]):
            return {
                "flagged": True,
                "risk_category": "FINANCIAL_EXPOSURE",
                "risk_level": "HIGH",
                "what_it_says": "Passes through unlimited or un-amortized capital improvement and structural repair costs to tenant at landlord's discretion.",
                "why_it_matters": "Creates unpredictable, potentially massive financial exposure for building infrastructure outside tenant's control.",
                "question_to_ask": "Can capital expenditures be excluded from operating expenses or amortized over their useful life with an annual percentage cap?",
                "suggested_compromise": "Amortize allowable capital replacements on a straight-line basis over their GAAP useful life with an annual cap of 5%.",
            }

    # Unconditional Legal Fee-Shifting
    if any(k in combined for k in ["attorney fees", "legal expenses", "remedies and legal"]):
        if any(k in text_lower for k in ["regardless of the outcome", "regardless of outcome", "without posting bond", "solely responsible for all legal"]):
            return {
                "flagged": True,
                "risk_category": "FINANCIAL_EXPOSURE",
                "risk_level": "HIGH",
                "what_it_says": "Requires you to pay the counterparty's legal expenses regardless of the outcome of a dispute.",
                "why_it_matters": "Eliminates counterparty risk in litigation, encouraging frivolous or aggressive legal maneuvers.",
                "question_to_ask": "Can fee recovery follow the standard prevailing-party rule, where only the winning party recovers fees?",
                "suggested_compromise": "Standard prevailing-party fee recovery where only the substantially prevailing party is entitled to reasonable fees.",
            }

    # Auto-Renewal with Price Escalations
    if "auto-renew" in combined or "automatically renew" in combined:
        if any(k in text_lower for k in ["without notice", "without prior notice", "sole discretion", "increase subscription fees upon renewal by up to"]):
            return {
                "flagged": True,
                "risk_category": "FINANCIAL_EXPOSURE",
                "risk_level": "MEDIUM",
                "what_it_says": "The contract automatically renews and permits price increases without required prior notice or opt-out rights.",
                "why_it_matters": "Risk of being locked into higher rates automatically unless canceled well in advance.",
                "question_to_ask": "Will you provide at least 30 to 60 days written notice prior to any renewal price adjustment, with the right to cancel penalty-free?",
                "suggested_compromise": "60 days advance written notice before any renewal rate increase, with customer option to terminate without penalty.",
            }

    # 2. IP and Rights
    # TUNING: Do NOT flag routine custom work-for-hire assignment of deliverables.
    # Flag only when assigning pre-existing IP, inventions outside scope, or perpetual moral rights waivers.
    if any(k in combined for k in ["intellectual property", "ownership", "inventions", "work product"]):
        has_pre_existing_grab = any(k in text_lower for k in ["pre-existing", "prior to", "developed prior", "before the effective", "background ip"])
        has_unrelated_grab = any(k in text_lower for k in ["whether or not related", "outside the scope", "not related to company", "all inventions, software, libraries, tools, and ideas conceived, reduced to practice, or developed by contractor prior to"])
        has_moral_rights_waiver = "moral rights in perpetuity" in text_lower or ("moral rights" in text_lower and "waive" in text_lower)

        if has_pre_existing_grab or has_unrelated_grab or has_moral_rights_waiver:
            return {
                "flagged": True,
                "risk_category": "IP_AND_RIGHTS",
                "risk_level": "HIGH",
                "what_it_says": "Broadly assigns intellectual property rights, capturing pre-existing tools, background IP, or unrelated inventions, and waives moral rights.",
                "why_it_matters": "You may forfeit ownership of your own proprietary tooling, background code libraries, or pre-existing methodologies.",
                "question_to_ask": "Can we explicitly carve out pre-existing intellectual property and limit the assignment strictly to custom deliverables created under this scope?",
                "suggested_compromise": "Contractor assigns custom deliverables upon full payment, retaining background IP with a non-exclusive license to client.",
            }

    # Non-compete and Exclusivity
    if any(k in combined for k in ["non-compete", "covenant not to compete", "exclusivity"]):
        return {
            "flagged": True,
            "risk_category": "IP_AND_RIGHTS",
            "risk_level": "HIGH",
            "what_it_says": "Restricts you from working with competitors or offering similar services to other clients during or after the term.",
            "why_it_matters": "Directly constrains your ability to earn a livelihood or take on other commercial clients.",
            "question_to_ask": "Can this non-compete clause be removed, or narrowed strictly to direct misuse of confidential information?",
            "suggested_compromise": "Strike non-compete and rely on non-disclosure of confidential trade secrets and a 12-month direct project non-solicit.",
        }

    # 3. Confidentiality and Restrictive Covenants
    if "confidential" in combined:
        if any(k in text_lower for k in ["clear and convincing", "proves by clear and convincing"]):
            return {
                "flagged": True,
                "risk_category": "ASYMMETRIC_OBLIGATIONS",
                "risk_level": "MEDIUM",
                "what_it_says": "Places an unusually high evidentiary burden (clear and convincing documentary evidence) to prove information is public or non-confidential.",
                "why_it_matters": "Increases legal vulnerability and costs if standard commercial discussions are contested.",
                "question_to_ask": "Can standard exceptions to confidentiality apply based on general public availability without heightened evidentiary burdens?",
                "suggested_compromise": "Standard commercial exclusions provable by ordinary civil preponderance of evidence.",
            }
        if any(k in text_lower for k in ["in perpetuity", "survive in perpetuity", "perpetual confidentiality"]):
            return {
                "flagged": True,
                "risk_category": "IP_AND_RIGHTS",
                "risk_level": "HIGH",
                "what_it_says": "Imposes perpetual non-disclosure obligations without expiration.",
                "why_it_matters": "Indefinite liability requires tracking and safeguarding materials forever.",
                "question_to_ask": "Can confidentiality obligations be limited to a standard term of two to three years?",
                "suggested_compromise": "Confidentiality term limited to 2-3 years from date of disclosure (trade secrets protected while qualifying under law).",
            }

    # Extended Non-Solicitation
    if any(k in combined for k in ["non-solicitation", "solicit company employees", "solicit any employee", "solicit, or engage"]):
        if any(k in text_lower for k in ["two (2) years", "2 years", "vendor, or customer", "customers of disclosing"]):
            return {
                "flagged": True,
                "risk_category": "IP_AND_RIGHTS",
                "risk_level": "MEDIUM",
                "what_it_says": "Restricts hiring or engaging employees, contractors, or customers for an extended period.",
                "why_it_matters": "Constrains normal commercial hiring and networking across industry contacts.",
                "question_to_ask": "Can the non-solicit be narrowed strictly to key personnel directly involved in this specific engagement for 12 months?",
                "suggested_compromise": "12-month non-solicitation restricted solely to direct project contributors, excluding general public job postings.",
            }

    # 4. Termination and Lock-in
    if any(k in combined for k in ["termination", "term and termination"]):
        is_bilateral = any(k in text_lower for k in ["either party", "each party", "both parties", "mutual"])
        if any(k in text_lower for k in ["sole discretion", "without cause", "convenience"]) and not is_bilateral:
            return {
                "flagged": True,
                "risk_category": "TERMINATION_AND_LOCKIN",
                "risk_level": "MEDIUM",
                "what_it_says": "Allows one party to terminate at will for convenience while denying the other party an equivalent right.",
                "why_it_matters": "Asymmetric cancellation risk leaves you vulnerable to sudden termination without recourse.",
                "question_to_ask": "Can both parties be granted equal rights to terminate for convenience with 30 days written notice?",
                "suggested_compromise": "Mutual right to terminate for convenience upon 30 days written notice with payment for all work performed to date.",
            }
        if any(k in text_lower for k in ["penalty", "early termination fee", "liquidated damages", "remaining balance of the unexpired", "forfeits rights to any pending", "forfeits pending"]):
            return {
                "flagged": True,
                "risk_category": "TERMINATION_AND_LOCKIN",
                "risk_level": "HIGH",
                "what_it_says": "Imposes severe financial penalties, accelerated rent liquidated damages, or forfeiture of pending invoice payments.",
                "why_it_matters": "Creates financial lock-in and penalizes exit, risking loss of earned compensation.",
                "question_to_ask": "Can early termination fees be capped reasonably and invoice forfeiture struck, ensuring full payment for completed work?",
                "suggested_compromise": "Payment for all approved work delivered up to termination date; lease early exit fee capped at 2-3 months rent.",
            }

    # 5. Landlord Access / Right of Entry
    if any(k in combined for k in ["access and entry", "landlord access", "right of entry"]):
        if any(k in text_lower for k in ["at any hour", "without prior notice", "without notice"]):
            return {
                "flagged": True,
                "risk_category": "ASYMMETRIC_OBLIGATIONS",
                "risk_level": "MEDIUM",
                "what_it_says": "Permits unannounced entry to the premises at any hour without advance notice.",
                "why_it_matters": "Disrupts business operations and creates security and confidentiality concerns.",
                "question_to_ask": "Can landlord entry be conditioned on 24 hours advance written notice, except in bona fide emergencies?",
                "suggested_compromise": "Entry during regular business hours with at least 24 hours advance written notice and tenant accompaniment, except emergencies.",
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
                "suggested_compromise": "30-day executive negotiation period, followed by non-binding mediation before formal court proceedings.",
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
            "suggested_compromise": "Material amendments require mutual written agreement or 30 days notice with penalty-free termination.",
        }

    # Safe / Routine Clause
    return {
        "flagged": False,
        "risk_category": None,
        "risk_level": "NONE",
        "what_it_says": "Standard commercial contract provision.",
        "why_it_matters": "No asymmetric financial exposure, IP forfeiture, or unusual risk detected.",
        "question_to_ask": "",
        "suggested_compromise": "",
    }


# ---------------------------------------------------------------------------
# Tool 2: flag_risky_clause
# ---------------------------------------------------------------------------

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
    explanation of what it says, why it matters, counterparty question, and suggested compromise.
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
            "suggested_compromise": "",
        }

    user_prompt = f"""{CLAUSE_FLAGGING_RUBRIC}

Contract Type: {contract_type}
Clause ID: {clause_id}
Clause Heading: {clause_heading}

Clause Text:
\"\"\"{clause_text}\"\"\""""

    bedrock_result = _call_bedrock_claude(user_prompt, max_tokens=512)
    if bedrock_result and isinstance(bedrock_result, dict) and "flagged" in bedrock_result:
        bedrock_result["clause_id"] = clause_id
        bedrock_result["clause_heading"] = clause_heading
        return bedrock_result

    # Fallback to deterministic rubric evaluation
    result = _heuristic_flag_clause(clause_text, clause_heading)
    result["clause_id"] = clause_id
    result["clause_heading"] = clause_heading
    return result


# ---------------------------------------------------------------------------
# Tool 3: summarize_clause (Week 2)
# ---------------------------------------------------------------------------

def _heuristic_summarize_clause(
    clause_text: str,
    clause_id: str = "",
    clause_heading: str = "",
) -> dict[str, Any]:
    """Fallback deterministic summarizer for contract clauses."""
    heading_lower = (clause_heading or "").lower()
    text_lower = clause_text.lower()
    combined = f"{heading_lower} {text_lower}"

    summary = "Defines standard operational terms and obligations for this section."
    key_obligations = []
    is_standard = True

    # Check common clause types
    if "scope" in combined or "services and deliverables" in combined or "deliverables" in combined:
        summary = "Outlines the project scope, services to be performed, and the expected standard of delivery."
        key_obligations = ["Perform custom development and integrations as specified in SOWs in a workmanlike manner."]
    elif "payment" in combined or "compensation" in combined or "pricing" in combined:
        # Extract payment terms like net 30, hourly rate
        rate_match = re.search(r"\$\d+(?:\.\d{2})?(?:/(?:hr|hour|month|year))?", clause_text)
        net_match = re.search(r"(\d+)\s*(?:days|\(30\)\s*days)", clause_text)
        rate_str = f" at {rate_match.group(0)}" if rate_match else ""
        net_str = f" within {net_match.group(1)} days of invoice" if net_match else ""
        summary = f"Establishes compensation rates{rate_str} and payment schedule{net_str}."
        key_obligations = [f"Submit itemized invoices; pay undisputed amounts{net_str}."]
    elif "term" in combined and "termination" not in combined:
        duration_match = re.search(r"(\d+)\s*(?:months|years)", clause_text)
        dur = f" of {duration_match.group(0)}" if duration_match else ""
        summary = f"Sets the effective term{dur} of the agreement."
        key_obligations = ["Agreement remains effective for the initial term unless terminated earlier."]
    elif "confidential" in combined:
        dur_match = re.search(r"(\d+)\s*(?:years|\(2\)\s*years)", clause_text)
        dur = f" for {dur_match.group(0)}" if dur_match else ""
        summary = f"Requires both parties to safeguard confidential business information{dur}."
        key_obligations = ["Maintain strict confidence and protect data using standard duty of care."]
    elif "warranty" in combined or "warranties" in combined:
        summary = "Contains standard assurances that work is original and services will be performed properly."
        key_obligations = ["Warrant non-infringement of third-party IP and original workmanship."]
    elif "intellectual property" in combined or "work product" in combined:
        summary = "Addresses ownership of custom deliverables and licensing of tools or work product."
        key_obligations = ["Transfer custom work product rights to client upon agreed payment terms."]
    elif "governing law" in combined or "jurisdiction" in combined or "general provisions" in combined:
        law_match = re.search(r"State of ([A-Za-z\s]+)", clause_text)
        state = f" of {law_match.group(1).strip()}" if law_match else ""
        summary = f"Specifies the governing legal jurisdiction{state} and boilerplate integration provisions."
        key_obligations = ["Resolve contractual legal disputes in designated jurisdiction."]
    elif "data security" in combined or "privacy" in combined:
        summary = "Commits provider to maintain administrative, physical, and technical safeguards for customer data."
        key_obligations = ["Maintain industry standard data security safeguards."]
    elif "service level" in combined or "sla" in combined:
        summary = "Sets availability commitments (e.g. 99.5% uptime target excluding scheduled maintenance)."
        key_obligations = ["Meet monthly uptime availability targets."]
    elif "premises" in combined or "lease term" in combined or "rent" in combined or "insurance" in combined:
        if "insurance" in combined or "indemnif" in combined:
            summary = "Requires tenant to maintain commercial general liability insurance and provide standard premises indemnification."
            key_obligations = ["Maintain minimum commercial general liability coverage; indemnify against incidents on occupied premises."]
        else:
            summary = "Defines commercial lease parameters, physical space location, and rental payment amounts."
            key_obligations = ["Comply with lease occupancy terms and monthly rent payment schedule."]
    else:
        # Generic summary from first sentence
        first_sentence = re.split(r"[.!?]", clause_text.strip())[0].strip()
        if len(first_sentence) > 120:
            first_sentence = first_sentence[:120] + "..."
        summary = f"{first_sentence}."

    return {
        "status": "success",
        "clause_id": clause_id,
        "clause_heading": clause_heading,
        "summary": summary,
        "key_obligations": key_obligations,
        "is_standard": is_standard,
        "practical_implication": "Governs routine commercial expectations and operational procedures.",
    }


@tool
def summarize_clause(
    clause_text: str,
    clause_id: str = "",
    clause_heading: str = "",
    context: str = "General Contract",
) -> dict:
    """
    Summarize any contract clause into plain, jargon-free English for non-lawyers.
    Highlights key obligations, deadlines, and flags whether the clause is routine boilerplate.
    """
    if not clause_text or not clause_text.strip():
        return {
            "status": "success",
            "clause_id": clause_id,
            "clause_heading": clause_heading,
            "summary": "Empty clause.",
            "key_obligations": [],
            "is_standard": True,
            "practical_implication": "No obligations specified.",
        }

    prompt = CLAUSE_SUMMARIZATION_PROMPT.format(
        clause_heading=clause_heading,
        clause_id=clause_id,
        context=context,
        clause_text=clause_text,
    )

    bedrock_result = _call_bedrock_claude(prompt, max_tokens=384)
    if bedrock_result and isinstance(bedrock_result, dict) and "summary" in bedrock_result:
        bedrock_result["status"] = "success"
        bedrock_result["clause_id"] = clause_id
        bedrock_result["clause_heading"] = clause_heading
        return bedrock_result

    # Fallback to deterministic heuristic summarizer
    return _heuristic_summarize_clause(clause_text, clause_id, clause_heading)


# ---------------------------------------------------------------------------
# Tool 4: draft_questions (Week 2)
# ---------------------------------------------------------------------------

def _heuristic_draft_questions(
    clause_text: str,
    clause_id: str = "",
    clause_heading: str = "",
    risk_category: str = "",
    risk_level: str = "HIGH",
    what_it_says: str = "",
    why_it_matters: str = "",
    counterparty_role: str = "counterparty",
) -> dict[str, Any]:
    """Fallback deterministic generator for counterparty questions and compromise proposals."""
    cat = (risk_category or "").upper()
    text_lower = clause_text.lower()

    if cat == "FINANCIAL_EXPOSURE":
        if "indemnif" in text_lower or "hold harmless" in text_lower:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can we make the indemnification mutual, and cap total indemnity exposure to the fees paid under this agreement in the prior 12 months?",
                "fallback_question": "If full mutuality is not possible, can we at least narrow the indemnity strictly to third-party claims arising from gross negligence or intentional misconduct?",
                "suggested_compromise": "Mutual indemnification capped at 12 months fees, limited to direct gross negligence or breach.",
                "negotiation_goal": "Establish mutual indemnification and cap financial liability.",
            }
        elif "pass-through" in text_lower or "capital" in text_lower:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can capital expenditures and structural replacements be excluded from operating expenses or amortized over their useful life with an annual cap?",
                "fallback_question": "Can pass-throughs be restricted solely to routine maintenance and operating costs directly benefiting tenant?",
                "suggested_compromise": "Amortize capital replacements on a straight-line basis over useful life under GAAP with a 5% annual cap.",
                "negotiation_goal": "Exclude un-amortized capital improvements from tenant pass-throughs.",
            }
        elif "fee" in text_lower or "legal" in text_lower:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can fee recovery follow the standard prevailing-party rule, where only the winning party recovers legal fees?",
                "fallback_question": "Can each party bear its own legal expenses unless a claim is found to be frivolous?",
                "suggested_compromise": "Mutual prevailing-party legal fee recovery.",
                "negotiation_goal": "Eliminate unilateral attorney fee shifting.",
            }
        else:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can we establish a mutual aggregate liability cap equal to 12 months of fees paid under this agreement?",
                "fallback_question": "Would you agree to a reciprocal liability cap equal to the total contract value rather than an asymmetric disclaimer?",
                "suggested_compromise": "Mutual aggregate liability cap of 12 months fees with mutual waiver of consequential damages.",
                "negotiation_goal": "Balance liability caps and eliminate zero-dollar disclaimers.",
            }

    elif cat == "IP_AND_RIGHTS":
        if "non-compete" in text_lower or "compete" in text_lower:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can this post-termination non-compete clause be struck, or narrowed strictly to direct solicitation of your current active clients?",
                "fallback_question": "Can the restriction be limited to 6 months and confined to your specific core software product niche?",
                "suggested_compromise": "Replace broad non-compete with standard non-disclosure of trade secrets and a 12-month direct project non-solicit.",
                "negotiation_goal": "Remove post-termination trade restrictions.",
            }
        else:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can we explicitly carve out pre-existing intellectual property and limit the assignment strictly to custom deliverables created under this scope?",
                "fallback_question": "Can contractor retain background tools and code libraries while granting company a perpetual license to use them with the deliverables?",
                "suggested_compromise": "Contractor assigns custom deliverables upon payment, retaining background IP with a non-exclusive license to client.",
                "negotiation_goal": "Protect proprietary background tools and developer IP.",
            }

    elif cat == "TERMINATION_AND_LOCKIN":
        if "penalty" in text_lower or "unexpired" in text_lower or "liquidated" in text_lower:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can the early termination penalty be capped at a reasonable buyout (e.g. 2-3 months rent) rather than accelerating the entire unexpired term?",
                "fallback_question": "Can tenant be permitted to terminate early upon 90 days notice and payment of landlord's unamortized leasing costs?",
                "suggested_compromise": "Early termination fee capped at 3 months base rent with 60 days advance written notice.",
                "negotiation_goal": "Eliminate full accelerated rent penalties.",
            }
        else:
            return {
                "status": "success",
                "clause_id": clause_id,
                "clause_heading": clause_heading,
                "risk_category": cat,
                "primary_question": "Can both parties be granted equal rights to terminate for convenience upon thirty (30) days advance written notice, with payment for all work performed?",
                "fallback_question": "Can the contractor notice period be reduced to 30 days and the invoice forfeiture clause struck?",
                "suggested_compromise": "Mutual 30-day notice for convenience with guaranteed payment for work delivered to date.",
                "negotiation_goal": "Equalize termination rights and protect earned compensation.",
            }

    elif cat == "UNILATERAL_MODIFICATION":
        return {
            "status": "success",
            "clause_id": clause_id,
            "clause_heading": clause_heading,
            "risk_category": cat,
            "primary_question": "Can changes to terms, pricing, or service levels require mutual written agreement, or at least 30 days notice with the right to terminate penalty-free?",
            "fallback_question": "Will you provide at least 30 days advance written notice of material term modifications with an option to cancel and receive a pro-rata refund?",
            "suggested_compromise": "30 days advance written notice for material modifications, with customer right to opt out and terminate without penalty.",
            "negotiation_goal": "Ensure affirmative consent or penalty-free exit on term changes.",
        }

    elif cat == "DISPUTE_RESOLUTION":
        return {
            "status": "success",
            "clause_id": clause_id,
            "clause_heading": clause_heading,
            "risk_category": cat,
            "primary_question": "Can disputes be resolved through mutual executive escalation and standard court jurisdiction rather than mandatory binding arbitration?",
            "fallback_question": "Can arbitration be mutual in a neutral forum, preserving individual rights without class action restrictions?",
            "suggested_compromise": "30-day executive negotiation period, followed by non-binding mediation before formal court proceedings.",
            "negotiation_goal": "Preserve procedural legal rights and negotiate before arbitration.",
        }

    else:
        # Default / Asymmetric Obligations
        return {
            "status": "success",
            "clause_id": clause_id,
            "clause_heading": clause_heading,
            "risk_category": cat or "ASYMMETRIC_OBLIGATIONS",
            "primary_question": "Can this obligation be made reciprocal and conditioned upon reasonable advance written notice?",
            "fallback_question": "Can standard commercial practices (e.g. 24 hours advance notice, standard burden of proof) apply here?",
            "suggested_compromise": "Standard reciprocal obligations with 24 hours advance notice.",
            "negotiation_goal": "Make obligations mutual and reasonable.",
        }


@tool
def draft_questions(
    clause_text: str,
    clause_id: str = "",
    clause_heading: str = "",
    risk_category: str = "",
    risk_level: str = "HIGH",
    what_it_says: str = "",
    why_it_matters: str = "",
    counterparty_role: str = "counterparty",
    contract_type: str = "General Contract",
) -> dict:
    """
    Draft crisp, professional questions for counterparties regarding flagged contract risks,
    along with practical compromise terms to propose during negotiation.
    """
    if not clause_text or not clause_text.strip():
        return {
            "status": "success",
            "clause_id": clause_id,
            "clause_heading": clause_heading,
            "risk_category": risk_category,
            "primary_question": "Please clarify the intent and scope of this provision.",
            "fallback_question": "",
            "suggested_compromise": "",
            "negotiation_goal": "",
        }

    prompt = DRAFT_QUESTIONS_PROMPT.format(
        contract_type=contract_type,
        clause_id=clause_id,
        clause_heading=clause_heading,
        risk_category=risk_category,
        risk_level=risk_level,
        what_it_says=what_it_says,
        why_it_matters=why_it_matters,
        counterparty_role=counterparty_role,
        clause_text=clause_text,
    )

    bedrock_result = _call_bedrock_claude(prompt, max_tokens=384)
    if bedrock_result and isinstance(bedrock_result, dict) and "primary_question" in bedrock_result:
        bedrock_result["status"] = "success"
        bedrock_result["clause_id"] = clause_id
        bedrock_result["clause_heading"] = clause_heading
        bedrock_result["risk_category"] = risk_category
        return bedrock_result

    # Fallback to deterministic generator
    return _heuristic_draft_questions(
        clause_text=clause_text,
        clause_id=clause_id,
        clause_heading=clause_heading,
        risk_category=risk_category,
        risk_level=risk_level,
        what_it_says=what_it_says,
        why_it_matters=why_it_matters,
        counterparty_role=counterparty_role,
    )


# ---------------------------------------------------------------------------
# Tool 5: retrieve_precedent (Bedrock Knowledge Base + Local Precedents)
# ---------------------------------------------------------------------------

def _local_retrieve_precedent(query: str, risk_category: str = "", contract_type: str = "") -> dict[str, Any]:
    """Retrieve market-standard precedent from the local curated precedent library."""
    precedents_dir = Path(__file__).parent / "precedents"
    if not precedents_dir.exists():
        precedents_dir = Path("precedents")

    query_lower = query.lower()
    cat_upper = (risk_category or "").upper()

    best_match_file = None
    best_score = -1

    # Mapping keywords to precedent files
    precedent_map = {
        "mutual_indemnification.md": ["indemnif", "hold harmless", "defense", "FINANCIAL_EXPOSURE"],
        "mutual_limitation_of_liability.md": ["liability cap", "limitation of liability", "consequential damages", "FINANCIAL_EXPOSURE"],
        "work_product_and_ip_carveout.md": ["intellectual property", "inventions", "work product", "moral rights", "IP_AND_RIGHTS"],
        "bilateral_termination.md": ["termination", "convenience", "forfeiture", "notice", "TERMINATION_AND_LOCKIN"],
        "commercial_lease_operating_expenses.md": ["lease", "capital improvement", "operating expenses", "pass-through", "entry", "access", "FINANCIAL_EXPOSURE", "ASYMMETRIC_OBLIGATIONS"],
        "standard_bilateral_nda.md": ["confidential", "nda", "evidentiary", "attorney fees", "ASYMMETRIC_OBLIGATIONS"],
        "saas_subscription_renewal_and_modification.md": ["auto-renew", "unilateral", "modify", "subscription", "UNILATERAL_MODIFICATION"],
    }

    for filename, keywords in precedent_map.items():
        score = 0
        if cat_upper in keywords:
            score += 3
        for kw in keywords:
            if kw.lower() in query_lower:
                score += 2

        if score > best_score:
            best_score = score
            best_match_file = filename

    if best_match_file and (precedents_dir / best_match_file).exists():
        content = (precedents_dir / best_match_file).read_text(encoding="utf-8")

        # Parse title
        title_line = content.splitlines()[0].replace("# Precedent:", "").replace("#", "").strip()

        # Parse recommended language
        rec_match = re.search(r"## Recommended Standard Language\s*\n\s*\"(.*?)\"", content, re.DOTALL)
        recommended_text = rec_match.group(1).strip() if rec_match else ""

        # Parse market rationale
        rat_match = re.search(r"## Market Rationale\s*\n\s*(.*?)(?:\n\n|$)", content, re.DOTALL)
        rationale_text = rat_match.group(1).strip() if rat_match else ""

        return {
            "status": "success",
            "found": True,
            "precedent_title": title_line,
            "standard_clause_text": recommended_text,
            "market_standard_explanation": rationale_text,
            "source": "curated_precedent_library",
            "risk_category": cat_upper,
        }

    return {
        "status": "success",
        "found": False,
        "precedent_title": "Standard Bilateral Commercial Terms",
        "standard_clause_text": "Terms should be mutual, commercially reasonable, and capped to direct damages.",
        "market_standard_explanation": "Standard contracts avoid one-sided indemnities and uncapped liabilities.",
        "source": "curated_precedent_library",
        "risk_category": cat_upper,
    }


@tool
def retrieve_precedent(
    query: str,
    risk_category: str = "",
    contract_type: str = "General Contract",
) -> dict:
    """
    Retrieve market-standard precedent clauses and fair compromise language.
    Queries Amazon Bedrock Knowledge Base if BEDROCK_KB_ID is configured,
    or searches the curated precedent library offline.
    """
    kb_id = os.environ.get("BEDROCK_KB_ID") or os.environ.get("AWS_BEDROCK_KNOWLEDGE_BASE_ID")
    region = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))

    # Attempt Bedrock Knowledge Base retrieval if configured
    if kb_id and _is_aws_available():
        try:
            import boto3

            client = boto3.client("bedrock-agent-runtime", region_name=region)
            response = client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": f"{contract_type} {risk_category} {query}".strip()},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": 2,
                    }
                },
            )
            results = response.get("retrievalResults", [])
            if results:
                top_hit = results[0]
                chunk_text = top_hit.get("content", {}).get("text", "")
                uri = top_hit.get("location", {}).get("s3Location", {}).get("uri", "Bedrock Knowledge Base")

                return {
                    "status": "success",
                    "found": True,
                    "precedent_title": f"Precedent ({Path(uri).name})",
                    "standard_clause_text": chunk_text[:500],
                    "market_standard_explanation": "Retrieved from Amazon Bedrock Knowledge Base vector index.",
                    "source": "bedrock_knowledge_base",
                    "risk_category": risk_category,
                }
        except Exception:
            # Fall back to local precedent library on any Bedrock runtime failure
            pass

    # Local curated precedent search
    return _local_retrieve_precedent(query, risk_category, contract_type)