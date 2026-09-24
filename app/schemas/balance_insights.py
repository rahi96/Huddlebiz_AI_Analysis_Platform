from pydantic import BaseModel, Field


class BalanceInsightsRequest(BaseModel):
    """Trigger Balance Insights AI analysis for a deal."""
    deal_id: str = Field(..., description="Backend deal UUID to fetch and analyse")
    low_balance_limit: float = Field(default=500, description="Threshold for low-balance-day counter (default $500)")
    session_id: str | None = Field(default=None)


# ── AI-generated structured output ────────────────────────────────────────────

class BalanceTimeseriesRow(BaseModel):
    """One row of the Monthly Cash Balance Timeseries table."""
    date: str | None = Field(default=None, description="YYYY-MM-DD")
    currency: str | None = Field(default="USD")
    daily_balance: float | None = Field(default=None)
    monthly_opening_balance: float | None = Field(default=None)
    monthly_closing_balance: float | None = Field(default=None)
    monthly_average_balance: float | None = Field(default=None)
    # Flags that drive row highlight colours in the UI
    is_zero_or_negative: bool = Field(default=False, description="Red row — balance ≤ 0")
    is_low_balance: bool = Field(default=False, description="Yellow row — balance between 0 and low_balance_limit")


class BalanceSummary(BaseModel):
    """Footer counters and threshold used for the timeseries table."""
    low_balance_limit: float | None = Field(default=500)
    number_zero_or_negative_balance_days: int | None = Field(default=None)
    number_low_balance_days: int | None = Field(default=None)
    highest_balance: float | None = Field(default=None)
    lowest_balance: float | None = Field(default=None)


class CashMovementRow(BaseModel):
    """One data point in the Monthly Cash Movement chart."""
    month: str | None = Field(default=None, description="YYYY-MM")
    inflows: float | None = Field(default=None)
    outflows: float | None = Field(default=None)
    net_change: float | None = Field(default=None, description="inflows − outflows")


class RiskFlag(BaseModel):
    area: str = Field(description="Which area is flagged, e.g. 'Balance Trend'")
    issue: str = Field(description="One-line description of the risk")
    severity: str = Field(description="low | medium | high")


class Recommendation(BaseModel):
    title: str
    detail: str


class BalanceInsightsInsight(BaseModel):
    """Full structured output returned by the AI for the Balance Insights tab."""
    # Panel 1 — Monthly Cash Balance Timeseries
    timeseries: list[BalanceTimeseriesRow] = Field(
        default_factory=list,
        description="One row per day (or per month if daily data unavailable)"
    )
    balance_summary: BalanceSummary = Field(default_factory=BalanceSummary)

    # Panel 2 — Monthly Cash Movement chart
    cash_movement: list[CashMovementRow] = Field(
        default_factory=list,
        description="Monthly inflows, outflows, net change"
    )

    # Narrative analysis
    summary: str = Field(description="2–3 sentence executive summary of balance health")
    balance_trend_insight: str = Field(description="Interpretation of the cash balance timeseries")
    cash_movement_insight: str = Field(description="Interpretation of inflows vs outflows trend")
    risks: list[RiskFlag] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    overall_health_score: int = Field(description="0–100 AI-estimated balance health score")
    overall_health_label: str = Field(description="Poor | Fair | Good | Excellent")
    data_source_note: str = Field(
        description="Note on whether balances came from bank statement PDFs or were modelled from financials"
    )


class BalanceInsightsResponse(BaseModel):
    deal_id: str
    session_id: str | None = None
    model: str
    insight: BalanceInsightsInsight
