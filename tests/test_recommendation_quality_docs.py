from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_recommendation_quality_criteria_document_covers_operating_checks() -> None:
    doc = (
        REPOSITORY_ROOT / "docs/engineering/RECOMMENDATION_QUALITY.md"
    ).read_text(encoding="utf-8")
    script = (
        REPOSITORY_ROOT / "scripts/check_recommendation_quality_smoke.py"
    ).read_text(encoding="utf-8")

    assert "Recommendation Quality Criteria" in doc
    assert "검토 후보 추천" in doc
    assert "/v1/recommendations/candidates" in doc
    assert "/v1/recommendations/candidates/{ticker}" in doc
    assert "/v1/stocks/{ticker}/evidence" in doc
    assert "data_freshness.live_evidence_latest_at" in doc
    assert "data_freshness.as_of" in doc
    assert "risk_tags" in doc
    assert "missing_data" in doc
    assert "score_components" in doc
    assert "score_component_count_mismatch" in doc
    assert "scripts/check_recommendation_quality_smoke.py" in doc
    assert "candidate_evidence_below_minimum" in doc
    assert "evidence_item_missing_source_metadata" in doc
    assert "metadata.source_identifier" in doc
    assert "provider_items_with_url" in script
    assert "internal_items_with_source_identifier" in script
    assert "EXPECTED_SCORE_COMPONENT_WEIGHTS" in script
    assert "does not print raw provider bodies" in doc
    assert "check_candidate_list" in script
    assert "check_candidate_detail" in script
    assert "check_stock_evidence" in script
