"""Profit & Loss AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Download bank statement + tax return PDFs (if present) and base64-encode them
  3. Claude reads PDFs natively + deal financials → computes all 6 P&L sections
  4. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report  profitAndLoss)
  5. Return ProfitLossInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import DEFAULT_PROFIT_LOSS_SYSTEM_PROMPT
from app.schemas.profit_loss import ProfitLossInsight, ProfitLossRequest
from app.services.backend_client import (
    download_document,
    fetch_deal_package,
    push_profit_loss,
)

_INSIGHT_SCHEMA = ProfitLossInsight.model_json_schema()

_PDF_TYPES = {"BANK_STATEMENT", "TAX_RETURN"}


def _collect_pdf_blocks(documents: list[dict]) -> list[dict]:
    """Download bank statement and tax return PDFs; return Claude document blocks."""
    blocks = []
    for doc in documents:
        if doc.get("type") not in _PDF_TYPES:
            continue
        url = doc.get("downloadUrl") or doc.get("presignedUrl") or doc.get("url") or ""
        if not url:
            continue
        try:
            pdf_bytes = download_document(url)
            encoded = base64.standard_b64encode(pdf_bytes).decode("ascii")
            label = doc.get("name", f"{doc.get('type', 'document').lower()}.pdf")
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": encoded,
                },
                "title": label,
                "cache_control": {"type": "ephemeral"},
            })
        except Exception:
            # Skip inaccessible documents; AI will fall back to financial estimates
            pass
    return blocks


def _fmt(val) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, (int, float)):
        return f"${val:,.2f}"
    return str(val)


def _build_context_block(package: dict) -> str:
    """Serialise deal package fields into a readable text block for the LLM."""
    company = package.get("company", {}) or {}
    financials = package.get("financials", {}) or {}
    loan = package.get("loan", {}) or {}
    owners = package.get("owners", []) or []
    documents = package.get("documents", []) or []

    bank_count = sum(1 for d in documents if d.get("type") == "BANK_STATEMENT")
    tax_count = sum(1 for d in documents if d.get("type") == "TAX_RETURN")

    owner_names = ", ".join(
        f"{o.get('firstName', '')} {o.get('lastName', '')}".strip()
        for o in owners if o.get("firstName") or o.get("lastName")
    ) or "N/A"

    lines = [
        f"Business:            {company.get('legalName') or 'Unknown'}",
        f"Industry:            {company.get('industry', 'N/A')}",
        f"Entity Type:         {company.get('entityType', 'N/A')}",
        f"State:               {company.get('state', 'N/A')}",
        f"Time in Business:    {financials.get('timeInBusinessYears', 'N/A')} years",
        f"Owner(s):            {owner_names}",
        "",
        "=== FINANCIALS ===",
        f"  Annual Revenue:    {_fmt(financials.get('annualRevenue'))}",
        f"  Monthly Cashflow:  {_fmt(financials.get('monthlyCashflow'))}",
        f"  Monthly Expenses:  {_fmt(financials.get('monthlyExpenses'))}",
        f"  Existing Debt:     {_fmt(financials.get('existingDebt'))}",
        f"  Credit Score:      {financials.get('creditScore', 'N/A')}",
        "",
        "=== LOAN REQUEST ===",
        f"  Requested Amount:  {_fmt(loan.get('requestedAmount'))}",
        f"  Use of Funds:      {loan.get('useOfFunds', 'N/A')}",
        f"  Loan Term:         {loan.get('termMonths', 'N/A')} months",
        "",
        "=== DOCUMENTS ATTACHED TO THIS REQUEST ===",
        f"  Bank Statements:   {bank_count} PDF(s)",
        f"  Tax Returns:       {tax_count} PDF(s)",
        "",
        "If PDFs are attached above, extract actual monthly income/expense figures from them.",
        "If no PDFs are attached, derive estimates from the financials using the computation rules.",
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


def _call_llm(pdf_blocks: list[dict], prompt_text: str) -> ProfitLossInsight:
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.1,
        max_tokens=8192,
    )

    content: list = [*pdf_blocks, {"type": "text", "text": prompt_text}]

    messages = [
        SystemMessage(content=DEFAULT_PROFIT_LOSS_SYSTEM_PROMPT),
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

    return ProfitLossInsight.model_validate(json.loads(raw))


def generate_profit_loss(request: ProfitLossRequest) -> ProfitLossInsight:
    """Orchestrate fetch → PDF parse → LLM → push → return."""
    package = fetch_deal_package(request.deal_id)

    documents = package.get("documents", []) or []
    pdf_blocks = _collect_pdf_blocks(documents)

    context = _build_context_block(package)
    prompt = _build_prompt(context)

    try:
        insight = _call_llm(pdf_blocks, prompt)
    except Exception as exc:
        push_profit_loss(request.deal_id, {}, error_message=str(exc))
        raise

    push_profit_loss(request.deal_id, insight.model_dump())
    return insight
