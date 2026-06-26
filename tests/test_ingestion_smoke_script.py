from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts/check_ingestion_smoke.py"


spec = importlib.util.spec_from_file_location("check_ingestion_smoke", SCRIPT_PATH)
assert spec is not None
smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


class FakeLambdaClient:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        request = json.loads(kwargs["Payload"].decode("utf-8"))
        operation = request["stockbrief_operation"]
        payload = self.responses.get(operation, {"ok": True})
        return {
            "StatusCode": 200,
            "Payload": io.BytesIO(json.dumps(payload).encode("utf-8")),
        }


class MalformedPayloadLambdaClient:
    def invoke(self, **kwargs):
        return {
            "StatusCode": 200,
            "Payload": io.BytesIO(b"not-json"),
        }


def test_ingestion_smoke_main_exits_nonzero_when_result_is_not_ok(monkeypatch) -> None:
    def fake_run_smoke(**kwargs):
        return {
            "ok": False,
            "ready_for_manual_ingestion": True,
            "operations": {
                "ingest_OpenDART": {
                    "ok": False,
                    "error_code": "operation_not_ready",
                }
            },
        }

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)

    assert smoke.main(["--run-provider-ingest", "--source-date", "2026-06-26"]) == 1


def test_ingestion_smoke_reports_readiness_without_exposing_secret_fields() -> None:
    client = FakeLambdaClient(
        {
            "check_ingestion_readiness": {
                "ok": False,
                "issues": [{"code": "missing_provider_credential", "field": "OPENDART_API_KEY"}],
                "checks": {
                    "providers": {
                        "OpenDART": {
                            "api_key_configured": False,
                            "api_key_preview": "should-not-leak",
                        }
                    }
                },
            },
            "check_raw_archive_write": {"ok": True},
            "check_provider_egress": {"ok": True},
            "get_ingestion_status": {"ok": True, "summary": {"provider_filter": ["OpenDART"]}},
            "check_ingestion_scheduler_enable_gate": {
                "ok": False,
                "blockers": [{"code": "readiness_not_ready"}],
            },
        }
    )

    result = smoke.run_smoke(
        function_name="stockbrief-dev-api",
        region="ap-northeast-2",
        providers=("OpenDART",),
        tickers=("005930",),
        status_limit=5,
        timeout_seconds=1,
        client=client,
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["ready_for_manual_ingestion"] is False
    assert "should-not-leak" not in serialized
    assert '"api_key_preview": "[REDACTED]"' in serialized
    assert {"operation": "readiness", "code": "missing_provider_credential", "field": "OPENDART_API_KEY"} in result[
        "blockers"
    ]


def test_ingestion_smoke_uses_selected_providers_and_tickers() -> None:
    client = FakeLambdaClient(
        {
            "check_ingestion_readiness": {"ok": True},
            "check_raw_archive_write": {"ok": True},
            "check_provider_egress": {"ok": True},
            "get_ingestion_status": {"ok": True},
            "check_ingestion_scheduler_enable_gate": {"ok": True, "scheduler_enable_ready": True},
            "ingest_provider_batch": {"ok": True},
        }
    )

    result = smoke.run_smoke(
        function_name="stockbrief-dev-api",
        region="ap-northeast-2",
        providers=("OpenDART", "NAVER_NEWS"),
        tickers=("005930", "000660"),
        status_limit=7,
        timeout_seconds=1,
        source_date="2026-06-26",
        run_provider_ingest=True,
        client=client,
    )

    payloads = [json.loads(call["Payload"].decode("utf-8")) for call in client.calls]
    assert result["ready_for_manual_ingestion"] is True
    assert {
        "stockbrief_operation": "check_provider_egress",
        "providers": ["OpenDART", "NAVER_NEWS"],
    } in payloads
    assert {
        "stockbrief_operation": "get_ingestion_status",
        "tickers": ["005930", "000660"],
        "providers": ["OpenDART", "NAVER_NEWS"],
        "limit": 7,
    } in payloads
    assert {
        "stockbrief_operation": "ingest_provider_batch",
        "provider": "OpenDART",
        "tickers": ["005930", "000660"],
        "source_date": "2026-06-26",
    } in payloads


def test_ingestion_smoke_provider_ingest_failure_blocks_overall_ok() -> None:
    client = FakeLambdaClient(
        {
            "check_ingestion_readiness": {"ok": True},
            "check_raw_archive_write": {"ok": True},
            "check_provider_egress": {"ok": True},
            "get_ingestion_status": {"ok": True},
            "check_ingestion_scheduler_enable_gate": {"ok": True},
            "ingest_provider_batch": {
                "ok": False,
                "issues": [{"code": "provider_ingest_failed"}],
            },
        }
    )

    result = smoke.run_smoke(
        function_name="stockbrief-dev-api",
        region="ap-northeast-2",
        providers=("OpenDART",),
        tickers=("005930",),
        status_limit=5,
        timeout_seconds=1,
        source_date="2026-06-26",
        run_provider_ingest=True,
        client=client,
    )

    assert result["ready_for_manual_ingestion"] is True
    assert result["ok"] is False
    assert {"operation": "ingest_OpenDART", "code": "provider_ingest_failed"} in result[
        "blockers"
    ]


def test_ingestion_smoke_requires_source_date_before_provider_ingest() -> None:
    result = smoke.run_smoke(
        function_name="stockbrief-dev-api",
        region="ap-northeast-2",
        providers=("OpenDART",),
        tickers=("005930",),
        status_limit=5,
        timeout_seconds=1,
        run_provider_ingest=True,
    )

    assert result["ok"] is False
    assert result["ready_for_manual_ingestion"] is False
    assert result["blockers"] == [{"code": "missing_source_date"}]


def test_invoke_operation_reports_invalid_lambda_payload() -> None:
    result = smoke.invoke_operation(
        MalformedPayloadLambdaClient(),
        "stockbrief-dev-api",
        {"stockbrief_operation": "check_ingestion_readiness"},
    )

    assert result.ok is False
    assert result.operation == "check_ingestion_readiness"
    assert result.status_code == 200
    assert result.payload == {}
    assert result.error_code == "invalid_lambda_payload"
