from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db_session
from app.main import app
from app.orm import (
    Base,
    Disclosure,
    EvidenceChunk,
    FinancialStatement,
    NewsItem,
    PriceMetric,
    RiskSignal,
    SourceDocument,
)
from app.seed.seed_stock_universe import seed_stock_universe
from app.seed.stock_universe import STOCK_UNIVERSE, StockUniverseItem
from app.services.recommendation.materializer import materialize_recommendation_scores


PROVIDER_FIXTURE_AS_OF_DATE = date(2026, 6, 9)
PROVIDER_FIXTURE_FETCHED_AT = datetime(2026, 6, 9, 8, 30, tzinfo=timezone.utc)
PROVIDER_FIXTURE_PUBLISHED_AT = datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def seeded_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_stock_universe(session)
        _seed_provider_fixture_data(session)
        yield session


@pytest.fixture()
def seeded_api_client(seeded_session: Session) -> TestClient:
    def override_db_session():
        yield seeded_session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_provider_fixture_data(session: Session) -> None:
    for index, item in enumerate(STOCK_UNIVERSE, start=1):
        _seed_provider_rows(session, item, index)
    materialize_recommendation_scores(
        session,
        as_of_date=PROVIDER_FIXTURE_AS_OF_DATE,
    )
    session.commit()


def _seed_provider_rows(session: Session, item: StockUniverseItem, index: int) -> None:
    published_at = PROVIDER_FIXTURE_PUBLISHED_AT
    fetched_at = PROVIDER_FIXTURE_FETCHED_AT
    disclosure_source = SourceDocument(
        ticker=item.ticker,
        source_type="disclosure",
        source_name="OpenDART",
        source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260608{index:06d}",
        external_id=f"opendart-{item.corp_code}-2026q1",
        title=f"{item.company_name} 2026 Q1 정기보고서",
        published_at=published_at,
        fetched_at=fetched_at,
        content_hash=f"provider-fixture-disclosure-{item.ticker}",
        raw_content="OpenDART provider fixture disclosure content",
        metadata_={"provider": "OpenDART", "fixture": "provider_sample"},
    )
    news_source = SourceDocument(
        ticker=item.ticker,
        source_type="news",
        source_name="NAVER_NEWS",
        source_url=f"https://news.example.com/{item.ticker}/provider-sample",
        external_id=f"naver-news-{item.ticker}-20260608",
        title=f"{item.company_name} 산업 동향 기사",
        published_at=published_at,
        fetched_at=fetched_at,
        content_hash=f"provider-fixture-news-{item.ticker}",
        raw_content="NAVER provider fixture news content",
        metadata_={"provider": "NAVER_NEWS", "fixture": "provider_sample"},
    )
    session.add_all([disclosure_source, news_source])
    session.flush()

    base = Decimal(900_000_000_000 + index * 10_000_000_000)
    current_revenue = base
    previous_revenue = base * Decimal("0.92")
    current_operating_income = current_revenue * Decimal("0.14")
    previous_operating_income = previous_revenue * Decimal("0.12")
    current_net_income = current_revenue * Decimal("0.10")
    equity = current_revenue * Decimal("1.90")
    assets = equity * Decimal("1.55")
    liabilities = assets - equity

    session.add_all(
        [
            FinancialStatement(
                ticker=item.ticker,
                fiscal_year=2026,
                fiscal_period="Q1",
                period_end_date=date(2026, 3, 31),
                revenue=current_revenue,
                operating_income=current_operating_income,
                net_income=current_net_income,
                total_assets=assets,
                total_liabilities=liabilities,
                total_equity=equity,
                source_document_id=disclosure_source.id,
            ),
            FinancialStatement(
                ticker=item.ticker,
                fiscal_year=2025,
                fiscal_period="Q1",
                period_end_date=date(2025, 3, 31),
                revenue=previous_revenue,
                operating_income=previous_operating_income,
                net_income=previous_revenue * Decimal("0.09"),
                total_assets=assets * Decimal("0.95"),
                total_liabilities=liabilities * Decimal("0.95"),
                total_equity=equity * Decimal("0.95"),
                source_document_id=disclosure_source.id,
            ),
            Disclosure(
                ticker=item.ticker,
                provider="OpenDART",
                receipt_no=f"20260608{index:06d}",
                title=f"{item.company_name} 2026 Q1 정기보고서",
                disclosure_type="periodic_report",
                published_at=published_at,
                source_url=disclosure_source.source_url,
                source_document_id=disclosure_source.id,
                raw_payload={"provider": "OpenDART", "ticker": item.ticker},
            ),
            NewsItem(
                ticker=item.ticker,
                provider="NAVER_NEWS",
                title=f"{item.company_name} 공개 데이터 검토 포인트",
                summary="공개 뉴스에서 사업 흐름 확인 포인트가 발견되었습니다.",
                publisher="NAVER News",
                published_at=published_at,
                source_url=news_source.source_url or "",
                sentiment_label="neutral",
                source_document_id=news_source.id,
                raw_payload={"provider": "NAVER_NEWS", "ticker": item.ticker},
            ),
            PriceMetric(
                ticker=item.ticker,
                trade_date=PROVIDER_FIXTURE_AS_OF_DATE,
                close_price=Decimal(40_000 + index * 750),
                volume=Decimal(1_500_000 + index * 25_000),
                trading_value=Decimal(80_000_000_000 + index * 1_000_000_000),
                market_cap=current_net_income * Decimal("14.5"),
                change_rate=Decimal("0.8000"),
                volatility_20d=Decimal("0.210000"),
                momentum_20d=Decimal("0.035000"),
                source="KRX",
            ),
        ]
    )
    disclosure_evidence_id = f"ev_provider_{item.ticker}_disclosure"
    news_evidence_id = f"ev_provider_{item.ticker}_news"
    session.add_all(
        [
            EvidenceChunk(
                evidence_id=disclosure_evidence_id,
                ticker=item.ticker,
                source_document_id=disclosure_source.id,
                evidence_type="financial_stability",
                chunk_text="OpenDART 공시에서 재무 안정성 검토 포인트가 확인됩니다.",
                source_url=disclosure_source.source_url,
                published_at=published_at,
                fetched_at=fetched_at,
                confidence=Decimal("0.8200"),
                metadata_={"provider": "OpenDART", "fixture": "provider_sample"},
            ),
            EvidenceChunk(
                evidence_id=news_evidence_id,
                ticker=item.ticker,
                source_document_id=news_source.id,
                evidence_type="news_attention",
                chunk_text="NAVER 뉴스에서 시장 관심도 검토 포인트가 확인됩니다.",
                source_url=news_source.source_url,
                published_at=published_at,
                fetched_at=fetched_at,
                confidence=Decimal("0.7600"),
                metadata_={"provider": "NAVER_NEWS", "fixture": "provider_sample"},
            ),
            RiskSignal(
                ticker=item.ticker,
                as_of_date=PROVIDER_FIXTURE_AS_OF_DATE,
                risk_tag="provider_data_review",
                severity="medium",
                penalty_points=Decimal("2.50"),
                display_text="원천 데이터의 최신성과 공시 원문 확인이 필요합니다.",
                description="원천 데이터의 최신성과 공시 원문 확인이 필요합니다.",
                evidence_ids=[disclosure_evidence_id, news_evidence_id],
            ),
        ]
    )
