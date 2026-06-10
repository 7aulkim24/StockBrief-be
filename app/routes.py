from decimal import Decimal

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_optional_current_user
from app.config import Settings, get_settings
from app.db import get_db_session
from app.models import (
    ChatRequest,
    ChatResponse,
    CompanyIdentifierResponse,
    ErrorResponse,
    HealthResponse,
    RecommendationCandidateListResponse,
    RecommendationCandidateResponse,
    RecommendationReasonResponse,
    RiskProfile,
    ScoreComponentResponse,
    ServicePolicyResponse,
    StockDetailResponse,
    StockEvidenceItemResponse,
    StockEvidenceResponse,
    StockSearchItemResponse,
    StockSearchResponse,
    StockScoreResponse,
)
from app.orm import (
    ChatMessage,
    ChatSession,
    CompanyIdentifier,
    EvidenceChunk,
    FinancialStatement,
    PriceMetric,
    RecommendationReason,
    RecommendationScore,
    RiskSignal,
    SourceDocument,
    Stock,
    User,
)
from app.services.chat import compose_chat_answer

router = APIRouter()

COMMON_ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Resource was not found."},
    422: {"model": ErrorResponse, "description": "Request validation failed."},
}

PROHIBITED_OUTPUTS = [
    "buy_instruction",
    "sell_instruction",
    "target_price",
    "guaranteed_return",
    "entry_price",
    "stop_loss",
]

DISCLAIMER = "공개 데이터 기반 검토 후보이며 최종 투자 판단은 사용자에게 있습니다."
EVIDENCE_LEVEL_MAP = {
    "strong": "strong",
    "medium": "medium",
    "moderate": "medium",
    "weak": "weak",
    "limited": "weak",
    "insufficient": "weak",
}


@router.get(
    "/health",
    response_model=HealthResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.service_version,
    )


@router.get(
    "/meta/service-policy",
    response_model=ServicePolicyResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def service_policy() -> ServicePolicyResponse:
    return ServicePolicyResponse(
        product_type="evidence_based_stock_candidate_recommendation",
        recommendation_type="review_candidate_not_buy_sell_advice",
        prohibited_outputs=PROHIBITED_OUTPUTS,
        mvp_auth="guest_first",
    )


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
    rows = _candidate_rows(session=session, market=market, sector=sector)
    candidates = [_candidate_response(session, stock, score) for stock, score in rows]
    candidates = _sort_candidates(candidates, risk_profile)[:limit]
    return RecommendationCandidateListResponse(
        items=candidates,
        count=len(candidates),
        risk_profile=risk_profile,
        disclaimer=DISCLAIMER,
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
    stock, score = _candidate_row(session, ticker)
    return _candidate_response(session, stock, score)


@router.get(
    "/stocks/candidates",
    response_model=RecommendationCandidateListResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def list_stock_candidates(
    risk_profile: RiskProfile = "balanced",
    market: str | None = Query(default=None, pattern="^(KOSPI|KOSDAQ)$"),
    sector: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> RecommendationCandidateListResponse:
    return list_recommendation_candidates(
        risk_profile=risk_profile,
        market=market,
        sector=sector,
        limit=limit,
        session=session,
    )


@router.get(
    "/stocks/candidates/{ticker}",
    response_model=RecommendationCandidateResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_stock_candidate(
    ticker: str,
    session: Session = Depends(get_db_session),
) -> RecommendationCandidateResponse:
    return get_recommendation_candidate(ticker=ticker, session=session)


@router.get(
    "/stocks/{ticker}/score",
    response_model=StockScoreResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_stock_score(
    ticker: str,
    session: Session = Depends(get_db_session),
) -> StockScoreResponse:
    stock, score = _candidate_row(session, ticker)
    candidate = _candidate_response(session, stock, score)
    return StockScoreResponse(
        ticker=candidate.ticker,
        as_of_date=score.as_of_date,
        recommendation_score=candidate.recommendation_score,
        score_components=candidate.score_components,
        risk_tags=candidate.risk_tags,
        evidence_level=candidate.evidence_level,
        evidence_count=candidate.evidence_count,
        missing_data=candidate.missing_data,
        data_freshness=candidate.data_freshness,
        disclaimer=DISCLAIMER,
    )


@router.get(
    "/stocks/search",
    response_model=StockSearchResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def search_stocks(
    q: str = Query(default="", max_length=100),
    market: str | None = Query(default=None, pattern="^(KOSPI|KOSDAQ)$"),
    limit: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_db_session),
) -> StockSearchResponse:
    statement = select(Stock)
    if q:
        query = f"%{q}%"
        statement = statement.where(
            (Stock.ticker.like(query)) | (Stock.company_name.like(query))
        )
    if market:
        statement = statement.where(Stock.market == market)
    statement = statement.order_by(Stock.ticker.asc()).limit(limit)

    items = [
        StockSearchItemResponse(
            ticker=stock.ticker,
            name=stock.company_name,
            market=stock.market,
            sector=stock.sector,
            industry=stock.industry,
        )
        for stock in session.scalars(statement).all()
    ]
    return StockSearchResponse(query=q, count=len(items), items=items)


@router.get(
    "/stocks/{ticker}",
    response_model=StockDetailResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_stock(
    ticker: str,
    session: Session = Depends(get_db_session),
) -> StockDetailResponse:
    stock = _stock_or_404(session, ticker)
    identifiers = session.scalars(
        select(CompanyIdentifier)
        .where(CompanyIdentifier.ticker == ticker)
        .order_by(CompanyIdentifier.is_primary.desc(), CompanyIdentifier.identifier_type.asc())
    ).all()
    return StockDetailResponse(
        ticker=stock.ticker,
        name=stock.company_name,
        name_en=stock.company_name_en,
        market=stock.market,
        sector=stock.sector,
        industry=stock.industry,
        listing_date=stock.listing_date,
        is_active=stock.is_active,
        identifiers=[
            CompanyIdentifierResponse(
                provider=identifier.provider,
                identifier_type=identifier.identifier_type,
                identifier_value=identifier.identifier_value,
                is_primary=identifier.is_primary,
            )
            for identifier in identifiers
        ],
    )


@router.get(
    "/stocks/{ticker}/evidence",
    response_model=StockEvidenceResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def get_stock_evidence(
    ticker: str,
    types: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> StockEvidenceResponse:
    _stock_or_404(session, ticker)
    requested_types = _parse_evidence_types(types)
    evidence = _evidence_items(session, ticker, requested_types)
    limited = evidence[:limit]
    message = None
    if not limited:
        message = "요청한 조건에서 확인 가능한 근거 데이터가 충분하지 않습니다."
    return StockEvidenceResponse(ticker=ticker, evidence=limited, message=message)


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses=COMMON_ERROR_RESPONSES,
)
def chat(
    request: ChatRequest,
    session: Session = Depends(get_db_session),
    current_user: User | None = Depends(get_optional_current_user),
) -> ChatResponse:
    stock, score = _candidate_row(session, request.ticker)
    candidate = _candidate_response(session, stock, score)
    evidence = _evidence_items(session, request.ticker, _parse_evidence_types(None))
    response = compose_chat_answer(
        message=request.message,
        candidate=candidate,
        evidence=evidence,
    )
    if current_user is None:
        return response
    return _persist_chat_exchange(
        session=session,
        user=current_user,
        request=request,
        response=response,
    )


def _candidate_rows(
    session: Session,
    market: str | None,
    sector: str | None,
) -> list[tuple[Stock, RecommendationScore]]:
    statement = (
        select(Stock, RecommendationScore)
        .join(RecommendationScore, RecommendationScore.ticker == Stock.ticker)
        .where(RecommendationScore.is_candidate_eligible.is_(True))
    )
    if market:
        statement = statement.where(Stock.market == market)
    if sector:
        statement = statement.where(Stock.sector == sector)

    return [
        (stock, score)
        for stock, score in session.execute(statement).all()
        if _passes_evidence_gate(session, stock, score)
    ]


def _persist_chat_exchange(
    *,
    session: Session,
    user: User,
    request: ChatRequest,
    response: ChatResponse,
) -> ChatResponse:
    session_id = request.session_id or f"chat_{uuid.uuid4().hex}"
    chat_session = session.scalars(
        select(ChatSession).where(
            ChatSession.session_id == session_id,
            ChatSession.user_id == user.id,
        )
    ).first()
    if chat_session is None:
        chat_session = ChatSession(
            session_id=session_id,
            user_id=user.id,
            title=request.title,
            ticker=request.ticker,
        )
        session.add(chat_session)
    else:
        chat_session.ticker = request.ticker
        if request.title:
            chat_session.title = request.title
    chat_session.updated_at = datetime.now(timezone.utc)

    user_message_id = f"msg_{uuid.uuid4().hex}"
    assistant_message_id = f"msg_{uuid.uuid4().hex}"
    session.add_all(
        [
            ChatMessage(
                message_id=user_message_id,
                session_id=session_id,
                role="user",
                content=request.message,
                ticker=request.ticker,
                citations=[],
                safety_flags=[],
            ),
            ChatMessage(
                message_id=assistant_message_id,
                session_id=session_id,
                role="assistant",
                content=response.answer,
                ticker=request.ticker,
                citations=[citation.model_dump(mode="json") for citation in response.citations],
                safety_flags=[{"policy_status": response.policy_status}],
            ),
        ]
    )
    session.commit()
    return response.model_copy(
        update={
            "session_id": session_id,
            "message_id": assistant_message_id,
        }
    )


def _stock_or_404(session: Session, ticker: str) -> Stock:
    stock = session.get(Stock, ticker)
    if stock is None:
        raise HTTPException(status_code=404, detail="Stock was not found.")
    return stock


def _candidate_row(
    session: Session,
    ticker: str,
) -> tuple[Stock, RecommendationScore]:
    row = session.execute(
        select(Stock, RecommendationScore)
        .join(RecommendationScore, RecommendationScore.ticker == Stock.ticker)
        .where(Stock.ticker == ticker)
    ).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Recommendation candidate was not found.",
        )
    stock, score = row
    return stock, score


def _candidate_response(
    session: Session,
    stock: Stock,
    score: RecommendationScore,
) -> RecommendationCandidateResponse:
    reasons = session.scalars(
        select(RecommendationReason)
        .where(RecommendationReason.recommendation_score_id == score.id)
        .order_by(RecommendationReason.created_at.asc())
    ).all()
    risks = session.scalars(
        select(RiskSignal)
        .where(
            RiskSignal.ticker == stock.ticker,
            RiskSignal.as_of_date == score.as_of_date,
        )
        .order_by(RiskSignal.created_at.asc())
    ).all()

    return RecommendationCandidateResponse(
        ticker=stock.ticker,
        name=stock.company_name,
        market=stock.market,
        sector=stock.sector,
        recommendation_score=_float(score.total_score),
        score_components=_score_components(score.component_scores),
        recommendation_reasons=[
            RecommendationReasonResponse(
                reason_id=reason.reason_id,
                component=reason.component,
                summary=reason.summary,
                evidence_ids=list(reason.evidence_ids or []),
                source_document_ids=list(reason.source_document_ids or []),
            )
            for reason in reasons
        ],
        risk_tags=[risk.risk_tag for risk in risks],
        evidence_level=_evidence_level(score.evidence_level),
        evidence_count=score.evidence_count,
        missing_data=list(score.missing_data or []),
        data_freshness=dict(score.data_freshness or {}),
        disclaimer=DISCLAIMER,
    )


def _passes_evidence_gate(
    session: Session,
    stock: Stock,
    score: RecommendationScore,
) -> bool:
    if score.evidence_count < 2:
        return False
    if not isinstance(score.missing_data, list):
        return False
    if not isinstance(score.data_freshness, dict) or not score.data_freshness.get("as_of"):
        return False
    risk_count = session.scalar(
        select(RiskSignal)
        .where(
            RiskSignal.ticker == stock.ticker,
            RiskSignal.as_of_date == score.as_of_date,
        )
        .limit(1)
    )
    return risk_count is not None


def _score_components(components: list[dict[str, object]]) -> list[ScoreComponentResponse]:
    responses = [
        ScoreComponentResponse(
            name=str(component["name"]),
            weight=int(component["weight"]),
            raw_score=_optional_float(component.get("raw_score")),
            weighted_score=_float(component.get("weighted_score")),
            reason=str(component.get("reason", "공개 데이터 기준 검토 포인트입니다.")),
            input_refs=[str(item) for item in component.get("input_refs", [])],
            evidence_ids=[str(item) for item in component.get("evidence_ids", [])],
        )
        for component in components
    ]
    if len(responses) != 8:
        raise HTTPException(
            status_code=500,
            detail="Stored recommendation score must contain 8 score components.",
        )
    return responses


def _sort_candidates(
    candidates: list[RecommendationCandidateResponse],
    risk_profile: RiskProfile,
) -> list[RecommendationCandidateResponse]:
    if risk_profile == "conservative":
        return sorted(candidates, key=lambda item: (len(item.risk_tags), -item.recommendation_score))
    if risk_profile == "aggressive":
        return sorted(candidates, key=lambda item: item.recommendation_score, reverse=True)
    return sorted(
        candidates,
        key=lambda item: item.recommendation_score - len(item.risk_tags) * 0.5,
        reverse=True,
    )


def _evidence_level(value: str) -> str:
    return EVIDENCE_LEVEL_MAP.get(value, "weak")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _float(value)


def _float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _parse_evidence_types(types: str | None) -> set[str]:
    allowed = {"financial", "news", "disclosure", "price"}
    if not types:
        return allowed
    parsed = {item.strip() for item in types.split(",") if item.strip()}
    invalid = parsed - allowed
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported evidence types: {', '.join(sorted(invalid))}.",
        )
    return parsed


def _evidence_items(
    session: Session,
    ticker: str,
    requested_types: set[str],
) -> list[StockEvidenceItemResponse]:
    items: list[StockEvidenceItemResponse] = []
    if "financial" in requested_types:
        items.extend(_financial_evidence(session, ticker))
    if "disclosure" in requested_types or "news" in requested_types:
        items.extend(_chunk_evidence(session, ticker, requested_types))
    if "price" in requested_types:
        items.extend(_price_evidence(session, ticker))
    return sorted(
        items,
        key=lambda item: (item.as_of_date is None, item.as_of_date, item.id),
        reverse=True,
    )


def _financial_evidence(
    session: Session,
    ticker: str,
) -> list[StockEvidenceItemResponse]:
    financials = session.scalars(
        select(FinancialStatement)
        .where(FinancialStatement.ticker == ticker)
        .order_by(FinancialStatement.period_end_date.desc())
    ).all()
    items = []
    for row in financials:
        source = session.get(SourceDocument, row.source_document_id) if row.source_document_id else None
        items.append(
            StockEvidenceItemResponse(
                id=f"financial_{ticker}_{row.fiscal_year}_{row.fiscal_period}",
                type="financial",
                title=f"{row.fiscal_year} {row.fiscal_period} 재무 mock 근거",
                summary="재무제표 mock 데이터의 주요 수치가 검토 근거로 사용됩니다.",
                source_name=source.source_name if source else "FINANCIAL_MOCK",
                source_url=source.source_url if source else None,
                source_identifier=source.external_id if source else f"{ticker}-{row.fiscal_year}-{row.fiscal_period}",
                published_at=source.published_at if source else None,
                as_of_date=row.period_end_date,
                data_status="available",
            )
        )
    return items


def _chunk_evidence(
    session: Session,
    ticker: str,
    requested_types: set[str],
) -> list[StockEvidenceItemResponse]:
    chunks = session.scalars(
        select(EvidenceChunk)
        .where(EvidenceChunk.ticker == ticker)
        .order_by(EvidenceChunk.fetched_at.desc())
    ).all()
    items = []
    for chunk in chunks:
        source = session.get(SourceDocument, chunk.source_document_id)
        evidence_type = _source_type_to_evidence_type(source.source_type if source else "")
        if evidence_type not in requested_types:
            continue
        items.append(
            StockEvidenceItemResponse(
                id=chunk.evidence_id,
                type=evidence_type,
                title=source.title if source else f"{ticker} 근거 데이터",
                summary=chunk.chunk_text,
                source_name=source.source_name if source else "UNKNOWN_SOURCE",
                source_url=chunk.source_url or (source.source_url if source else None),
                source_identifier=source.external_id if source else str(chunk.source_document_id),
                published_at=chunk.published_at or (source.published_at if source else None),
                as_of_date=(chunk.published_at.date() if chunk.published_at else None),
                data_status="available",
            )
        )
    return items


def _price_evidence(
    session: Session,
    ticker: str,
) -> list[StockEvidenceItemResponse]:
    prices = session.scalars(
        select(PriceMetric)
        .where(PriceMetric.ticker == ticker)
        .order_by(PriceMetric.trade_date.desc())
    ).all()
    return [
        StockEvidenceItemResponse(
            id=f"price_{ticker}_{row.trade_date.isoformat()}",
            type="price",
            title=f"{row.trade_date.isoformat()} 가격 지표 fallback mock",
            summary="가격과 유동성 fallback mock 데이터가 검토 근거로 사용됩니다.",
            source_name=row.source,
            source_url=None,
            source_identifier=f"{row.source}:{ticker}:{row.trade_date.isoformat()}",
            published_at=None,
            as_of_date=row.trade_date,
            data_status="fallback" if "FALLBACK" in row.source else "available",
        )
        for row in prices
    ]


def _source_type_to_evidence_type(source_type: str) -> str:
    if source_type == "news":
        return "news"
    if source_type == "disclosure":
        return "disclosure"
    if source_type == "financial":
        return "financial"
    if source_type == "price":
        return "price"
    return "disclosure"
