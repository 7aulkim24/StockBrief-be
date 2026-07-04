#!/usr/bin/env python3
"""Validate backend-dev-deploy TFVARS_JSON before Terraform runs.

This script owns JSON shape and semantic deploy-profile checks.
It does not inspect a rendered Terraform plan; scripts/check_dev_terraform_plan.sh remains responsible for plan-output guardrails after Terraform has produced a plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TfvarsValidationError(Exception):
    messages: tuple[str, ...]
    heading: str | None = None

    def __str__(self) -> str:
        if self.heading:
            return "\n".join([self.heading, *[f"- {message}" for message in self.messages]])
        return "\n".join(self.messages)


def _list_value(tfvars: dict[str, Any], name: str) -> list[Any]:
    value = tfvars.get(name, [])
    return value if isinstance(value, list) else []


def parse_tfvars_json(tfvars_json: str) -> dict[str, Any]:
    try:
        parsed_tfvars = json.loads(tfvars_json)
    except json.JSONDecodeError as exc:
        raise TfvarsValidationError((f"TFVARS_JSON is not valid JSON: {exc}",)) from exc
    if not isinstance(parsed_tfvars, dict):
        raise TfvarsValidationError(("TFVARS_JSON must be a JSON object.",))
    return parsed_tfvars


def validate_tfvars_environment(tfvars: dict[str, Any], target_env: str) -> list[str]:
    if tfvars.get("environment") != target_env:
        return [f"TFVARS_JSON environment must match target_env ({target_env})."]
    return []


def validate_semantic_tfvars(tfvars: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    chat_provider = tfvars.get("chat_provider", "mock")
    agentcore_enabled = bool(tfvars.get("agentcore_runtime_enabled", False))
    agentcore_container_uri = str(tfvars.get("agentcore_runtime_container_uri", "")).strip()
    agentcore_external_arn = str(tfvars.get("agentcore_runtime_external_arn", "")).strip()
    agentcore_external_id = str(tfvars.get("agentcore_runtime_external_id", "")).strip()
    agentcore_endpoint_name = str(tfvars.get("agentcore_runtime_endpoint_name", "")).strip()
    lambda_subnet_ids = _list_value(tfvars, "lambda_subnet_ids")
    lambda_nat_route_subnet_ids = _list_value(tfvars, "lambda_nat_route_subnet_ids")
    nat_public_subnet_id = str(tfvars.get("lambda_nat_public_subnet_id", "")).strip()
    nat_create_public_subnet = bool(tfvars.get("lambda_nat_create_public_subnet", False))
    nat_public_subnet_cidr = str(tfvars.get("lambda_nat_public_subnet_cidr_block", "")).strip()
    nat_internet_gateway_id = str(tfvars.get("lambda_nat_internet_gateway_id", "")).strip()
    nat_create_internet_gateway = bool(tfvars.get("lambda_nat_create_internet_gateway", False))
    live_chat_provider_enabled = chat_provider in {"bedrock", "agentcore"}

    if agentcore_enabled and not agentcore_container_uri:
        errors.append("agentcore_runtime_enabled=true requires agentcore_runtime_container_uri.")
    if chat_provider == "agentcore" and not agentcore_enabled:
        errors.append("chat_provider=agentcore requires agentcore_runtime_enabled=true.")
    if chat_provider == "agentcore" and not agentcore_container_uri:
        errors.append("chat_provider=agentcore requires a non-empty agentcore_runtime_container_uri.")
    if not agentcore_enabled and (
        agentcore_external_arn or agentcore_external_id or agentcore_endpoint_name
    ):
        errors.append(
            "AgentCore external runtime metadata requires agentcore_runtime_enabled=true."
        )
    if bool(agentcore_external_arn) != bool(agentcore_external_id):
        errors.append(
            "agentcore_runtime_external_arn and agentcore_runtime_external_id must be set together."
        )
    if agentcore_endpoint_name and not (agentcore_external_arn and agentcore_external_id):
        errors.append(
            "agentcore_runtime_endpoint_name requires agentcore_runtime_external_arn "
            "and agentcore_runtime_external_id."
        )
    if tfvars.get("agentcore_network_mode", "PUBLIC") == "VPC":
        managed_networking = (
            bool(tfvars.get("vpc_id"))
            and bool(_list_value(tfvars, "db_subnet_ids"))
            and bool(lambda_subnet_ids)
        )
        explicit_security_groups = bool(_list_value(tfvars, "lambda_security_group_ids"))
        if not managed_networking and not explicit_security_groups:
            errors.append(
                "agentcore_network_mode=VPC requires managed networking "
                "(vpc_id, db_subnet_ids, lambda_subnet_ids) or lambda_security_group_ids."
            )
    if lambda_subnet_ids and live_chat_provider_enabled:
        nat_ready = bool(tfvars.get("enable_lambda_nat_egress", False)) or (
            bool(nat_public_subnet_id) and bool(lambda_nat_route_subnet_ids)
        )
        if not nat_ready:
            errors.append(
                "VPC-attached Lambda with chat_provider=bedrock/agentcore requires outbound "
                "egress: set enable_lambda_nat_egress=true with "
                "lambda_nat_public_subnet_id/lambda_nat_route_subnet_ids, or record reviewed "
                "NAT subnet ids when an existing route table already provides egress."
            )
    if tfvars.get("enable_lambda_nat_egress", False):
        if nat_public_subnet_id and nat_create_public_subnet:
            errors.append(
                "enable_lambda_nat_egress must use either lambda_nat_public_subnet_id or "
                "lambda_nat_create_public_subnet=true, not both."
            )
        if nat_create_public_subnet and not nat_public_subnet_cidr:
            errors.append(
                "lambda_nat_create_public_subnet=true requires "
                "lambda_nat_public_subnet_cidr_block."
            )
        if nat_create_public_subnet and not nat_create_internet_gateway and not nat_internet_gateway_id:
            errors.append(
                "lambda_nat_create_public_subnet=true requires either "
                "lambda_nat_create_internet_gateway=true or "
                "lambda_nat_internet_gateway_id in backend-dev-deploy; "
                "otherwise Terraform auto-discovers an Internet Gateway "
                "attached to vpc_id and may fail with 'no matching Internet Gateway found'."
            )
        if nat_create_internet_gateway and nat_internet_gateway_id:
            errors.append(
                "enable_lambda_nat_egress must use either lambda_nat_internet_gateway_id or "
                "lambda_nat_create_internet_gateway=true, not both."
            )
        if not lambda_nat_route_subnet_ids:
            errors.append("enable_lambda_nat_egress=true requires lambda_nat_route_subnet_ids.")
        if not nat_public_subnet_id and not nat_create_public_subnet:
            errors.append(
                "enable_lambda_nat_egress=true requires lambda_nat_public_subnet_id or "
                "lambda_nat_create_public_subnet=true."
            )
    return errors


def load_validated_tfvars_json(tfvars_json: str, target_env: str) -> dict[str, Any]:
    parsed_tfvars = parse_tfvars_json(tfvars_json)
    environment_errors = validate_tfvars_environment(parsed_tfvars, target_env)
    if environment_errors:
        raise TfvarsValidationError(tuple(environment_errors))
    semantic_errors = validate_semantic_tfvars(parsed_tfvars)
    if semantic_errors:
        raise TfvarsValidationError(
            tuple(semantic_errors),
            heading="TFVARS_JSON failed deploy profile validation:",
        )
    return parsed_tfvars


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate backend-dev-deploy TFVARS_JSON and print normalized JSON."
    )
    parser.add_argument("--target-env", required=True)
    parser.add_argument(
        "--tfvars-json",
        help="Raw TFVARS_JSON value. If omitted, stdin is used.",
    )
    args = parser.parse_args()

    tfvars_json = args.tfvars_json if args.tfvars_json is not None else sys.stdin.read()
    try:
        parsed_tfvars = load_validated_tfvars_json(tfvars_json, args.target_env)
    except TfvarsValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    json.dump(parsed_tfvars, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
