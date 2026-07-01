import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts/bootstrap_github_oidc.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _stubbed_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "aws",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                'if [ "${1:-}" = "sts" ] && [ "${2:-}" = "get-caller-identity" ]; then',
                "  printf '123456789012\\n'",
                "  exit 0",
                "fi",
                "",
                'case "${1:-} ${2:-}" in',
                '  "s3api head-bucket"|"dynamodb describe-table"|"iam get-open-id-connect-provider"|"iam get-role")',
                "    exit 1",
                "    ;;",
                "esac",
                "",
                "exit 0",
                "",
            ]
        ),
    )
    _write_executable(
        bin_dir / "gh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "exit 0",
                "",
            ]
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def test_bootstrap_dry_run_can_generate_deploy_profile_variables(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(SCRIPT),
            "--environment",
            "dev-owen",
            "--region",
            "ap-northeast-2",
            "--github-owner",
            "80-hours-a-week",
            "--github-repo",
            "StockBrief-be",
            "--alarm-emails-json",
            "[]",
            "--write-deploy-profile-vars",
            "--vpc-id",
            "vpc-123",
            "--db-subnet-ids",
            "subnet-a,subnet-b",
            "--lambda-subnet-ids",
            "subnet-a,subnet-b",
            "--vpc-endpoint-route-table-ids",
            "rtb-123",
            "--dry-run",
        ],
        cwd=REPOSITORY_ROOT,
        env=_stubbed_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "key            = \"stockbrief/dev-owen/terraform.tfstate\"" in result.stdout
    assert "DRY RUN: gh variable set TF_BACKEND_CONFIG_HCL" in result.stdout
    assert "DRY RUN: gh variable set TFVARS_JSON" in result.stdout
    assert "TF_BACKEND_CONFIG_HCL=<generated>" in result.stdout
    assert "TFVARS_JSON=<generated>" in result.stdout


def test_bootstrap_profile_generation_rejects_partial_network_inputs(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            str(SCRIPT),
            "--environment",
            "dev-owen",
            "--region",
            "ap-northeast-2",
            "--github-owner",
            "80-hours-a-week",
            "--github-repo",
            "StockBrief-be",
            "--alarm-emails-json",
            "[]",
            "--write-deploy-profile-vars",
            "--db-subnet-ids",
            "subnet-a,subnet-b",
            "--dry-run",
        ],
        cwd=REPOSITORY_ROOT,
        env=_stubbed_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "--vpc-id is required" in result.stderr
