import json

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.overview import OverviewRequest, OverviewResponse
from app.services.overview_service import generate_overview_insight

router = APIRouter(prefix="/api", tags=["overview"])


@router.post("/deals/{deal_id}", response_model=OverviewResponse)
def overview(deal_id: str):
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
