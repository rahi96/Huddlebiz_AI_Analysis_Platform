"""Bank & Debt Summary AI service.

Flow:
  1. Fetch deal package  (GET /api/v1/internal/ai/deals/{id}/package)
  2. Download bank statement PDFs and base64-encode them
  3. Claude reads PDFs natively → extracts all table data + narrative
  4. Push result back    (PUT /api/v1/internal/ai/deals/{id}/cashflow-report  bankDebtSummary)
  5. Return BankDebtInsight to the caller
"""

import base64
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.prompts.system_prompts import DEFAULT_BANK_DEBT_SYSTEM_PROMPT
from app.schemas.bank_debt import BankDebtInsight, BankDebtRequest
from app.services.backend_client import download_document, fetch_deal_package, push_bank_debt_summary

# 2 bank stmts keeps well under the 200K token limit for large PDFs
_MAX_BANK_STMTS = 2

_INSIGHT_SCHEMA = BankDebtInsight.model_json_schema()


def _collect_pdf_blocks(documents: list[dict]) -> list[dict]:
    """Download bank statement PDFs and return Claude document content blocks."""
    count = 0
    blocks = []
    for doc in documents:
        if doc.get("type") != "BANK_STATEMENT":
            continue
        if count >= _MAX_BANK_STMTS:
            continue
        url = doc.get("downloadUrl") or doc.get("presignedUrl") or doc.get("url") or ""
        if not url:
            continue
        try:
            pdf_bytes = download_document(url)
            encoded = base64.standard_b64encode(pdf_bytes).decode("ascii")
            label = doc.get("fileName") or doc.get("name") or "bank_statement.pdf"
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
                "title": f"[BANK_STATEMENT] {label}",
            })
            count += 1
        except Exception:
            pass
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


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


def _build_prompt(package: dict) -> str:
    data_block = _build_data_block(package)
    schema_str = json.dumps(_INSIGHT_SCHEMA, indent=2)
    return (
        f"Here is the deal data to analyse:\n\n{data_block}\n\n"
        "If bank statement PDFs are attached above, extract all transaction figures directly "
        "from them and populate every table field. Do not leave fields null if the data exists in the PDFs.\n\n"
        f"Return ONLY a JSON object conforming to this JSON Schema:\n\n{schema_str}"
    )


def _call_llm(pdf_blocks: list[dict], package: dict) -> BankDebtInsight:
    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.1,
        max_tokens=16000,
    )
    content: list = [*pdf_blocks, {"type": "text", "text": _build_prompt(package)}]
    messages = [
        SystemMessage(content=DEFAULT_BANK_DEBT_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]
    response = llm.invoke(messages)
    raw: str = response.content

    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]

    return BankDebtInsight.model_validate(json.loads(raw.strip()))


def generate_bank_debt_insight(req: BankDebtRequest) -> BankDebtInsight:
    package = fetch_deal_package(req.deal_id)
    documents = package.get("documents", []) or []
    pdf_blocks = _collect_pdf_blocks(documents)

    try:
        insight = _call_llm(pdf_blocks, package)
    except Exception as exc:
        push_bank_debt_summary(req.deal_id, {}, error_message=str(exc))
        raise

    push_bank_debt_summary(req.deal_id, insight.model_dump())
    return insight
