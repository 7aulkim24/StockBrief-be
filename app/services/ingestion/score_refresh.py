"""Recommendation score snapshot refresh orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.orm import PriceMetric, RecommendationScore, Stock
from app.services.ingestion.event_helpers import (
    _event_as_of_date,
    _event_market_filter,
    _event_tickers,
    _unique_tickers,
)
from app.services.ingestion.parsing import _string_or_none
from app.services.ingestion.request import (
    ProviderIngestionRequest,
    _nonnegative_int,
    _positive_int,
)
from app.services.recommendation.materializer import materialize_recommendation_scores


SCORE_REFRESH_UNIVERSE_LIMITS = {
    "all": 300,
    "tier_a": 100,
    "tier_b": 300,
}

def handle_refresh_score_snapshots_event(event: dict[str, object]) -> dict[str, Any]:
    # Lazy lookup keeps app.services.ingestion.get_session_factory patchable.
    from app.services import ingestion as _ingestion_pkg

    with _ingestion_pkg.get_session_factory()() as session:
        result = refresh_score_snapshots(session, event)
        session.commit()
    if event.get("raise_on_failure") is True and result.get("ok") is False:
        raise RuntimeError("refresh_score_snapshots_failed")
    return result

def refresh_score_snapshots(session: Session, event: dict[str, object]) -> dict[str, Any]:
    as_of_date = _event_as_of_date(event)
    requested_tickers = _event_tickers(event)
    ingestion_result: dict[str, Any] | None = None
    provider_statuses: dict[str, dict[str, Any]] = {}
    batch_tickers: list[str] | None = None

    if event.get("provider"):
        request = ProviderIngestionRequest.from_event(event)
        # Lazy lookup keeps app.services.ingestion.ProviderIngestionService patchable.
        from app.services import ingestion as _ingestion_pkg

        ingestion_result = _ingestion_pkg.ProviderIngestionService(session).run_provider_batch(request)
        provider_statuses = _provider_freshness_statuses(ingestion_result)
        refresh_tickers = _successful_ingestion_tickers(ingestion_result)
        target_tickers = _unique_tickers(request.tickers)
    else:
        refresh_tickers = _unique_tickers(requested_tickers)
        if not refresh_tickers:
            batch_tickers = _score_refresh_tickers(session, event)
            if batch_tickers is not None:
                refresh_tickers = batch_tickers
        target_tickers = refresh_tickers
        provider_statuses = {
            "refresh_operation": {
                "status": "stale",
                "reason": "no_provider_ingestion",
                "as_of": as_of_date.isoformat(),
            }
        }

    materializer_tickers = refresh_tickers if batch_tickers is not None else (refresh_tickers or None)
    if ingestion_result is not None and not refresh_tickers:
        refresh_result: dict[str, int | str] = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "reasons": 0,
            "risk_signals": 0,
        }
    else:
        refresh_result = materialize_recommendation_scores(
            session,
            as_of_date=as_of_date,
            tickers=materializer_tickers,
        )

    annotated = _annotate_score_provider_freshness(
        session,
        as_of_date=as_of_date,
        tickers=refresh_tickers or target_tickers,
        score_version=_string_or_none(refresh_result.get("score_version")),
        provider_statuses=provider_statuses,
    )
    provider_status = _aggregate_provider_status(provider_statuses)
    return {
        "ok": provider_status in {"success", "stale"} and int(refresh_result["processed"]) > 0,
        "operation": "refresh_score_snapshots",
        "as_of_date": as_of_date.isoformat(),
        "ingestion": ingestion_result,
        "successful_tickers": refresh_tickers,
        "failed_tickers": _failed_ingestion_tickers(ingestion_result),
        "provider_status": provider_status,
        "provider_freshness": provider_statuses,
        "batch": _score_refresh_batch_metadata(event, batch_tickers),
        "refresh": {
            **refresh_result,
            "provider_freshness_annotated": annotated,
        },
    }

def _successful_ingestion_tickers(result: dict[str, Any] | None) -> list[str]:
    if not isinstance(result, dict):
        return []
    return [
        str(item["ticker"])
        for item in result.get("results", [])
        if isinstance(item, dict)
        if item.get("status") in {"succeeded", "replayed"}
        if item.get("ticker")
    ]

def _failed_ingestion_tickers(result: dict[str, Any] | None) -> list[str]:
    if not isinstance(result, dict):
        return []
    return [
        str(item["ticker"])
        for item in result.get("results", [])
        if isinstance(item, dict)
        if item.get("status") in {"failed", "partial_failed"}
        if item.get("ticker")
    ]

def _provider_freshness_statuses(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    provider = str(result.get("provider") or "unknown")
    successful = _successful_ingestion_tickers(result)
    failed = _failed_ingestion_tickers(result)
    status = "success"
    if failed and successful:
        status = "partial_failed"
    elif failed:
        status = "failed"
    elif result.get("ok") is False:
        status = "failed"
    return {
        provider: {
            "status": status,
            "source_date": result.get("source_date"),
            "successful_tickers": successful,
            "failed_tickers": failed,
        }
    }

def _aggregate_provider_status(provider_statuses: dict[str, dict[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in provider_statuses.values()}
    if "failed" in statuses:
        return "failed"
    if "partial_failed" in statuses:
        return "partial_failed"
    if "stale" in statuses:
        return "stale"
    return "success"

def _annotate_score_provider_freshness(
    session: Session,
    *,
    as_of_date: date,
    tickers: list[str],
    score_version: str | None,
    provider_statuses: dict[str, dict[str, Any]],
) -> int:
    if not tickers or not provider_statuses:
        return 0
    statement = select(RecommendationScore).where(
        RecommendationScore.as_of_date == as_of_date,
        RecommendationScore.ticker.in_(_unique_tickers(tickers)),
    )
    if score_version:
        statement = statement.where(RecommendationScore.score_version == score_version)
    scores = session.scalars(statement).all()
    for score in scores:
        freshness = dict(score.data_freshness or {})
        providers = dict(freshness.get("providers") or {})
        providers.update(provider_statuses)
        freshness["providers"] = providers
        score.data_freshness = freshness
    session.flush()
    return len(scores)

def _score_refresh_tickers(session: Session, event: dict[str, object]) -> list[str] | None:
    has_batch_selector = any(
        key in event
        for key in (
            "score_universe",
            "universe",
            "stock_limit",
            "stock_offset",
            "limit",
            "offset",
            "markets",
            "market",
        )
    )
    if not has_batch_selector:
        return None
    universe = _event_score_universe(event)
    markets = _event_market_filter(event)
    limit = _score_refresh_limit(event.get("stock_limit", event.get("limit")), universe=universe)
    offset = _nonnegative_int(event.get("stock_offset", event.get("offset")), default=0)
    statement = select(Stock.ticker).where(Stock.is_active.is_(True))
    if markets:
        statement = statement.where(Stock.market.in_(markets))
    if universe in {"tier_a", "tier_b"}:
        latest_price_dates = (
            select(
                PriceMetric.ticker.label("ticker"),
                func.max(PriceMetric.trade_date).label("trade_date"),
            )
            .group_by(PriceMetric.ticker)
            .subquery()
        )
        statement = (
            statement.outerjoin(
                latest_price_dates,
                latest_price_dates.c.ticker == Stock.ticker,
            )
            .outerjoin(
                PriceMetric,
                and_(
                    PriceMetric.ticker == Stock.ticker,
                    PriceMetric.trade_date == latest_price_dates.c.trade_date,
                ),
            )
            .order_by(
                PriceMetric.market_cap.is_(None).asc(),
                PriceMetric.market_cap.desc(),
                PriceMetric.trading_value.is_(None).asc(),
                PriceMetric.trading_value.desc(),
                Stock.ticker.asc(),
            )
        )
    else:
        statement = statement.order_by(Stock.ticker.asc())
    return list(
        session.scalars(
            statement.limit(limit).offset(offset)
        ).all()
    )

def _score_refresh_batch_metadata(
    event: dict[str, object],
    tickers: list[str] | None,
) -> dict[str, object] | None:
    if tickers is None:
        return None
    return {
        "universe": _event_score_universe(event),
        "limit": _score_refresh_limit(
            event.get("stock_limit", event.get("limit")),
            universe=_event_score_universe(event),
        ),
        "offset": _nonnegative_int(event.get("stock_offset", event.get("offset")), default=0),
        "markets": _event_market_filter(event),
        "selected_count": len(tickers),
        "first_ticker": tickers[0] if tickers else None,
        "last_ticker": tickers[-1] if tickers else None,
    }

def _event_score_universe(event: dict[str, object]) -> str:
    value = event.get("score_universe", event.get("universe", "all"))
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in SCORE_REFRESH_UNIVERSE_LIMITS:
        return normalized
    return "all"

def _score_refresh_limit(value: object, *, universe: str = "all") -> int:
    limit = _positive_int(
        value,
        default=SCORE_REFRESH_UNIVERSE_LIMITS.get(universe, 300),
    )
    return min(limit, 300)
