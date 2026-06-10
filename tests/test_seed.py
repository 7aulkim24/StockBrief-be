from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.orm import (
    CompanyIdentifier,
    Disclosure,
    EvidenceChunk,
    FinancialStatement,
    NewsItem,
    PriceMetric,
    RecommendationReason,
    RecommendationScore,
    RiskSignal,
    SourceDocument,
    Stock,
)
from app.seed.mock_data import MOCK_STOCKS
from app.seed.seed_mock_data import seed_mock_data


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _text_values(values: Iterable[object]) -> str:
    return "\n".join(str(value) for value in values if value is not None)


def test_seeded_session_fixture_loads_mvp_vertical_flow_data(
    seeded_session: Session,
) -> None:
    seed_stock_count = len(MOCK_STOCKS)

    assert seed_stock_count >= 30
    assert _count(seeded_session, Stock) == seed_stock_count
    assert _count(seeded_session, CompanyIdentifier) == seed_stock_count * 2
    assert _count(seeded_session, FinancialStatement) == seed_stock_count
    assert _count(seeded_session, Disclosure) == seed_stock_count
    assert _count(seeded_session, NewsItem) == seed_stock_count
    assert _count(seeded_session, PriceMetric) == seed_stock_count
    assert _count(seeded_session, SourceDocument) == seed_stock_count * 2
    assert _count(seeded_session, EvidenceChunk) == seed_stock_count * 2
    assert _count(seeded_session, RiskSignal) == seed_stock_count
    assert _count(seeded_session, RecommendationScore) == seed_stock_count
    assert _count(seeded_session, RecommendationReason) == seed_stock_count


def test_seed_includes_opendart_corp_code_and_stock_code(
    seeded_session: Session,
) -> None:
    rows = seeded_session.scalars(
        select(CompanyIdentifier).where(CompanyIdentifier.ticker == "005930")
    ).all()

    assert {
        (row.provider, row.identifier_type, row.identifier_value) for row in rows
    } == {
        ("OpenDART", "corp_code", "MOCK00126380"),
        ("OpenDART", "stock_code", "005930"),
    }


def test_seeded_candidates_pass_evidence_gate_inputs(seeded_session: Session) -> None:
    scores = seeded_session.scalars(select(RecommendationScore)).all()
    risks = seeded_session.scalars(select(RiskSignal)).all()

    assert all(score.is_candidate_eligible for score in scores)
    assert all(score.evidence_count >= 2 for score in scores)
    assert all(score.missing_data == [] for score in scores)
    assert all(score.data_freshness["as_of"] for score in scores)
    assert all(risk.display_text for risk in risks)


def test_seed_is_idempotent(seeded_session: Session) -> None:
    seed_mock_data(seeded_session)

    seed_stock_count = len(MOCK_STOCKS)

    assert _count(seeded_session, Stock) == seed_stock_count
    assert _count(seeded_session, CompanyIdentifier) == seed_stock_count * 2
    assert _count(seeded_session, RecommendationScore) == seed_stock_count
    assert _count(seeded_session, RecommendationReason) == seed_stock_count


def test_seed_user_facing_copy_uses_review_candidate_tone(
    seeded_session: Session,
) -> None:
    reasons = seeded_session.scalars(select(RecommendationReason)).all()
    evidence = seeded_session.scalars(select(EvidenceChunk)).all()
    risks = seeded_session.scalars(select(RiskSignal)).all()

    text = _text_values(
        [stock.company_name for stock in MOCK_STOCKS]
        + [reason.summary for reason in reasons]
        + [chunk.chunk_text for chunk in evidence]
        + [risk.display_text for risk in risks]
    )

    assert "공개 데이터 기준 검토 포인트" in text
    for prohibited in ["매수", "매도", "목표가", "진입가", "손절가", "수익 보장", "확실", "무조건"]:
        assert prohibited not in text
