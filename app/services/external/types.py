from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


DataStatus = Literal["available", "fallback"]


@dataclass(frozen=True)
class ExternalApiResult:
    provider: str
    endpoint: str
    cache_key: str
    payload: dict[str, Any]
    data_status: DataStatus
    status_code: int | None = None
    missing_data: list[dict[str, Any]] = field(default_factory=list)
    from_cache: bool = False


@dataclass(frozen=True)
class ExternalRequest:
    method: str
    url: str
    params: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class ExternalResponse:
    status_code: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class RateLimitPolicy:
    max_retries: int = 1
    backoff_seconds: float = 0.1
    timeout_seconds: float = 5.0
    retry_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)


ExternalTransport = Callable[[ExternalRequest], ExternalResponse]
