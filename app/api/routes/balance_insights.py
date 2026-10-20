import json

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.balance_insights import BalanceInsightsRequest, BalanceInsightsResponse
from app.services.balance_insights_service import generate_balance_insights

router = APIRouter(prefix="/api", tags=["balance-insights"])


@router.post("/balance-insights", response_model=BalanceInsightsResponse)
def balance_insights(request: BalanceInsightsRequest):
    try:
        insight = generate_balance_insights(request)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Balance Insights AI request failed: {exc}") from exc

    return BalanceInsightsResponse(
        deal_id=request.deal_id,
        session_id=None,
        model=settings.claude_model,
        insight=insight,
    )
