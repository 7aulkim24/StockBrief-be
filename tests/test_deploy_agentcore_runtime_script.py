from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

from scripts.deploy_agentcore_runtime import (
    _deploy_runtime,
    _patch_tfvars,
    _runtime_environment,
    _validate_ssm_metadata,
    _write_tfvars,
)


IMAGE_URI = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/stockbrief-agent:test"
RUNTIME_ARN = "arn:aws:bedrock-agentcore:ap-northeast-2:123456789012:runtime/test"
RUNTIME_ID = "stockbrief_dev_owen_agent-ABCDEFGHIJ"
ENDPOINT_NAME = "stockbrief_dev_owen_default"
ENDPOINT_ARN = (
    "arn:aws:bedrock-agentcore:ap-northeast-2:123456789012:runtime-endpoint/test"
)
ROLE_ARN = "arn:aws:iam::123456789012:role/stockbrief-dev-owen-agentcore-runtime-role"


def _client():
    return boto3.client(
        "bedrock-agentcore-control",
        region_name="ap-northeast-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def _tfvars(**overrides):
    tfvars = {
        "environment": "dev-owen",
        "aws_region": "ap-northeast-2",
        "agentcore_runtime_container_uri": IMAGE_URI,
        "agentcore_network_mode": "PUBLIC",
        "bedrock_chat_region": "",
        "bedrock_chat_model_id": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "bedrock_chat_max_tokens": 1000,
        "bedrock_chat_temperature": 0.2,
        "bedrock_chat_timeout_seconds": 8,
        "agentcore_runtime_max_turns": 4,
    }
    tfvars.update(overrides)
    return tfvars


def _runtime_request():
    return {
        "agentRuntimeArtifact": {
            "containerConfiguration": {"containerUri": IMAGE_URI}
        },
        "roleArn": ROLE_ARN,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "environmentVariables": _runtime_environment(_tfvars()),
        "requestHeaderConfiguration": {
            "requestHeaderAllowlist": ["x-correlation-id", "x-user-id"]
        },
    }


def _ready_runtime():
    now = datetime(2026, 7, 4, tzinfo=UTC)
    return {
        "agentRuntimeArn": RUNTIME_ARN,
        "agentRuntimeName": "stockbrief_dev_owen_agent",
        "agentRuntimeId": RUNTIME_ID,
        "agentRuntimeVersion": "1",
        "createdAt": now,
        "lastUpdatedAt": now,
        "roleArn": ROLE_ARN,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "status": "READY",
        "lifecycleConfiguration": {},
    }


def _ready_endpoint():
    now = datetime(2026, 7, 4, tzinfo=UTC)
    return {
        "liveVersion": "1",
        "targetVersion": "1",
        "agentRuntimeEndpointArn": ENDPOINT_ARN,
        "agentRuntimeArn": RUNTIME_ARN,
        "status": "READY",
        "createdAt": now,
        "lastUpdatedAt": now,
        "name": ENDPOINT_NAME,
        "id": "endpoint-id",
    }


def test_agentcore_metadata_patches_external_runtime_tfvars() -> None:
    tfvars = {
        "environment": "dev-owen",
        "agentcore_runtime_external_arn": "",
        "agentcore_runtime_external_id": "",
        "agentcore_runtime_endpoint_name": "",
    }

    changed = _patch_tfvars(
        tfvars,
        {
            "runtime_arn": "arn:aws:bedrock-agentcore:ap-northeast-2:123456789012:runtime/test",
            "runtime_id": "stockbrief_dev_owen_agent-ABCDEFGHIJ",
            "endpoint_name": "stockbrief_dev_owen_default",
        },
    )

    assert changed is True
    assert tfvars["agentcore_runtime_external_arn"].endswith(":runtime/test")
    assert tfvars["agentcore_runtime_external_id"] == "stockbrief_dev_owen_agent-ABCDEFGHIJ"
    assert tfvars["agentcore_runtime_endpoint_name"] == "stockbrief_dev_owen_default"


def test_rejects_partial_ssm_metadata() -> None:
    with pytest.raises(ValueError) as exc_info:
        _validate_ssm_metadata(
            {
                "runtime_arn": RUNTIME_ARN,
                "runtime_id": RUNTIME_ID,
            }
        )

    assert "Incomplete AgentCore SSM metadata" in str(exc_info.value)
    assert "endpoint_name" in str(exc_info.value)


def test_agentcore_runtime_environment_matches_tfvars() -> None:
    env = _runtime_environment(
        {
            "environment": "dev-owen",
            "aws_region": "ap-northeast-2",
            "bedrock_chat_region": "",
            "bedrock_chat_model_id": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "bedrock_chat_max_tokens": 1000,
            "bedrock_chat_temperature": 0.2,
            "bedrock_chat_timeout_seconds": 8,
            "agentcore_runtime_max_turns": 4,
        }
    )

    assert env["APP_ENV"] == "dev-owen"
    assert env["SERVICE_NAME"] == "stockbrief-agent"
    assert env["BEDROCK_CHAT_MODEL_ID"] == "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert env["BEDROCK_CHAT_REGION"] == "ap-northeast-2"
    assert env["BEDROCK_CHAT_MAX_TOKENS"] == "1000"
    assert env["AGENTCORE_RUNTIME_USE_DEV_MODEL"] == "false"


def test_write_tfvars_preserves_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "deploy.auto.tfvars.json"
    _write_tfvars(path, {"environment": "dev-owen"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"environment": "dev-owen"}


def test_deploy_runtime_creates_runtime_and_endpoint_with_expected_payload() -> None:
    client = _client()
    stubber = Stubber(client)
    now = datetime(2026, 7, 4, tzinfo=UTC)
    stubber.add_response(
        "list_agent_runtimes",
        {"agentRuntimes": []},
        {},
    )
    stubber.add_response(
        "create_agent_runtime",
        {
            "agentRuntimeArn": RUNTIME_ARN,
            "agentRuntimeId": RUNTIME_ID,
            "agentRuntimeVersion": "1",
            "createdAt": now,
            "status": "CREATING",
        },
        {"agentRuntimeName": "stockbrief_dev_owen_agent", **_runtime_request()},
    )
    stubber.add_response(
        "get_agent_runtime",
        _ready_runtime(),
        {"agentRuntimeId": RUNTIME_ID},
    )
    stubber.add_client_error(
        "get_agent_runtime_endpoint",
        service_error_code="ResourceNotFoundException",
        expected_params={"agentRuntimeId": RUNTIME_ID, "endpointName": ENDPOINT_NAME},
    )
    stubber.add_response(
        "create_agent_runtime_endpoint",
        {
            "targetVersion": "1",
            "agentRuntimeEndpointArn": ENDPOINT_ARN,
            "agentRuntimeArn": RUNTIME_ARN,
            "agentRuntimeId": RUNTIME_ID,
            "endpointName": ENDPOINT_NAME,
            "status": "CREATING",
            "createdAt": now,
        },
        {
            "agentRuntimeId": RUNTIME_ID,
            "name": ENDPOINT_NAME,
            "agentRuntimeVersion": "1",
        },
    )
    stubber.add_response(
        "get_agent_runtime_endpoint",
        _ready_endpoint(),
        {"agentRuntimeId": RUNTIME_ID, "endpointName": ENDPOINT_NAME},
    )

    with stubber:
        metadata = _deploy_runtime(
            client=client,
            tfvars=_tfvars(),
            role_arn=ROLE_ARN,
            wait_seconds=1,
        )

    assert metadata == {
        "runtime_arn": RUNTIME_ARN,
        "runtime_id": RUNTIME_ID,
        "endpoint_name": ENDPOINT_NAME,
        "image_uri": IMAGE_URI,
        "model_id": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "version": "1",
    }


def test_deploy_runtime_updates_existing_runtime_and_endpoint() -> None:
    client = _client()
    stubber = Stubber(client)
    now = datetime(2026, 7, 4, tzinfo=UTC)
    stubber.add_response(
        "update_agent_runtime",
        {
            "agentRuntimeArn": RUNTIME_ARN,
            "agentRuntimeId": RUNTIME_ID,
            "agentRuntimeVersion": "2",
            "createdAt": now,
            "lastUpdatedAt": now,
            "status": "UPDATING",
        },
        {"agentRuntimeId": RUNTIME_ID, **_runtime_request()},
    )
    stubber.add_response(
        "get_agent_runtime",
        {**_ready_runtime(), "agentRuntimeVersion": "2"},
        {"agentRuntimeId": RUNTIME_ID},
    )
    stubber.add_response(
        "get_agent_runtime_endpoint",
        _ready_endpoint(),
        {"agentRuntimeId": RUNTIME_ID, "endpointName": ENDPOINT_NAME},
    )
    stubber.add_response(
        "update_agent_runtime_endpoint",
        {
            "liveVersion": "1",
            "targetVersion": "2",
            "agentRuntimeEndpointArn": ENDPOINT_ARN,
            "agentRuntimeArn": RUNTIME_ARN,
            "status": "UPDATING",
            "createdAt": now,
            "lastUpdatedAt": now,
        },
        {
            "agentRuntimeId": RUNTIME_ID,
            "endpointName": ENDPOINT_NAME,
            "agentRuntimeVersion": "2",
        },
    )
    stubber.add_response(
        "get_agent_runtime_endpoint",
        {**_ready_endpoint(), "liveVersion": "2", "targetVersion": "2"},
        {"agentRuntimeId": RUNTIME_ID, "endpointName": ENDPOINT_NAME},
    )

    with stubber:
        metadata = _deploy_runtime(
            client=client,
            tfvars=_tfvars(
                agentcore_runtime_external_id=RUNTIME_ID,
                agentcore_runtime_endpoint_name=ENDPOINT_NAME,
            ),
            role_arn=ROLE_ARN,
            wait_seconds=1,
        )

    assert metadata["runtime_id"] == RUNTIME_ID
    assert metadata["endpoint_name"] == ENDPOINT_NAME
    assert metadata["model_id"] == "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert metadata["version"] == "2"
