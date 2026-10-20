import json

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.bank_debt import BankDebtRequest, BankDebtResponse
from app.services.bank_debt_service import generate_bank_debt_insight

router = APIRouter(prefix="/api", tags=["bank-debt"])


@router.post("/bank-debt", response_model=BankDebtResponse)
def bank_debt(request: BankDebtRequest):
    try:
        insight = generate_bank_debt_insight(request)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bank & Debt AI request failed: {exc}") from exc

    return BankDebtResponse(
        deal_id=request.deal_id,
        session_id=None,
        model=settings.claude_model,
        insight=insight,
    )
