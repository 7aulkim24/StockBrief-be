"""Shared request/caching machinery for external provider clients."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import Settings
from app.services.external.cache import ExternalApiCacheService
from app.services.external.logger import ExternalApiCallLogger
from app.services.external.transport import urllib_transport
from app.services.external.types import (
    ExternalApiResult,
    ExternalRequest,
    ExternalResponse,
    ExternalTransport,
    RateLimitPolicy,
)


class BaseExternalApiClient:
    def __init__(
        self,
        *,
        settings: Settings,
        session: Session,
        transport: ExternalTransport | None = None,
        rate_limit_policy: RateLimitPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.session = session
        self.transport = transport or urllib_transport
        self.rate_limit_policy = rate_limit_policy or RateLimitPolicy()
        self.cache = ExternalApiCacheService(session)
        self.logger = ExternalApiCallLogger(session)

    def _from_cache(
        self,
        *,
        provider: str,
        endpoint: str,
        cache_key: str,
    ) -> ExternalApiResult | None:
        cached = self.cache.get(provider=provider, cache_key=cache_key)
        if cached is None:
            return None
        self.logger.log(
            provider=provider,
            endpoint=endpoint,
            method="CACHE",
            request_params={"cache_key": cache_key},
            status_code=200,
            duration_ms=0,
            error_code=None,
        )
        return _result_from_cached(
            provider=provider,
            endpoint=endpoint,
            cache_key=cache_key,
            cached=cached,
        )

    def _fallback_result(
        self,
        *,
        provider: str,
        endpoint: str,
        cache_key: str,
        payload: dict[str, Any],
        missing_data: list[dict[str, Any]],
        request_params: dict[str, Any],
        error_code: str,
    ) -> ExternalApiResult:
        self.cache.set(
            provider=provider,
            cache_key=cache_key,
            response_payload=_cache_payload(
                payload=payload,
                data_status="fallback",
                missing_data=missing_data,
            ),
            status_code=None,
        )
        self.logger.log(
            provider=provider,
            endpoint=endpoint,
            method="FALLBACK",
            request_params=request_params,
            status_code=None,
            duration_ms=0,
            error_code=error_code,
        )
        return ExternalApiResult(
            provider=provider,
            endpoint=endpoint,
            cache_key=cache_key,
            payload=payload,
            data_status="fallback",
            status_code=None,
            missing_data=missing_data,
        )

    def _request_result(
        self,
        *,
        provider: str,
        endpoint: str,
        cache_key: str,
        request: ExternalRequest,
        request_params: dict[str, Any],
        fallback_payload: dict[str, Any],
        fallback_field: str,
        normalize_payload: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> ExternalApiResult:
        started = time.monotonic()
        status_code: int | None = None
        try:
            response = _request_with_backoff(
                transport=self.transport,
                request=request,
                policy=self.rate_limit_policy,
            )
            status_code = response.status_code
            if status_code != 200:
                raise RuntimeError(f"unexpected_status_{status_code}")
            payload = normalize_payload(response.payload) if normalize_payload else response.payload
            self.cache.set(
                provider=provider,
                cache_key=cache_key,
                response_payload=_cache_payload(
                    payload=payload,
                    data_status="available",
                    missing_data=[],
                ),
                status_code=status_code,
            )
            self.logger.log(
                provider=provider,
                endpoint=endpoint,
                method="GET",
                request_params=request_params,
                status_code=status_code,
                duration_ms=_duration_ms(started),
                error_code=None,
            )
            return ExternalApiResult(
                provider=provider,
                endpoint=endpoint,
                cache_key=cache_key,
                payload=payload,
                data_status="available",
                status_code=status_code,
            )
        except Exception as exc:
            error_code = _error_code(exc)
            missing_data = [
                _missing_data(
                    provider=provider,
                    field=fallback_field,
                    reason=error_code,
                )
            ]
            payload = {**fallback_payload, "fallback": True, "missing_data": missing_data}
            self.cache.set(
                provider=provider,
                cache_key=cache_key,
                response_payload=_cache_payload(
                    payload=payload,
                    data_status="fallback",
                    missing_data=missing_data,
                ),
                status_code=status_code,
            )
            self.logger.log(
                provider=provider,
                endpoint=endpoint,
                method="GET",
                request_params=request_params,
                status_code=status_code,
                duration_ms=_duration_ms(started),
                error_code=error_code,
            )
            return ExternalApiResult(
                provider=provider,
                endpoint=endpoint,
                cache_key=cache_key,
                payload=payload,
                data_status="fallback",
                status_code=status_code,
                missing_data=missing_data,
            )

def _request_with_backoff(
    *,
    transport: ExternalTransport,
    request: ExternalRequest,
    policy: RateLimitPolicy,
) -> ExternalResponse:
    attempts = policy.max_retries + 1
    response: ExternalResponse | None = None
    for index in range(attempts):
        response = transport(request)
        if response.status_code not in policy.retry_status_codes:
            return response
        if index < attempts - 1:
            time.sleep(policy.backoff_seconds * (index + 1))
    return response

def _iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]

def _cache_payload(
    *,
    payload: dict[str, Any],
    data_status: str,
    missing_data: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "payload": payload,
        "data_status": data_status,
        "missing_data": missing_data,
    }

def _result_from_cached(
    *,
    provider: str,
    endpoint: str,
    cache_key: str,
    cached: dict[str, Any],
) -> ExternalApiResult:
    data_status = "fallback" if cached.get("data_status") == "fallback" else "available"
    missing_data = cached.get("missing_data", [])
    if not isinstance(missing_data, list):
        missing_data = []
    payload = cached.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    return ExternalApiResult(
        provider=provider,
        endpoint=endpoint,
        cache_key=cache_key,
        payload=payload,
        data_status=data_status,
        status_code=200,
        missing_data=missing_data,
        from_cache=True,
    )

def _missing_data(*, provider: str, field: str, reason: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "field": field,
        "reason": reason,
        "data_status": "fallback",
    }

def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

def _error_code(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("unexpected_status_"):
        return message
    return exc.__class__.__name__
