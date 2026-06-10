from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orm import ApiCacheEntry


class ExternalApiCacheService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, *, provider: str, cache_key: str) -> dict[str, Any] | None:
        entry = self.session.scalars(
            select(ApiCacheEntry).where(
                ApiCacheEntry.provider == provider,
                ApiCacheEntry.cache_key == cache_key,
            )
        ).first()
        if entry is None:
            return None
        if entry.expires_at and _as_utc(entry.expires_at) <= datetime.now(timezone.utc):
            return None
        return dict(entry.response_payload)

    def set(
        self,
        *,
        provider: str,
        cache_key: str,
        response_payload: dict[str, Any],
        status_code: int | None,
        ttl_seconds: int = 1800,
    ) -> ApiCacheEntry:
        entry = self.session.scalars(
            select(ApiCacheEntry).where(
                ApiCacheEntry.provider == provider,
                ApiCacheEntry.cache_key == cache_key,
            )
        ).first()
        values = {
            "request_hash": _hash_payload({"provider": provider, "cache_key": cache_key}),
            "response_payload": response_payload,
            "status_code": status_code,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        }
        if entry is None:
            entry = ApiCacheEntry(
                provider=provider,
                cache_key=cache_key,
                **values,
            )
            self.session.add(entry)
        else:
            for key, value in values.items():
                setattr(entry, key, value)
        self.session.commit()
        return entry


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
