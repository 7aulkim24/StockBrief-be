# API Contract

This document is the canonical StockBrief public API contract for the
`factor-rank-2026-06-30` score contract.

The API serves stored StockBrief data materialized from the stock universe and
real provider ingestion paths. OpenDART, NAVER, KRX, Bedrock, and RAG ingestion
adapters must keep the same response shape as provider coverage expands.

## 1. Base URL

Local backend:

```text
http://localhost:8000/v1
```

Frontend environment variable:

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/v1
```

All public API paths start with `/v1`.

## 2. Common Response

`GET /v1/health` is the only public endpoint that returns a plain health
object. All other public success responses use this envelope:

```json
{
  "success": true,
  "data": {},
  "message": "요청이 성공적으로 처리되었습니다.",
  "request_id": "req_..."
}
```

Common error response:

```json
{
  "success": false,
  "error": {
    "code": "STOCK_NOT_FOUND",
    "message": "Stock not found.",
    "details": null
  },
  "request_id": "req_..."
}
```

Supported sprint error codes:

| HTTP | Code |
| --- | --- |
| `400` | `INVALID_REQUEST` |
| `404` | `STOCK_NOT_FOUND` |
| `408` | `UPSTREAM_TIMEOUT` |
| `429` | `RATE_LIMITED` |
| `500` | `INTERNAL_ERROR` |
| `503` | `SERVICE_UNAVAILABLE` |

List responses use common pagination:

```json
{
  "limit": 20,
  "offset": 0,
  "total": 30,
  "has_more": true
}
```

## 3. Public Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/health` | Runtime health metadata |
| `GET` | `/v1/stocks/search` | Search stock universe rows |
| `GET` | `/v1/stocks/candidates` | List materialized score candidates |
| `GET` | `/v1/stocks/{ticker}` | Stock detail for the detail page |
| `GET` | `/v1/stocks/{ticker}/evidence` | Evidence for tabs and chat citations |
| `POST` | `/v1/chat` | Stored-score Agent/RAG answer |

Legacy/internal recommendation engine endpoints remain available for backend
compatibility:

- `GET /v1/recommendations/candidates`
- `GET /v1/recommendations/candidates/{ticker}`
- `GET /v1/stocks/{ticker}/score`

New frontend work should prefer the public endpoints in the table above.

### 3.1 Envelope migration status (`/recommendations/*`)

`GET /v1/recommendations/candidates` and
`GET /v1/recommendations/candidates/{ticker}` intentionally return their raw
`RecommendationCandidateListResponse` / `RecommendationCandidateResponse`
bodies (no `success`/`data`/`message`/`request_id` envelope). This is a
deliberate exception, not an oversight:

- `StockBrief-fe/src/lib/api.ts` (`getRecommendationCandidates`,
  `getRecommendationCandidate`) calls its internal `request<T>()` helper,
  which returns `response.json()` directly as the typed payload. It does not
  unwrap a `data` field. Wrapping these endpoints in the standard envelope
  would silently break the frontend until it migrates its client to read
  `response.data`.
- `scripts/check_recommendation_quality_smoke.py`'s `check_candidate_detail`
  reads fields (`ticker`, `evidence_count`, `risk_tags`, ...) directly off the
  top-level response payload, not off `payload["data"]`.

Until the frontend and smoke scripts are updated to consume the enveloped
shape, these two legacy paths stay frozen on their raw response models
(pinned by
`tests/test_recommendation_api.py::test_legacy_recommendation_endpoints_keep_raw_response_shape`
and
`tests/test_api_contract_snapshot.py::test_legacy_recommendation_endpoints_stay_on_raw_response_models`).

`GET /v1/stocks/candidates/{ticker}` (the `/stocks/*` equivalent of the
legacy detail endpoint) has been converted to the standard envelope in this
change, since it has no frontend or smoke-script consumers today. It now
returns `RecommendationCandidateContractResponse`:

```json
{
  "success": true,
  "data": { "...": "RecommendationCandidateResponse fields" },
  "message": "추천 후보 상세를 반환했습니다.",
  "request_id": "req_..."
}
```

**Migration plan for a future PR:** once `StockBrief-fe/src/lib/api.ts` is
updated to unwrap `response.data` for `getRecommendationCandidates` /
`getRecommendationCandidate`, and
`scripts/check_recommendation_quality_smoke.py::check_candidate_detail` is
updated to read `response_payload(payload)` (the same helper
`check_candidate_list` already uses), `/v1/recommendations/candidates` and
`/v1/recommendations/candidates/{ticker}` can be converted to the standard
envelope in the same way.

Score-backed candidate and score endpoints use stored materialized scores.
The current public baseline stores `factor-rank-2026-06-30` in public
`score.version` fields.

Candidate score contract fields:

- `recommendation_score`: total score from `0` to `100`.
- `score_components`: exactly 8 component score records when all persisted
  component data is available. Each component includes `name`, `weight`,
  `raw_score`, `weighted_score`, `reason`, `input_refs`, and `evidence_ids`.
- `evidence_count`: distinct evidence item count used by the score.
- `evidence_level`: `strong`, `medium`, or `weak`.
- `missing_data`: missing input keys. Present even when empty.
- `data_freshness`: freshness metadata, including `as_of`.
- `risk_tags`: risk signal tags associated with the same ticker and score date.

Materialized score fields not currently exposed in public responses:

- `fallback_data`: fallback component names from the score engine contract.
  Downstream persistence preserves it for internal freshness diagnostics.
- Component `rule_version`: the score engine emits this internally, but the
  current public component response does not expose it.
- Score result `score_version`: the score engine emits this internally, while
  the current public API exposes persisted score version as `score.version`.

## 4. GET /health

Response:

```json
{
  "status": "ok",
  "service": "stockbrief-api",
  "version": "0.1.0"
}
```

## 5. GET /stocks/search

Query:

| Name | Required | Default |
| --- | --- | --- |
| `q` | no | empty |
| `market` | no | all |
| `limit` | no | `20` |
| `offset` | no | `0` |

Response `data`:

```json
{
  "items": [
    {
      "ticker": "005930",
      "name": "삼성전자",
      "market": "KOSPI",
      "sector": "반도체",
      "corp_code": "00126380",
      "match_reason": "name"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 1,
    "has_more": false
  }
}
```

## 6. GET /stocks/candidates

Query:

| Name | Required | Default |
| --- | --- | --- |
| `risk_profile` | no | `balanced` |
| `market` | no | all |
| `sector` | no | all |
| `sort` | no | `score_desc` |
| `limit` | no | `20` |
| `offset` | no | `0` |

`sort` supports `score_desc`, `volume_desc`, and `updated_desc`.
`risk_profile` supports `conservative`, `balanced`, and `aggressive`.
When `sort=score_desc`, risk profile affects ordering:

- `conservative`: fewer risk signals first, then higher score.
- `balanced`: higher score with a small risk-count penalty.
- `aggressive`: higher score first.

Response `data`:

```json
{
  "as_of": "2026-06-09",
  "items": [
    {
      "ticker": "005930",
      "name": "삼성전자",
      "market": "KOSPI",
      "sector": "반도체",
      "score": {
        "total": 78.5,
        "grade": "B",
        "as_of": "2026-06-09",
        "version": "factor-rank-2026-06-30",
        "breakdown": {
          "momentum": 7.5,
          "liquidity": 7.8,
          "disclosure": 7.5,
          "news": 7.8
        }
      },
      "price": {
        "close": 70200,
        "change_rate": 0.8,
        "volume": 7800000,
        "trade_date": "2026-06-09"
      },
      "evidence_summary": {
        "news_count": 1,
        "disclosure_count": 1,
        "latest_at": "2026-06-08T09:00:00Z"
      }
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 30,
    "has_more": true
  }
}
```

### 6.1 GET /stocks/candidates/{ticker}

Returns the same candidate detail as the legacy
`GET /recommendations/candidates/{ticker}`, wrapped in the standard envelope.
Response `data` is a `RecommendationCandidateResponse` (see
`RECOMMENDATION_CANDIDATE_REQUIRED_FIELDS` in
`tests/test_api_contract_snapshot.py` for the required field set):

```json
{
  "success": true,
  "data": {
    "ticker": "005930",
    "name": "삼성전자",
    "market": "KOSPI",
    "sector": "반도체",
    "recommendation_score": 78.5,
    "score_components": [ "... 8 components ..." ],
    "recommendation_reasons": [ "..." ],
    "risk_tags": [ "..." ],
    "evidence_level": "strong",
    "evidence_count": 4,
    "missing_data": [],
    "data_freshness": { "as_of": "2026-06-09" },
    "disclaimer": "공개 데이터 기반 검토 후보이며 최종 투자 판단은 사용자에게 있습니다."
  },
  "message": "추천 후보 상세를 반환했습니다.",
  "request_id": "req_..."
}
```

## 7. GET /stocks/{ticker}

Response `data`:

```json
{
  "stock": {
    "ticker": "005930",
    "name": "삼성전자",
    "market": "KOSPI",
    "sector": "반도체",
    "corp_code": "00126380"
  },
  "price": {
    "close": 70200,
    "change_rate": 0.8,
    "volume": 7800000,
    "trade_date": "2026-06-09"
  },
  "score": {
    "total": 78.5,
    "grade": "B",
    "as_of": "2026-06-09",
    "version": "factor-rank-2026-06-30",
    "breakdown": {
      "momentum": 7.5,
      "liquidity": 7.8,
      "disclosure": 7.5,
      "news": 7.8
    }
  },
  "brief": {
    "summary": "삼성전자는 공개 데이터 기반 점수와 근거로 검토 후보에 포함된 종목입니다.",
    "risk_notes": [
      "OpenDART, NAVER, KRX 등 연결된 원천 데이터 기준입니다.",
      "투자 판단 전 원문과 최신 데이터를 확인해야 합니다."
    ],
    "as_of": "2026-06-09"
  },
  "evidence_preview": [
    {
      "id": "ev_provider_005930_news",
      "source_type": "NEWS",
      "title": "삼성전자 산업 동향 기사",
      "source_name": "NAVER_NEWS",
      "url": "https://news.naver.com/main/read.naver?oid=000&aid=0000000000",
      "published_at": "2026-06-08T09:00:00Z"
    }
  ]
}
```

## 8. GET /stocks/{ticker}/evidence

Query:

| Name | Required | Default |
| --- | --- | --- |
| `source_type` | no | all |
| `from_date` | no | none |
| `to_date` | no | none |
| `limit` | no | `20` |
| `offset` | no | `0` |

`source_type` supports `NEWS`, `DISCLOSURE`, `SCORE`, and `CHUNK`.

Response `data`:

```json
{
  "ticker": "005930",
  "items": [
    {
      "id": "ev_provider_005930_news",
      "source_type": "NEWS",
      "title": "삼성전자 산업 동향 기사",
      "source_name": "NAVER_NEWS",
      "url": "https://news.naver.com/main/read.naver?oid=000&aid=0000000000",
      "published_at": "2026-06-08T09:00:00Z",
      "snippet": "NAVER 뉴스에서 시장 관심도 검토 포인트가 확인됩니다.",
      "metadata": {
        "data_status": "available",
        "source_identifier": "naver-news-005930-20260608",
        "as_of_date": "2026-06-08"
      }
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 4,
    "has_more": false
  }
}
```

## 9. POST /chat

Chat providers explain stored scores, evidence, freshness, missing data, and
risk tags. They must not generate, replace, or modify score values.
`CHAT_PROVIDER=agentcore` is a dev-only provider that calls an AgentCore
Runtime-compatible `/invocations` endpoint and then repeats the same API
boundary safety and citation validation before returning `/v1/chat` data.

Request:

```json
{
  "message": "삼성전자 최근 근거 요약해줘",
  "ticker": "005930",
  "session_id": "local-session-1"
}
```

Response `data`:

```json
{
  "session_id": "local-session-1",
  "message_id": null,
  "answer": "공개 데이터 기준 설명입니다.",
  "citations": [
    {
      "id": "ev_provider_005930_news",
      "source_type": "NEWS",
      "title": "삼성전자 산업 동향 기사",
      "url": "https://news.naver.com/main/read.naver?oid=000&aid=0000000000",
      "published_at": null
    }
  ],
  "safety": {
    "policy_action": "ALLOW",
    "disclaimer": "이 정보는 투자 조언이 아니며, 투자 판단 전 원문과 최신 데이터를 확인하세요."
  }
}
```

AgentCore Runtime dev contract:

- `GET /ping` returns `{"status":"Healthy"}`.
- `POST /invocations` accepts JSON with `input.message`, `input.ticker`,
  `input.candidate`, `input.evidence`, and `input.baseline`.
- `POST /invocations` returns JSON with `status`, `response.answer`, and
  redacted `response.trace` metadata for selected read-only tools, tool
  latency/error status, metrics, policy status, and citation IDs.

## 10. Authenticated Account Endpoints

These endpoints require the Cognito JWT authorizer or the local test auth
override. They are scoped to the current user.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/me` | Current user profile |
| `PATCH` | `/v1/me` | Update current user profile |
| `GET` | `/v1/me/preferences` | Current user preferences |
| `PUT` | `/v1/me/preferences` | Replace current user preferences |
| `GET` | `/v1/me/watchlist` | Current user watchlist |
| `POST` | `/v1/me/watchlist` | Add a watchlist item |
| `PATCH` | `/v1/me/watchlist/{ticker}` | Update a watchlist item |
| `DELETE` | `/v1/me/watchlist/{ticker}` | Remove a watchlist item |
| `POST` | `/v1/me/watchlist/import` | Merge guest watchlist items into the server watchlist |
| `GET` | `/v1/me/chat-sessions` | List current user chat sessions |
| `POST` | `/v1/me/chat-sessions` | Create an empty current user chat session |
| `GET` | `/v1/me/chat-sessions/{session_id}` | Read current user chat session messages |

`PUT /v1/me/preferences` stores the current user's product preferences. Unknown
preference keys are preserved for forward compatibility, but known keys are
validated:

- `risk_profile`: `conservative`, `balanced`, or `aggressive`
- `notifications.email_enabled`: boolean
- `notifications.watchlist_digest`: `off`, `daily`, or `weekly`

When any known preference key above is present, `null` is rejected as invalid.

Request:

```json
{
  "preferences": {
    "risk_profile": "balanced",
    "markets": ["KOSPI"],
    "notifications": {
      "email_enabled": true,
      "watchlist_digest": "weekly"
    }
  }
}
```

Invalid known preference values return `400 INVALID_PREFERENCES` with field-level
details.

`GET /v1/me/chat-sessions/{session_id}` returns `404 CHAT_SESSION_NOT_FOUND`
when the session does not exist or belongs to another user.

Response:

```json
{
  "session": {
    "session_id": "chat_20260624_001",
    "ticker": "005930",
    "title": "삼성전자 설명",
    "created_at": "2026-06-24T09:00:00Z",
    "updated_at": "2026-06-24T09:05:00Z"
  },
  "messages": [
    {
      "message_id": "msg_20260624_001",
      "role": "user",
      "content": "왜 추천됐나요?",
      "ticker": "005930",
      "citations": [],
      "safety_flags": [],
      "created_at": "2026-06-24T09:00:01Z"
    },
    {
      "message_id": "msg_20260624_002",
      "role": "assistant",
      "content": "공개 데이터 기준 설명입니다.",
      "ticker": "005930",
      "citations": [
        {
          "evidence_id": "ev_provider_005930_news",
          "type": "news",
          "title": "삼성전자 산업 동향 기사",
          "source_url": "https://news.naver.com/main/read.naver?oid=000&aid=0000000000",
          "published_at": "2026-06-08T09:00:00Z"
        }
      ],
      "safety_flags": [
        {
          "policy_status": "allowed"
        }
      ],
      "created_at": "2026-06-24T09:00:02Z"
    }
  ]
}
