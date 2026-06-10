from datetime import date

from app.services.recommendation import (
    EvidenceReference,
    RecommendationScoreInput,
    RiskPenaltyInput,
    calculate_recommendation_score,
)


def _base_input() -> RecommendationScoreInput:
    return RecommendationScoreInput(
        ticker="005930",
        as_of_date=date(2026, 6, 9),
        financials={
            "revenue": 100_000_000_000,
            "operating_income": 13_000_000_000,
            "net_income": 10_000_000_000,
            "total_assets": 300_000_000_000,
            "total_liabilities": 90_000_000_000,
            "total_equity": 210_000_000_000,
        },
        previous_financials={
            "revenue": 90_000_000_000,
            "operating_income": 10_000_000_000,
        },
        price_metrics={
            "market_cap": 180_000_000_000,
            "volume": 1_500_000,
            "trading_value": 120_000_000_000,
            "momentum_20d": 0.08,
            "volatility_20d": 0.21,
        },
        evidence=[
            EvidenceReference(
                evidence_id="ev_financial",
                evidence_type="financial_stability",
                source_type="disclosure",
                confidence=0.9,
            ),
            EvidenceReference(
                evidence_id="ev_profit",
                evidence_type="profitability",
                source_type="disclosure",
                confidence=0.8,
            ),
            EvidenceReference(
                evidence_id="ev_news",
                evidence_type="news_attention",
                source_type="news",
                confidence=0.7,
            ),
            EvidenceReference(
                evidence_id="ev_disclosure",
                evidence_type="disclosure_event",
                source_type="disclosure",
                confidence=0.85,
            ),
        ],
        risks=[
            RiskPenaltyInput(
                risk_tag="high_volatility",
                penalty_points=2.5,
                display_text="변동성 지표 확인이 필요합니다.",
                evidence_ids=["ev_news"],
            )
        ],
    )


def test_score_engine_is_deterministic_for_same_input() -> None:
    score_input = _base_input()

    first = calculate_recommendation_score(score_input)
    second = calculate_recommendation_score(score_input)

    assert first == second


def test_score_engine_deterministic_snapshot_for_base_input() -> None:
    result = calculate_recommendation_score(_base_input())

    assert result.total_score == 75.5
    assert result.evidence_count == 4
    assert result.evidence_level == "strong"
    assert result.risk_penalty == 2.5
    assert [component.name for component in result.components] == [
        "financial_stability",
        "profitability",
        "growth",
        "valuation",
        "news_attention",
        "disclosure_event",
        "liquidity",
        "momentum_volatility",
    ]
    assert [reason.component for reason in result.reasons] == [
        "financial_stability",
        "growth",
        "profitability",
    ]


def test_score_total_is_bounded_and_has_eight_components() -> None:
    result = calculate_recommendation_score(_base_input())

    assert 0 <= result.total_score <= 100
    assert len(result.components) == 8
    assert sum(component.weight for component in result.components) == 100
    assert all(0 <= component.weighted_score <= component.weight for component in result.components)


def test_missing_data_is_reported_and_weak_evidence_level_when_inputs_are_sparse() -> None:
    result = calculate_recommendation_score(
        RecommendationScoreInput(
            ticker="000000",
            as_of_date=date(2026, 6, 9),
            financials=None,
            previous_financials=None,
            price_metrics=None,
            evidence=[],
            risks=[],
        )
    )

    assert result.total_score == 0
    assert result.evidence_level == "weak"
    assert "financial_stability.inputs" in result.missing_data
    assert "growth.inputs" in result.missing_data
    assert "liquidity.inputs" in result.missing_data


def test_fallback_price_metrics_are_used_without_marking_price_components_missing() -> None:
    score_input = _base_input().model_copy(
        update={
            "price_metrics": None,
            "fallback_price_metrics": {
                "market_cap": 180_000_000_000,
                "volume": 1_500_000,
                "trading_value": 120_000_000_000,
                "momentum_20d": 0.08,
                "volatility_20d": 0.21,
            },
        }
    )

    result = calculate_recommendation_score(score_input)

    assert set(result.fallback_data) == {
        "liquidity",
        "momentum_volatility",
        "valuation",
    }
    assert "liquidity.inputs" not in result.missing_data
    assert "valuation.inputs" not in result.missing_data


def test_risk_penalty_reduces_total_score() -> None:
    base = _base_input()
    without_risk = calculate_recommendation_score(base.model_copy(update={"risks": []}))
    with_risk = calculate_recommendation_score(base)

    assert with_risk.risk_penalty == 2.5
    assert with_risk.total_score == round(without_risk.total_score - 2.5, 1)


def test_evidence_level_rules() -> None:
    strong = calculate_recommendation_score(_base_input())
    medium = calculate_recommendation_score(
        _base_input().model_copy(update={"evidence": _base_input().evidence[:2]})
    )
    weak = calculate_recommendation_score(
        _base_input().model_copy(update={"evidence": _base_input().evidence[:1]})
    )

    assert strong.evidence_level == "strong"
    assert medium.evidence_level == "medium"
    assert weak.evidence_level == "weak"


def test_reasons_use_top_contributors_and_evidence_without_trading_language() -> None:
    result = calculate_recommendation_score(_base_input())

    assert len(result.reasons) == 3
    assert result.reasons[0].contribution >= result.reasons[-1].contribution
    assert any(reason.evidence_ids for reason in result.reasons)

    reason_text = "\n".join(reason.summary for reason in result.reasons)
    assert "공개 데이터 기준" in reason_text
    for prohibited in ["매수", "매도", "목표가", "진입가", "손절가", "수익 보장", "확실", "무조건"]:
        assert prohibited not in reason_text
