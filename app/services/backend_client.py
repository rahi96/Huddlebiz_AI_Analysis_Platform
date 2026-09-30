"""HTTP client for the Huddlebiz Internal AI endpoints."""

import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

_TIMEOUT = 30.0

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.ai_service_token}"}


def notify_webhook(deal_id: str, section: str, status: str) -> None:
    """POST a completion event to the configured webhook. No-op if unset.

    Failures are logged but never raised — the AI result is already saved.
    """
    if not settings.webhook_url:
        return

    payload = {
        "event": "ai.section.completed",
        "deal_id": deal_id,
        "section": section,
        "status": status,
        "message": f"{section} {status.lower()} for deal {deal_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    headers = {"Content-Type": "application/json"}
    if settings.webhook_token:
        headers["Authorization"] = f"Bearer {settings.webhook_token}"

    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(settings.webhook_url, json=payload, headers=headers)
    except Exception as exc:
        logger.warning("Webhook notify failed for deal %s: %s", deal_id, exc)


def fetch_deal_package(deal_id: str) -> dict:
    """GET /api/v1/internal/ai/deals/{dealId}/package

    The backend wraps payloads in {success, statusCode, data}; return the inner
    `data` object so callers work with the deal fields directly.
    """
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/package"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", body) if isinstance(body, dict) else body


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
    notify_webhook(deal_id, "overview", body["status"])


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
    notify_webhook(deal_id, "bankDebtSummary", body["status"])


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
    notify_webhook(deal_id, "balanceInsights", body["status"])


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
    notify_webhook(deal_id, "profitAndLoss", body["status"])


def push_lender_match(deal_id: str, lender_match: dict, error_message: str | None = None) -> None:
    """PUT /api/v1/internal/ai/deals/{dealId}/underwriting-result  (lender match result)

    The backend DTO has no dedicated lenderMatch field, so the result is stored
    under `rawResponse` (which accepts arbitrary JSON).
    """
    url = f"{settings.backend_api_url}/api/v1/internal/ai/deals/{deal_id}/underwriting-result"
    body: dict = {
        "status": "FAILED" if error_message else "READY",
        "rawResponse": {"lenderMatch": lender_match},
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        body["errorMessage"] = error_message

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, json=body, headers=_headers())
    resp.raise_for_status()
    notify_webhook(deal_id, "lenderMatch", body["status"])


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
    notify_webhook(deal_id, "underwritingResult", body["status"])
