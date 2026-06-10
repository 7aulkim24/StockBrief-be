from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.orm import (
    ApiCacheEntry,
    CompanyIdentifier,
    Disclosure,
    EvidenceChunk,
    ExternalApiCallLog,
    FinancialStatement,
    NewsItem,
    PriceMetric,
    RecommendationReason,
    RecommendationScore,
    RecommendationScoreRule,
    RiskSignal,
    SourceDocument,
    Stock,
)
from app.seed.mock_data import MOCK_STOCKS, SCORE_COMPONENTS, SCORE_VERSION, SEED_AS_OF_DATE, MockStock

ModelT = TypeVar("ModelT")

FETCHED_AT = datetime(2026, 6, 9, 8, 30, tzinfo=timezone.utc)
PUBLISHED_AT = datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc)


def _hash_key(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _upsert_one(
    session: Session,
    model: type[ModelT],
    filters: dict[str, Any],
    values: dict[str, Any],
) -> ModelT:
    instance = session.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    if instance is None:
        instance = model(**filters, **values)
        session.add(instance)
    else:
        for key, value in values.items():
            setattr(instance, key, value)
    session.flush()
    return instance


def _component_scores(base_score: int) -> list[dict[str, Any]]:
    scores = []
    for index, (name, weight) in enumerate(SCORE_COMPONENTS):
        raw_score = max(45, min(90, base_score + ((index % 3) - 1) * 3))
        scores.append(
            {
                "name": name,
                "weight": weight,
                "raw_score": raw_score,
                "weighted_score": round(raw_score * weight / 100, 2),
                "reason": "공개 데이터 기준 검토 포인트가 확인됩니다.",
                "input_refs": [f"mock:{name}"],
                "rule_version": SCORE_VERSION,
            }
        )
    return scores


def _total_score(component_scores: list[dict[str, Any]]) -> Decimal:
    total = sum(Decimal(str(component["weighted_score"])) for component in component_scores)
    return total.quantize(Decimal("0.1"))


def _seed_score_rules(session: Session) -> None:
    for component, weight in SCORE_COMPONENTS:
        _upsert_one(
            session,
            RecommendationScoreRule,
            {"rule_version": SCORE_VERSION, "component": component},
            {
                "weight": weight,
                "formula": {
                    "source": "mock_seed",
                    "normalization": "bounded_demo_score",
                    "llm_scoring": False,
                },
                "description": f"{component} mock seed rule for MVP vertical flow.",
                "is_active": True,
            },
        )


def _seed_stock(session: Session, item: MockStock) -> None:
    _upsert_one(
        session,
        Stock,
        {"ticker": item.ticker},
        {
            "company_name": item.company_name,
            "company_name_en": item.company_name_en,
            "market": item.market,
            "sector": item.sector,
            "industry": item.industry,
            "listing_date": item.listing_date,
            "is_active": True,
        },
    )

    for identifier_type, identifier_value, is_primary in [
        ("corp_code", item.corp_code, True),
        ("stock_code", item.ticker, False),
    ]:
        _upsert_one(
            session,
            CompanyIdentifier,
            {
                "ticker": item.ticker,
                "provider": "OpenDART",
                "identifier_type": identifier_type,
            },
            {
                "identifier_value": identifier_value,
                "is_primary": is_primary,
            },
        )

    disclosure_doc = _upsert_one(
        session,
        SourceDocument,
        {"source_name": "OpenDART_MOCK", "external_id": f"mock-disclosure-{item.ticker}"},
        {
            "ticker": item.ticker,
            "source_type": "disclosure",
            "source_url": f"https://mock.stockbrief.local/opendart/{item.ticker}",
            "title": f"[MOCK] {item.company_name} 분기 공시 데모 자료",
            "published_at": PUBLISHED_AT,
            "fetched_at": FETCHED_AT,
            "content_hash": _hash_key(f"disclosure:{item.ticker}"),
            "raw_content": "MVP 데모용 공시 원문 대체 데이터입니다.",
            "metadata_": {"mock": True, "provider": "OpenDART"},
        },
    )
    news_doc = _upsert_one(
        session,
        SourceDocument,
        {"source_name": "NAVER_NEWS_MOCK", "external_id": f"mock-news-{item.ticker}"},
        {
            "ticker": item.ticker,
            "source_type": "news",
            "source_url": f"https://mock.stockbrief.local/naver-news/{item.ticker}",
            "title": f"[MOCK NEWS] {item.company_name} 산업 동향 데모 기사",
            "published_at": PUBLISHED_AT,
            "fetched_at": FETCHED_AT,
            "content_hash": _hash_key(f"news:{item.ticker}"),
            "raw_content": "MVP 데모용 뉴스 원문 대체 데이터입니다.",
            "metadata_": {"mock": True, "provider": "NAVER"},
        },
    )

    _upsert_one(
        session,
        FinancialStatement,
        {"ticker": item.ticker, "fiscal_year": 2026, "fiscal_period": "Q1"},
        {
            "period_end_date": date(2026, 3, 31),
            "revenue": Decimal(item.base_score * 1_000_000_000),
            "operating_income": Decimal(item.base_score * 90_000_000),
            "net_income": Decimal(item.base_score * 70_000_000),
            "total_assets": Decimal(item.base_score * 6_000_000_000),
            "total_liabilities": Decimal(item.base_score * 2_100_000_000),
            "total_equity": Decimal(item.base_score * 3_900_000_000),
            "source_document_id": disclosure_doc.id,
        },
    )

    _upsert_one(
        session,
        Disclosure,
        {"provider": "OpenDART_MOCK", "receipt_no": f"mock-rcept-{item.ticker}-2026q1"},
        {
            "ticker": item.ticker,
            "title": f"[MOCK] {item.company_name} 2026 Q1 공시 데모",
            "disclosure_type": "periodic_report",
            "published_at": PUBLISHED_AT,
            "source_url": f"https://mock.stockbrief.local/opendart/{item.ticker}",
            "source_document_id": disclosure_doc.id,
            "raw_payload": {"mock": True, "ticker": item.ticker},
        },
    )

    _upsert_one(
        session,
        NewsItem,
        {"source_url": f"https://mock.stockbrief.local/naver-news/{item.ticker}"},
        {
            "ticker": item.ticker,
            "provider": "NAVER_NEWS_MOCK",
            "title": f"[MOCK NEWS] {item.company_name} 공개 데이터 검토 포인트",
            "summary": "MVP 화면 확인을 위한 데모 뉴스 요약입니다.",
            "publisher": "StockBrief Mock Desk",
            "published_at": PUBLISHED_AT,
            "sentiment_label": "neutral",
            "source_document_id": news_doc.id,
            "raw_payload": {"mock": True, "ticker": item.ticker},
        },
    )

    _upsert_one(
        session,
        PriceMetric,
        {"ticker": item.ticker, "trade_date": SEED_AS_OF_DATE},
        {
            "close_price": Decimal(item.base_score * 900),
            "volume": Decimal(item.base_score * 100_000),
            "trading_value": Decimal(item.base_score * 90_000_000),
            "market_cap": Decimal(item.base_score * 8_000_000_000),
            "change_rate": Decimal("0.80"),
            "volatility_20d": Decimal("0.210000"),
            "momentum_20d": Decimal("0.035000"),
            "source": "KRX_FALLBACK_MOCK",
        },
    )

    evidence_1 = _upsert_one(
        session,
        EvidenceChunk,
        {"evidence_id": f"ev_mock_{item.ticker}_disclosure"},
        {
            "ticker": item.ticker,
            "source_document_id": disclosure_doc.id,
            "evidence_type": "financial_stability",
            "chunk_text": "공개 공시 형식의 mock 데이터에서 재무 안정성 검토 포인트가 확인됩니다.",
            "source_url": f"https://mock.stockbrief.local/opendart/{item.ticker}",
            "published_at": PUBLISHED_AT,
            "fetched_at": FETCHED_AT,
            "confidence": Decimal("0.8200"),
            "metadata_": {"mock": True, "screen": "evidence"},
        },
    )
    evidence_2 = _upsert_one(
        session,
        EvidenceChunk,
        {"evidence_id": f"ev_mock_{item.ticker}_news"},
        {
            "ticker": item.ticker,
            "source_document_id": news_doc.id,
            "evidence_type": "news_attention",
            "chunk_text": "데모 뉴스 데이터에서 시장 관심도 검토 포인트가 확인됩니다.",
            "source_url": f"https://mock.stockbrief.local/naver-news/{item.ticker}",
            "published_at": PUBLISHED_AT,
            "fetched_at": FETCHED_AT,
            "confidence": Decimal("0.7600"),
            "metadata_": {"mock": True, "screen": "evidence"},
        },
    )

    _upsert_one(
        session,
        RiskSignal,
        {"ticker": item.ticker, "as_of_date": SEED_AS_OF_DATE, "risk_tag": item.risk_tag},
        {
            "severity": "medium",
            "penalty_points": Decimal("2.50"),
            "display_text": item.risk_text,
            "description": item.risk_text,
            "evidence_ids": [evidence_1.evidence_id, evidence_2.evidence_id],
        },
    )

    components = _component_scores(item.base_score)
    score = _upsert_one(
        session,
        RecommendationScore,
        {"ticker": item.ticker, "as_of_date": SEED_AS_OF_DATE, "score_version": SCORE_VERSION},
        {
            "total_score": _total_score(components),
            "evidence_level": "medium",
            "component_scores": components,
            "evidence_count": 2,
            "missing_data": [],
            "data_freshness": {
                "as_of": SEED_AS_OF_DATE.isoformat(),
                "price_as_of": SEED_AS_OF_DATE.isoformat(),
                "financials_as_of": "2026-03-31",
                "disclosures_fetched_at": FETCHED_AT.isoformat(),
                "news_fetched_at": FETCHED_AT.isoformat(),
            },
            "is_candidate_eligible": True,
        },
    )

    _upsert_one(
        session,
        RecommendationReason,
        {"reason_id": f"rsn_mock_{item.ticker}_001"},
        {
            "recommendation_score_id": score.id,
            "ticker": item.ticker,
            "component": "financial_stability",
            "summary": "공개 데이터 기준 검토 포인트가 확인되어 추천 후보 설명에 사용할 수 있습니다.",
            "evidence_ids": [evidence_1.evidence_id, evidence_2.evidence_id],
            "source_document_ids": [str(disclosure_doc.id), str(news_doc.id)],
        },
    )

    _upsert_one(
        session,
        ApiCacheEntry,
        {"provider": "MOCK", "cache_key": f"candidate:{item.ticker}:{SEED_AS_OF_DATE.isoformat()}"},
        {
            "request_hash": _hash_key(f"candidate:{item.ticker}"),
            "response_payload": {
                "mock": True,
                "ticker": item.ticker,
                "score_version": SCORE_VERSION,
            },
            "status_code": 200,
            "expires_at": datetime(2026, 6, 10, 8, 30, tzinfo=timezone.utc),
        },
    )

    _upsert_one(
        session,
        ExternalApiCallLog,
        {"provider": "MOCK", "endpoint": f"/seed/{item.ticker}", "called_at": FETCHED_AT},
        {
            "method": "SEED",
            "request_params": {"ticker": item.ticker, "mock": True},
            "status_code": 200,
            "duration_ms": 0,
            "error_code": None,
        },
    )


def seed_mock_data(session: Session) -> dict[str, int]:
    _seed_score_rules(session)
    for item in MOCK_STOCKS:
        _seed_stock(session, item)
    session.commit()
    return {
        "stocks": len(MOCK_STOCKS),
        "score_rules": len(SCORE_COMPONENTS),
        "recommendation_scores": len(MOCK_STOCKS),
    }


def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        result = seed_mock_data(session)
    print(
        "Seeded StockBrief mock data: "
        f"{result['stocks']} stocks, "
        f"{result['score_rules']} score rules, "
        f"{result['recommendation_scores']} recommendation scores."
    )


if __name__ == "__main__":
    main()
