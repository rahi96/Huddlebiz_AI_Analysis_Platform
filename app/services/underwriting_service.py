"""AI Underwriting service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Download ALL document types: bank statements, tax returns, ID docs, supporting
  3. Claude reads PDFs natively → extracts metrics, scores risk, writes summary
  4. Push full underwriting result back (PUT /underwriting-result)
  5. Return UnderwritingInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import DEFAULT_UNDERWRITING_SYSTEM_PROMPT
from app.schemas.underwriting import UnderwritingInsight, UnderwritingRequest
from app.services.backend_client import (
    download_document,
    fetch_deal_package,
    push_underwriting_result,
)

_INSIGHT_SCHEMA = UnderwritingInsight.model_json_schema()

# Read every document type — underwriting needs the full picture
_ALL_DOC_TYPES = {"BANK_STATEMENT", "TAX_RETURN", "ID_DOCUMENT", "SUPPORTING"}


def _collect_pdf_blocks(documents: list[dict]) -> list[dict]:
    """Download all documents and return Claude document content blocks."""
    blocks = []
    for doc in documents:
        if doc.get("type") not in _ALL_DOC_TYPES:
            continue
        mime = doc.get("mimeType", "application/pdf")
        # Only attach PDFs and images; skip unsupported types
        if mime not in ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"):
            continue
        url = doc.get("downloadUrl") or doc.get("presignedUrl") or doc.get("url") or ""
        if not url:
            continue
        try:
            file_bytes = download_document(url)
            encoded = base64.standard_b64encode(file_bytes).decode("ascii")
            doc_type = doc.get("type", "DOCUMENT")
            label = doc.get("fileName") or doc.get("name") or f"{doc_type.lower()}.pdf"
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": encoded,
                },
                "title": f"[{doc_type}] {label}",
                "cache_control": {"type": "ephemeral"},
            })
        except Exception:
            # Skip inaccessible documents; AI will note them as missing
            pass
    return blocks


def _build_context_block(package: dict) -> str:
    """Serialise deal application data as supplementary context for the LLM."""
    company    = package.get("company", {}) or {}
    financials = package.get("financials", {}) or {}
    loan       = package.get("loan", {}) or {}
    owners     = package.get("owners", []) or []
    documents  = package.get("documents", []) or []

    doc_summary = {}
    for d in documents:
        t = d.get("type", "OTHER")
        doc_summary[t] = doc_summary.get(t, 0) + 1

    owner_lines = [
        f"    {o.get('legalName') or 'Unknown'} — {o.get('ownershipPercent', 0):.0f}% — {o.get('title', '')}"
        for o in owners
    ] or ["    N/A"]

    lines = [
        "=== APPLICATION DATA (supplement; prioritise PDF extractions above) ===",
        f"  Business Name:         {company.get('legalName') or 'Unknown'}",
        f"  Entity Type:           {company.get('entityType', 'N/A')}",
        f"  State:                 {company.get('state', 'N/A')}",
        f"  NAICS Code:            {company.get('naicsCode', 'N/A')}",
        f"  Industry:              {company.get('industry', 'N/A')}",
        "",
        f"  Stated Annual Revenue: {financials.get('annualRevenue', 'N/A')}",
        f"  Stated Monthly CF:     {financials.get('monthlyCashflow', 'N/A')}",
        f"  Stated Monthly Exp:    {financials.get('monthlyExpenses', 'N/A')}",
        f"  Stated Existing Debt:  {financials.get('existingDebt', 'N/A')}",
        f"  Stated FICO:           {financials.get('creditScore', 'N/A')}",
        f"  Time in Business:      {financials.get('timeInBusinessYears', 'N/A')} years",
        "",
        f"  Loan Requested:        {loan.get('requestedAmount', 'N/A')}",
        f"  Use of Funds:          {loan.get('useOfFunds', 'N/A')}",
        "",
        "  Owners / Guarantors:",
        *owner_lines,
        "",
        "  Documents in package:",
        *[f"    {t}: {n}" for t, n in doc_summary.items()],
        "",
        "Now analyse all attached PDFs and produce the underwriting JSON.",
    ]
    return "\n".join(lines)


def _build_prompt(context: str) -> str:
    schema_str = json.dumps(_INSIGHT_SCHEMA, indent=2)
    return (
        f"{context}\n\n"
        "---\n"
        "Return a JSON object that exactly matches this schema:\n"
        f"```json\n{schema_str}\n```\n\n"
        "Respond with ONLY the JSON object — no markdown fences, no explanation."
    )


def _call_llm(pdf_blocks: list[dict], prompt_text: str) -> UnderwritingInsight:
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.1,
        max_tokens=8192,
    )

    content: list = [*pdf_blocks, {"type": "text", "text": prompt_text}]

    messages = [
        SystemMessage(content=DEFAULT_UNDERWRITING_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]

    response = llm.invoke(messages)
    raw = response.content

    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rstrip("`").strip()

    return UnderwritingInsight.model_validate(json.loads(raw))


def generate_underwriting(request: UnderwritingRequest) -> UnderwritingInsight:
    """Orchestrate fetch → download all PDFs → LLM → push → return."""
    package = fetch_deal_package(request.deal_id)

    documents = package.get("documents", []) or []
    pdf_blocks = _collect_pdf_blocks(documents)

    context = _build_context_block(package)
    prompt  = _build_prompt(context)

    try:
        insight = _call_llm(pdf_blocks, prompt)
    except Exception as exc:
        push_underwriting_result(
            request.deal_id,
            confidence_score=0.0,
            risk_level="UNKNOWN",
            summary="",
            rule_validation=[],
            extracted_data={},
            error_message=str(exc),
        )
        raise

    # Push in the exact shape the backend underwriting-result endpoint expects
    extracted_raw = {
        k: v.model_dump() if hasattr(v, "model_dump") else v
        for k, v in insight.extracted_data.__dict__.items()
    }

    push_underwriting_result(
        request.deal_id,
        confidence_score=insight.confidence_score,
        risk_level=insight.risk_level,
        summary=insight.summary,
        rule_validation=[r.model_dump() for r in insight.rule_validation],
        extracted_data=extracted_raw,
    )
    return insight
