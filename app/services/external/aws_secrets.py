from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


DEFAULT_TIMEOUT_SECONDS = 5.0


def load_secret_json(secret_id: str, *, region: str | None = None) -> dict[str, Any]:
    raw = load_secret_string(secret_id, region=region)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("AWS Secrets Manager payload must be a JSON object.")
    return payload


def load_secret_string(secret_id: str, *, region: str | None = None) -> str:
    client = boto3.client(
        "secretsmanager",
        region_name=region,
        config=_client_config(),
    )
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"Failed to load AWS secret {secret_id!r}.") from exc

    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string:
        raise RuntimeError(f"AWS secret {secret_id!r} did not return SecretString.")
    return secret_string


def _client_config():
    return Config(
        connect_timeout=DEFAULT_TIMEOUT_SECONDS,
        read_timeout=DEFAULT_TIMEOUT_SECONDS,
        retries={"max_attempts": 2, "mode": "standard"},
    )
