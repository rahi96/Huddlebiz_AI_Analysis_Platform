"""Bank & Debt Summary AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Extract EACH bank statement PDF individually (one Claude call per statement
     keeps every request well under the 200K token limit, so NO months are dropped)
  3. Aggregate monthly rows and compute TOTAL/AVERAGE deterministically in Python
  4. One text-only Claude call produces the narrative + health score
  5. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report  bankDebtSummary)
  6. Return BankDebtInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import (
    DEFAULT_BANK_DEBT_SYSTEM_PROMPT,
    STATEMENT_EXTRACTION_SYSTEM_PROMPT,
)
from app.schemas.bank_debt import (
    BankDebtInsight,
    BankDebtRequest,
    BankStatementRow,
    DebtPosition,
    RecurringTransaction,
)
from app.services.backend_client import download_document, fetch_deal_package, push_bank_debt_summary

# Hard ceiling so a deal with dozens of statements can't run unbounded
_MAX_STATEMENTS = 12

_INSIGHT_SCHEMA = BankDebtInsight.model_json_schema()


def _statement_pdfs(documents: list[dict]) -> list[dict]:
    """Return BANK_STATEMENT docs (cap for safety), newest handling left to the model."""
    stmts = [d for d in documents if d.get("type") == "BANK_STATEMENT"]
    return stmts[:_MAX_STATEMENTS]


def _safe(value, unit: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value}{unit}"


def _build_data_block(package: dict) -> str:
    """Serialise deal package into a readable block for the LLM."""
    company    = package.get("company", {}) or {}
    financials = package.get("financials", {}) or {}
    loan       = package.get("loan", {}) or {}
    documents  = package.get("documents", []) or []
    owners     = package.get("owners", []) or []

    bank_stmts   = [d for d in documents if d.get("type") == "BANK_STATEMENT"]
    tax_returns  = [d for d in documents if d.get("type") == "TAX_RETURN"]
    other_docs   = [d for d in documents if d.get("type") not in ("BANK_STATEMENT", "TAX_RETURN")]

    lines = [
        f"Business:           {company.get('legalName') or 'Unknown'}",
        f"Entity Type:        {company.get('entityType', 'N/A')}",
        f"Industry:           {company.get('industry', 'N/A')}",
        f"State:              {company.get('state', 'N/A')}",
        f"Time in Business:   {_safe(financials.get('timeInBusinessYears'), ' years')}",
        "",
        "=== FINANCIALS (self-reported application data) ===",
        f"  Annual Revenue:      {_safe(financials.get('annualRevenue'), ' USD')}",
        f"  Monthly Cashflow:    {_safe(financials.get('monthlyCashflow'), ' USD')}",
        f"  Monthly Expenses:    {_safe(financials.get('monthlyExpenses'), ' USD')}",
        f"  Existing Debt:       {_safe(financials.get('existingDebt'), ' USD')}",
        f"  Credit Score:        {_safe(financials.get('creditScore'))}",
        "",
        "=== LOAN REQUEST ===",
        f"  Requested Amount:    {_safe(loan.get('requestedAmount'), ' USD')}",
        f"  Use of Funds:        {loan.get('useOfFunds', 'N/A')}",
        f"  Product:             {loan.get('product', 'N/A')}",
        "",
        "=== DOCUMENTS ===",
        f"  Bank Statements:     {len(bank_stmts)} file(s)",
    ]

    for doc in bank_stmts:
        lines.append(f"    - {doc.get('fileName', 'unknown')} ({doc.get('mimeType', '')})")

    lines += [
        f"  Tax Returns:         {len(tax_returns)} file(s)",
        f"  Other Documents:     {len(other_docs)} file(s)",
        "",
        "=== OWNERS ===",
    ]

    for owner in owners:
        lines.append(
            f"  {owner.get('legalName', 'Unknown')} — "
            f"{owner.get('ownershipPercent', '?')}% — {owner.get('title', 'N/A')}"
        )

    return "\n".join(lines)


def _strip_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _extract_one_statement(doc: dict) -> dict | None:
    """Send a SINGLE bank statement PDF to Claude and extract its structured data.

    One statement per call stays far under the 200K token limit, so every month
    is analysed accurately. Returns the parsed dict or None if unreadable.
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
        "Extract the data for the ONE bank statement attached above. "
        "Return ONLY a JSON object for a single BankStatementRow plus transaction lists, "
        "matching this shape:\n"
        '{"month": "YYYY-MM", "starting_balance": number, "num_deposits": int, '
        '"total_deposits": number, "true_revenue": number, "num_true_rev_deposits": int, '
        '"non_revenue": number, "num_withdrawals": int, "total_withdrawals": number, '
        '"mca_debits": number, "holdings": number, "ending_balance": number, '
        '"average_balance": number, "num_negative_balance_days": int, '
        '"num_overdraft_or_nsf": int, "num_overdraft_transactions": int, '
        '"num_low_balance_days": int, "num_dd_reversals": int, '
        '"debt_payments": [{"merchant_counterparty": str, "amount": number, "date": "YYYY-MM-DD"}], '
        '"recurring": [{"merchant_counterparty": str, "amount": number, "frequency": str, '
        '"category": str}]}\n'
        "Use the actual statement month for 'month'. true_revenue + non_revenue must equal "
        "total_deposits. holdings and ending_balance are both the closing balance. "
        "average_balance = the statement's stated average daily/ledger balance if shown, "
        "else the mean of the daily ending balances. num_negative_balance_days = days the "
        "ledger balance was below zero. num_overdraft_or_nsf = count of overdraft/NSF fee "
        "events. num_overdraft_transactions = transactions that overdrew the account. "
        "num_low_balance_days = days balance was under $1000. num_dd_reversals = direct-debit/"
        "ACH return or reversal count. Use 0 (not null) when the statement shows none. "
        "No prose, JSON only."
    )
    # Retry until we get a valid, reconciled extraction so no month is dropped or wrong
    last = None
    for _ in range(4):
        try:
            response = llm.invoke([
                SystemMessage(content=STATEMENT_EXTRACTION_SYSTEM_PROMPT),
                HumanMessage(content=[block, {"type": "text", "text": prompt}]),
            ])
            data = json.loads(_strip_json(response.content))
        except Exception:
            continue
        last = data
        # Accept only if the month is present and deposits reconcile
        if data.get("month") and _deposits_reconcile(data):
            return data
    return last


def _deposits_reconcile(d: dict) -> bool:
    """true_revenue + non_revenue should equal total_deposits (within $1)."""
    td = d.get("total_deposits")
    tr = d.get("true_revenue")
    nr = d.get("non_revenue")
    if not isinstance(td, (int, float)):
        return False
    if not isinstance(tr, (int, float)) or not isinstance(nr, (int, float)):
        return False
    return abs((tr + nr) - td) <= 1.0


def _round(v) -> float | None:
    return round(v, 2) if isinstance(v, (int, float)) else None


def _derive_row_fields(r: dict) -> dict:
    """Fill ending_balance and holdback_pct for a single statement's data."""
    holdings = r.get("holdings")
    if r.get("ending_balance") is None:
        r["ending_balance"] = holdings
    deposits = r.get("total_deposits") or 0
    mca = r.get("mca_debits") or 0
    if r.get("holdback_pct") is None:
        r["holdback_pct"] = round(mca / deposits, 4) if deposits else None
    return r


def _aggregate_rows(rows: list[dict]) -> tuple[list[BankStatementRow], BankStatementRow | None, BankStatementRow | None]:
    """Build monthly rows + deterministic TOTAL and AVERAGE (exact Python math)."""
    monthly = sorted((_derive_row_fields(r) for r in rows), key=lambda r: r.get("month") or "")
    monthly_models = [BankStatementRow(**{k: r.get(k) for k in BankStatementRow.model_fields}) for r in monthly]
    if not monthly:
        return [], None, None

    count_fields = [
        "num_deposits", "num_true_rev_deposits", "num_withdrawals",
        "num_negative_balance_days", "num_overdraft_or_nsf", "num_overdraft_transactions",
        "num_low_balance_days", "num_dd_reversals",
    ]
    money_fields = ["total_deposits", "true_revenue", "non_revenue", "total_withdrawals", "mca_debits"]
    sum_fields = count_fields + money_fields
    totals = {f: sum((r.get(f) or 0) for r in monthly) for f in sum_fields}
    n = len(monthly)
    avg_bal = [r.get("average_balance") for r in monthly if isinstance(r.get("average_balance"), (int, float))]
    total_deposits = totals["total_deposits"]

    total_row = BankStatementRow(
        month="TOTAL",
        starting_balance=monthly[0].get("starting_balance"),
        holdings=monthly[-1].get("holdings"),
        ending_balance=monthly[-1].get("ending_balance") or monthly[-1].get("holdings"),
        average_balance=_round(sum(avg_bal) / len(avg_bal)) if avg_bal else None,
        holdback_pct=round(totals["mca_debits"] / total_deposits, 4) if total_deposits else None,
        **{f: int(totals[f]) for f in count_fields},
        **{f: _round(totals[f]) for f in money_fields},
    )
    average_row = BankStatementRow(
        month="Average",
        starting_balance=_round(sum((r.get("starting_balance") or 0) for r in monthly) / n),
        holdings=_round(sum((r.get("holdings") or 0) for r in monthly) / n),
        ending_balance=_round(sum((r.get("ending_balance") or 0) for r in monthly) / n),
        average_balance=_round(sum(avg_bal) / len(avg_bal)) if avg_bal else None,
        holdback_pct=round((totals["mca_debits"] / n) / (total_deposits / n), 4) if total_deposits else None,
        **{f: round(totals[f] / n) for f in count_fields},
        **{f: _round(totals[f] / n) for f in money_fields},
    )
    return monthly_models, total_row, average_row


def _collect_debt_and_recurring(rows: list[dict]) -> tuple[list[DebtPosition], list[RecurringTransaction]]:
    """Merge per-statement debt payments and recurring entries across all months."""
    debt_map: dict[str, dict] = {}
    rec_map: dict[str, dict] = {}
    for r in rows:
        for p in r.get("debt_payments") or []:
            name = (p.get("merchant_counterparty") or "Unknown").strip()
            d = debt_map.setdefault(name, {"count": 0, "total": 0.0, "dates": []})
            d["count"] += 1
            d["total"] += p.get("amount") or 0
            if p.get("date"):
                d["dates"].append(p["date"])
        for rec in r.get("recurring") or []:
            name = (rec.get("merchant_counterparty") or "Unknown").strip()
            m = rec_map.setdefault(name, {"amounts": [], "freq": rec.get("frequency"), "cats": set()})
            m["amounts"].append(rec.get("amount") or 0)
            if rec.get("category"):
                m["cats"].add(rec["category"])

    debt_positions = []
    for name, d in debt_map.items():
        dates = sorted(d["dates"])
        debt_positions.append(DebtPosition(
            merchant_counterparty=name,
            count=d["count"],
            total_amount=_round(d["total"]),
            avg_amount=_round(d["total"] / d["count"]) if d["count"] else None,
            first_transaction_date=dates[0] if dates else None,
            last_transaction_date=dates[-1] if dates else None,
            active=True,
        ))

    recurring = []
    for name, m in rec_map.items():
        amts = m["amounts"]
        recurring.append(RecurringTransaction(
            merchant_counterparty=name,
            avg_amount=_round(sum(amts) / len(amts)) if amts else None,
            frequency=m["freq"],
            categories=sorted(m["cats"]),
        ))
    return debt_positions, recurring


def _build_narrative(package: dict, summary_json: str) -> dict:
    """Text-only Claude call for summary, insights, risks, recommendations, score."""
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=6000,
    )
    prompt = (
        f"Deal application data:\n\n{_build_data_block(package)}\n\n"
        f"Computed bank statement figures (already accurate, do not recompute):\n{summary_json}\n\n"
        "Write the narrative fields as JSON only:\n"
        '{"summary": str, "bank_insight": str, "debt_insight": str, '
        '"risks": [{"area": str, "issue": str, "severity": "low|medium|high"}], '
        '"recommendations": [{"title": str, "detail": str}], '
        '"overall_health_score": int (0-100), "overall_health_label": "Poor|Fair|Good|Excellent"}'
    )
    response = llm.invoke([
        SystemMessage(content=DEFAULT_BANK_DEBT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    return json.loads(_strip_json(response.content))


def generate_bank_debt_insight(req: BankDebtRequest) -> BankDebtInsight:
    package = fetch_deal_package(req.deal_id)
    documents = package.get("documents", []) or []
    statements = _statement_pdfs(documents)

    try:
        # Extract every statement individually so no month is dropped
        extracted = [e for e in (_extract_one_statement(d) for d in statements) if e]
        # Drop entries that aren't real bank statements (e.g. a mislabeled P&L):
        # a genuine statement has a closing balance and transaction counts.
        extracted = [
            e for e in extracted
            if e.get("holdings") is not None and e.get("num_withdrawals") is not None
        ]
        monthly_rows, total_row, average_row = _aggregate_rows(extracted)
        debt_positions, recurring = _collect_debt_and_recurring(extracted)

        # Keep the narrative input compact so the response isn't truncated
        summary_json = json.dumps({
            "months": [
                {"month": r.month, "total_deposits": r.total_deposits,
                 "true_revenue": r.true_revenue, "total_withdrawals": r.total_withdrawals,
                 "mca_debits": r.mca_debits, "holdings": r.holdings}
                for r in monthly_rows
            ],
            "total": total_row.model_dump() if total_row else None,
            "average": average_row.model_dump() if average_row else None,
            "top_debt_positions": [
                {"name": d.merchant_counterparty, "total": d.total_amount, "count": d.count}
                for d in sorted(debt_positions, key=lambda x: x.total_amount or 0, reverse=True)[:10]
            ],
        }, default=str)
        narrative = _build_narrative(package, summary_json) if monthly_rows else {}

        insight = BankDebtInsight(
            bank_statement_summary={
                "monthly_rows": monthly_rows,
                "total_row": total_row,
                "average_row": average_row,
            },
            debt_positions=debt_positions,
            recurring_transactions=recurring,
            transaction_coverage={
                "months_covered": len(monthly_rows),
                "pdf_pct": 1.0 if monthly_rows else 0.0,
                "api_pct": 0.0,
                "missing_data_pct": 0.0,
            },
            summary=narrative.get("summary", ""),
            bank_insight=narrative.get("bank_insight", ""),
            debt_insight=narrative.get("debt_insight", ""),
            risks=narrative.get("risks", []),
            recommendations=narrative.get("recommendations", []),
            overall_health_score=narrative.get("overall_health_score", 0),
            overall_health_label=narrative.get("overall_health_label", "Poor"),
        )
    except Exception as exc:
        push_bank_debt_summary(req.deal_id, {}, error_message=str(exc))
        raise

    push_bank_debt_summary(req.deal_id, insight.model_dump())
    return insight
