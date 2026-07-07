"""KRX stock master seeding and technical metric refresh."""

from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.orm import PriceMetric, Stock
from app.services.external.clients import KRX_PROVIDER, KrxClient
from app.services.ingestion.event_helpers import _event_markets, _event_source_dates
from app.services.ingestion.parsing import (
    _iter_dicts,
    _normalize_krx_price_item,
    _normalize_krx_stock_item,
    _normalize_provider_market,
)
from app.services.ingestion.readiness import hydrate_external_api_settings
from app.services.ingestion.request import MAX_KRX_STOCK_UNIVERSE_SOURCE_DATES


logger = logging.getLogger("app.services.ingestion")


def seed_krx_stock_universe_from_event(event: dict[str, object]) -> dict[str, Any]:
    source_dates = _event_source_dates(event)
    if len(source_dates) > MAX_KRX_STOCK_UNIVERSE_SOURCE_DATES:
        return {
            "ok": False,
            "operation": "seed_krx_stock_universe",
            "error": "source_date_limit_exceeded",
            "max_source_dates": MAX_KRX_STOCK_UNIVERSE_SOURCE_DATES,
            "source_date_count": len(source_dates),
        }
    markets = _event_markets(event)
    # Lazy lookup keeps app.services.ingestion.get_session_factory patchable.
    from app.services import ingestion as _ingestion_pkg

    with _ingestion_pkg.get_session_factory()() as session:
        settings = hydrate_external_api_settings(get_settings())
        client = KrxClient(settings=settings, session=session)
        results = []
        totals = {"inserted": 0, "updated": 0, "skipped": 0}
        for source_date in source_dates:
            for market in markets:
                result = client.daily_trading(
                    ticker="",
                    base_date=source_date,
                    market=market,
                    bypass_cache=True,
                )
                counts = persist_krx_stock_master(
                    session,
                    market=market,
                    payload=result.payload,
                )
                for key in totals:
                    totals[key] += counts[key]
                results.append(
                    {
                        "source_date": source_date,
                        "market": market,
                        "data_status": result.data_status,
                        "status_code": result.status_code,
                        "counts": counts,
                        "missing_data": result.missing_data,
                    }
                )
        session.commit()
    return {
        "ok": any(item["counts"]["inserted"] + item["counts"]["updated"] > 0 for item in results),
        "operation": "seed_krx_stock_universe",
        "source_date": source_dates[-1],
        "source_dates": source_dates,
        "markets": markets,
        "totals": totals,
        "results": results,
    }

def persist_krx_stock_master(
    session: Session,
    *,
    market: str,
    payload: dict[str, Any],
) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    market_key = _normalize_provider_market(market)
    price_items: list[dict[str, Any]] = []
    for item in _iter_dicts(payload.get("OutBlock_1")):
        normalized = _normalize_krx_stock_item(item, market=market_key)
        if normalized is None:
            counts["skipped"] += 1
            continue
        stock = session.get(Stock, normalized["ticker"])
        if stock is None:
            session.add(Stock(**normalized))
            counts["inserted"] += 1
        else:
            for key, value in normalized.items():
                setattr(stock, key, value)
            counts["updated"] += 1
        price_items.append(item)
    session.flush()
    for item in price_items:
        _upsert_krx_price_metric_from_item(session, item=item, payload=payload)
    session.flush()
    return counts

def _upsert_krx_price_metric_from_item(
    session: Session,
    *,
    item: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    base_date = str(payload.get("base_date") or payload.get("basDd") or "").strip()
    normalized = _normalize_krx_price_item(item, base_date=base_date)
    if normalized is None:
        return
    if normalized["trade_date"] is None:
        return
    existing = session.scalars(
        select(PriceMetric).where(
            PriceMetric.ticker == normalized["ticker"],
            PriceMetric.trade_date == normalized["trade_date"],
        )
    ).first()
    if existing is None:
        session.add(
            PriceMetric(
                ticker=normalized["ticker"],
                trade_date=normalized["trade_date"],
                close_price=normalized["close_price"],
                volume=normalized["volume"],
                trading_value=normalized["trading_value"],
                market_cap=normalized["market_cap"],
                change_rate=normalized["change_rate"],
                source=KRX_PROVIDER,
            )
        )
        _refresh_krx_technical_metrics(session, normalized["ticker"])
        return
    existing.close_price = normalized["close_price"]
    existing.volume = normalized["volume"]
    existing.trading_value = normalized["trading_value"]
    existing.market_cap = normalized["market_cap"]
    existing.change_rate = normalized["change_rate"]
    existing.source = KRX_PROVIDER
    _refresh_krx_technical_metrics(session, normalized["ticker"])

def _refresh_krx_technical_metrics(session: Session, ticker: str) -> str | None:
    """Refresh momentum/volatility for the latest row.

    Returns a skip reason instead of failing silently so callers can surface
    why a ticker has no technical metrics (early listings, data gaps).
    """
    rows = session.scalars(
        select(PriceMetric)
        .where(PriceMetric.ticker == ticker)
        .order_by(PriceMetric.trade_date.desc())
        .limit(21)
    ).all()
    if len(rows) < 21:
        logger.info(
            "krx technical metrics skipped: ticker=%s reason=insufficient_samples "
            "sample_count=%d required=21",
            ticker,
            len(rows),
        )
        return "insufficient_samples"
    ordered = list(reversed(rows))
    maybe_closes = [_decimal_to_float(row.close_price) for row in ordered]
    if any(value is None or value <= 0 for value in maybe_closes):
        logger.warning(
            "krx technical metrics skipped: ticker=%s reason=non_positive_close",
            ticker,
        )
        return "non_positive_close"
    closes = [value for value in maybe_closes if value is not None]

    latest = ordered[-1]
    first_close = closes[0]
    latest_close = closes[-1]
    latest.momentum_20d = Decimal(
        str(round((latest_close - first_close) / first_close, 6))
    )

    daily_returns = []
    for previous, current in zip(closes, closes[1:]):
        daily_returns.append((current - previous) / previous)
    latest.volatility_20d = Decimal(
        str(round(_sample_stddev(daily_returns) * math.sqrt(252), 6))
    )
    return None

def _sample_stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)

def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
