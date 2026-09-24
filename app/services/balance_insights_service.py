"""Balance Insights AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Download bank statement PDFs (if present) and base64-encode them
  3. Claude reads PDFs natively + deal financials → computes timeseries, cash movement, narrative
  4. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report  balanceInsights)
  5. Return BalanceInsightsInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import DEFAULT_BALANCE_INSIGHTS_SYSTEM_PROMPT
from app.schemas.balance_insights import BalanceInsightsInsight, BalanceInsightsRequest
from app.services.backend_client import (
    download_document,
    fetch_deal_package,
    push_balance_insights,
)

_INSIGHT_SCHEMA = BalanceInsightsInsight.model_json_schema()


def _collect_pdf_blocks(documents: list[dict]) -> list[dict]:
    """Download BANK_STATEMENT PDFs and return Claude document content blocks."""
    blocks = []
    for doc in documents:
        if doc.get("type") != "BANK_STATEMENT":
            continue
        url = doc.get("downloadUrl") or doc.get("presignedUrl") or doc.get("url") or ""
        if not url:
            continue
        try:
            pdf_bytes = download_document(url)
            encoded = base64.standard_b64encode(pdf_bytes).decode("ascii")
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": encoded,
                },
                "title": doc.get("name", "bank_statement.pdf"),
                "cache_control": {"type": "ephemeral"},
            })
        except Exception:
            # Skip inaccessible documents; Claude will fall back to financial estimates
            pass
    return blocks


def _build_context_block(package: dict, low_balance_limit: float) -> str:
    """Serialise deal financials into a text block for the LLM."""
    company = package.get("company", {}) or {}
    financials = package.get("financials", {}) or {}
    loan = package.get("loan", {}) or {}
    documents = package.get("documents", []) or []

    bank_stmt_count = sum(1 for d in documents if d.get("type") == "BANK_STATEMENT")

    lines = [
        f"Business:            {company.get('legalName') or 'Unknown'}",
        f"Industry:            {company.get('industry', 'N/A')}",
        f"Time in Business:    {financials.get('timeInBusinessYears', 'N/A')} years",
        "",
        "=== FINANCIALS ===",
        f"  Annual Revenue:    ${financials.get('annualRevenue', 'N/A'):,}" if financials.get('annualRevenue') else "  Annual Revenue:    N/A",
        f"  Monthly Cashflow:  ${financials.get('monthlyCashflow', 'N/A'):,}" if financials.get('monthlyCashflow') else "  Monthly Cashflow:  N/A",
        f"  Monthly Expenses:  ${financials.get('monthlyExpenses', 'N/A'):,}" if financials.get('monthlyExpenses') else "  Monthly Expenses:  N/A",
        f"  Existing Debt:     ${financials.get('existingDebt', 0):,}" if financials.get('existingDebt') is not None else "  Existing Debt:     N/A",
        f"  Credit Score:      {financials.get('creditScore', 'N/A')}",
        "",
        "=== LOAN REQUEST ===",
        f"  Requested Amount:  ${loan.get('requestedAmount', 'N/A'):,}" if loan.get('requestedAmount') else "  Requested Amount:  N/A",
        f"  Use of Funds:      {loan.get('useOfFunds', 'N/A')}",
        "",
        f"=== DOCUMENTS ===",
        f"  Bank Statements attached: {bank_stmt_count}",
        "",
        f"=== BALANCE INSIGHTS PARAMETERS ===",
        f"  Low Balance Limit: ${low_balance_limit:,.2f}",
        "",
        "If bank statement PDFs are attached above, read the actual daily balances, deposits, and withdrawals from them.",
        "If no PDFs are attached, derive estimated monthly series from the financials.",
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


def _call_llm(pdf_blocks: list[dict], prompt_text: str) -> BalanceInsightsInsight:
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.1,
        max_tokens=8192,
    )

    # Build content: PDF document blocks first, then the text prompt
    content: list = [*pdf_blocks, {"type": "text", "text": prompt_text}]

    messages = [
        SystemMessage(content=DEFAULT_BALANCE_INSIGHTS_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]

    response = llm.invoke(messages)
    raw = response.content

    # Strip accidental markdown fences
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rstrip("`").strip()

    return BalanceInsightsInsight.model_validate(json.loads(raw))


def generate_balance_insights(request: BalanceInsightsRequest) -> BalanceInsightsInsight:
    """Orchestrate fetch → PDF parse → LLM → push → return."""
    package = fetch_deal_package(request.deal_id)

    documents = package.get("documents", []) or []
    pdf_blocks = _collect_pdf_blocks(documents)

    context = _build_context_block(package, request.low_balance_limit)
    prompt = _build_prompt(context)

    try:
        insight = _call_llm(pdf_blocks, prompt)
    except Exception as exc:
        push_balance_insights(request.deal_id, {}, error_message=str(exc))
        raise

    push_balance_insights(request.deal_id, insight.model_dump())
    return insight
