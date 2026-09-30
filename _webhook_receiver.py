"""Local webhook receiver for testing the outgoing AI completion webhook.

Run:  .venv\\Scripts\\python.exe _webhook_receiver.py
Then set in .env:
    WEBHOOK_URL=http://localhost:9000/webhook
    WEBHOOK_TOKEN=test-secret-123
"""

import json
from datetime import datetime

from fastapi import FastAPI, Header, Request
import uvicorn

EXPECTED_TOKEN = "test-secret-123"

app = FastAPI(title="Webhook Receiver")


@app.post("/webhook")
async def receive(request: Request, authorization: str | None = Header(default=None)):
    body = await request.json()
    print("\n" + "=" * 60)
    print(f"  WEBHOOK RECEIVED  @ {datetime.now().isoformat()}")
    print("=" * 60)
    print("  Authorization:", authorization)
    print("  Token valid:  ", authorization == f"Bearer {EXPECTED_TOKEN}")
    print("  Payload:")
    print(json.dumps(body, indent=4))
    print("=" * 60)
    return {"received": True}


if __name__ == "__main__":
    print("Webhook receiver listening on http://localhost:9000/webhook")
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")
