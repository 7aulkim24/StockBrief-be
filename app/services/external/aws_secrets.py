from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AWS_SERVICE = "secretsmanager"
AWS_TARGET = "secretsmanager.GetSecretValue"
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


def load_secret_json(secret_id: str, *, region: str | None = None) -> dict[str, Any]:
    raw = load_secret_string(secret_id, region=region)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("AWS Secrets Manager payload must be a JSON object.")
    return payload


def load_secret_string(secret_id: str, *, region: str | None = None) -> str:
    resolved_region = region or _aws_region()
    credentials = _aws_credentials()
    payload = json.dumps({"SecretId": secret_id}).encode("utf-8")
    timestamp = datetime.now(timezone.utc)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = timestamp.strftime("%Y%m%d")

    headers = {
        "content-type": "application/x-amz-json-1.1",
        "host": f"{AWS_SERVICE}.{resolved_region}.amazonaws.com",
        "x-amz-date": amz_date,
        "x-amz-target": AWS_TARGET,
        "x-amz-content-sha256": hashlib.sha256(payload).hexdigest(),
    }
    if credentials.session_token:
        headers["x-amz-security-token"] = credentials.session_token

    authorization = _authorization_header(
        method="POST",
        region=resolved_region,
        service=AWS_SERVICE,
        canonical_uri="/",
        headers=headers,
        payload_hash=headers["x-amz-content-sha256"],
        credentials=credentials,
        date_stamp=date_stamp,
    )
    headers["authorization"] = authorization

    request = Request(
        url=f"https://{AWS_SERVICE}.{resolved_region}.amazonaws.com/",
        data=payload,
        method="POST",
        headers=headers,
    )

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"Failed to load AWS secret {secret_id!r}: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to load AWS secret {secret_id!r}: {exc.reason}") from exc

    decoded = json.loads(body) if body else {}
    secret_string = decoded.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string:
        raise RuntimeError(f"AWS secret {secret_id!r} did not return SecretString.")
    return secret_string


def _aws_region() -> str:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        raise RuntimeError("AWS_REGION or AWS_DEFAULT_REGION is required to load Secrets Manager secrets.")
    return region


def _aws_credentials() -> AwsCredentials:
    access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    session_token = os.getenv("AWS_SESSION_TOKEN")
    if not access_key_id or not secret_access_key:
        raise RuntimeError("AWS credentials are required to load Secrets Manager secrets.")
    return AwsCredentials(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token or None,
    )


def _authorization_header(
    *,
    method: str,
    region: str,
    service: str,
    canonical_uri: str,
    headers: dict[str, str],
    payload_hash: str,
    credentials: AwsCredentials,
    date_stamp: str,
) -> str:
    canonical_headers, signed_headers = _canonical_headers(headers)
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            headers["x-amz-date"],
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _signing_key(
        secret_access_key=credentials.secret_access_key,
        date_stamp=date_stamp,
        region=region,
        service=service,
    )
    signature = hmac.new(
        signing_key,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        "AWS4-HMAC-SHA256 "
        f"Credential={credentials.access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


def _canonical_headers(headers: dict[str, str]) -> tuple[str, str]:
    normalized = {key.casefold(): " ".join(value.strip().split()) for key, value in headers.items()}
    signed_headers = ";".join(sorted(normalized))
    canonical_headers = "".join(f"{key}:{normalized[key]}\n" for key in sorted(normalized))
    return canonical_headers, signed_headers


def _signing_key(
    *,
    secret_access_key: str,
    date_stamp: str,
    region: str,
    service: str,
) -> bytes:
    k_date = _sign(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _sign(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
