"""Balance Insights AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Extract EACH bank statement PDF individually (one Claude call per statement
     keeps every request under the 200K token limit, so NO months are dropped)
  3. Build the daily timeseries + monthly cash movement + summary deterministically
     in Python (exact counts and min/max)
  4. One text-only Claude call produces the narrative + health score
  5. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report  balanceInsights)
  6. Return BalanceInsightsInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import (
    BALANCE_STATEMENT_EXTRACTION_SYSTEM_PROMPT,
    DEFAULT_BALANCE_INSIGHTS_SYSTEM_PROMPT,
)
from app.schemas.balance_insights import (
    BalanceInsightsInsight,
    BalanceInsightsRequest,
    BalanceSummary,
    BalanceTimeseriesRow,
    CashMovementRow,
)
from app.services.backend_client import (
    download_document,
    fetch_deal_package,
    push_balance_insights,
)

_INSIGHT_SCHEMA = BalanceInsightsInsight.model_json_schema()

# Hard ceiling so a deal with dozens of statements can't run unbounded
_MAX_STATEMENTS = 12


def _statement_pdfs(documents: list[dict]) -> list[dict]:
    """Return BANK_STATEMENT docs (capped for safety)."""
    stmts = [d for d in documents if d.get("type") == "BANK_STATEMENT"]
    return stmts[:_MAX_STATEMENTS]


def _strip_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _round(v) -> float | None:
    return round(v, 2) if isinstance(v, (int, float)) else None


def _extract_one_statement(doc: dict) -> dict | None:
    """Send a SINGLE bank statement PDF to Claude and extract its balance data.

    One statement per call stays under the 200K token limit, so every month is
    analysed accurately. Returns the parsed dict or None if unreadable.
    """
    url = doc.get("downloadUrl") or doc.get("presignedUrl") or doc.get("url") or ""
    if not url:
        return None
    try:
        pdf_bytes = download_document(url)
    except Exception:
        return None

    encoded = base64.standard_b64encode(pdf_bytes).decode("ascii")
    label = doc.get("fileName") or doc.get("name") or "bank_statement.pdf"
    block = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
        "title": f"[BANK_STATEMENT] {label}",
        "cache_control": {"type": "ephemeral"},
    }

    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.0,
        max_tokens=8000,
    )
    prompt = (
        "Extract the balance data for the ONE bank statement attached above. "
        "Return ONLY a JSON object matching this shape:\n"
        '{"month": "YYYY-MM", "opening_balance": number, "closing_balance": number, '
        '"inflows": number, "outflows": number, "average_balance": number, '
        '"lowest_balance": number, "highest_balance": number, '
        '"daily_balances": [{"date": "YYYY-MM-DD", "balance": number}]}\n'
        "Include every day the statement shows a balance. Use exact numbers. JSON only, no prose."
    )
    # Retry so a transient failure never silently drops a month of financial data
    for _ in range(3):
        try:
            response = llm.invoke([
                SystemMessage(content=BALANCE_STATEMENT_EXTRACTION_SYSTEM_PROMPT),
                HumanMessage(content=[block, {"type": "text", "text": prompt}]),
            ])
            return json.loads(_strip_json(response.content))
        except Exception:
            continue
    return None


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


def _aggregate(rows: list[dict], low_balance_limit: float) -> dict:
    """Build timeseries, cash movement and summary deterministically from extractions."""
    months = sorted(rows, key=lambda r: r.get("month") or "")

    # Panel 1 — daily timeseries across all months, with per-month opening/closing/avg
    timeseries: list[BalanceTimeseriesRow] = []
    all_balances: list[float] = []
    zero_neg_days = 0
    low_days = 0
    for r in months:
        dailies = sorted(
            (d for d in (r.get("daily_balances") or []) if d.get("date") is not None),
            key=lambda d: d.get("date") or "",
        )
        opening = r.get("opening_balance")
        closing = r.get("closing_balance")
        day_vals = [d.get("balance") for d in dailies if isinstance(d.get("balance"), (int, float))]
        avg = round(sum(day_vals) / len(day_vals), 2) if day_vals else r.get("average_balance")
        for d in dailies:
            bal = d.get("balance")
            is_zero_neg = isinstance(bal, (int, float)) and bal <= 0
            is_low = isinstance(bal, (int, float)) and 0 < bal <= low_balance_limit
            if is_zero_neg:
                zero_neg_days += 1
            if is_low:
                low_days += 1
            if isinstance(bal, (int, float)):
                all_balances.append(bal)
            timeseries.append(BalanceTimeseriesRow(
                date=d.get("date"),
                daily_balance=_round(bal),
                monthly_opening_balance=_round(opening),
                monthly_closing_balance=_round(closing),
                monthly_average_balance=_round(avg),
                is_zero_or_negative=is_zero_neg,
                is_low_balance=is_low,
            ))

    balance_summary = BalanceSummary(
        low_balance_limit=low_balance_limit,
        number_zero_or_negative_balance_days=zero_neg_days,
        number_low_balance_days=low_days,
        highest_balance=_round(max(all_balances)) if all_balances else None,
        lowest_balance=_round(min(all_balances)) if all_balances else None,
    )

    # Panel 2 — monthly cash movement (exact inflows/outflows per month)
    cash_movement = []
    for r in months:
        inflows = r.get("inflows") or 0
        outflows = r.get("outflows") or 0
        cash_movement.append(CashMovementRow(
            month=r.get("month"),
            inflows=_round(inflows),
            outflows=_round(outflows),
            net_change=round(inflows - outflows, 2),
        ))

    return {
        "timeseries": timeseries,
        "balance_summary": balance_summary,
        "cash_movement": cash_movement,
    }


def _build_narrative(package: dict, low_balance_limit: float, summary_json: str) -> dict:
    """Text-only Claude call for narrative + health score."""
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=4000,
    )
    prompt = (
        f"Deal application data:\n\n{_build_context_block(package, low_balance_limit)}\n\n"
        f"Computed balance figures (already accurate, do not recompute):\n{summary_json}\n\n"
        "Write the narrative fields as JSON only:\n"
        '{"summary": str, "balance_trend_insight": str, "cash_movement_insight": str, '
        '"risks": [{"area": str, "issue": str, "severity": "low|medium|high"}], '
        '"recommendations": [{"title": str, "detail": str}], '
        '"overall_health_score": int, "overall_health_label": "Poor|Fair|Good|Excellent", '
        '"data_source_note": str}'
    )
    response = llm.invoke([
        SystemMessage(content=DEFAULT_BALANCE_INSIGHTS_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    return json.loads(_strip_json(response.content))


def generate_balance_insights(request: BalanceInsightsRequest) -> BalanceInsightsInsight:
    """Orchestrate fetch → per-statement extract → aggregate → narrative → push."""
    package = fetch_deal_package(request.deal_id)
    documents = package.get("documents", []) or []
    statements = _statement_pdfs(documents)
    limit = request.low_balance_limit

    try:
        extracted = [e for e in (_extract_one_statement(d) for d in statements) if e]
        # Keep only entries with real monthly balance figures
        extracted = [
            e for e in extracted
            if e.get("month") and (e.get("closing_balance") is not None or e.get("daily_balances"))
        ]
        sections = _aggregate(extracted, limit)

        compact = json.dumps({
            "cash_movement": [c.model_dump() for c in sections["cash_movement"]],
            "balance_summary": sections["balance_summary"].model_dump(),
            "months_covered": len(extracted),
        }, default=str)
        narrative = _build_narrative(package, limit, compact) if extracted else {}

        insight = BalanceInsightsInsight(
            timeseries=sections["timeseries"],
            balance_summary=sections["balance_summary"],
            cash_movement=sections["cash_movement"],
            summary=narrative.get("summary", ""),
            balance_trend_insight=narrative.get("balance_trend_insight", ""),
            cash_movement_insight=narrative.get("cash_movement_insight", ""),
            risks=narrative.get("risks", []),
            recommendations=narrative.get("recommendations", []),
            overall_health_score=narrative.get("overall_health_score", 0),
            overall_health_label=narrative.get("overall_health_label", "Poor"),
            data_source_note=narrative.get("data_source_note", ""),
        )
    except Exception as exc:
        push_balance_insights(request.deal_id, {}, error_message=str(exc))
        raise

    push_balance_insights(request.deal_id, insight.model_dump())
    return insight
