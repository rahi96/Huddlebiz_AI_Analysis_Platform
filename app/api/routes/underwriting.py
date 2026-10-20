import json

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.underwriting import UnderwritingRequest, UnderwritingResponse
from app.services.underwriting_service import generate_underwriting

router = APIRouter(prefix="/api", tags=["underwriting"])


@router.post("/underwriting", response_model=UnderwritingResponse)
def underwriting(request: UnderwritingRequest):
    try:
        insight = generate_underwriting(request)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI Underwriting request failed: {exc}") from exc

    return UnderwritingResponse(
        deal_id=request.deal_id,
        session_id=None,
        model=settings.claude_model,
        insight=insight,
    )
