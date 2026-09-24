from pydantic import BaseModel, Field


class ProfitLossRequest(BaseModel):
    """Trigger Profit & Loss AI analysis for a deal."""
    deal_id: str = Field(..., description="Backend deal UUID to fetch and analyse")
    session_id: str | None = Field(default=None)


# ── AI-generated structured output ────────────────────────────────────────────

class MonthlySummaryRow(BaseModel):
    """One row of the Monthly Cash Summary P&L table (top-level)."""
    month: str | None = Field(default=None, description="YYYY-MM")
    gross_revenue: float | None = Field(default=None)
    total_expenses: float | None = Field(default=None)
    net_profit_loss: float | None = Field(default=None)
    profit_margin_pct: float | None = Field(default=None, description="net_profit_loss / gross_revenue, 0-1")
    is_loss: bool = Field(default=False, description="true when net_profit_loss < 0")


class CategoryMonthAmount(BaseModel):
    """Amount for a single category in a single month."""
    month: str | None = Field(default=None, description="YYYY-MM")
    amount: float | None = Field(default=None)


class IncomeBreakdownLine(BaseModel):
    """One income category row across all months."""
    category: str = Field(description="e.g. 'Sales Revenue', 'Service Income', 'Other Income'")
    monthly: list[CategoryMonthAmount] = Field(default_factory=list)
    total: float | None = Field(default=None)


class ExpenseBreakdownLine(BaseModel):
    """One expense category row across all months."""
    category: str = Field(description="e.g. 'Payroll', 'Rent', 'Utilities', 'Loan Repayment', 'Operating Costs'")
    monthly: list[CategoryMonthAmount] = Field(default_factory=list)
    total: float | None = Field(default=None)


class UniqueTransaction(BaseModel):
    """Notable one-off large transaction (bar chart data + table)."""
    date: str | None = Field(default=None, description="YYYY-MM-DD")
    description: str | None = Field(default=None)
    amount: float | None = Field(default=None)
    type: str | None = Field(default=None, description="'income' | 'expense'")
    category: str | None = Field(default=None)


class SalesForecastRow(BaseModel):
    """One month of projected forward P&L (sales forecast chart)."""
    month: str | None = Field(default=None, description="YYYY-MM")
    projected_revenue: float | None = Field(default=None)
    projected_expenses: float | None = Field(default=None)
    projected_net: float | None = Field(default=None)
    is_forecast: bool = Field(default=True)


class CounterpartyRow(BaseModel):
    """One row in the top vendors / top customers table."""
    name: str | None = Field(default=None)
    total_amount: float | None = Field(default=None)
    transaction_count: int | None = Field(default=None)
    type: str | None = Field(default=None, description="'vendor' | 'customer'")


class RiskFlag(BaseModel):
    area: str
    issue: str
    severity: str = Field(description="low | medium | high")


class Recommendation(BaseModel):
    title: str
    detail: str


class ProfitLossInsight(BaseModel):
    """Full structured output returned by the AI for the Profit & Loss tab."""

    # Section 1 — top trend chart + main table
    monthly_summary: list[MonthlySummaryRow] = Field(
        default_factory=list,
        description="One row per month; drives the top revenue/expenses/net line chart"
    )

    # Section 2 — income breakdown (sub-rows of the Monthly Cash Summary)
    income_breakdown: list[IncomeBreakdownLine] = Field(
        default_factory=list,
        description="Categorised income lines across all months"
    )

    # Section 3 — expense breakdown
    expense_breakdown: list[ExpenseBreakdownLine] = Field(
        default_factory=list,
        description="Categorised expense lines across all months"
    )

    # Section 4 — unique / one-off large transactions bar chart
    unique_transactions: list[UniqueTransaction] = Field(
        default_factory=list,
        description="Notable non-recurring transactions"
    )

    # Section 5 — sales forecast
    sales_forecast: list[SalesForecastRow] = Field(
        default_factory=list,
        description="Projected P&L for next 3–6 months"
    )

    # Section 6 — top vendors and customers table
    top_vendors: list[CounterpartyRow] = Field(default_factory=list)
    top_customers: list[CounterpartyRow] = Field(default_factory=list)

    # Narrative
    summary: str = Field(description="2–3 sentence executive summary of P&L health")
    income_insight: str = Field(description="Interpretation of income trends and sources")
    expense_insight: str = Field(description="Interpretation of expense structure and trends")
    forecast_insight: str = Field(description="Commentary on the sales forecast and trajectory")
    risks: list[RiskFlag] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    overall_health_score: int = Field(description="0–100 AI-estimated P&L health score")
    overall_health_label: str = Field(description="Poor | Fair | Good | Excellent")
    data_source_note: str = Field(
        description="Whether data came from bank statement PDFs, tax returns, or was modelled from financials"
    )


class ProfitLossResponse(BaseModel):
    deal_id: str
    session_id: str | None = None
    model: str
    insight: ProfitLossInsight
