import os
os.environ.pop("DEBUG", None)

import sys
import time

DEAL_ID = "a65ef0c3-d1d5-4ab5-9431-dd786d6478db"

# Run: python _test_all_routes.py [a|b|all]  (default: all)
MODE = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
if MODE not in ("a", "b", "all"):
    print(f"Usage: python _test_all_routes.py [a|b|all]")
    sys.exit(1)


def run(label, fn, *args):
    print("\n" + "=" * 72)
    print(f"  {label}")
    print("=" * 72)
    for attempt in range(4):
        try:
            result = fn(*args)
            data = result.model_dump()
            print(f"  OK (attempt {attempt + 1})")
            print(f"  Top-level fields: {list(data.keys())}")
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

# ── METHOD A: PUT /underwriting-result ───────────────────────────────────────
# Services: underwriting, lender-match
if MODE in ("a", "all"):
    print("\n" + "#" * 72)
    print("  METHOD A  →  PUT /underwriting-result")
    print("#" * 72)

    from app.schemas.underwriting import UnderwritingRequest
    from app.services.underwriting_service import generate_underwriting
    results["underwriting"] = run("A1. UNDERWRITING", generate_underwriting, UnderwritingRequest(deal_id=DEAL_ID))

    from app.schemas.lender_match import LenderMatchRequest
    from app.services.lender_match_service import generate_lender_match
    results["lender-match"] = run("A2. LENDER MATCH", generate_lender_match, LenderMatchRequest(deal_id=DEAL_ID))

# ── METHOD B: PUT /cashflow-report ───────────────────────────────────────────
# Services: overview, bank-debt, balance-insights, profit-loss
if MODE in ("b", "all"):
    print("\n" + "#" * 72)
    print("  METHOD B  →  PUT /cashflow-report")
    print("#" * 72)

    from app.schemas.overview import OverviewRequest
    from app.services.overview_service import generate_overview_insight
    results["overview"] = run("B1. OVERVIEW", generate_overview_insight, OverviewRequest(deal_id=DEAL_ID))

    from app.schemas.bank_debt import BankDebtRequest
    from app.services.bank_debt_service import generate_bank_debt_insight
    results["bank-debt"] = run("B2. BANK & DEBT", generate_bank_debt_insight, BankDebtRequest(deal_id=DEAL_ID))

    from app.schemas.balance_insights import BalanceInsightsRequest
    from app.services.balance_insights_service import generate_balance_insights
    results["balance-insights"] = run("B3. BALANCE INSIGHTS", generate_balance_insights, BalanceInsightsRequest(deal_id=DEAL_ID))

    from app.schemas.profit_loss import ProfitLossRequest
    from app.services.profit_loss_service import generate_profit_loss
    results["profit-loss"] = run("B4. PROFIT & LOSS", generate_profit_loss, ProfitLossRequest(deal_id=DEAL_ID))

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print(f"  FINAL SUMMARY  (deal: {DEAL_ID}  mode: {MODE.upper()})")
print("=" * 72)
for name, ok in results.items():
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
