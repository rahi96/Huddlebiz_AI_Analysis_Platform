"""Cashflow overview AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Download bank statement / tax return PDFs when present
  3. Map backend fields  → readable metrics block
  4. Claude reads PDFs + metrics → structured OverviewInsight JSON
  5. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report)
  6. Return OverviewInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import DEFAULT_OVERVIEW_SYSTEM_PROMPT
from app.schemas.overview import OverviewInsight, OverviewRequest
from app.services.backend_client import download_document, fetch_deal_package, push_cashflow_overview

# Cap per type to stay under Anthropic's 100-page limit
_MAX_BANK_STMTS = 6
_MAX_TAX_RETURNS = 2
_PDF_TYPES = {"BANK_STATEMENT", "TAX_RETURN"}

_INSIGHT_SCHEMA = OverviewInsight.model_json_schema()


def _collect_pdf_blocks(documents: list[dict]) -> list[dict]:
    """Download bank statement and tax return PDFs; return Claude document blocks."""
    counts: dict[str, int] = {}
    blocks = []
    for doc in documents:
        doc_type = doc.get("type", "")
        if doc_type not in _PDF_TYPES:
            continue
        limit = _MAX_BANK_STMTS if doc_type == "BANK_STATEMENT" else _MAX_TAX_RETURNS
        if counts.get(doc_type, 0) >= limit:
            continue
        url = doc.get("downloadUrl") or doc.get("presignedUrl") or doc.get("url") or ""
        if not url:
            continue
        try:
            pdf_bytes = download_document(url)
            encoded = base64.standard_b64encode(pdf_bytes).decode("ascii")
            label = doc.get("fileName") or doc.get("name") or f"{doc_type.lower()}.pdf"
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
                "title": f"[{doc_type}] {label}",
            })
            counts[doc_type] = counts.get(doc_type, 0) + 1
        except Exception:
            pass
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _safe(value, unit: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value}{unit}"


def _build_metrics_block(package: dict) -> str:
    """Map deal package fields from the backend into a readable block for the LLM."""
    company    = package.get("company", {}) or {}
    financials = package.get("financials", {}) or {}
    loan       = package.get("loan", {}) or {}
    documents  = package.get("documents", []) or []
    owners     = package.get("owners", []) or []

    annual_revenue    = financials.get("annualRevenue")
    monthly_expenses  = financials.get("monthlyExpenses")
    monthly_cashflow  = financials.get("monthlyCashflow")
    existing_debt     = financials.get("existingDebt")
    credit_score      = financials.get("creditScore")
    time_in_biz       = financials.get("timeInBusinessYears")

    # Derived estimates from self-reported application data
    daily_cashflow   = round(monthly_cashflow / 30, 2) if monthly_cashflow else None
    monthly_balance  = round((annual_revenue / 12) - (monthly_expenses or 0), 2) if annual_revenue else None
    daily_debt_repay = round(existing_debt / 365, 2) if existing_debt else None
    bank_stmt_count  = sum(1 for d in documents if d.get("type") == "BANK_STATEMENT")

    owner_summary = "; ".join(
        f"{o.get('legalName', 'Unknown')} ({o.get('ownershipPercent', '?')}% – {o.get('title', 'N/A')})"
        for o in owners
    ) or "N/A"

    lines = [
        f"Business:          {company.get('legalName') or company.get('dba') or 'Unknown'}",
        f"Entity Type:       {company.get('entityType', 'N/A')}",
        f"Industry:          {company.get('industry', 'N/A')}",
        f"NAICS Code:        {company.get('naicsCode', 'N/A')}",
        f"State:             {company.get('state', 'N/A')}",
        f"Time in Business:  {_safe(time_in_biz, ' years')}",
        f"Credit Score:      {_safe(credit_score)}",
        f"Owners:            {owner_summary}",
        "",
        "=== REVENUE ===",
        f"  Annual Revenue:                    {_safe(annual_revenue, ' USD')}",
        f"  Monthly Expenses (self-reported):  {_safe(monthly_expenses, ' USD')}",
        f"  Monthly Cashflow (self-reported):  {_safe(monthly_cashflow, ' USD')}",
        f"  Net Cashflow Daily Avg (derived):  {_safe(daily_cashflow, ' USD')}",
        "",
        "=== BALANCE (estimated) ===",
        f"  Est. Monthly Balance:              {_safe(monthly_balance, ' USD')}",
        f"  Predicted Balance Daily Avg:       N/A (requires live bank feed)",
        f"  Negative Balance Days (last 90d):  N/A (requires bank statement analysis)",
        f"  NSF Days (last 90d):               N/A (requires bank statement analysis)",
        "",
        "=== DEBT ===",
        f"  Existing Debt:                     {_safe(existing_debt, ' USD')}",
        f"  Debt Repayment Daily Avg (est.):   {_safe(daily_debt_repay, ' USD')}",
        f"  Requested Loan Amount:             {_safe(loan.get('requestedAmount'), ' USD')}",
        f"  Use of Funds:                      {loan.get('useOfFunds', 'N/A')}",
        f"  Debt Service Coverage Ratio:       N/A (requires income statement)",
        "",
        "=== DATA QUALITY ===",
        f"  Source:           Loan application (self-reported financials)",
        f"  Bank Statements:  {bank_stmt_count} document(s) attached",
        f"  Total Documents:  {len(documents)}",
        f"  Confidence:       Moderate — self-reported data; no live bank feed yet",
    ]
    return "\n".join(lines)


def _build_prompt(package: dict) -> str:
    metrics = _build_metrics_block(package)
    schema_str = json.dumps(_INSIGHT_SCHEMA, indent=2)
    return (
        f"Here are the cashflow metrics from the deal application:\n\n{metrics}\n\n"
        "If bank statement or tax return PDFs are attached above, extract financial figures "
        "from them and use those values in preference to any N/A application fields.\n\n"
        f"Return ONLY a JSON object conforming to this JSON Schema:\n\n{schema_str}"
    )


def _call_llm(pdf_blocks: list[dict], package: dict) -> OverviewInsight:
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=16000,
    )
    prompt_text = _build_prompt(package)
    content: list = [*pdf_blocks, {"type": "text", "text": prompt_text}]
    messages = [
        SystemMessage(content=DEFAULT_OVERVIEW_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]
    response = llm.invoke(messages)
    raw: str = response.content

    # Strip markdown fences if the model wraps its JSON
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]

    return OverviewInsight.model_validate(json.loads(raw.strip()))


def generate_overview_insight(req: OverviewRequest) -> OverviewInsight:
    package = fetch_deal_package(req.deal_id)
    documents = package.get("documents", []) or []
    pdf_blocks = _collect_pdf_blocks(documents)

    try:
        insight = _call_llm(pdf_blocks, package)
    except Exception as exc:
        push_cashflow_overview(req.deal_id, {}, error_message=str(exc))
        raise

    push_cashflow_overview(req.deal_id, insight.model_dump())
    return insight
