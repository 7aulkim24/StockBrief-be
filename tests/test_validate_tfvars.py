from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from scripts.validate_tfvars import TfvarsValidationError, load_validated_tfvars_json


def _tfvars(**overrides):
    tfvars = {
        "environment": "dev-owen",
        "chat_provider": "mock",
        "agentcore_runtime_enabled": False,
        "lambda_subnet_ids": [],
        "enable_lambda_nat_egress": False,
    }
    tfvars.update(overrides)
    return tfvars


def _load(tfvars):
    return load_validated_tfvars_json(json.dumps(tfvars), "dev-owen")


def _messages(exc_info) -> str:
    return str(exc_info.value)


def test_accepts_minimal_mock_profile() -> None:
    assert _load(_tfvars())["environment"] == "dev-owen"


def test_rejects_invalid_json() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        load_validated_tfvars_json("{", "dev-owen")

    assert "TFVARS_JSON is not valid JSON" in _messages(exc_info)


def test_rejects_environment_mismatch() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        load_validated_tfvars_json(json.dumps(_tfvars(environment="dev")), "dev-owen")

    assert "TFVARS_JSON environment must match target_env (dev-owen)." in _messages(exc_info)


def test_rejects_agentcore_chat_without_runtime_enabled() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        _load(
            _tfvars(
                chat_provider="agentcore",
                agentcore_runtime_enabled=False,
                agentcore_runtime_container_uri="",
            )
        )

    message = _messages(exc_info)
    assert "TFVARS_JSON failed deploy profile validation" in message
    assert "chat_provider=agentcore requires agentcore_runtime_enabled=true" in message
    assert "chat_provider=agentcore requires a non-empty agentcore_runtime_container_uri" in message


def test_rejects_vpc_agentcore_without_networking_or_security_groups() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        _load(_tfvars(agentcore_network_mode="VPC"))

    assert "agentcore_network_mode=VPC requires managed networking" in _messages(exc_info)


def test_rejects_vpc_live_chat_without_egress() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        _load(_tfvars(chat_provider="bedrock", lambda_subnet_ids=["subnet-lambda-a"]))

    assert "VPC-attached Lambda with chat_provider=bedrock/agentcore" in _messages(exc_info)


def test_rejects_managed_nat_public_subnet_without_explicit_igw_choice() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        _load(
            _tfvars(
                enable_lambda_nat_egress=True,
                lambda_nat_create_public_subnet=True,
                lambda_nat_public_subnet_cidr_block="10.0.100.0/24",
                lambda_nat_route_subnet_ids=["subnet-lambda-a"],
            )
        )

    message = _messages(exc_info)
    assert "lambda_nat_internet_gateway_id in backend-dev-deploy" in message
    assert "no matching Internet Gateway found" in message


def test_rejects_conflicting_nat_public_subnet_modes() -> None:
    with pytest.raises(TfvarsValidationError) as exc_info:
        _load(
            _tfvars(
                enable_lambda_nat_egress=True,
                lambda_nat_public_subnet_id="subnet-public",
                lambda_nat_create_public_subnet=True,
                lambda_nat_public_subnet_cidr_block="10.0.100.0/24",
                lambda_nat_create_internet_gateway=True,
                lambda_nat_route_subnet_ids=["subnet-lambda-a"],
            )
        )

    assert "lambda_nat_public_subnet_id or lambda_nat_create_public_subnet=true, not both" in _messages(
        exc_info
    )


def test_cli_prints_normalized_json_for_valid_profile() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_tfvars.py",
            "--target-env",
            "dev-owen",
        ],
        input=json.dumps(_tfvars()),
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["environment"] == "dev-owen"
    assert result.stderr == ""


def test_resolver_writes_profile_files_and_github_outputs(tmp_path) -> None:
    tf_dir = tmp_path / "infra" / "terraform"
    tfvars = _tfvars()
    variables = {
        "AWS_DEV_OWEN_DEPLOY_ROLE_ARN": "arn:aws:iam::123456789012:role/deploy",
        "TF_BACKEND_CONFIG_HCL": 'bucket = "state-bucket"\nkey = "dev-owen/terraform.tfstate"\n',
        "TFVARS_JSON": json.dumps(tfvars),
    }
    env = {
        **os.environ,
        "TARGET_ENV": "dev-owen",
        "TF_DIR": str(tf_dir),
        "GITHUB_VARIABLES_JSON": json.dumps(variables),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    result = subprocess.run(
        [sys.executable, "scripts/resolve_backend_deploy_profile.py"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert "target_env=dev-owen" in result.stdout
    assert "tf_var_file=envs/dev-owen/deploy.auto.tfvars.json" in result.stdout
    assert "tf_backend_config=backends/dev-owen.hcl" in result.stdout
    assert "deploy_role_arn=arn:aws:iam::123456789012:role/deploy" in result.stdout
    assert json.loads(
        (tf_dir / "envs/dev-owen/deploy.auto.tfvars.json").read_text(encoding="utf-8")
    ) == tfvars
    assert "state-bucket" in (tf_dir / "backends/dev-owen.hcl").read_text(encoding="utf-8")
