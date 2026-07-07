"""KRX daily trading client."""

from __future__ import annotations

from app.services.external.base import BaseExternalApiClient, _missing_data
from app.services.external.types import ExternalApiResult, ExternalRequest


KRX_PROVIDER = "KRX"

class KrxClient(BaseExternalApiClient):
    def daily_trading(
        self,
        *,
        ticker: str,
        base_date: str,
        market: str = "KOSPI",
        bypass_cache: bool = False,
    ) -> ExternalApiResult:
        market_key = _krx_market_key(market)
        endpoint = self._daily_endpoint(market_key)
        cache_key = f"daily_trading:{market_key}:{base_date}"
        fallback_cache_key = f"{cache_key}:{ticker}"
        if not bypass_cache:
            cached = self._from_cache(
                provider=KRX_PROVIDER,
                endpoint=endpoint or f"missing_krx_{market_key.lower()}_daily_url",
                cache_key=cache_key,
            )
            if cached is not None:
                return cached

        if not endpoint:
            return self._fallback(
                endpoint=f"missing_krx_{market_key.lower()}_daily_url",
                cache_key=fallback_cache_key,
                ticker=ticker,
                base_date=base_date,
                market=market_key,
                reason="missing_daily_url",
                field=self._daily_endpoint_field(market_key),
            )
        if not self.settings.krx_api_key:
            return self._fallback(
                endpoint=endpoint,
                cache_key=fallback_cache_key,
                ticker=ticker,
                base_date=base_date,
                market=market_key,
                reason="missing_api_key",
                field="KRX_API_KEY",
            )

        return self._request_result(
            provider=KRX_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            request=ExternalRequest(
                method="GET",
                url=endpoint,
                params={"basDd": base_date},
                headers={self.settings.krx_api_key_header: self.settings.krx_api_key},
                timeout_seconds=max(self.rate_limit_policy.timeout_seconds, 24.0),
            ),
            request_params={"basDd": base_date, "market": market_key},
            fallback_payload={
                "base_date": base_date,
                "market": market_key,
                "OutBlock_1": [],
            },
            fallback_field="KRX daily trading response",
            normalize_payload=lambda payload: {
                **payload,
                "base_date": base_date,
                "market": market_key,
            },
        )

    def _daily_endpoint(self, market_key: str) -> str:
        if market_key == "KOSDAQ":
            return self.settings.krx_kosdaq_daily_url
        return self.settings.krx_daily_url or self.settings.krx_kospi_daily_url

    @staticmethod
    def _daily_endpoint_field(market_key: str) -> str:
        if market_key == "KOSDAQ":
            return "KRX_KOSDAQ_DAILY_URL"
        return "KRX_DAILY_URL/KRX_KOSPI_DAILY_URL"

    def _fallback(
        self,
        *,
        endpoint: str,
        cache_key: str,
        ticker: str,
        base_date: str,
        market: str,
        reason: str,
        field: str,
    ) -> ExternalApiResult:
        missing_data = [_missing_data(provider=KRX_PROVIDER, field=field, reason=reason)]
        payload = {
            "fallback": True,
            "ticker": ticker,
            "base_date": base_date,
            "market": market,
            "OutBlock_1": [],
            "missing_data": missing_data,
        }
        return self._fallback_result(
            provider=KRX_PROVIDER,
            endpoint=endpoint,
            cache_key=cache_key,
            request_params={
                "ticker": ticker,
                "basDd": base_date,
                "market": market,
                "reason": reason,
            },
            error_code=reason,
            payload=payload,
            missing_data=missing_data,
        )

def _krx_market_key(market: str) -> str:
    normalized = market.strip().upper()
    if normalized in {"KOSDAQ", "KQ"}:
        return "KOSDAQ"
    return "KOSPI"
