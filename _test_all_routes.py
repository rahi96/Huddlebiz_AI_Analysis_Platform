import os
os.environ.pop("DEBUG", None)

import json
import time
import traceback

DEAL_ID = "bef6d654-f25e-4e39-8f05-16606d2b6ad9"


def run(label, fn, *args):
    print("\n" + "=" * 72)
    print(f"  {label}")
    print("=" * 72)
    for attempt in range(4):
        try:
            result = fn(*args)
            data = result.model_dump()
            print(f"  OK (attempt {attempt + 1})")
            # Print a compact summary + a few key fields
            keys = list(data.keys())
            print(f"  Top-level fields: {keys}")
            for probe in ("summary", "overall_health_score", "overall_health_label",
                          "overall_match_score", "overall_match_label",
                          "confidence_score", "risk_level", "repayment_capacity"):
                if probe in data:
                    val = data[probe]
                    if isinstance(val, str) and len(val) > 100:
                        val = val[:100] + "..."
                    print(f"    {probe}: {val}")
            return True
        except Exception as e:
            print(f"  attempt {attempt + 1}: {type(e).__name__}: {str(e)[:160]}")
            time.sleep(3)
    print("  >>> FAILED after retries")
    return False


results = {}

from app.schemas.overview import OverviewRequest
from app.services.overview_service import generate_overview_insight
results["overview"] = run("1. OVERVIEW", generate_overview_insight, OverviewRequest(deal_id=DEAL_ID))

from app.schemas.bank_debt import BankDebtRequest
from app.services.bank_debt_service import generate_bank_debt_insight
results["bank-debt"] = run("2. BANK & DEBT", generate_bank_debt_insight, BankDebtRequest(deal_id=DEAL_ID))

from app.schemas.balance_insights import BalanceInsightsRequest
from app.services.balance_insights_service import generate_balance_insights
results["balance-insights"] = run("3. BALANCE INSIGHTS", generate_balance_insights, BalanceInsightsRequest(deal_id=DEAL_ID))

from app.schemas.profit_loss import ProfitLossRequest
from app.services.profit_loss_service import generate_profit_loss
results["profit-loss"] = run("4. PROFIT & LOSS", generate_profit_loss, ProfitLossRequest(deal_id=DEAL_ID))

from app.schemas.lender_match import LenderMatchRequest
from app.services.lender_match_service import generate_lender_match
results["lender-match"] = run("5. LENDER MATCH", generate_lender_match, LenderMatchRequest(deal_id=DEAL_ID))

from app.schemas.underwriting import UnderwritingRequest
from app.services.underwriting_service import generate_underwriting
results["underwriting"] = run("6. UNDERWRITING", generate_underwriting, UnderwritingRequest(deal_id=DEAL_ID))

print("\n" + "=" * 72)
print("  FINAL SUMMARY")
print("=" * 72)
for name, ok in results.items():
    print(f"  {'PASS' if ok else 'FAIL'}  /api/{name}")
