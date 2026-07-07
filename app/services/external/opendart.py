"""OpenDART disclosure/financial statement client."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.orm import CompanyIdentifier
from app.services.external.base import (
    BaseExternalApiClient,
    _cache_payload,
    _iter_dicts,
    _missing_data,
)
from app.services.external.types import ExternalApiResult, ExternalRequest


OPENDART_PROVIDER = "OpenDART"

class OpenDartClient(BaseExternalApiClient):
    base_url = "https://opendart.fss.or.kr/api"

    def resolve_corp_code(self, ticker: str) -> str | None:
        identifier = self.session.scalars(
            select(CompanyIdentifier).where(
                CompanyIdentifier.ticker == ticker,
                CompanyIdentifier.provider == OPENDART_PROVIDER,
                CompanyIdentifier.identifier_type == "corp_code",
            )
        ).first()
        return identifier.identifier_value if identifier else None

    def list_disclosures(
        self,
        *,
        ticker: str,
        corp_code: str | None = None,
        page_count: int = 10,
        bgn_de: str | None = None,
        end_de: str | None = None,
    ) -> ExternalApiResult:
        resolved_corp_code = corp_code or self.resolve_corp_code(ticker)
        endpoint = "/list.json"
        cache_key = (
            f"disclosures:{ticker}:{resolved_corp_code or 'missing'}:"
            f"{bgn_de or 'default'}:{end_de or 'default'}:{page_count}"
        )

        cached = self._from_cache(
            provider=OPENDART_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
        )
        if cached:
            return cached

        if not self.settings.opendart_api_key:
            return self._fallback(
                endpoint=endpoint,
                cache_key=cache_key,
                ticker=ticker,
                reason="missing_api_key",
                field="OPENDART_API_KEY",
            )

        if not resolved_corp_code:
            return self._fallback(
                endpoint=endpoint,
                cache_key=cache_key,
                ticker=ticker,
                reason="missing_corp_code",
                field="corp_code",
            )

        params = {
            "crtfc_key": self.settings.opendart_api_key,
            "corp_code": resolved_corp_code,
            "page_count": page_count,
        }
        if bgn_de:
            params["bgn_de"] = bgn_de
        if end_de:
            params["end_de"] = end_de
        safe_request_params = {
            "corp_code": resolved_corp_code,
            "page_count": page_count,
        }
        if bgn_de:
            safe_request_params["bgn_de"] = bgn_de
        if end_de:
            safe_request_params["end_de"] = end_de
        result = self._request(
            endpoint=endpoint,
            cache_key=cache_key,
            params=params,
            request_params=safe_request_params,
            fallback_payload={"ticker": ticker, "corp_code": resolved_corp_code, "list": []},
            fallback_field="OpenDART response",
        )
        result.payload.setdefault("ticker", ticker)
        result.payload.setdefault("corp_code", resolved_corp_code)
        return result

    def list_financial_statements(
        self,
        *,
        ticker: str,
        corp_code: str | None = None,
        business_years: list[int],
        report_code: str = "11011",
    ) -> ExternalApiResult:
        resolved_corp_code = corp_code or self.resolve_corp_code(ticker)
        endpoint = "/fnlttSinglAcntAll.json"
        year_key = ",".join(str(year) for year in business_years)
        cache_key = f"financials:{ticker}:{resolved_corp_code or 'missing'}:{year_key}:{report_code}"

        cached = self._from_cache(
            provider=OPENDART_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
        )
        if cached:
            return cached

        if not self.settings.opendart_api_key:
            return self._fallback(
                endpoint=endpoint,
                cache_key=cache_key,
                ticker=ticker,
                reason="missing_api_key",
                field="OPENDART_API_KEY",
            )

        if not resolved_corp_code:
            return self._fallback(
                endpoint=endpoint,
                cache_key=cache_key,
                ticker=ticker,
                reason="missing_corp_code",
                field="corp_code",
            )

        rows: list[dict[str, Any]] = []
        missing_data: list[dict[str, Any]] = []
        status_code: int | None = None
        for business_year in business_years:
            year_rows, year_status, year_missing = self._financial_statement_rows(
                endpoint=endpoint,
                ticker=ticker,
                corp_code=resolved_corp_code,
                business_year=business_year,
                report_code=report_code,
            )
            rows.extend(year_rows)
            status_code = year_status if year_status is not None else status_code
            missing_data.extend(year_missing)

        payload = {
            "ticker": ticker,
            "corp_code": resolved_corp_code,
            "financial_statements": rows,
            "missing_data": missing_data,
        }
        data_status = "available" if rows else "fallback"
        self.cache.set(
            provider=OPENDART_PROVIDER,
            cache_key=cache_key,
            response_payload=_cache_payload(
                payload=payload,
                data_status=data_status,
                missing_data=missing_data,
            ),
            status_code=status_code,
        )
        return ExternalApiResult(
            provider=OPENDART_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            payload=payload,
            data_status=data_status,
            status_code=status_code,
            missing_data=missing_data,
        )

    def _financial_statement_rows(
        self,
        *,
        endpoint: str,
        ticker: str,
        corp_code: str,
        business_year: int,
        report_code: str,
    ) -> tuple[list[dict[str, Any]], int | None, list[dict[str, Any]]]:
        year_missing: list[dict[str, Any]] = []
        status_code: int | None = None
        for fs_div in ("CFS", "OFS"):
            params = {
                "crtfc_key": self.settings.opendart_api_key,
                "corp_code": corp_code,
                "bsns_year": str(business_year),
                "reprt_code": report_code,
                "fs_div": fs_div,
            }
            result = self._request(
                endpoint=endpoint,
                cache_key=(
                    f"financials:{ticker}:{corp_code}:{business_year}:"
                    f"{report_code}:{fs_div}"
                ),
                params=params,
                request_params={key: value for key, value in params.items() if key != "crtfc_key"},
                fallback_payload={
                    "ticker": ticker,
                    "corp_code": corp_code,
                    "bsns_year": str(business_year),
                    "reprt_code": report_code,
                    "fs_div": fs_div,
                    "list": [],
                },
                fallback_field="OpenDART financial statements",
            )
            status_code = result.status_code if result.status_code is not None else status_code
            rows = _iter_dicts(result.payload.get("list"))
            if _opendart_status_ok(result.payload) and rows:
                return [
                    {
                        **row,
                        "ticker": ticker,
                        "corp_code": corp_code,
                        "bsns_year": str(business_year),
                        "reprt_code": report_code,
                        "fs_div": fs_div,
                    }
                    for row in rows
                ], status_code, []
            year_missing.extend(result.missing_data)

        return [], status_code, year_missing or [
            _missing_data(
                provider=OPENDART_PROVIDER,
                field=f"financial_statements:{business_year}",
                reason="no_financial_statement_rows",
            )
        ]

    def _fallback(
        self,
        *,
        endpoint: str,
        cache_key: str,
        ticker: str,
        reason: str,
        field: str,
    ) -> ExternalApiResult:
        missing_data = [_missing_data(provider=OPENDART_PROVIDER, field=field, reason=reason)]
        payload = {
            "fallback": True,
            "ticker": ticker,
            "list": [],
            "missing_data": missing_data,
        }
        return self._fallback_result(
            provider=OPENDART_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            request_params={"ticker": ticker, "reason": reason},
            error_code=reason,
            payload=payload,
            missing_data=missing_data,
        )

    def _request(
        self,
        *,
        endpoint: str,
        cache_key: str,
        params: dict[str, Any],
        request_params: dict[str, Any],
        fallback_payload: dict[str, Any],
        fallback_field: str,
    ) -> ExternalApiResult:
        return self._request_result(
            provider=OPENDART_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            request=ExternalRequest(
                method="GET",
                url=f"{self.base_url}{endpoint}",
                params=params,
                timeout_seconds=self.rate_limit_policy.timeout_seconds,
            ),
            request_params=request_params,
            fallback_payload=fallback_payload,
            fallback_field=fallback_field,
        )

def _opendart_status_ok(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "000").strip()
    return status in {"", "000"}
