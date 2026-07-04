#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


READY_STATES = {"READY"}
FAILED_STATES = {"CREATE_FAILED", "UPDATE_FAILED", "FAILED", "DELETE_FAILED"}
REQUIRED_METADATA_KEYS = {"runtime_arn", "runtime_id", "endpoint_name"}


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _runtime_name(name_prefix: str) -> str:
    return f"{name_prefix}_agent".replace("-", "_")


def _endpoint_name(name_prefix: str) -> str:
    return f"{name_prefix}_default".replace("-", "_")


def _name_prefix(tfvars: dict[str, Any]) -> str:
    project = str(tfvars.get("project", "stockbrief")).strip() or "stockbrief"
    environment = str(tfvars.get("environment", "")).strip()
    if not environment:
        raise ValueError("TFVARS_JSON requires environment.")
    return f"{project}-{environment}"


def _ssm_prefix(tfvars: dict[str, Any]) -> str:
    return f"/stockbrief/{tfvars['environment']}/agentcore"


def _runtime_environment(tfvars: dict[str, Any]) -> dict[str, str]:
    region = str(tfvars.get("aws_region", "ap-northeast-2"))
    bedrock_region = str(tfvars.get("bedrock_chat_region") or region)
    return {
        "APP_ENV": str(tfvars["environment"]),
        "SERVICE_NAME": "stockbrief-agent",
        "BEDROCK_CHAT_MODEL_ID": str(
            tfvars.get("bedrock_chat_model_id", "apac.amazon.nova-micro-v1:0")
        ),
        "BEDROCK_CHAT_REGION": bedrock_region,
        "BEDROCK_CHAT_MAX_TOKENS": str(tfvars.get("bedrock_chat_max_tokens", 700)),
        "BEDROCK_CHAT_TEMPERATURE": str(tfvars.get("bedrock_chat_temperature", 0.2)),
        "BEDROCK_CHAT_TIMEOUT_SECONDS": str(
            tfvars.get("bedrock_chat_timeout_seconds", 8)
        ),
        "AGENTCORE_RUNTIME_MAX_TURNS": str(
            tfvars.get("agentcore_runtime_max_turns", 4)
        ),
        "AGENTCORE_RUNTIME_USE_DEV_MODEL": "false",
    }


def _network_configuration(tfvars: dict[str, Any]) -> dict[str, Any]:
    mode = str(tfvars.get("agentcore_network_mode", "PUBLIC"))
    config: dict[str, Any] = {"networkMode": mode}
    if mode == "VPC":
        security_groups = tfvars.get("lambda_security_group_ids") or []
        subnets = tfvars.get("lambda_subnet_ids") or []
        if not security_groups or not subnets:
            raise ValueError(
                "agentcore_network_mode=VPC requires lambda_security_group_ids "
                "and lambda_subnet_ids for direct deploy."
            )
        config["networkModeConfig"] = {
            "securityGroups": security_groups,
            "subnets": subnets,
        }
    return config


def _load_tfvars(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as tfvars_file:
        tfvars = json.load(tfvars_file)
    if not isinstance(tfvars, dict):
        raise ValueError("tfvars file must contain a JSON object.")
    return tfvars


def _write_tfvars(path: Path, tfvars: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as tfvars_file:
        json.dump(tfvars, tfvars_file, ensure_ascii=False, indent=2)
        tfvars_file.write("\n")


def _ssm_metadata(ssm, prefix: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    paginator = ssm.get_paginator("get_parameters_by_path")
    for page in paginator.paginate(Path=prefix, Recursive=False, WithDecryption=False):
        for parameter in page.get("Parameters", []):
            name = str(parameter.get("Name", "")).rsplit("/", 1)[-1]
            value = str(parameter.get("Value", ""))
            if name:
                metadata[name] = value
    return metadata


def _write_ssm_metadata(ssm, prefix: str, metadata: dict[str, str]) -> None:
    for name, value in metadata.items():
        ssm.put_parameter(
            Name=f"{prefix}/{name}",
            Value=value,
            Type="String",
            Overwrite=True,
        )


def _validate_ssm_metadata(metadata: dict[str, str]) -> None:
    present = {key for key in REQUIRED_METADATA_KEYS if metadata.get(key)}
    if present and present != REQUIRED_METADATA_KEYS:
        missing = ", ".join(sorted(REQUIRED_METADATA_KEYS - present))
        raise ValueError(f"Incomplete AgentCore SSM metadata. Missing: {missing}.")


def _patch_tfvars(tfvars: dict[str, Any], metadata: dict[str, str]) -> bool:
    mapping = {
        "runtime_arn": "agentcore_runtime_external_arn",
        "runtime_id": "agentcore_runtime_external_id",
        "endpoint_name": "agentcore_runtime_endpoint_name",
    }
    changed = False
    for source, target in mapping.items():
        value = metadata.get(source, "")
        if value and tfvars.get(target, "") != value:
            tfvars[target] = value
            changed = True
    return changed


def _find_runtime_id(client, runtime_name: str) -> str:
    paginator = client.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for runtime in page.get("agentRuntimes", []):
            name = str(runtime.get("agentRuntimeName", ""))
            runtime_id = str(runtime.get("agentRuntimeId", ""))
            if name == runtime_name or runtime_id.startswith(f"{runtime_name}-"):
                return runtime_id
    return ""


def _wait_runtime(client, runtime_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.get_agent_runtime(agentRuntimeId=runtime_id)
        status = str(last.get("status", ""))
        if status in READY_STATES:
            return last
        if status in FAILED_STATES:
            raise RuntimeError(f"AgentCore Runtime failed: {status}")
        time.sleep(10)
    raise TimeoutError(f"AgentCore Runtime did not become READY: {last}")


def _endpoint_exists(client, runtime_id: str, endpoint_name: str) -> bool:
    try:
        client.get_agent_runtime_endpoint(
            agentRuntimeId=runtime_id,
            endpointName=endpoint_name,
        )
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"ResourceNotFoundException", "ValidationException"}:
            return False
        raise


def _wait_endpoint(
    client,
    runtime_id: str,
    endpoint_name: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.get_agent_runtime_endpoint(
            agentRuntimeId=runtime_id,
            endpointName=endpoint_name,
        )
        status = str(last.get("status", ""))
        if status in READY_STATES:
            return last
        if status in FAILED_STATES:
            raise RuntimeError(f"AgentCore Runtime endpoint failed: {status}")
        time.sleep(10)
    raise TimeoutError(f"AgentCore Runtime endpoint did not become READY: {last}")


def _deploy_runtime(
    *,
    client,
    tfvars: dict[str, Any],
    role_arn: str,
    wait_seconds: int,
) -> dict[str, str]:
    name_prefix = _name_prefix(tfvars)
    runtime_name = _runtime_name(name_prefix)
    endpoint_name = str(tfvars.get("agentcore_runtime_endpoint_name") or "").strip()
    endpoint_name = endpoint_name or _endpoint_name(name_prefix)
    runtime_id = str(tfvars.get("agentcore_runtime_external_id") or "").strip()
    runtime_id = runtime_id or _find_runtime_id(client, runtime_name)
    container_uri = str(tfvars.get("agentcore_runtime_container_uri", "")).strip()
    if not container_uri:
        raise ValueError("agentcore_runtime_container_uri is required.")

    request = {
        "agentRuntimeArtifact": {
            "containerConfiguration": {"containerUri": container_uri}
        },
        "roleArn": role_arn,
        "networkConfiguration": _network_configuration(tfvars),
        "environmentVariables": _runtime_environment(tfvars),
        "requestHeaderConfiguration": {
            "requestHeaderAllowlist": ["x-correlation-id", "x-user-id"]
        },
    }
    if runtime_id:
        response = client.update_agent_runtime(
            agentRuntimeId=runtime_id,
            **request,
        )
    else:
        response = client.create_agent_runtime(
            agentRuntimeName=runtime_name,
            **request,
        )
        runtime_id = str(response["agentRuntimeId"])

    runtime = _wait_runtime(client, runtime_id, wait_seconds)
    runtime_version = str(runtime.get("agentRuntimeVersion") or response["agentRuntimeVersion"])
    if _endpoint_exists(client, runtime_id, endpoint_name):
        client.update_agent_runtime_endpoint(
            agentRuntimeId=runtime_id,
            endpointName=endpoint_name,
            agentRuntimeVersion=runtime_version,
        )
    else:
        client.create_agent_runtime_endpoint(
            agentRuntimeId=runtime_id,
            name=endpoint_name,
            agentRuntimeVersion=runtime_version,
        )
    _wait_endpoint(client, runtime_id, endpoint_name, wait_seconds)
    return {
        "runtime_arn": str(runtime.get("agentRuntimeArn") or response["agentRuntimeArn"]),
        "runtime_id": runtime_id,
        "endpoint_name": endpoint_name,
        "image_uri": container_uri,
        "model_id": str(tfvars.get("bedrock_chat_model_id", "")).strip(),
        "version": runtime_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or update the StockBrief AgentCore Runtime outside Terraform."
    )
    parser.add_argument("--var-file", required=True, type=Path)
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--role-arn", default="")
    parser.add_argument("--hydrate-only", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()

    try:
        tfvars = _load_tfvars(args.var_file)
        if not bool(tfvars.get("agentcore_runtime_enabled", False)):
            print("AgentCore direct deploy skipped: agentcore_runtime_enabled=false.")
            return 0

        ssm = boto3.client("ssm", region_name=args.region)
        metadata = _ssm_metadata(ssm, _ssm_prefix(tfvars))
        _validate_ssm_metadata(metadata)
        if _patch_tfvars(tfvars, metadata):
            _write_tfvars(args.var_file, tfvars)
            print("AgentCore tfvars hydrated from SSM metadata.")

        if args.hydrate_only:
            return 0

        if not args.role_arn:
            return _fail("--role-arn is required unless --hydrate-only is set.")

        client = boto3.client("bedrock-agentcore-control", region_name=args.region)
        metadata = _deploy_runtime(
            client=client,
            tfvars=tfvars,
            role_arn=args.role_arn,
            wait_seconds=args.wait_seconds,
        )
        _write_ssm_metadata(ssm, _ssm_prefix(tfvars), metadata)
        _patch_tfvars(tfvars, metadata)
        _write_tfvars(args.var_file, tfvars)
        print(json.dumps(metadata, sort_keys=True))
        return 0
    except (ClientError, OSError, ValueError, RuntimeError, TimeoutError) as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
