#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


DEFAULT_FUNCTION_NAME = "stockbrief-dev-api"
DEFAULT_PROVIDERS = ("OpenDART", "NAVER_NEWS", "KRX")
DEFAULT_TICKERS = ("005930",)
SECRET_KEY_FRAGMENTS = (
    "api_key",
    "client_secret",
    "database_url",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    operation: str
    status_code: int | None
    payload: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "status_code": self.status_code,
            "payload": redact(self.payload),
            "error_code": self.error_code,
            "error_message": redact(self.error_message),
        }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_smoke(
        function_name=args.function_name,
        region=args.region,
        profile=args.profile,
        providers=tuple(args.providers),
        tickers=tuple(args.tickers),
        status_limit=args.status_limit,
        timeout_seconds=args.timeout_seconds,
        source_date=args.source_date,
        run_provider_ingest=args.run_provider_ingest,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run redacted Lambda ingestion readiness checks for the dev stack."
    )
    parser.add_argument("--function-name", default=DEFAULT_FUNCTION_NAME)
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--profile")
    parser.add_argument("--providers", nargs="+", default=list(DEFAULT_PROVIDERS))
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--status-limit", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--source-date")
    parser.add_argument(
        "--run-provider-ingest",
        action="store_true",
        help=(
            "When preflight passes, seed stock universe rows and run one "
            "refresh_score_snapshots per selected provider."
        ),
    )
    return parser.parse_args(argv)


def run_smoke(
    *,
    function_name: str,
    region: str,
    profile: str | None = None,
    providers: tuple[str, ...],
    tickers: tuple[str, ...],
    status_limit: int,
    timeout_seconds: float,
    source_date: str | None = None,
    run_provider_ingest: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    if run_provider_ingest and not source_date:
        return {
            "ok": False,
            "ready_for_manual_ingestion": False,
            "function_name": function_name,
            "region": region,
            "profile": profile,
            "providers": list(providers),
            "tickers": list(tickers),
            "operations": {},
            "blockers": [{"code": "missing_source_date"}],
        }

    if client is None:
        try:
            session = boto3.Session(profile_name=profile) if profile else boto3.Session()
            lambda_client = session.client(
                "lambda",
                region_name=region,
                config=Config(
                    connect_timeout=timeout_seconds,
                    read_timeout=timeout_seconds,
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            )
        except BotoCoreError as exc:
            return client_setup_error_result(
                exc,
                function_name=function_name,
                region=region,
                profile=profile,
                providers=providers,
                tickers=tickers,
                source_date=source_date,
            )
    else:
        lambda_client = client

    operations: dict[str, OperationResult] = {
        "readiness": invoke_operation(
            lambda_client,
            function_name,
            {
                "stockbrief_operation": "check_ingestion_readiness",
                "providers": list(providers),
            },
        ),
        "raw_archive": invoke_operation(
            lambda_client,
            function_name,
            {"stockbrief_operation": "check_raw_archive_write"},
        ),
        "provider_egress": invoke_operation(
            lambda_client,
            function_name,
            {
                "stockbrief_operation": "check_provider_egress",
                "providers": list(providers),
            },
        ),
        "status": invoke_operation(
            lambda_client,
            function_name,
            {
                "stockbrief_operation": "get_ingestion_status",
                "tickers": list(tickers),
                "providers": list(providers),
                "limit": status_limit,
            },
        ),
        "scheduler_gate": invoke_operation(
            lambda_client,
            function_name,
            {
                "stockbrief_operation": "check_ingestion_scheduler_enable_gate",
                "providers": list(providers),
                "tickers": list(tickers),
                "limit": status_limit,
            },
        ),
    }

    ready_for_manual_ingestion = all(
        operations[name].ok for name in ("readiness", "raw_archive", "provider_egress")
    )

    if run_provider_ingest and ready_for_manual_ingestion:
        operations["seed_stock_universe"] = invoke_operation(
            lambda_client,
            function_name,
            {
                "stockbrief_operation": "seed_stock_universe",
                "tickers": list(tickers),
            },
        )
        if operations["seed_stock_universe"].ok:
            for provider in providers:
                operations[f"refresh_{provider}"] = invoke_operation(
                    lambda_client,
                    function_name,
                    {
                        "stockbrief_operation": "refresh_score_snapshots",
                        "provider": provider,
                        "tickers": list(tickers),
                        "source_date": source_date,
                    },
                )

    required_operation_names = [
        "readiness",
        "raw_archive",
        "provider_egress",
    ]
    if "seed_stock_universe" in operations:
        required_operation_names.append("seed_stock_universe")
    required_operation_names.extend(
        f"refresh_{provider}"
        for provider in providers
        if f"refresh_{provider}" in operations
    )
    required_operations = {
        name: result
        for name, result in operations.items()
        if name in required_operation_names
    }
    optional_operations = {
        name: result
        for name, result in operations.items()
        if name not in required_operation_names
    }
    blockers = collect_blockers(required_operations)
    observations = collect_blockers(optional_operations)
    if run_provider_ingest and not ready_for_manual_ingestion:
        blockers.append(
            {
                "operation": "provider_ingest",
                "code": "preflight_not_ready",
                "skipped_operations": [
                    "seed_stock_universe",
                    *[f"refresh_{provider}" for provider in providers],
                ],
            }
        )
    if run_provider_ingest and "seed_stock_universe" in operations and not any(
        name.startswith("refresh_") for name in operations
    ):
        blockers.append(
            {
                "operation": "provider_ingest",
                "code": "stock_universe_seed_not_ready",
                "skipped_operations": [f"refresh_{provider}" for provider in providers],
            }
        )
    return {
        "ok": all(result.ok for result in required_operations.values()) and not blockers,
        "ready_for_manual_ingestion": ready_for_manual_ingestion,
        "scheduler_enable_ready": operations["scheduler_gate"].ok,
        "function_name": function_name,
        "region": region,
        "profile": profile,
        "providers": list(providers),
        "tickers": list(tickers),
        "source_date": source_date,
        "operations": {name: result.as_dict() for name, result in operations.items()},
        "blockers": blockers,
        "observations": observations,
    }


def invoke_operation(
    client: Any,
    function_name: str,
    payload: dict[str, Any],
) -> OperationResult:
    operation = str(payload["stockbrief_operation"])
    try:
        response = client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        status_code = response.get("StatusCode")
        function_error = response.get("FunctionError")
    except (BotoCoreError, ClientError) as exc:
        return OperationResult(
            ok=False,
            operation=operation,
            status_code=None,
            payload={},
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

    try:
        parsed_payload = parse_lambda_payload(response.get("Payload"))
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        return OperationResult(
            ok=False,
            operation=operation,
            status_code=status_code if isinstance(status_code, int) else None,
            payload={},
            error_code="invalid_lambda_payload",
            error_message=str(exc),
        )

    return OperationResult(
        ok=status_code == 200 and not function_error and bool(parsed_payload.get("ok")),
        operation=operation,
        status_code=status_code if isinstance(status_code, int) else None,
        payload=parsed_payload,
        error_code=str(function_error) if function_error else None,
    )


def parse_lambda_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if hasattr(payload, "read"):
        raw = payload.read()
    else:
        raw = payload
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = bytes(raw)
    if not raw_bytes:
        return {}
    parsed = json.loads(raw_bytes.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def client_setup_error_result(
    exc: BotoCoreError,
    *,
    function_name: str,
    region: str,
    profile: str | None,
    providers: tuple[str, ...],
    tickers: tuple[str, ...],
    source_date: str | None,
) -> dict[str, Any]:
    operation = OperationResult(
        ok=False,
        operation="lambda_client",
        status_code=None,
        payload={},
        error_code=type(exc).__name__,
        error_message=str(exc),
    )
    return {
        "ok": False,
        "ready_for_manual_ingestion": False,
        "scheduler_enable_ready": False,
        "function_name": function_name,
        "region": region,
        "profile": profile,
        "providers": list(providers),
        "tickers": list(tickers),
        "source_date": source_date,
        "operations": {"lambda_client": operation.as_dict()},
        "blockers": [{"operation": "lambda_client", "code": type(exc).__name__}],
        "observations": [],
    }


def collect_blockers(operations: dict[str, OperationResult]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name, result in operations.items():
        payload = result.payload
        for issue in payload.get("issues", []):
            if isinstance(issue, dict):
                blockers.append({"operation": name, **redact(issue)})
        for blocker in payload.get("blockers", []):
            if isinstance(blocker, dict):
                blockers.append({"operation": name, **redact(blocker)})
        if not result.ok and not payload.get("issues") and not payload.get("blockers"):
            blockers.append(
                {
                    "operation": name,
                    "code": result.error_code or "operation_not_ready",
                }
            )
    return blockers


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if is_secret_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.lower()
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def redact_string(value: str) -> str:
    redacted = re.sub(r"\b\d{12}\b", "[REDACTED_ACCOUNT]", value)
    return re.sub(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", "[REDACTED_ACCESS_KEY]", redacted)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
