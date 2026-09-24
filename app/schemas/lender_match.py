from pydantic import BaseModel, Field


class LenderMatchRequest(BaseModel):
    """Trigger Lender Match AI analysis for a deal."""
    deal_id: str = Field(..., description="Backend deal UUID to fetch and analyse")
    session_id: str | None = Field(default=None)


# ── AI-generated structured output ────────────────────────────────────────────

class DealProfile(BaseModel):
    """The tag chips shown in the header bar below the KPI cards."""
    fico_score: int | None = Field(default=None)
    avg_monthly_revenue: float | None = Field(default=None)
    naics_code: str | None = Field(default=None)
    state: str | None = Field(default=None)
    time_in_business_years: float | None = Field(default=None)
    nsf_count_90d: int | None = Field(default=None)
    open_positions_count: int | None = Field(default=None)
    statements_extracted_count: int | None = Field(default=None, description="Number of bank statements in deal package")
    entity_type: str | None = Field(default=None)
    needs_verification: bool = Field(default=False, description="True when any critical field has low confidence")


class SummaryKpis(BaseModel):
    """The 4 top KPI cards."""
    eligible_count: int | None = Field(default=None, description="Lenders with status Eligible")
    total_lenders_evaluated: int | None = Field(default=None)
    needs_review_count: int | None = Field(default=None, description="Lenders with status Review")
    est_offer_max: float | None = Field(default=None, description="Highest est. offer across eligible lenders")
    est_offer_display: str | None = Field(default=None, description="Formatted display string, e.g. '$240K'")
    fastest_response_hours: int | None = Field(default=None, description="Fastest typical lender response time in hours")


class CriterionCheck(BaseModel):
    """One criterion row within a lender's eligibility check."""
    criterion: str = Field(description="e.g. 'FICO Score', 'Time in Business', 'NAICS Code'")
    required: str | None = Field(default=None, description="What the lender requires, e.g. '≥ 680'")
    actual: str | None = Field(default=None, description="Deal's actual value, e.g. '692'")
    passed: bool = Field(default=False)
    notes: str | None = Field(default=None, description="Extra context or reason for failure")


class LenderMatch(BaseModel):
    """One row in the lender match table."""
    lender_name: str = Field(description="e.g. 'SmartBiz Bank', 'Breakout Capital', 'Idea Financial'")
    program_name: str | None = Field(default=None, description="e.g. 'SBA Streamline', 'Breakout Prime'")
    criteria_met_count: int | None = Field(default=None)
    criteria_total_count: int | None = Field(default=None)
    criteria_summary: str | None = Field(default=None, description="e.g. '5 of 5 met' or '4 of 5 · positions'")
    criteria_details: list[CriterionCheck] = Field(default_factory=list)
    est_offer_min: float | None = Field(default=None)
    est_offer_max: float | None = Field(default=None)
    est_offer_display: str | None = Field(default=None, description="e.g. '$180–240K' or 'Pending'")
    status: str = Field(description="'Eligible' | 'Review' | 'Ineligible'")
    status_reason: str | None = Field(default=None, description="Short reason shown in status chip, e.g. 'NAICS excluded'")
    ineligibility_reasons: list[str] = Field(default_factory=list, description="Full list of hard-stop reasons")
    selected: bool = Field(default=False, description="Pre-checked in the UI for Eligible lenders")
    typical_response_hours: int | None = Field(default=None)


class RiskFlag(BaseModel):
    area: str
    issue: str
    severity: str = Field(description="low | medium | high")


class Recommendation(BaseModel):
    title: str
    detail: str


class LenderMatchInsight(BaseModel):
    """Full structured output for the Lender Match dashboard tab."""
    deal_profile: DealProfile = Field(default_factory=DealProfile)
    summary_kpis: SummaryKpis = Field(default_factory=SummaryKpis)
    lender_matches: list[LenderMatch] = Field(default_factory=list)

    # Narrative
    summary: str = Field(description="2–3 sentence executive summary of lender eligibility")
    match_insight: str = Field(description="Interpretation of why certain lenders matched or didn't")
    risks: list[RiskFlag] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    overall_match_score: int = Field(description="0–100 AI-estimated overall lender match quality")
    overall_match_label: str = Field(description="Poor | Fair | Good | Excellent")


class LenderMatchResponse(BaseModel):
    deal_id: str
    session_id: str | None = None
    model: str
    insight: LenderMatchInsight
