# StockBrief-be

StockBrief 백엔드 레포지토리. FastAPI, PostgreSQL, AWS Lambda, Terraform 인프라를 포함한다.

StockBrief는 한국 국내 주식 추천 후보 서비스다. 이 레포는 투자 조언을 제공하지 않는다. 모든 추천은 `검토 후보 추천`이며, 매수·매도 지시, 목표가, 수익 보장이 아니다.

## 레포 범위

| 구분 | 내용 |
| --- | --- |
| `app/` | FastAPI 애플리케이션 (라우트, 모델, 서비스) |
| `app/services/recommendation/` | 결정론적 스코어 엔진 (8개 컴포넌트) |
| `app/services/external/` | OpenDART, NAVER, KRX 어댑터, 캐시, 로거 |
| `app/services/chat/` | AI 설명 컴포저 (채점 없음) |
| `app/seed/` | 종목 universe master 시드 |
| `tests/` | pytest 테스트 스위트 |
| `migrations/` | Alembic DB 마이그레이션 |
| `infra/terraform/` | AWS 인프라 코드 |
| `scripts/` | 패키징, 금지어 스캔 유틸리티 |
| `docs/engineering/` | API 계약, DB 스키마, 스코어 엔진, AI 안전 정책 |

## 로컬 셋업

Python 3.13 기준으로 개발한다. `mise install`로 런타임을 맞춘 뒤 `uv`로 의존성을 동기화한다.

```bash
mise install
uv sync --extra dev
```

환경변수 설정:

```bash
cp .env.example .env
# .env에서 DATABASE_URL, OPENDART_API_KEY 등 설정
```

로컬 PostgreSQL 실행:

```bash
docker compose up -d postgres
```

## 서버 실행

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

헬스 체크:

```bash
curl http://127.0.0.1:8000/v1/health
```

## 데이터베이스 마이그레이션

```bash
uv run alembic upgrade head
```

롤백:

```bash
uv run alembic downgrade -1
```

## 시드 데이터

종목 master와 OpenDART 식별자만 적재한다. 추천 점수, 근거, 가격은 provider ingestion과 materializer가 생성한다.

```bash
uv run alembic upgrade head
uv run stockbrief-seed-stock-universe
uv run python scripts/check_ingestion_smoke.py \
  --source-date 2026-06-27 \
  --run-provider-ingest
```

로컬 API 확인:

```bash
curl http://127.0.0.1:8000/v1/health
curl "http://127.0.0.1:8000/v1/recommendations/candidates?limit=3"
```

## 테스트

```bash
uv run pytest
```

특정 테스트 그룹:

```bash
uv run pytest tests/test_api_contract_snapshot.py   # API 계약 스냅샷
uv run pytest tests/test_recommendation_score_engine.py  # 스코어 엔진
uv run pytest tests/test_evidence_gate.py           # 에비던스 게이트
uv run pytest tests/test_chat_api.py                # 채팅 정책
uv run pytest tests/test_external_adapters.py       # 외부 어댑터
```

## 금지어 스캔

```bash
uv run python scripts/check_prohibited_terms.py
```

의도적인 테스트/정책 예외는 `policy-scan: allow <reason>` 형식으로만
억제합니다. 사유 없는 `policy-scan: allow` 주석은 실패로 처리됩니다.

## 구현된 엔드포인트

- `GET /v1/health`
- `GET /v1/meta/service-policy`
- `GET /v1/recommendations/candidates`
- `GET /v1/recommendations/candidates/{ticker}`
- `GET /v1/stocks/candidates` (호환 alias)
- `POST /v1/chat`
- `GET /v1/me` (P1, Cognito 인증 필요)
- `PATCH /v1/me`
- `GET /v1/me/watchlist`
- `POST /v1/me/watchlist`
- `POST /v1/me/watchlist/import`

## 브랜치 정책

- `main`: 보호 브랜치, 직접 push 금지
- `feat/<issue>-<slug>`: 새 기능
- `fix/<issue>-<slug>`: 버그 수정
- `docs/<slug>`: 문서 변경
- `release/<version>`: 릴리즈 직전 안정화

커밋 타입: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`

## 관련 레포

- [StockBrief-fe](https://github.com/your-org/StockBrief-fe) — Next.js 프론트엔드
- [StockBrief-wiki](https://github.com/your-org/StockBrief-wiki) — 결정 로그, 회의록, 스프린트 기록
