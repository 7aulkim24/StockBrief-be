from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.orm import (
    EvidenceChunk,
    RecommendationReason,
    RecommendationScore,
    RiskSignal,
    SourceDocument,
)
from app.services.recommendation.engine import SCORE_VERSION
from app.services.recommendation.materializer import materialize_recommendation_scores


AS_OF_DATE = date(2026, 6, 9)


def _factor_score(session: Session) -> RecommendationScore:
    return session.scalars(
        select(RecommendationScore).where(
            RecommendationScore.ticker == "005930",
            RecommendationScore.as_of_date == AS_OF_DATE,
            RecommendationScore.score_version == SCORE_VERSION,
        )
    ).one()


def test_materializer_persists_factor_rank_snapshot_from_seeded_rows(
    seeded_session: Session,
) -> None:
    result = materialize_recommendation_scores(
        seeded_session,
        as_of_date=AS_OF_DATE,
        tickers=["005930"],
    )

    score = _factor_score(seeded_session)
    reason_count = seeded_session.scalar(
        select(func.count())
        .select_from(RecommendationReason)
        .where(RecommendationReason.recommendation_score_id == score.id)
    )
    risk_count = seeded_session.scalar(
        select(func.count())
        .select_from(RiskSignal)
        .where(RiskSignal.ticker == "005930", RiskSignal.as_of_date == AS_OF_DATE)
    )

    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["score_version"] == SCORE_VERSION
    assert score.evidence_count == 2
    assert score.evidence_level == "medium"
    assert score.is_candidate_eligible is True
    assert len(score.component_scores) == 8
    assert score.missing_data == []
    assert score.data_freshness["as_of"] == "2026-06-09"
    assert score.data_freshness["risk_penalty"] == 2.5
    assert score.data_freshness["fallback_data"] == []
    assert reason_count == 3
    assert risk_count == 1


def test_materializer_rerun_does_not_duplicate_score_rows(
    seeded_session: Session,
) -> None:
    materialize_recommendation_scores(
        seeded_session,
        as_of_date=AS_OF_DATE,
        tickers=["005930"],
    )
    second = materialize_recommendation_scores(
        seeded_session,
        as_of_date=AS_OF_DATE,
        tickers=["005930"],
    )
    score = _factor_score(seeded_session)
    score_count = seeded_session.scalar(
        select(func.count())
        .select_from(RecommendationScore)
        .where(
            RecommendationScore.ticker == "005930",
            RecommendationScore.as_of_date == AS_OF_DATE,
            RecommendationScore.score_version == SCORE_VERSION,
        )
    )
    reason_count = seeded_session.scalar(
        select(func.count())
        .select_from(RecommendationReason)
        .where(RecommendationReason.recommendation_score_id == score.id)
    )
    risk_count = seeded_session.scalar(
        select(func.count())
        .select_from(RiskSignal)
        .where(RiskSignal.ticker == "005930", RiskSignal.as_of_date == AS_OF_DATE)
    )

    assert second["created"] == 0
    assert second["updated"] == 1
    assert score_count == 1
    assert reason_count == 3
    assert risk_count == 1


def test_materializer_ignores_legacy_mock_evidence_rows(
    seeded_session: Session,
) -> None:
    fetched_at = datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc)
    source = SourceDocument(
        ticker="005930",
        source_type="news",
        source_name="NAVER_NEWS",
        source_url="https://news.example.com/legacy-mock",
        external_id="legacy-mock-news",
        title="legacy mock evidence",
        published_at=fetched_at,
        fetched_at=fetched_at,
        raw_content="legacy mock content",
        metadata_={"provider": "NAVER_NEWS"},
    )
    seeded_session.add(source)
    seeded_session.flush()
    seeded_session.add(
        EvidenceChunk(
            evidence_id="ev_mock_005930_news",
            ticker="005930",
            source_document_id=source.id,
            evidence_type="news_attention",
            chunk_text="legacy mock evidence should not be scored",
            source_url=source.source_url,
            published_at=fetched_at,
            fetched_at=fetched_at,
            confidence=Decimal("0.9900"),
            metadata_={"provider": "NAVER_NEWS"},
        )
    )
    seeded_session.add(
        EvidenceChunk(
            evidence_id="evXmock_005930_news",
            ticker="005930",
            source_document_id=source.id,
            evidence_type="news_attention",
            chunk_text="similarly named evidence should still be scored",
            source_url=source.source_url,
            published_at=fetched_at,
            fetched_at=fetched_at,
            confidence=Decimal("0.9900"),
            metadata_={"provider": "NAVER_NEWS"},
        )
    )
    seeded_session.commit()

    materialize_recommendation_scores(
        seeded_session,
        as_of_date=AS_OF_DATE,
        tickers=["005930"],
    )

    score = _factor_score(seeded_session)
    reasons = seeded_session.scalars(
        select(RecommendationReason).where(
            RecommendationReason.recommendation_score_id == score.id
        )
    ).all()
    component_evidence = [
        evidence_id
        for component in score.component_scores
        for evidence_id in component.get("evidence_ids", [])
    ]
    reason_evidence = [evidence_id for reason in reasons for evidence_id in reason.evidence_ids]

    assert "ev_mock_005930_news" not in component_evidence
    assert "ev_mock_005930_news" not in reason_evidence
    assert "evXmock_005930_news" in component_evidence
