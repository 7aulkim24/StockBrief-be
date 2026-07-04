from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts/check_agentcore_runtime_preflight.sh"


def _write_tfvars(terraform_dir: Path, profile: dict) -> None:
    tfvars_path = terraform_dir / "envs/dev-owen/deploy.auto.tfvars.json"
    tfvars_path.parent.mkdir(parents=True)
    tfvars_path.write_text(json.dumps(profile), encoding="utf-8")


def _write_aws_stub(bin_dir: Path, body: str) -> Path:
    aws_stub = bin_dir / "aws"
    aws_stub.write_text(body, encoding="utf-8")
    aws_stub.chmod(0o755)
    return aws_stub


def _run_preflight(terraform_dir: Path, env: dict[str, str]):
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--terraform-dir",
            str(terraform_dir),
            "--var-file",
            "envs/dev-owen/deploy.auto.tfvars.json",
            "--region",
            "ap-northeast-2",
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def test_agentcore_preflight_skips_when_runtime_disabled(tmp_path: Path) -> None:
    terraform_dir = tmp_path / "terraform"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "aws.log"
    _write_tfvars(
        terraform_dir,
        {
            "agentcore_runtime_enabled": False,
            "agentcore_runtime_container_uri": "",
        },
    )
    _write_aws_stub(
        bin_dir,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"echo unexpected > {log_path}",
                "exit 1",
            ]
        ),
    )

    result = _run_preflight(
        terraform_dir,
        {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0
    assert "agentcore_runtime_enabled=false" in result.stdout
    assert not log_path.exists()


def test_agentcore_preflight_checks_configured_ecr_image(tmp_path: Path) -> None:
    terraform_dir = tmp_path / "terraform"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "aws.log"
    _write_tfvars(
        terraform_dir,
        {
            "agentcore_runtime_enabled": True,
            "agentcore_runtime_container_uri": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/stockbrief-agent:test",
        },
    )
    _write_aws_stub(
        bin_dir,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"printf '%s\\n' \"$*\" >> {log_path}",
                "exit 0",
            ]
        ),
    )

    result = _run_preflight(
        terraform_dir,
        {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0
    assert "AgentCore Runtime preflight passed" in result.stdout
    calls = log_path.read_text(encoding="utf-8")
    assert "ecr describe-images" in calls
    assert "--repository-name stockbrief-agent" in calls
    assert "imageTag=test" in calls


def test_agentcore_preflight_fails_with_actionable_message(tmp_path: Path) -> None:
    terraform_dir = tmp_path / "terraform"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_tfvars(
        terraform_dir,
        {
            "agentcore_runtime_enabled": True,
            "agentcore_runtime_container_uri": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/stockbrief-agent:test",
        },
    )
    _write_aws_stub(
        bin_dir,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "echo 'AccessDenied: simulated AgentCore type denial' >&2",
                "exit 254",
            ]
        ),
    )

    result = _run_preflight(
        terraform_dir,
        {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 1
    assert "AgentCore Runtime preflight failed for stockbrief-agent" in result.stderr
    assert "Push the AgentCore image first" in result.stderr
    assert "AccessDenied: simulated AgentCore type denial" in result.stderr
