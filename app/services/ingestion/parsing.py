"""Pure parsing/normalization helpers for provider ingestion payloads."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

from app.services.external.clients import OPENDART_PROVIDER
from app.services.external.types import ExternalApiResult


logger = logging.getLogger("app.services.ingestion")


def _combined_opendart_result(
    disclosures: ExternalApiResult,
    financials: ExternalApiResult,
) -> ExternalApiResult:
    payload = {
        **disclosures.payload,
        "financial_statements": list(
            financials.payload.get("financial_statements") or []
        ),
        "financial_missing_data": list(financials.missing_data),
    }
    missing_data = [*disclosures.missing_data, *financials.missing_data]
    data_status = (
        "available"
        if disclosures.data_status == "available" or financials.data_status == "available"
        else "fallback"
    )
    return ExternalApiResult(
        provider=OPENDART_PROVIDER,
        endpoint=f"{disclosures.endpoint}+{financials.endpoint}",
        cache_key=f"{disclosures.cache_key}+{financials.cache_key}",
        payload=payload,
        data_status=data_status,
        status_code=disclosures.status_code or financials.status_code,
        missing_data=missing_data,
    )

def _opendart_financial_years(source_date: str) -> list[int]:
    compact = _compact_source_date(source_date)
    as_of = _parse_yyyymmdd(compact)
    source_day = as_of.date() if as_of is not None else date.today()
    latest_available_year = source_day.year - 1
    if source_day.month <= 3:
        latest_available_year -= 1
    return [latest_available_year, latest_available_year - 1]

def _opendart_disclosure_window(source_date: str) -> dict[str, str]:
    compact = _compact_source_date(source_date)
    try:
        end_date = datetime.strptime(compact, "%Y%m%d").date()
    except ValueError:
        end_date = date.today()
    begin_date = end_date - timedelta(days=365)
    return {
        "bgn_de": begin_date.strftime("%Y%m%d"),
        "end_de": end_date.strftime("%Y%m%d"),
    }

def _financial_statement_values(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    unmapped: set[str] = set()
    for row in rows:
        account_name = _normalize_account_name(row.get("account_nm"))
        amount = _decimal_from_provider(row, "thstrm_amount", "thstrm_add_amount")
        if amount is None:
            continue
        if account_name in {"매출액", "수익매출액", "영업수익"}:
            values.setdefault("revenue", amount)
        elif account_name in {"영업이익", "영업이익손실"}:
            values.setdefault("operating_income", amount)
        elif account_name in {"당기순이익", "당기순이익손실", "연결당기순이익"}:
            values.setdefault("net_income", amount)
        elif account_name == "자산총계":
            values.setdefault("total_assets", amount)
        elif account_name == "부채총계":
            values.setdefault("total_liabilities", amount)
        elif account_name == "자본총계":
            values.setdefault("total_equity", amount)
        else:
            unmapped.add(account_name)
    if unmapped:
        # Account naming varies by issuer; surface what fell through so data
        # quality gaps are diagnosable instead of silently missing columns.
        logger.debug(
            "unmapped financial statement accounts: %s", sorted(unmapped)
        )
    return values

def _normalize_account_name(value: object) -> str:
    return re.sub(r"[\s()]", "", str(value or ""))

def _normalize_krx_stock_item(
    item: dict[str, Any],
    *,
    market: str,
) -> dict[str, Any] | None:
    ticker = _ticker_from_provider(item, "ISU_SRT_CD", "isuSrtCd", "ticker", "ISU_CD", "isuCd")
    if not ticker or not ticker.isdigit() or len(ticker) != 6:
        return None
    name = _first_text(item, "ISU_ABBRV", "isuAbrv", "ISU_NM", "isuNm", "name")
    if not name:
        return None
    item_market = _first_text(item, "MKT_NM", "mktNm", "market") or market
    listing_date = _parse_yyyymmdd(_first_text(item, "LIST_DD", "listDd"))
    sector = _first_text(item, "SECT_TP_NM", "MKT_TP_NM", "secugrpNm", "SECUGRP_NM") or None
    return {
        "ticker": ticker,
        "company_name": name,
        "company_name_en": _first_text(item, "ISU_ENG_NM", "isuEngNm") or None,
        "market": _normalize_provider_market(item_market),
        "sector": sector,
        "industry": _first_text(item, "IDX_IND_NM", "industry") or sector,
        "listing_date": listing_date.date() if listing_date else None,
        "is_active": True,
    }

def _normalize_krx_price_item(
    item: dict[str, Any],
    *,
    base_date: str,
) -> dict[str, Any] | None:
    ticker = _ticker_from_provider(item, "ISU_CD", "isuCd", "ISU_SRT_CD", "isuSrtCd", "ticker")
    raw_date = _first_text(item, "BAS_DD", "basDd", "base_date") or base_date
    trade_date = _parse_yyyymmdd(_compact_source_date(raw_date))
    if not ticker or trade_date is None:
        return None
    return {
        "ticker": ticker,
        "trade_date": trade_date.date(),
        "close_price": _decimal_from_provider(item, "TDD_CLSPRC", "close_price", "close"),
        "volume": _decimal_from_provider(item, "ACC_TRDVOL", "volume"),
        "trading_value": _decimal_from_provider(item, "ACC_TRDVAL", "trading_value"),
        "market_cap": _decimal_from_provider(item, "MKTCAP", "market_cap"),
        "change_rate": _decimal_from_provider(item, "FLUC_RT", "change_rate"),
    }

def _ticker_from_provider(item: dict[str, Any], *keys: str) -> str:
    first_raw = ""
    for key in keys:
        raw = _first_text(item, key)
        if not raw:
            continue
        first_raw = first_raw or raw
        if raw.startswith("A") and raw[1:].isdigit() and len(raw) <= 7:
            return raw[1:].zfill(6)
        if raw.isdigit() and len(raw) <= 6:
            return raw.zfill(6)
    return first_raw

def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def _decimal_from_provider(item: dict[str, Any], *keys: str) -> Decimal | None:
    raw = _first_text(item, *keys).replace(",", "")
    if raw in {"", "-", "+"}:
        return None
    try:
        return Decimal(raw)
    except Exception:
        return None

def _compact_source_date(value: object) -> str:
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return raw
    parsed = _parse_iso_date(raw)
    if parsed is not None:
        return parsed.strftime("%Y%m%d")
    return raw.replace("-", "")

def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None

def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]

def _normalize_provider_market(market: str) -> str:
    normalized = market.strip().upper()
    if normalized in {"KOSDAQ", "KQ", "KSQ"}:
        return "KOSDAQ"
    return "KOSPI"

def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_aware_datetime(value).isoformat()

def _ensure_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _parse_yyyymmdd(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def _parse_rfc2822(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def _clean_provider_text(value: object) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split()).strip()

def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
