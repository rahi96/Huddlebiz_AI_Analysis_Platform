import json

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.lender_match import LenderMatchRequest, LenderMatchResponse
from app.services.lender_match_service import generate_lender_match

router = APIRouter(prefix="/api", tags=["lender-match"])


@router.post("/lender-match", response_model=LenderMatchResponse)
def lender_match(request: LenderMatchRequest):
    try:
        insight = generate_lender_match(request)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lender Match AI request failed: {exc}") from exc

    return LenderMatchResponse(
        deal_id=request.deal_id,
        session_id=None,
        model=settings.claude_model,
        insight=insight,
    )
