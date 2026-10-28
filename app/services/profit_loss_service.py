"""Profit & Loss AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Extract EACH bank statement PDF individually (one Claude call per statement
     keeps every request under the 200K token limit, so NO months are dropped)
  3. Aggregate monthly summary, income/expense breakdowns, counterparties, and
     unique transactions deterministically in Python (exact math)
  4. One text-only Claude call produces narrative + forecast + health score
  5. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report  profitAndLoss)
  6. Return ProfitLossInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import (
    DEFAULT_PROFIT_LOSS_SYSTEM_PROMPT,
    PL_STATEMENT_EXTRACTION_SYSTEM_PROMPT,
)
from app.schemas.profit_loss import (
    CategoryMonthAmount,
    CounterpartyRow,
    ExpenseBreakdownLine,
    IncomeBreakdownLine,
    MonthlySummaryRow,
    ProfitLossInsight,
    ProfitLossRequest,
    UniqueTransaction,
)
from app.services.backend_client import (
    download_document,
    fetch_deal_package,
    push_profit_loss,
)

_INSIGHT_SCHEMA = ProfitLossInsight.model_json_schema()

# Hard ceiling so a deal with dozens of statements can't run unbounded
_MAX_STATEMENTS = 12


def _statement_pdfs(documents: list[dict]) -> list[dict]:
    """Return BANK_STATEMENT docs (capped for safety)."""
    stmts = [d for d in documents if d.get("type") == "BANK_STATEMENT"]
    return stmts[:_MAX_STATEMENTS]


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
    """Send a SINGLE bank statement PDF to Claude and extract its P&L data.

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
        "Extract the P&L data for the ONE bank statement attached above. "
        "Return ONLY a JSON object matching this shape:\n"
        '{"month": "YYYY-MM", "gross_revenue": number, "total_expenses": number, '
        '"income_by_category": [{"category": str, "amount": number}], '
        '"expense_by_category": [{"category": str, "amount": number}], '
        '"unique_transactions": [{"date": "YYYY-MM-DD", "description": str, "amount": number, '
        '"type": "income|expense", "category": str}], '
        '"top_vendors": [{"name": str, "total_amount": number, "transaction_count": int}], '
        '"top_customers": [{"name": str, "total_amount": number, "transaction_count": int}]}\n'
        "income_by_category amounts must sum to gross_revenue; expense_by_category amounts "
        "must sum to total_expenses. Use the actual statement month. JSON only, no prose."
    )
    # Retry so a transient failure never silently drops a month of financial data
    for _ in range(3):
        try:
            response = llm.invoke([
                SystemMessage(content=PL_STATEMENT_EXTRACTION_SYSTEM_PROMPT),
                HumanMessage(content=[block, {"type": "text", "text": prompt}]),
            ])
            return json.loads(_strip_json(response.content))
        except Exception:
            continue
    return None


def _aggregate(rows: list[dict]) -> dict:
    """Build the P&L sections deterministically from per-statement extractions."""
    months = sorted(rows, key=lambda r: r.get("month") or "")
    month_keys = [r.get("month") for r in months]

    # Section 1 — monthly summary (exact per-month math)
    monthly_summary = []
    for r in months:
        gr = r.get("gross_revenue") or 0
        te = r.get("total_expenses") or 0
        net = round(gr - te, 2)
        monthly_summary.append(MonthlySummaryRow(
            month=r.get("month"),
            gross_revenue=_round(gr),
            total_expenses=_round(te),
            net_profit_loss=net,
            profit_margin_pct=round(net / gr, 4) if gr else None,
            is_loss=net < 0,
        ))

    # Sections 2 & 3 — income/expense breakdown by category across all months
    def _breakdown(key: str, line_cls):
        cat_month: dict[str, dict[str, float]] = {}
        for r in months:
            m = r.get("month")
            for item in r.get(key) or []:
                cat = (item.get("category") or "Other").strip()
                cat_month.setdefault(cat, {})[m] = cat_month.setdefault(cat, {}).get(m, 0) + (item.get("amount") or 0)
        lines = []
        for cat, per_month in cat_month.items():
            monthly = [CategoryMonthAmount(month=mk, amount=_round(per_month.get(mk, 0))) for mk in month_keys]
            lines.append(line_cls(category=cat, monthly=monthly, total=_round(sum(per_month.values()))))
        return sorted(lines, key=lambda x: x.total or 0, reverse=True)

    income_breakdown = _breakdown("income_by_category", IncomeBreakdownLine)
    expense_breakdown = _breakdown("expense_by_category", ExpenseBreakdownLine)

    # Section 4 — unique transactions (merge, keep largest 20 by absolute amount)
    uniques = []
    for r in months:
        for u in r.get("unique_transactions") or []:
            uniques.append(UniqueTransaction(
                date=u.get("date"), description=u.get("description"),
                amount=_round(u.get("amount")), type=u.get("type"), category=u.get("category"),
            ))
    uniques = sorted(uniques, key=lambda x: abs(x.amount or 0), reverse=True)[:20]

    # Section 6 — top vendors/customers (merge counterparties across months)
    def _counterparties(key: str, cp_type: str):
        agg: dict[str, dict] = {}
        for r in months:
            for c in r.get(key) or []:
                name = (c.get("name") or "Unknown").strip()
                a = agg.setdefault(name, {"total": 0.0, "count": 0})
                a["total"] += c.get("total_amount") or 0
                a["count"] += c.get("transaction_count") or 0
        out = [CounterpartyRow(name=n, total_amount=_round(v["total"]),
                               transaction_count=v["count"], type=cp_type)
               for n, v in agg.items()]
        return sorted(out, key=lambda x: x.total_amount or 0, reverse=True)[:10]

    top_vendors = _counterparties("top_vendors", "vendor")
    top_customers = _counterparties("top_customers", "customer")

    return {
        "monthly_summary": monthly_summary,
        "income_breakdown": income_breakdown,
        "expense_breakdown": expense_breakdown,
        "unique_transactions": uniques,
        "top_vendors": top_vendors,
        "top_customers": top_customers,
    }


def _build_narrative(package: dict, summary_json: str) -> dict:
    """Text-only Claude call for narrative, forecast, and health score."""
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=6000,
    )
    prompt = (
        f"Deal application data:\n\n{_build_context_block(package)}\n\n"
        f"Computed monthly P&L figures (already accurate, do not recompute):\n{summary_json}\n\n"
        "Produce the narrative and forward forecast as JSON only:\n"
        '{"sales_forecast": [{"month": "YYYY-MM", "projected_revenue": number, '
        '"projected_expenses": number, "projected_net": number, "is_forecast": true}], '
        '"summary": str, "income_insight": str, "expense_insight": str, "forecast_insight": str, '
        '"risks": [{"area": str, "issue": str, "severity": "low|medium|high"}], '
        '"recommendations": [{"title": str, "detail": str}], '
        '"overall_health_score": int, "overall_health_label": "Poor|Fair|Good|Excellent", '
        '"data_source_note": str}\n'
        "Base the 3-month forecast on the historical trend in the computed figures."
    )
    response = llm.invoke([
        SystemMessage(content=DEFAULT_PROFIT_LOSS_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    return json.loads(_strip_json(response.content))


def generate_profit_loss(request: ProfitLossRequest) -> ProfitLossInsight:
    """Orchestrate fetch → per-statement extract → aggregate → narrative → push."""
    package = fetch_deal_package(request.deal_id)
    documents = package.get("documents", []) or []
    statements = _statement_pdfs(documents)

    try:
        extracted = [e for e in (_extract_one_statement(d) for d in statements) if e]
        # Keep only entries with real monthly figures (skip mislabeled non-statements)
        extracted = [
            e for e in extracted
            if e.get("month") and (e.get("gross_revenue") is not None or e.get("total_expenses") is not None)
        ]
        sections = _aggregate(extracted)

        compact = json.dumps({
            "monthly_summary": [m.model_dump() for m in sections["monthly_summary"]],
            "income_categories": [{"category": l.category, "total": l.total} for l in sections["income_breakdown"]],
            "expense_categories": [{"category": l.category, "total": l.total} for l in sections["expense_breakdown"]],
        }, default=str)
        narrative = _build_narrative(package, compact) if sections["monthly_summary"] else {}

        insight = ProfitLossInsight(
            **sections,
            sales_forecast=narrative.get("sales_forecast", []),
            summary=narrative.get("summary", ""),
            income_insight=narrative.get("income_insight", ""),
            expense_insight=narrative.get("expense_insight", ""),
            forecast_insight=narrative.get("forecast_insight", ""),
            risks=narrative.get("risks", []),
            recommendations=narrative.get("recommendations", []),
            overall_health_score=narrative.get("overall_health_score", 0),
            overall_health_label=narrative.get("overall_health_label", "Poor"),
            data_source_note=narrative.get("data_source_note", ""),
        )
    except Exception as exc:
        push_profit_loss(request.deal_id, {}, error_message=str(exc))
        raise

    push_profit_loss(request.deal_id, insight.model_dump())
    return insight
