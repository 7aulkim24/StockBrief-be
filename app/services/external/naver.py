"""NAVER news search client."""

from __future__ import annotations

from typing import Any

from app.services.external.base import (
    BaseExternalApiClient,
    _iter_dicts,
    _missing_data,
)
from app.services.external.types import ExternalApiResult, ExternalRequest


NAVER_PROVIDER = "NAVER_NEWS"

class NaverNewsClient(BaseExternalApiClient):
    base_url = "https://openapi.naver.com/v1/search/news.json"

    def search_news(
        self,
        *,
        ticker: str,
        company_name: str,
        display: int = 10,
    ) -> ExternalApiResult:
        endpoint = "/v1/search/news.json"
        cache_key = f"news:{ticker}:{company_name}:{display}"
        cached = self._from_cache(
            provider=NAVER_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
        )
        if cached is not None:
            return cached

        if not self.settings.naver_client_id or not self.settings.naver_client_secret:
            return self._fallback(
                endpoint=endpoint,
                cache_key=cache_key,
                ticker=ticker,
                company_name=company_name,
                reason="missing_api_key",
            )

        params = {"query": company_name, "display": display, "sort": "date"}
        return self._request_result(
            provider=NAVER_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            request=ExternalRequest(
                method="GET",
                url=self.base_url,
                params=params,
                headers={
                    "X-Naver-Client-Id": self.settings.naver_client_id,
                    "X-Naver-Client-Secret": self.settings.naver_client_secret,
                },
                timeout_seconds=self.rate_limit_policy.timeout_seconds,
            ),
            request_params=params,
            fallback_payload=_fallback_news_payload(
                ticker=ticker,
                company_name=company_name,
                missing_data=[],
            ),
            fallback_field="NAVER news response",
            normalize_payload=lambda payload: {
                **_normalize_naver_payload(payload),
                "ticker": ticker,
            },
        )

    def _fallback(
        self,
        *,
        endpoint: str,
        cache_key: str,
        ticker: str,
        company_name: str,
        reason: str,
    ) -> ExternalApiResult:
        missing_data = [
            _missing_data(
                provider=NAVER_PROVIDER,
                field="NAVER_CLIENT_ID/NAVER_CLIENT_SECRET",
                reason=reason,
            )
        ]
        payload = _fallback_news_payload(
            ticker=ticker,
            company_name=company_name,
            missing_data=missing_data,
        )
        return self._fallback_result(
            provider=NAVER_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            request_params={"ticker": ticker, "company_name": company_name, "reason": reason},
            error_code=reason,
            payload=payload,
            missing_data=missing_data,
        )

def _normalize_naver_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items", [])
    normalized_items = [
        {
            "title": str(item.get("title", "")),
            "originallink": str(item.get("originallink", "")),
            "link": str(item.get("link", "")),
            "description": str(item.get("description", "")),
            "pubDate": str(item.get("pubDate", "")),
        }
        for item in _iter_dicts(items)
    ]
    return {
        "lastBuildDate": payload.get("lastBuildDate"),
        "total": payload.get("total"),
        "start": payload.get("start"),
        "display": payload.get("display"),
        "items": normalized_items,
    }

def _fallback_news_payload(
    *,
    ticker: str,
    company_name: str,
    missing_data: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "fallback": True,
        "ticker": ticker,
        "query": company_name,
        "items": [],
        "missing_data": missing_data,
    }
