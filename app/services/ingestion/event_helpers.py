"""Event payload extraction helpers shared across ingestion operations."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.services.external.clients import KRX_PROVIDER, NAVER_PROVIDER, OPENDART_PROVIDER
from app.services.ingestion.parsing import (
    _compact_source_date,
    _normalize_provider_market,
    _parse_iso_date,
    _parse_yyyymmdd,
)
from app.services.ingestion_idempotency import IngestionIdempotencyService


def build_run_id(*, provider: str, source_date: str, ticker: str) -> str:
    normalized_provider = provider.lower().replace("_", "-")
    return f"{normalized_provider}-{source_date}-{ticker}"

def build_request_hash(
    *,
    provider: str,
    ticker: str,
    source_date: str,
    request_params: dict[str, Any],
) -> str:
    return IngestionIdempotencyService.compute_input_hash(
        {
            "provider": provider,
            "ticker": ticker,
            "source_date": source_date,
            "request_hash": IngestionIdempotencyService.compute_input_hash(request_params),
        }
    )

def _event_as_of_date(event: dict[str, object]) -> date:
    raw = str(event.get("as_of_date") or event.get("source_date") or "").strip()
    if raw:
        if len(raw) == 8 and raw.isdigit():
            parsed_compact = _parse_yyyymmdd(raw)
            if parsed_compact is not None:
                return parsed_compact.date()
        parsed = _parse_iso_date(raw)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc).date()

def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_")
    if normalized == "opendart":
        return OPENDART_PROVIDER
    if normalized in {"naver", "naver_news"}:
        return NAVER_PROVIDER
    if normalized in {"krx", "krx_price", "krx_prices"}:
        return KRX_PROVIDER
    return provider

def _job_type(provider: str) -> str:
    if provider == OPENDART_PROVIDER:
        return "disclosure"
    if provider == KRX_PROVIDER:
        return "price"
    return "news"

def _provider_payload_version(provider: str) -> str:
    if provider == OPENDART_PROVIDER:
        return "opendart-disclosure-financial-v2"
    if provider == KRX_PROVIDER:
        return "krx-price-technical-v2"
    return "provider-payload-v1"

def _first_secret_value(secret: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = secret.get(key)
        if isinstance(value, str) and value:
            return value
    return ""

def _unique_tickers(tickers: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        unique.append(ticker)
    return unique

def _event_tickers(event: dict[str, object]) -> list[str]:
    tickers_value = event.get("tickers")
    if isinstance(tickers_value, str):
        return [item.strip() for item in tickers_value.split(",") if item.strip()]
    if isinstance(tickers_value, list):
        return [str(item).strip() for item in tickers_value if str(item).strip()]
    ticker_value = event.get("ticker")
    if isinstance(ticker_value, str) and ticker_value.strip():
        return [ticker_value.strip()]
    return []

def _event_providers(event: dict[str, object]) -> list[str]:
    providers_value = event.get("providers")
    if isinstance(providers_value, str):
        values = [item.strip() for item in providers_value.split(",") if item.strip()]
    elif isinstance(providers_value, list):
        values = [str(item).strip() for item in providers_value if str(item).strip()]
    else:
        provider_value = event.get("provider")
        values = [str(provider_value).strip()] if isinstance(provider_value, str) and provider_value.strip() else []
    return [_normalize_provider(value) for value in values]

def _event_source_dates(event: dict[str, object]) -> list[str]:
    source_dates_value = event.get("source_dates")
    if isinstance(source_dates_value, str):
        values = [item.strip() for item in source_dates_value.split(",") if item.strip()]
    elif isinstance(source_dates_value, list):
        values = [str(item).strip() for item in source_dates_value if str(item).strip()]
    else:
        values = []
    if not values:
        values = [str(event.get("source_date") or datetime.now(timezone.utc).date().isoformat())]
    seen: set[str] = set()
    source_dates = []
    for value in values:
        source_date = _compact_source_date(value)
        if source_date and source_date not in seen:
            seen.add(source_date)
            source_dates.append(source_date)
    return source_dates

def _event_markets(event: dict[str, object]) -> list[str]:
    markets_value = event.get("markets")
    if isinstance(markets_value, str):
        values = [item.strip() for item in markets_value.split(",") if item.strip()]
    elif isinstance(markets_value, list):
        values = [str(item).strip() for item in markets_value if str(item).strip()]
    else:
        market_value = event.get("market")
        values = [str(market_value).strip()] if isinstance(market_value, str) and market_value.strip() else []
    markets = [_normalize_provider_market(value) for value in values]
    return markets or ["KOSPI", "KOSDAQ"]

def _event_market_filter(event: dict[str, object]) -> list[str]:
    if "markets" not in event and "market" not in event:
        return []
    return _event_markets(event)

def _event_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return default

def _unique_providers(providers: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for provider in providers:
        if provider in seen:
            continue
        seen.add(provider)
        unique.append(provider)
    return unique
