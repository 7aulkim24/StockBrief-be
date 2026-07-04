from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.orm import CompanyIdentifier, Stock
from app.seed.stock_universe import STOCK_UNIVERSE, StockUniverseItem

ModelT = TypeVar("ModelT")


def seed_stock_universe(
    session: Session,
    *,
    tickers: Iterable[str] | None = None,
) -> dict[str, object]:
    selected_stocks, unknown_tickers = _selected_stocks(tickers)
    for item in selected_stocks:
        _seed_stock_master(session, item)
    session.commit()
    return {
        "stocks": len(selected_stocks),
        "identifiers": len(selected_stocks) * 2,
        "tickers": [item.ticker for item in selected_stocks],
        "unknown_tickers": unknown_tickers,
    }


def seed_stock_universe_from_event(event: dict[str, object]) -> dict[str, object]:
    with get_session_factory()() as session:
        result = seed_stock_universe(session, tickers=_event_tickers(event))
    unknown_tickers = result["unknown_tickers"]
    return {
        "ok": not unknown_tickers,
        "operation": "seed_stock_universe",
        "result": result,
        "issues": [
            {"code": "unknown_stock_universe_ticker", "ticker": ticker}
            for ticker in unknown_tickers
        ],
    }


def _seed_stock_master(session: Session, item: StockUniverseItem) -> None:
    _upsert_one(
        session,
        Stock,
        {"ticker": item.ticker},
        {
            "company_name": item.company_name,
            "company_name_en": item.company_name_en,
            "market": item.market,
            "sector": item.sector,
            "industry": item.industry,
            "listing_date": item.listing_date,
            "is_active": True,
        },
    )
    for identifier_type, identifier_value, is_primary in (
        ("corp_code", item.corp_code, True),
        ("stock_code", item.ticker, False),
    ):
        _upsert_one(
            session,
            CompanyIdentifier,
            {
                "ticker": item.ticker,
                "provider": "OpenDART",
                "identifier_type": identifier_type,
            },
            {
                "identifier_value": identifier_value,
                "is_primary": is_primary,
            },
        )


def _selected_stocks(
    tickers: Iterable[str] | None,
) -> tuple[list[StockUniverseItem], list[str]]:
    by_ticker = {item.ticker: item for item in STOCK_UNIVERSE}
    requested = _unique_tickers(tickers)
    if not requested:
        return list(STOCK_UNIVERSE), []
    return (
        [by_ticker[ticker] for ticker in requested if ticker in by_ticker],
        [ticker for ticker in requested if ticker not in by_ticker],
    )


def _event_tickers(event: dict[str, object]) -> list[str]:
    value = event.get("tickers")
    if isinstance(value, str):
        return _unique_tickers(value.split(","))
    if isinstance(value, list):
        return _unique_tickers(str(item) for item in value)
    return []


def _unique_tickers(tickers: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in tickers or []:
        ticker = str(item).strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        unique.append(ticker)
    return unique


def _upsert_one(
    session: Session,
    model: type[ModelT],
    filters: dict[str, Any],
    values: dict[str, Any],
) -> ModelT:
    instance = session.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    if instance is None:
        instance = model(**filters, **values)
        session.add(instance)
    else:
        for key, value in values.items():
            setattr(instance, key, value)
    session.flush()
    return instance


def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        result = seed_stock_universe(session)
    print(
        "Seeded StockBrief stock universe: "
        f"{result['stocks']} stocks, "
        f"{result['identifiers']} identifiers."
    )


if __name__ == "__main__":
    main()
