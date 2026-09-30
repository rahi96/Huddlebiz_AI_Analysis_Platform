import os
os.environ.pop("DEBUG", None)
os.environ["WEBHOOK_URL"] = "http://localhost:9000/webhook"
os.environ["WEBHOOK_TOKEN"] = "test-secret-123"

import time
from app.schemas.overview import OverviewRequest
from app.services.overview_service import generate_overview_insight

DEAL_ID = "bef6d654-f25e-4e39-8f05-16606d2b6ad9"

print("Triggering overview route -> should fire webhook after backend PUT...")
for attempt in range(4):
    try:
        insight = generate_overview_insight(OverviewRequest(deal_id=DEAL_ID))
        print(f"Route succeeded (attempt {attempt + 1}) — health {insight.overall_health_score}")
        break
    except Exception as e:
        print(f"  attempt {attempt + 1}: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(3)

# give the webhook a moment to arrive
time.sleep(1)
print("Done — check the receiver terminal for the webhook payload.")
