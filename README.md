<<<<<<< HEAD
# Huddlebiz — AI Analysis Platform

A production-ready **Generative AI backend** built with **FastAPI**, **LangChain**, and **Anthropic Claude**. The platform powers the Huddlebiz Cashflow Reports dashboard by fetching deal data and financial documents from the Huddlebiz backend, running AI analysis using Claude (including native PDF parsing), and pushing structured insights back to be displayed in the UI.

The system handles six distinct analysis domains — each mapped to a dashboard tab — and a standalone AI underwriting module that reads all deal documents directly.

---

## Architecture Overview

```
Huddlebiz Admin UI
       │
       ▼
Huddlebiz Backend API  ◄──────────────────────────────────┐
  (deals, documents,                                       │
   cashflow reports)                                       │ PUT structured
       │                                                   │ JSON results
       │  GET /api/v1/internal/ai/deals/{id}/package       │
       ▼                                                   │
┌─────────────────────────────────────────────────────┐   │
│           Huddlebiz AI Platform  (this repo)        │   │
│                                                     │   │
│  POST /api/overview           → overview_service    │───┘
│  POST /api/bank-debt          → bank_debt_service   │
│  POST /api/balance-insights   → balance_insights_   │
│  POST /api/profit-loss        → profit_loss_service │
│  POST /api/lender-match       → lender_match_service│
│  POST /api/underwriting       → underwriting_service│
│                                                     │
│  Each service:                                      │
│    1. Fetches deal package from backend             │
│    2. Downloads PDFs (bank stmts, tax returns, etc) │
│    3. Sends to Claude as native document blocks     │
│    4. Validates structured JSON response            │
│    5. Pushes result back to backend                 │
└─────────────────────────────────────────────────────┘
```

---

## Tech Stack

- **Framework:** FastAPI
- **AI Orchestration:** LangChain
- **LLM Provider:** Anthropic Claude (text + vision)
- **Database:** SQLite (SQLAlchemy ORM)

## Project Structure

## Tech Stack

| Layer | Technology |
|---|---|
| **Web Framework** | FastAPI 0.115+ |
| **AI Orchestration** | LangChain 1.4+ with LangChain-Anthropic |
| **LLM** | Anthropic Claude (`claude-opus-4-5-20251101`) |
| **PDF Parsing** | Claude native document blocks (base64 PDF → direct reading) |
| **HTTP Client** | httpx (sync, for backend API calls + document downloads) |
| **Config** | pydantic-settings (env-file based) |
| **Runtime** | Python 3.14, Uvicorn with hot reload |

---

## Project Structure

```
c:\FS_Projects\Huddlebiz\
├── app/
│   ├── main.py                        # FastAPI app — CORS, lifespan, router registration
│   ├── config.py                      # All settings via pydantic-settings + .env
│   │
│   ├── api/routes/                    # FastAPI route handlers (thin — just call service + raise HTTP errors)
│   │   ├── health.py                  # GET /health
│   │   ├── overview.py                # POST /api/overview
│   │   ├── bank_debt.py               # POST /api/bank-debt
│   │   ├── balance_insights.py        # POST /api/balance-insights
│   │   ├── profit_loss.py             # POST /api/profit-loss
│   │   ├── lender_match.py            # POST /api/lender-match
│   │   └── underwriting.py            # POST /api/underwriting
│   │
│   ├── services/                      # Business logic layer
│   │   ├── backend_client.py          # All Huddlebiz backend API calls (fetch + push)
│   │   ├── llm_service.py             # get_chat_llm() — ChatAnthropic factory
│   │   ├── overview_service.py        # Cashflow overview AI analysis
│   │   ├── bank_debt_service.py       # Bank & debt summary AI analysis
│   │   ├── balance_insights_service.py# Balance timeseries + cash movement (PDF parsing)
│   │   ├── profit_loss_service.py     # P&L monthly table + forecast (PDF parsing)
│   │   ├── lender_match_service.py    # Lender eligibility against 3 credit boxes
│   │   └── underwriting_service.py    # Full document AI underwriting (all PDF types)
│   │
│   ├── schemas/                       # Pydantic request + response models
│   │   ├── overview.py
│   │   ├── bank_debt.py
│   │   ├── balance_insights.py
│   │   ├── profit_loss.py
│   │   ├── lender_match.py
│   │   └── underwriting.py
│   │
│   ├── prompts/
│   │   └── system_prompts.py          # All Claude system prompts (one per route)
│   │
│   └── utils/
│       └── logging.py                 # Log level setup
│
├── Backend_access/
│   ├── ai-platform-integration.md    # Full backend API contract (pull/push endpoints)
│   └── LENDER_UNDERWRITING_SPECS.md  # Credit boxes for SmartBiz, Breakout, Idea Financial
│
├── .env                               # Local secrets (gitignored)
├── .env.example                       # Template for env vars
├── requirements.txt
├── run.py                             # Uvicorn entrypoint
└── README.md
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```ini
# Anthropic / Claude
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-opus-4-5-20251101

# App
APP_ENV=development
DEBUG=true
HOST=0.0.0.0
PORT=8000

# Backend AI Integration
BACKEND_API_URL=https://huddlebiz-api.softvenceomegaforce.cloud
AI_SERVICE_TOKEN=<shared_secret_from_huddlebiz_backend>
```

The `AI_SERVICE_TOKEN` is the shared bearer token that authenticates this AI platform against the Huddlebiz internal API (`/api/v1/internal/ai/*` endpoints).

---

## Setup & Running

```powershell
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and AI_SERVICE_TOKEN

# 4. Start the server
python run.py
```

Server starts at **http://0.0.0.0:8000**

- **Interactive API docs:** http://localhost:8000/docs
- **OpenAPI JSON:** http://localhost:8000/openapi.json
- **Health check:** http://localhost:8000/health

---

## API Endpoints

All AI routes accept `{ "deal_id": "uuid" }` and follow the same internal flow.

### `GET /health`
Returns `{ "status": "ok" }`. Used for uptime checks.

---

### `POST /api/overview`
**Dashboard tab: Cashflow Overview**

Fetches deal financials from the backend, Claude computes all 4 KPI card sections, pushes result to `cashflow-report.overview`.

**Request:**
```json
{ "deal_id": "uuid" }
```

**AI output (`insight`):**
```json
{
  "revenue": {
    "net_operating_cashflow_daily_avg_90d": 65,
    "revenue_sources_count_365d": 1,
    "balance_average_90d": 45968
  },
  "balance": {
    "balance_average_90d": 45968,
    "predicted_balance_daily_avg_30d": 46609,
    "negative_balance_days_90d": 0,
    "nsf_days_90d": 0
  },
  "debt": {
    "debt_investment_count_365d": 0,
    "debt_repayment_daily_avg_90d": 0,
    "debt_service_coverage_ratio_3m": null
  },
  "data_quality": {
    "unconnected_account_ratio_365d": 0.12,
    "data_freshness_days": 1,
    "confidence": 0.91
  },
  "summary": "...",
  "risks": [...],
  "recommendations": [...],
  "overall_health_score": 72,
  "overall_health_label": "Good"
}
```

---

### `POST /api/bank-debt`
**Dashboard tab: Bank & Debt Summary**

Reads deal data, Claude computes 5 sections: transaction coverage, monthly bank statement table, debt positions, debt candidates, and recurring transactions.

**AI output sections:** `transaction_coverage`, `bank_statement_summary`, `debt_positions[]`, `debt_candidates[]`, `recurring_transactions[]`, narrative fields.

---

### `POST /api/balance-insights`
**Dashboard tab: Balance Insights**

Downloads bank statement PDFs and reads them natively. Claude builds the daily balance timeseries (Graph/Table view) and monthly cash movement chart (Inflows/Net Change/Outflows).

**Request:**
```json
{ "deal_id": "uuid", "low_balance_limit": 500 }
```

**AI output sections:** `timeseries[]` (with `is_zero_or_negative`, `is_low_balance` flags for row colours), `balance_summary`, `cash_movement[]`, narrative fields.

**PDF source:** `BANK_STATEMENT` documents from deal package.

---

### `POST /api/profit-loss`
**Dashboard tab: Profit & Loss**

Downloads bank statement + tax return PDFs. Claude builds 6 dashboard sections.

**AI output sections:**
- `monthly_summary[]` — revenue / expenses / net per month (drives top trend chart)
- `income_breakdown[]` — categorised income lines (Sales, Service, Other)
- `expense_breakdown[]` — categorised expense lines (Payroll, Rent, Utilities, Loan Repayment, Operating)
- `unique_transactions[]` — notable one-off large transactions (bar chart)
- `sales_forecast[]` — projected 3–6 months forward
- `top_vendors[]` / `top_customers[]` — counterparty table

**PDF source:** `BANK_STATEMENT` + `TAX_RETURN` documents.

---

### `POST /api/lender-match`
**Dashboard tab: Lender Match**

No PDF download needed. Claude cross-checks deal data against the full credit boxes of 3 integrated lenders (embedded in the system prompt from `LENDER_UNDERWRITING_SPECS.md`).

**Lenders evaluated:**
| Lender | Programs | FICO Min | TIB Min | Revenue Min |
|---|---|---|---|---|
| SmartBiz Bank | SBA Streamline ($50k–$150k) / SBA Traditional ($150k–$350k) | 680 / 660 | 3 yrs | — |
| Breakout Capital | Breakout Prime (up to $1M) / Breakout Waive (up to $250k) | 600 | 1 yr | $50k/mo |
| Idea Financial | Line of Credit / Term Loan | 650 | 3 yrs | $15k/mo |

**AI output sections:** `deal_profile` (tag chips), `summary_kpis` (4 KPI cards), `lender_matches[]` (table with per-criterion check, est. offer range, status: Eligible/Review/Ineligible).

---

### `POST /api/underwriting`
**Panel: AI Underwriting (deal detail page)**

Downloads **all** document types (bank statements, tax returns, ID documents, supporting docs). Claude reads every PDF and produces a full underwriting assessment.

**AI output:**
```json
{
  "confidence_score": 0.94,
  "confidence_display": "94%",
  "summary": "Johnson Supply Co. is a wholesale LLC with $1,250,000 in annual revenue...",
  "risk_level": "LOW - MEDIUM",
  "repayment_capacity": "STRONG",
  "document_completeness": 0.94,
  "document_completeness_display": "94%",
  "extracted_data": {
    "fico": { "value": 692, "confidence": 0.95, "source": "Credit Bureau" },
    "avg_monthly_revenue": { "value": 184000, "confidence": 0.98, "source": "Bank Statements" },
    "annual_revenue": { "value": 2208000, "confidence": 0.97, "source": "Tax Return" },
    "time_in_business_years": { "value": 4, "confidence": 0.9, "source": "Application" },
    "nsfs_90d": { "value": 3, "confidence": 0.85, "source": "Bank Statements" },
    "open_positions": { "value": 2, "confidence": 0.7, "source": "Bank Statements" },
    "dscr": { "value": 1.3, "confidence": 0.75, "source": "Calculated" }
  },
  "rule_validation": [
    { "rule": "Bank statements present", "passed": true },
    { "rule": "Minimum 3 months bank statements", "passed": true },
    { "rule": "FICO above 600", "passed": true },
    { "rule": "Positive monthly cashflow", "passed": true }
  ],
  "documents_analysed": ["bank_stmt_apr.pdf", "bank_stmt_may.pdf", "tax_return_2025.pdf"],
  "missing_documents": []
}
```

**PDF source:** ALL document types (`BANK_STATEMENT`, `TAX_RETURN`, `ID_DOCUMENT`, `SUPPORTING`).

---

## Backend Integration

All AI routes use two backend API calls:

### Pull — Fetch Deal Package
```
GET /api/v1/internal/ai/deals/{dealId}/package
Authorization: Bearer <AI_SERVICE_TOKEN>
```
Returns: company, financials, loan, owners, documents (with presigned download URLs).

### Push — Write Results Back
```
PUT /api/v1/internal/ai/deals/{dealId}/cashflow-report
PUT /api/v1/internal/ai/deals/{dealId}/underwriting-result
Authorization: Bearer <AI_SERVICE_TOKEN>
```

Each route pushes to its corresponding section:
| Route | Backend field pushed |
|---|---|
| `/api/overview` | `cashflow-report.overview` |
| `/api/bank-debt` | `cashflow-report.bankDebtSummary` |
| `/api/balance-insights` | `cashflow-report.balanceInsights` |
| `/api/profit-loss` | `cashflow-report.profitAndLoss` |
| `/api/lender-match` | `underwriting-result.lenderMatch` |
| `/api/underwriting` | `underwriting-result` (full shape) |

---

## How PDF Parsing Works

Services that need document data download PDFs from their presigned URLs and encode them as base64. These are passed to Claude as native `document` content blocks:

```python
{
    "type": "document",
    "source": {
        "type": "base64",
        "media_type": "application/pdf",
        "data": "<base64_encoded_pdf>"
    },
    "title": "[BANK_STATEMENT] apr_2026.pdf",
    "cache_control": {"type": "ephemeral"}
}
```

Claude reads the PDF pages directly — no OCR library required. If a document download fails, the service silently skips it and Claude falls back to estimating from the deal financials.

---

## Error Handling

All routes return consistent HTTP errors:

| Code | Cause |
|---|---|
| `502` | LLM call failed, backend API unreachable, or Claude returned malformed JSON |
| `422` | Invalid request body (Pydantic validation) |

On LLM failure, the service also pushes `status: FAILED` + `errorMessage` to the backend so the UI can display an error state.

---

## Development

```powershell
# Run with hot reload (default when DEBUG=true)
python run.py

# Run tests
.venv\Scripts\python.exe -m pytest tests/ -v

# Verify all routes registered
.venv\Scripts\python.exe -c "from app.main import app; print(list(app.openapi()['paths'].keys()))"
```
=======
# Huddlebiz_AI_Analysis_Platform
The system handles six distinct analysis domains — each mapped to a dashboard tab — and a standalone AI underwriting module that reads all deal documents directly.
>>>>>>> 3bac24fd5924aff2ff0d378a5fd7a701f2596e79
