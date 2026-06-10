from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceLevel = Literal["strong", "medium", "weak"]


class EvidenceReference(BaseModel):
    evidence_id: str
    evidence_type: str
    source_type: str
    confidence: float = Field(default=1.0, ge=0, le=1)


class RiskPenaltyInput(BaseModel):
    risk_tag: str
    penalty_points: float = Field(default=0, ge=0)
    display_text: str
    evidence_ids: list[str] = Field(default_factory=list)


class RecommendationScoreInput(BaseModel):
    ticker: str
    as_of_date: date
    financials: dict[str, Any] | None = None
    previous_financials: dict[str, Any] | None = None
    price_metrics: dict[str, Any] | None = None
    fallback_price_metrics: dict[str, Any] | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    risks: list[RiskPenaltyInput] = Field(default_factory=list)


class ScoreComponent(BaseModel):
    name: str
    weight: int
    raw_score: float | None
    weighted_score: float
    reason: str
    input_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    used_fallback: bool = False
    missing_data: list[str] = Field(default_factory=list)


class RecommendationReason(BaseModel):
    component: str
    summary: str
    contribution: float
    evidence_ids: list[str] = Field(default_factory=list)


class RecommendationScoreResult(BaseModel):
    ticker: str
    as_of_date: date
    total_score: float = Field(ge=0, le=100)
    components: list[ScoreComponent]
    missing_data: list[str] = Field(default_factory=list)
    fallback_data: list[str] = Field(default_factory=list)
    risk_penalty: float = Field(default=0, ge=0)
    evidence_count: int = Field(ge=0)
    evidence_level: EvidenceLevel
    reasons: list[RecommendationReason] = Field(default_factory=list)

