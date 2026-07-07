"""Raw payload archiving backends for provider ingestion."""

from __future__ import annotations

import json
from typing import Any, Protocol

import boto3
from botocore.config import Config

from app.config import Settings


class PayloadArchiver(Protocol):
    def archive(
        self,
        *,
        run_id: str,
        provider: str,
        ticker: str,
        payload: dict[str, Any],
    ) -> str | None:
        ...

class NoopPayloadArchiver:
    def archive(
        self,
        *,
        run_id: str,
        provider: str,
        ticker: str,
        payload: dict[str, Any],
    ) -> str | None:
        return None

class S3PayloadArchiver:
    def __init__(self, *, bucket: str, client: Any | None = None) -> None:
        self.bucket = bucket
        self.client = client or boto3.client(
            "s3",
            config=Config(
                connect_timeout=5,
                read_timeout=5,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def archive(
        self,
        *,
        run_id: str,
        provider: str,
        ticker: str,
        payload: dict[str, Any],
    ) -> str | None:
        key = f"raw/provider={provider}/ticker={ticker}/run_id={run_id}.json"
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        return f"s3://{self.bucket}/{key}"

def _archiver_from_settings(settings: Settings) -> PayloadArchiver:
    if settings.ingestion_raw_bucket:
        return S3PayloadArchiver(bucket=settings.ingestion_raw_bucket)
    return NoopPayloadArchiver()
