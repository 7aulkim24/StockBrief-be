"""Ingestion request/result models and request limit validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.external.clients import KRX_PROVIDER, NAVER_PROVIDER, OPENDART_PROVIDER
from app.services.ingestion.event_helpers import _normalize_provider
from app.services.ingestion.parsing import _string_or_none


SUPPORTED_PROVIDERS = (OPENDART_PROVIDER, NAVER_PROVIDER, KRX_PROVIDER)

MAX_TICKERS_PER_BATCH = 20

MAX_OPENDART_PAGE_COUNT = 100

MAX_NAVER_NEWS_DISPLAY = 50

MAX_KRX_STOCK_UNIVERSE_SOURCE_DATES = 31

@dataclass(frozen=True)
class ProviderIngestionRequest:
    provider: str
    tickers: list[str]
    source_date: str
    run_id: str | None = None
    page_count: int = 10
    news_display: int = 10

    @classmethod
    def from_event(cls, event: dict[str, object]) -> ProviderIngestionRequest:
        provider = _normalize_provider(str(event.get("provider") or "").strip())
        tickers_value = event.get("tickers")
        if isinstance(tickers_value, str):
            tickers = [item.strip() for item in tickers_value.split(",") if item.strip()]
        elif isinstance(tickers_value, list):
            tickers = [str(item).strip() for item in tickers_value if str(item).strip()]
        else:
            tickers = []

        source_date = str(event.get("source_date") or datetime.now(timezone.utc).date().isoformat())
        return cls(
            provider=provider,
            tickers=tickers,
            source_date=source_date,
            run_id=_string_or_none(event.get("run_id")),
            page_count=_positive_int(event.get("page_count"), default=10),
            news_display=_positive_int(event.get("news_display"), default=10),
        )

@dataclass(frozen=True)
class TickerIngestionResult:
    ticker: str
    run_id: str
    status: str
    result_counts: dict[str, int]
    raw_archive_uri: str | None = None
    error_summary: dict[str, Any] | None = None

def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

def _nonnegative_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default

def _request_limit_violations(request: ProviderIngestionRequest) -> list[dict[str, int | str]]:
    checks = (
        ("tickers", len(request.tickers), MAX_TICKERS_PER_BATCH),
        ("page_count", request.page_count, MAX_OPENDART_PAGE_COUNT),
        ("news_display", request.news_display, MAX_NAVER_NEWS_DISPLAY),
    )
    return [
        {"field": field, "value": value, "max": max_value}
        for field, value, max_value in checks
        if value > max_value
    ]

def _request_limits() -> dict[str, int]:
    return {
        "max_tickers": MAX_TICKERS_PER_BATCH,
        "max_page_count": MAX_OPENDART_PAGE_COUNT,
        "max_news_display": MAX_NAVER_NEWS_DISPLAY,
    }

def _result_dict(result: TickerIngestionResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ticker": result.ticker,
        "run_id": result.run_id,
        "status": result.status,
        "result_counts": result.result_counts,
    }
    if result.raw_archive_uri:
        payload["raw_archive_uri"] = result.raw_archive_uri
    if result.error_summary:
        payload["error_summary"] = result.error_summary
    return payload
