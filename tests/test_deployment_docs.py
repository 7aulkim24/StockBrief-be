from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

SECRET_ENV_KEYS = {
    "DATABASE_URL",
    "OPENDART_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "KRX_DATA_PATH",
}


def test_env_example_secret_keys_match_terraform_secret_docs() -> None:
    env_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    terraform_readme = (REPOSITORY_ROOT / "infra/terraform/README.md").read_text(
        encoding="utf-8"
    )

    for key in SECRET_ENV_KEYS:
        assert f"{key}=" in env_example, f".env.example missing secret-like key: {key}"
        assert key in terraform_readme, f"Terraform README secret list missing key: {key}"


def test_lambda_handler_target_is_documented_and_importable() -> None:
    terraform_readme = (REPOSITORY_ROOT / "infra/terraform/README.md").read_text(
        encoding="utf-8"
    )

    assert "app.lambda_handler.handler" in terraform_readme
    from app.lambda_handler import handler

    assert handler is not None


def test_lambda_packaging_script_targets_backend_repository_root() -> None:
    script = (REPOSITORY_ROOT / "scripts/package_api_lambda.sh").read_text(
        encoding="utf-8"
    )

    assert 'API_DIR="${ROOT_DIR}"' in script
    assert 'PYTHON_BIN="${PYTHON_BIN:-python3}"' in script
    assert '"${PYTHON_BIN}" -m pip install' in script
    assert "services/api" not in script


def test_terraform_readme_documents_multi_repository_layout() -> None:
    terraform_readme = (REPOSITORY_ROOT / "infra/terraform/README.md").read_text(
        encoding="utf-8"
    )

    assert "StockBrief-fe" in terraform_readme
    assert "apps/web" not in terraform_readme
    assert "services/api" not in terraform_readme
