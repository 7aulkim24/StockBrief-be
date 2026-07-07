from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import (
    RecommendationCandidateContractResponse,
    RecommendationCandidateListResponse,
    RecommendationCandidateResponse,
    RiskProfile,
    StockCandidateContractResponse,
    StockScoreResponse,
)
from app.routes.common import COMMON_ERROR_RESPONSES, request_id
from app.services.candidate_service import CandidateService

router = APIRouter()


@router.get(
    "/recommendations/candidates",
    response_model=RecommendationCandidateListResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def list_recommendation_candidates(
    risk_profile: RiskProfile = "balanced",
    market: str | None = Query(default=None, pattern="^(KOSPI|KOSDAQ)$"),
    sector: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> RecommendationCandidateListResponse:
    return CandidateService(session).list_recommendation_candidates(
        risk_profile=risk_profile,
        market=market,
        sector=sector,
        limit=limit,
    )


@router.get(
    "/recommendations/candidates/{ticker}",
    response_model=RecommendationCandidateResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_recommendation_candidate(
    ticker: str,
    session: Session = Depends(get_db_session),
) -> RecommendationCandidateResponse:
    return CandidateService(session).get_recommendation_candidate(ticker)


@router.get(
    "/stocks/candidates",
    response_model=StockCandidateContractResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def list_stock_candidates(
    request: Request,
    risk_profile: RiskProfile = "balanced",
    market: str | None = Query(default=None, pattern="^(KOSPI|KOSDAQ)$"),
    sector: str | None = None,
    sort: str = Query(default="score_desc", pattern="^(score_desc|volume_desc|updated_desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> StockCandidateContractResponse:
    data = CandidateService(session).list_stock_candidates(
        risk_profile=risk_profile,
        market=market,
        sector=sector,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return StockCandidateContractResponse(
        data=data,
        message="추천 후보 목록을 반환했습니다.",
        request_id=request_id(request),
    )


@router.get(
    "/stocks/candidates/{ticker}",
    response_model=RecommendationCandidateContractResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_stock_candidate(
    ticker: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> RecommendationCandidateContractResponse:
    candidate = CandidateService(session).get_recommendation_candidate(ticker)
    return RecommendationCandidateContractResponse(
        data=candidate,
        message="추천 후보 상세를 반환했습니다.",
        request_id=request_id(request),
    )


@router.get(
    "/stocks/{ticker}/score",
    response_model=StockScoreResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_stock_score(
    ticker: str,
    session: Session = Depends(get_db_session),
) -> StockScoreResponse:
    return CandidateService(session).stock_score(ticker)
