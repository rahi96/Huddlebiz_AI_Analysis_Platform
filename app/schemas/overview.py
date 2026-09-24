from pydantic import BaseModel, Field


class OverviewRequest(BaseModel):
    """Trigger cashflow overview AI analysis for a deal."""
    deal_id: str = Field(..., description="Backend deal UUID to fetch and analyse")
    session_id: str | None = Field(default=None, description="Attach insight to an existing chat session")


# ── AI-generated structured output ────────────────────────────────────────────

# Dashboard card values the AI derives from raw deal data
class RevenueKPIs(BaseModel):
    net_operating_cashflow_daily_avg_90d: float | None = Field(default=None, description="Net operating cashflow daily avg, last 90 days (USD)")
    revenue_sources_count_365d: int | None = Field(default=None, description="Distinct revenue sources, last 365 days")
    balance_average_90d: float | None = Field(default=None, description="Balance average, last 90 days (USD)")


class BalanceKPIs(BaseModel):
    balance_average_90d: float | None = Field(default=None, description="Balance average, last 90 days (USD)")
    predicted_balance_daily_avg_30d: float | None = Field(default=None, description="Predicted balance daily avg, next 30 days (USD)")
    negative_balance_days_90d: int | None = Field(default=None, description="Days with negative balance, last 90 days")
    nsf_days_90d: int | None = Field(default=None, description="NSF days, last 90 days")


class DebtKPIs(BaseModel):
    debt_investment_count_365d: int | None = Field(default=None, description="Active debt positions, last 365 days")
    debt_repayment_daily_avg_90d: float | None = Field(default=None, description="Debt repayment daily avg, last 90 days (USD)")
    # null renders as '--' in the UI when there is insufficient data
    debt_service_coverage_ratio_3m: float | None = Field(default=None, description="DSCR, last 3 calendar months; null = insufficient data")


class DataQualityKPIs(BaseModel):
    # stored 0-1; UI renders as percentage
    unconnected_account_ratio_365d: float | None = Field(default=None, description="Unconnected account ratio, last 365 days (0-1)")
    data_freshness_days: int | None = Field(default=None, description="Age of most recent data pull in days")
    # stored 0-1; UI renders as percentage
    confidence: float | None = Field(default=None, description="Overall data confidence score (0-1)")


class RiskFlag(BaseModel):
    area: str = Field(description="Dashboard section flagged: Revenue | Balance | Debt | Data Quality")
    issue: str = Field(description="One-line description of the risk")
    severity: str = Field(description="low | medium | high")


class Recommendation(BaseModel):
    title: str = Field(description="Short action title")
    detail: str = Field(description="Concrete next step the business owner can take")


class OverviewInsight(BaseModel):
    """Full AI output for the Overview tab: computed KPI values + narrative analysis."""
    # Computed dashboard card values (AI derives from backend deal data)
    revenue: RevenueKPIs = Field(default_factory=RevenueKPIs)
    balance: BalanceKPIs = Field(default_factory=BalanceKPIs)
    debt: DebtKPIs = Field(default_factory=DebtKPIs)
    data_quality: DataQualityKPIs = Field(default_factory=DataQualityKPIs)
    # Narrative analysis
    summary: str = Field(description="2-3 sentence executive summary of cashflow health")
    revenue_insight: str = Field(description="One paragraph interpreting the revenue KPIs")
    balance_insight: str = Field(description="One paragraph interpreting the balance KPIs")
    debt_insight: str = Field(description="One paragraph interpreting the debt KPIs")
    data_quality_note: str = Field(description="Comment on data reliability and impact on these insights")
    risks: list[RiskFlag] = Field(default_factory=list, description="Risk flags; empty list if none")
    recommendations: list[Recommendation] = Field(default_factory=list, description="2-4 prioritised action items")
    overall_health_score: int = Field(description="Cashflow health score 0-100")
    overall_health_label: str = Field(description="Poor | Fair | Good | Excellent")


class OverviewResponse(BaseModel):
    deal_id: str
    session_id: str | None = None
    model: str
    insight: OverviewInsight
