import json

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.profit_loss import ProfitLossRequest, ProfitLossResponse
from app.services.profit_loss_service import generate_profit_loss

router = APIRouter(prefix="/api", tags=["profit-loss"])


@router.post("/profit-loss", response_model=ProfitLossResponse)
def profit_loss(request: ProfitLossRequest):
    try:
        insight = generate_profit_loss(request)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Profit & Loss AI request failed: {exc}") from exc

    return ProfitLossResponse(
        deal_id=request.deal_id,
        session_id=None,
        model=settings.claude_model,
        insight=insight,
    )
