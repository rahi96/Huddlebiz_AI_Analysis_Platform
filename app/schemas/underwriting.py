from pydantic import BaseModel, Field


class UnderwritingRequest(BaseModel):
    """Trigger AI Underwriting analysis — reads all deal PDFs."""
    deal_id: str = Field(..., description="Backend deal UUID to fetch and analyse")
    session_id: str | None = Field(default=None)


# ── Extracted data fields (matches the backend extractedData schema exactly) ──

class ExtractedField(BaseModel):
    """A single extracted metric with confidence and source attribution."""
    value: float | int | str | None = Field(default=None)
    confidence: float | None = Field(default=None, description="0–1 extraction confidence")
    source: str | None = Field(default=None, description="e.g. 'Bank Statements', 'Tax Return', 'Application'")


class ExtractedData(BaseModel):
    """Mirrors the backend extractedData shape exactly for lender-match compatibility."""
    fico: ExtractedField = Field(default_factory=ExtractedField)
    avg_monthly_revenue: ExtractedField = Field(default_factory=ExtractedField)
    annual_revenue: ExtractedField = Field(default_factory=ExtractedField)
    time_in_business_years: ExtractedField = Field(default_factory=ExtractedField)
    nsfs_90d: ExtractedField = Field(default_factory=ExtractedField)
    open_positions: ExtractedField = Field(default_factory=ExtractedField)
    naics_code: ExtractedField = Field(default_factory=ExtractedField)
    state: ExtractedField = Field(default_factory=ExtractedField)
    bank_statement_count: ExtractedField = Field(default_factory=ExtractedField)
    average_daily_balance: ExtractedField = Field(default_factory=ExtractedField)
    monthly_expenses: ExtractedField = Field(default_factory=ExtractedField)
    existing_debt: ExtractedField = Field(default_factory=ExtractedField)
    dscr: ExtractedField = Field(default_factory=ExtractedField, description="Debt Service Coverage Ratio")


# ── Rule validation checklist ──────────────────────────────────────────────────

class RuleValidation(BaseModel):
    rule: str = Field(description="e.g. 'Bank statements present', 'FICO above 600'")
    passed: bool
    notes: str | None = Field(default=None)


# ── AI-generated dashboard fields (the 3 KPI rows in the UI) ──────────────────

class UnderwritingInsight(BaseModel):
    """Structured output for the AI Underwriting panel."""

    # Top KPI — Overall Confidence bar
    confidence_score: float = Field(description="0–1 overall confidence; e.g. 0.94 = 94%")
    confidence_display: str = Field(description="Formatted display string e.g. '94%'")

    # AI Summary paragraph
    summary: str = Field(description="Underwriter-facing narrative paragraph about the business")

    # Three KPI row values shown in the panel
    risk_level: str = Field(description="e.g. 'LOW', 'LOW - MEDIUM', 'MEDIUM', 'HIGH'")
    repayment_capacity: str = Field(description="e.g. 'STRONG', 'MODERATE', 'WEAK'")
    document_completeness: float = Field(description="0–1 score; e.g. 0.94 = 94%")
    document_completeness_display: str = Field(description="Formatted display string e.g. '94%'")

    # Extracted data fields (used by lender-match downstream)
    extracted_data: ExtractedData = Field(default_factory=ExtractedData)

    # Rule validation checklist
    rule_validation: list[RuleValidation] = Field(default_factory=list)

    # Documents found
    documents_analysed: list[str] = Field(
        default_factory=list,
        description="List of document file names that were read"
    )
    missing_documents: list[str] = Field(
        default_factory=list,
        description="Documents expected but not present (e.g. 'Tax Return', '3rd Bank Statement')"
    )


class UnderwritingResponse(BaseModel):
    deal_id: str
    session_id: str | None = None
    model: str
    insight: UnderwritingInsight
