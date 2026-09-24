from pydantic import BaseModel, Field


class BankDebtRequest(BaseModel):
    """Trigger Bank & Debt Summary AI analysis for a deal."""
    deal_id: str = Field(..., description="Backend deal UUID to fetch and analyse")
    session_id: str | None = Field(default=None)


# ── AI-generated structured output ────────────────────────────────────────────

# ---- Transaction Coverage bar chart ----------------------------------------

class TransactionCoverage(BaseModel):
    """Mirrors the Transaction Data Coverage bar at the top of the tab."""
    months_covered: int | None = Field(default=None, description="Number of months of bank data available")
    pdf_pct: float | None = Field(default=None, description="Share of coverage from PDF statements (0-1)")
    api_pct: float | None = Field(default=None, description="Share of coverage from API/live feed (0-1)")
    missing_data_pct: float | None = Field(default=None, description="Share of time with missing data (0-1)")
    transactions_reconciled: int | None = Field(default=None, description="Count of reconciled transactions")
    transactions_unreconciled: int | None = Field(default=None, description="Count of unreconciled transactions")


# ---- Bank Statement Summary monthly table ----------------------------------

class BankStatementRow(BaseModel):
    """One row of the Bank Statement Summary table (monthly or totals/average)."""
    month: str | None = Field(default=None, description="YYYY-MM or 'TOTAL' or 'Average'")
    starting_balance: float | None = Field(default=None)
    num_deposits: int | None = Field(default=None, description="# Deposits")
    total_deposits: float | None = Field(default=None)
    true_revenue: float | None = Field(default=None)
    num_true_rev_deposits: int | None = Field(default=None, description="# True Rev Deposits")
    non_revenue: float | None = Field(default=None, description="Non-revenue deposit amount")
    num_withdrawals: int | None = Field(default=None, description="# Withdrawals")
    total_withdrawals: float | None = Field(default=None)
    mca_debits: float | None = Field(default=None)
    holdings: float | None = Field(default=None, description="End-of-period holdings / closing balance")


class BankStatementSummary(BaseModel):
    monthly_rows: list[BankStatementRow] = Field(default_factory=list)
    total_row: BankStatementRow | None = Field(default=None)
    average_row: BankStatementRow | None = Field(default=None)


# ---- Debt Positions --------------------------------------------------------

class DebtPosition(BaseModel):
    """One row in the Debt Positions or Debt Candidates table."""
    merchant_counterparty: str | None = Field(default=None)
    group: str | None = Field(default=None)
    first_transaction_date: str | None = Field(default=None, description="ISO date string")
    last_transaction_date: str | None = Field(default=None, description="ISO date string")
    active: bool | None = Field(default=None)
    count: int | None = Field(default=None)
    total_amount: float | None = Field(default=None)
    avg_amount: float | None = Field(default=None)
    frequency: str | None = Field(default=None, description="e.g. weekly, monthly")
    estimated_monthly_amount: float | None = Field(default=None)


# ---- Recurring Transactions ------------------------------------------------

class RecurringTransaction(BaseModel):
    """One row in the Recurring Transactions table."""
    merchant_counterparty: str | None = Field(default=None)
    avg_amount: float | None = Field(default=None)
    frequency: str | None = Field(default=None, description="e.g. weekly, weekday, monthly")
    # 0-1 stored; UI renders as percentage
    avg_confidence: float | None = Field(default=None)
    categories: list[str] = Field(default_factory=list, description="e.g. ['Debt Repayment', 'Revenue']")
    mark_as: list[str] = Field(default_factory=list, description="e.g. ['MCA Debt', 'Debt']")


# ---- Top-level AI insight --------------------------------------------------

class RiskFlag(BaseModel):
    area: str = Field(description="Section flagged: Bank | Debt | Recurring | Coverage")
    issue: str = Field(description="One-line description of the risk")
    severity: str = Field(description="low | medium | high")


class Recommendation(BaseModel):
    title: str = Field(description="Short action title")
    detail: str = Field(description="Concrete next step")


class BankDebtInsight(BaseModel):
    """Full AI output for the Bank & Debt Summary tab."""
    # Computed dashboard sections
    transaction_coverage: TransactionCoverage = Field(default_factory=TransactionCoverage)
    bank_statement_summary: BankStatementSummary = Field(default_factory=BankStatementSummary)
    debt_positions: list[DebtPosition] = Field(default_factory=list)
    debt_candidates: list[DebtPosition] = Field(default_factory=list)
    recurring_transactions: list[RecurringTransaction] = Field(default_factory=list)
    # Narrative analysis
    summary: str = Field(description="2-3 sentence executive summary of bank and debt health")
    bank_insight: str = Field(description="One paragraph on deposit/withdrawal patterns")
    debt_insight: str = Field(description="One paragraph on debt positions and MCA exposure")
    risks: list[RiskFlag] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list, description="2-4 prioritised action items")
    overall_health_score: int = Field(description="Bank & debt health score 0-100")
    overall_health_label: str = Field(description="Poor | Fair | Good | Excellent")


class BankDebtResponse(BaseModel):
    deal_id: str
    session_id: str | None = None
    model: str
    insight: BankDebtInsight
