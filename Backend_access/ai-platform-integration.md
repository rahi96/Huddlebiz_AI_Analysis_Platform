# AI Platform Integration Contract (B + A Hybrid)

HuddleBiz owns storage, UI, and rule-based lender matching.  
The **AI platform** (separate team) owns extraction and analysis.

**One-line brief for the AI developer:**

> Pull documents and deal data from our API, POST structured JSON results back; we store and display what you send.

Browser clients never call the AI platform. Admin UI only talks to HuddleBiz.

---

## Architecture

```text
Admin uploads docs / lender guideline PDF
        ↓
HuddleBiz stores files (S3/MinIO) + deal rows (Postgres)
        ↓
Admin clicks "Run underwriting" / "Extract guidelines"
        ↓
HuddleBiz sets status PENDING and notifies AI (job trigger)
        ↓
AI GETs deal + presigned document URLs from HuddleBiz
        ↓
AI computes on its platform
        ↓
AI POSTs results to HuddleBiz ingest endpoints
        ↓
HuddleBiz upserts UnderwritingResult / CashflowReport / Lender.criteria
        ↓
Status → READY | FAILED
        ↓
Admin UI reads HuddleBiz only
```

Lender **eligibility** stays rule-based in HuddleBiz (`GET .../lender-match`) using:

- Deal metrics from `UnderwritingResult.extractedData`
- Lender credit box from `Lender.criteria` JSON

AI fills those inputs; it does not own the match UI.

---

## Auth (to implement)

Use a **service credential**, not an admin browser session:

| Header                                     | Purpose                           |
| ------------------------------------------ | --------------------------------- |
| `Authorization: Bearer <AI_SERVICE_TOKEN>` | AI platform → HuddleBiz pull/push |
| Optional: `X-Job-Id`                       | Correlate trigger → ingest        |

Env (HuddleBiz): `AI_SERVICE_TOKEN` (shared secret or rotating key).  
Env (AI platform): same token + `HUDDLEBIZ_API_BASE_URL`.

Do **not** expose ingest routes to `CUSTOMER` / `PARTNER` JWTs.

---

## Status model

| Entity                         | Statuses                                   | Meaning                          |
| ------------------------------ | ------------------------------------------ | -------------------------------- |
| `UnderwritingResult.status`    | `PENDING` → `READY` \| `FAILED` \| `STALE` | Deal AI underwriting job         |
| `CashflowReport.status`        | `PENDING` → `READY` \| `FAILED`            | Cashflow sections for UI         |
| `Lender.guidelinesExtractedAt` | timestamp or null                          | Last guidelines/criteria refresh |

When admin re-uploads docs after `NEEDS_MORE_INFO`, existing underwriting is marked **STALE** (already implemented).

---

## 1. Trigger (HuddleBiz → AI)

### Deal underwriting

- Admin: `POST /api/v1/admin/deals/:dealId/trigger-ai-underwriting`
- Sets `UnderwritingResult` + `CashflowReport` to `PENDING`
- If `AI_WEBHOOK_URL` is set: notifies AI and returns `{ mode: "ai_platform", status: "PENDING" }`
- If unset: runs in-process **mock** analysis (local/dev fallback)

**Notify payload:**

```json
{
  "jobType": "DEAL_UNDERWRITING",
  "jobId": "uuid",
  "dealId": "uuid",
  "triggeredAt": "2026-09-08T12:00:00.000Z"
}
```

### Lender guidelines extraction

- Admin uploads PDF: `POST /api/v1/admin/lenders/:id/guidelines` (stores PDF)
- If `AI_WEBHOOK_URL` is set: notifies AI with `LENDER_GUIDELINES` job
- Until AI posts criteria: admin may `PATCH /api/v1/admin/lenders/:id/criteria` manually

```json
{
  "jobType": "LENDER_GUIDELINES",
  "jobId": "uuid",
  "lenderId": "uuid",
  "guidelinePdfKey": "users/.../file.pdf",
  "triggeredAt": "2026-09-08T12:00:00.000Z"
}
```

---

## 2. Pull APIs (AI → HuddleBiz)

Auth: `Authorization: Bearer <AI_SERVICE_TOKEN>`

### Get deal package for underwriting

`GET /api/v1/internal/ai/deals/:dealId/package`

Returns:

```json
{
  "dealId": "uuid",
  "status": "IN_REVIEW",
  "company": {
    "legalName": "string",
    "entityType": "string",
    "naicsCode": "string|null",
    "industry": "string|null",
    "state": "string|null",
    "addressLine1": "string"
  },
  "loan": {
    "requestedAmount": "number",
    "useOfFunds": "string",
    "product": "string|null"
  },
  "financials": {
    "annualRevenue": "number|null",
    "creditScore": "number|null",
    "timeInBusinessYears": "number|null",
    "existingDebt": "number|null"
  },
  "owners": [
    {
      "legalName": "string",
      "ownershipPercent": "number",
      "title": "string"
    }
  ],
  "documents": [
    {
      "id": "uuid",
      "type": "BANK_STATEMENT|TAX_RETURN|ID_DOCUMENT|SUPPORTING",
      "fileName": "string",
      "mimeType": "string",
      "downloadUrl": "https://presigned...",
      "expiresInSeconds": 3600
    }
  ]
}
```

### Get lender guideline PDF

`GET /api/v1/internal/ai/lenders/:lenderId/guidelines`

```json
{
  "lenderId": "uuid",
  "name": "SmartBiz Bank (SBA)",
  "guidelinePdfName": "smartbiz.pdf",
  "downloadUrl": "https://presigned...",
  "currentCriteria": {}
}
```

Credit-box field names: see [`LENDER_UNDERWRITING_SPECS.md`](./LENDER_UNDERWRITING_SPECS.md).

---

## 3. Push APIs (AI → HuddleBiz)

Auth: `Authorization: Bearer <AI_SERVICE_TOKEN>`. Idempotent upserts by `dealId` / `lenderId`.

### A) Underwriting result

`PUT /api/v1/internal/ai/deals/:dealId/underwriting-result`

```json
{
  "status": "READY",
  "confidenceScore": 0.91,
  "riskLevel": "LOW - MEDIUM",
  "summary": "Short underwriter-facing summary",
  "ruleValidation": [{ "rule": "Bank statements present", "passed": true }],
  "extractedData": {
    "fico": { "value": 680, "confidence": 0.95, "source": "Credit Bureau" },
    "avgMonthlyRevenue": {
      "value": 85000,
      "confidence": 0.98,
      "source": "Bank Stmt Avg"
    },
    "annualRevenue": {
      "value": 1020000,
      "confidence": 0.98,
      "source": "Tax Return"
    },
    "timeInBusinessYears": {
      "value": 4,
      "confidence": 0.9,
      "source": "Application"
    },
    "nsfs90d": { "value": 2, "confidence": 0.8, "source": "Bank Statements" },
    "openPositions": {
      "value": 1,
      "confidence": 0.7,
      "source": "Bank Statements"
    },
    "naicsCode": {
      "value": "541511",
      "confidence": 1,
      "source": "Application"
    },
    "state": { "value": "TX", "confidence": 1, "source": "Application" },
    "bankStatementCount": {
      "value": 4,
      "confidence": 0.99,
      "source": "Documents"
    }
  },
  "rawResponse": {},
  "generatedAt": "2026-09-08T12:05:00.000Z",
  "errorMessage": null
}
```

On failure:

```json
{
  "status": "FAILED",
  "errorMessage": "OCR failed on bank statement page 2",
  "generatedAt": "2026-09-08T12:05:00.000Z"
}
```

`extractedData` field names above are what **lender-match** already reads. Prefer this shape so matching works without remapping.

### B) Cashflow report

`PUT /api/v1/internal/ai/deals/:dealId/cashflow-report`

```json
{
  "status": "READY",
  "overview": {},
  "bankDebtSummary": {},
  "balanceInsights": {},
  "profitAndLoss": {},
  "bankStatementSummary": {},
  "generatedAt": "2026-09-08T12:05:00.000Z",
  "errorMessage": null
}
```

Section JSON schemas can evolve; UI currently has mock tabs until live binding. Store whatever the AI team defines as long as each section is a JSON object.

### C) Lender criteria draft (guidelines PDF)

`PUT /api/v1/internal/ai/lenders/:lenderId/criteria-draft`

```json
{
  "criteria": {
    "tier": "Tier 1 (SBA)",
    "channel": "API",
    "typicalResponseHours": 24,
    "estOfferMinK": 50,
    "estOfferMaxK": 350,
    "ficoMin": 680,
    "revenueMinMonthly": 12500,
    "minTibYears": 3,
    "maxNsfs90d": 3,
    "maxPositions": 0,
    "allowedStates": ["TX", "NY", "FL"],
    "excludedNaics": ["4841", "4842"],
    "hardStops": ["MCA_OUTSTANDING"]
  },
  "confidence": 0.88,
  "extractedAt": "2026-09-08T12:05:00.000Z",
  "requiresAdminConfirm": true
}
```

**Recommended product rule:** store as draft; admin confirms via existing  
`PATCH /api/v1/admin/lenders/:id/criteria` before match uses it.  
(Optional later: auto-activate if `requiresAdminConfirm: false`.)

Canonical credit-box definitions: [`LENDER_UNDERWRITING_SPECS.md`](./LENDER_UNDERWRITING_SPECS.md).

---

## 4. What HuddleBiz displays (no AI call)

| UI                           | Data source                                          |
| ---------------------------- | ---------------------------------------------------- |
| Deal underwriting panel      | `UnderwritingResult`                                 |
| Cashflow tabs                | `CashflowReport`                                     |
| Lender match tab             | Rule engine over `extractedData` + `Lender.criteria` |
| Settings → Lender Guidelines | `Lender` + PDF + criteria JSON                       |

Existing read APIs:

- `GET /api/v1/admin/deals/:id`
- `GET /api/v1/admin/deals/:id/cashflow-report`
- `GET /api/v1/admin/deals/:id/lender-match`
- `GET /api/v1/admin/lenders`

---

## 5. Implementation checklist (HuddleBiz)

| Priority | Task                                                      | Status          |
| -------- | --------------------------------------------------------- | --------------- |
| P0       | This contract shared with AI team                         | Done (this doc) |
| P0       | Honest UI: PDF upload ≠ “AI updated”                      | Done            |
| P1       | Service auth for `/internal/ai/*` (`AI_SERVICE_TOKEN`)    | Done            |
| P1       | Pull package + guideline download endpoints               | Done            |
| P1       | Push underwriting + cashflow + criteria ingest            | Done            |
| P1       | Trigger notifies AI when `AI_WEBHOOK_URL` set (else mock) | Done            |
| P2       | Admin confirm step for criteria draft (optional column)   | Open            |
| P2       | Bind cashflow UI to live report JSON                      | Mock UI today   |
| P3       | Real syndication packets on lender submit                 | DB row only     |

---

## 6. Out of scope for AI platform

- Admin/partner/customer portals
- Deal status transitions (`APPROVED` / `DECLINED` / `FUNDED`)
- Lender Eligible/Review/Ineligible rule engine
- Document approve/reject workflow
- Email/SMS to borrowers

---

## Related docs

- [`admin-ai-underwriting.md`](./admin-ai-underwriting.md) — storage ownership notes
- [`LENDER_UNDERWRITING_SPECS.md`](./LENDER_UNDERWRITING_SPECS.md) — real lender credit boxes
