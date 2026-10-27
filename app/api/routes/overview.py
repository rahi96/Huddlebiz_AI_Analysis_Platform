import json
import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.balance_insights import BalanceInsightsRequest
from app.schemas.bank_debt import BankDebtRequest
from app.schemas.lender_match import LenderMatchRequest
from app.schemas.overview import OverviewRequest, OverviewResponse
from app.schemas.profit_loss import ProfitLossRequest
from app.schemas.underwriting import UnderwritingRequest
from app.services.balance_insights_service import generate_balance_insights
from app.services.bank_debt_service import generate_bank_debt_insight
from app.services.lender_match_service import generate_lender_match
from app.services.overview_service import generate_overview_insight
from app.services.profit_loss_service import generate_profit_loss
from app.services.underwriting_service import generate_underwriting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["overview"])


# The backend auto-trigger calls only this endpoint, so it orchestrates the full
# analysis: every section pushes its own result to the backend. A failure in one
# section is logged but never blocks the others or the overview response.
def _run_section(name: str, fn, request) -> None:
    try:
        fn(request)
    except Exception as exc:
        logger.error("Section '%s' failed for deal %s: %s", name, request.deal_id, exc)


@router.post("/deals/{deal_id}", response_model=OverviewResponse)
def overview(deal_id: str):
    # Underwriting + lender match (Method A) and the other cashflow sections (Method B)
    _run_section("underwriting", generate_underwriting, UnderwritingRequest(deal_id=deal_id))
    _run_section("lender_match", generate_lender_match, LenderMatchRequest(deal_id=deal_id))
    _run_section("bank_debt", generate_bank_debt_insight, BankDebtRequest(deal_id=deal_id))
    _run_section("balance_insights", generate_balance_insights, BalanceInsightsRequest(deal_id=deal_id))
    _run_section("profit_loss", generate_profit_loss, ProfitLossRequest(deal_id=deal_id))

    # Overview runs last and its result is returned to the backend (it validates insight.overall_health_score)
    try:
        insight = generate_overview_insight(OverviewRequest(deal_id=deal_id))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Overview AI request failed: {exc}") from exc

    return OverviewResponse(
        deal_id=deal_id,
        session_id=None,
        model=settings.claude_model,
        insight=insight,
    )
