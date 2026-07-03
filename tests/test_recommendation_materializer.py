from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.orm import RecommendationReason, RecommendationScore, RiskSignal
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
