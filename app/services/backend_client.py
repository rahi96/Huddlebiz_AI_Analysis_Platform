"""HTTP client for the Huddlebiz Internal AI endpoints."""

from datetime import datetime, timezone

import httpx

from app.config import settings

_TIMEOUT = 30.0


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.ai_service_token}"}


def fetch_deal_package(deal_id: str) -> dict:
    """GET /api/v1/internal/ai/deals/{dealId}/package"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/package"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
    resp.raise_for_status()
    return resp.json()


def push_cashflow_overview(deal_id: str, overview: dict, error_message: str | None = None) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/cashflow-report  (overview section only)"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/cashflow-report"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "overview": overview,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()


def push_bank_debt_summary(deal_id: str, bank_debt: dict, error_message: str | None = None) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/cashflow-report  (bankDebtSummary section only)"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/cashflow-report"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "bankDebtSummary": bank_debt,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()


def download_document(download_url: str) -> bytes:
    """Fetch a document from its presigned URL (no auth header required)."""
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(download_url)
    resp.raise_for_status()
    return resp.content


def push_balance_insights(deal_id: str, balance_insights: dict, error_message: str | None = None) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/cashflow-report  (balanceInsights section only)"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/cashflow-report"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "balanceInsights": balance_insights,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()


def push_profit_loss(deal_id: str, profit_loss: dict, error_message: str | None = None) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/cashflow-report  (profitAndLoss section only)"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/cashflow-report"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "profitAndLoss": profit_loss,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()


def push_lender_match(deal_id: str, lender_match: dict, error_message: str | None = None) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/underwriting-result  (lender match result)"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/underwriting-result"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "lenderMatch": lender_match,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()


def push_underwriting_result(
    deal_id: str,
    confidence_score: float,
    risk_level: str,
    summary: str,
    rule_validation: list,
    extracted_data: dict,
    error_message: str | None = None,
) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/underwriting-result (full underwriting shape)"""
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/underwriting-result"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "confidenceScore": confidence_score,
        "riskLevel": risk_level,
        "summary": summary,
        "ruleValidation": rule_validation,
        "extractedData": extracted_data,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()
