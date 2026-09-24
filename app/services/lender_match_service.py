"""Lender Match AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Format deal data into a readable context block for Claude
  3. Claude cross-checks deal against each lender's embedded credit box
  4. Push result back    (PUT /api/v1/internal/ai/deals/{id}/underwriting-result)
  5. Return LenderMatchInsight to the caller
"""

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import DEFAULT_LENDER_MATCH_SYSTEM_PROMPT
from app.schemas.lender_match import LenderMatchInsight, LenderMatchRequest
from app.services.backend_client import fetch_deal_package, push_lender_match

_INSIGHT_SCHEMA = LenderMatchInsight.model_json_schema()


def _fmt(val) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, (int, float)):
        return f"${val:,.2f}"
    return str(val)


def _build_context_block(package: dict) -> str:
    """Serialise deal package into a readable block for the LLM."""
    company    = package.get("company", {}) or {}
    financials = package.get("financials", {}) or {}
    loan       = package.get("loan", {}) or {}
    owners     = package.get("owners", []) or []
    documents  = package.get("documents", []) or []

    bank_count = sum(1 for d in documents if d.get("type") == "BANK_STATEMENT")
    tax_count  = sum(1 for d in documents if d.get("type") == "TAX_RETURN")

    annual_rev = financials.get("annualRevenue")
    monthly_rev = (annual_rev / 12) if annual_rev else None

    ownership_pct = sum(o.get("ownershipPercent", 0) for o in owners)
    owner_lines = [
        f"    {o.get('legalName') or 'Unknown'} — {o.get('ownershipPercent', 0):.0f}% — {o.get('title', '')}"
        for o in owners
    ] or ["    N/A"]

    lines = [
        "=== DEAL PROFILE ===",
        f"  Business:              {company.get('legalName') or 'Unknown'}",
        f"  Entity Type:           {company.get('entityType', 'N/A')}",
        f"  State:                 {company.get('state', 'N/A')}",
        f"  NAICS Code:            {company.get('naicsCode', 'N/A')}",
        f"  Industry:              {company.get('industry', 'N/A')}",
        "",
        "=== FINANCIALS ===",
        f"  Annual Revenue:        {_fmt(annual_rev)}",
        f"  Monthly Revenue (est): {_fmt(monthly_rev)}",
        f"  Monthly Cashflow:      {_fmt(financials.get('monthlyCashflow'))}",
        f"  Monthly Expenses:      {_fmt(financials.get('monthlyExpenses'))}",
        f"  Existing Debt:         {_fmt(financials.get('existingDebt'))}",
        f"  FICO / Credit Score:   {financials.get('creditScore', 'N/A')}",
        f"  Time in Business:      {financials.get('timeInBusinessYears', 'N/A')} years",
        "",
        "=== LOAN REQUEST ===",
        f"  Requested Amount:      {_fmt(loan.get('requestedAmount'))}",
        f"  Use of Funds:          {loan.get('useOfFunds', 'N/A')}",
        f"  Product:               {loan.get('product', 'N/A')}",
        "",
        "=== OWNERS / GUARANTORS ===",
        f"  Total Guarantor Ownership: {ownership_pct:.0f}%",
        *owner_lines,
        "",
        "=== DOCUMENTS ===",
        f"  Bank Statements:       {bank_count}",
        f"  Tax Returns:           {tax_count}",
        "",
        "=== DATA NOTES ===",
        "  NSF count (90d):       Unknown — derive from bank statements if available, else mark as unknown",
        "  Open positions count:  Estimate from existingDebt (>0 = at least 1 position)",
        "  Average Daily Balance: Unknown — derive from monthlyCashflow if available",
        "",
        "Now evaluate this deal against all 3 lenders using the credit boxes in your instructions.",
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


def _call_llm(prompt_text: str) -> LenderMatchInsight:
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.1,
        max_tokens=8192,
    )

    messages = [
        SystemMessage(content=DEFAULT_LENDER_MATCH_SYSTEM_PROMPT),
        HumanMessage(content=prompt_text),
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

    return LenderMatchInsight.model_validate(json.loads(raw))


def generate_lender_match(request: LenderMatchRequest) -> LenderMatchInsight:
    """Orchestrate fetch → LLM → push → return."""
    package = fetch_deal_package(request.deal_id)
    context = _build_context_block(package)
    prompt  = _build_prompt(context)

    try:
        insight = _call_llm(prompt)
    except Exception as exc:
        push_lender_match(request.deal_id, {}, error_message=str(exc))
        raise

    push_lender_match(request.deal_id, insight.model_dump())
    return insight
