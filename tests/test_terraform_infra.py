from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_ROOT = REPOSITORY_ROOT / "infra/terraform"


def _read(path: str) -> str:
    return (TERRAFORM_ROOT / path).read_text(encoding="utf-8")


def test_amplify_module_targets_frontend_repository_root() -> None:
    main_tf = _read("modules/amplify/main.tf")

    assert "appRoot: ." in main_tf
    assert "apps/web" not in main_tf


def test_rds_proxy_module_exists_and_is_wired_to_api_lambda() -> None:
    rds_proxy_tf = _read("modules/rds_proxy/main.tf")
    root_main_tf = _read("main.tf")
    api_lambda_tf = _read("modules/api_lambda/main.tf")

    assert "aws_db_proxy" in rds_proxy_tf
    assert "aws_db_proxy_default_target_group" in rds_proxy_tf
    assert "aws_db_proxy_target" in rds_proxy_tf
    assert 'module "rds_proxy"' in root_main_tf
    assert "DATABASE_HOST" in api_lambda_tf
    assert "DATABASE_PORT" in api_lambda_tf
    assert "DATABASE_NAME" in api_lambda_tf


def test_agentcore_runtime_module_uses_cloudformation_resources() -> None:
    agentcore_tf = _read("modules/agentcore_runtime/main.tf")
    root_main_tf = _read("main.tf")

    assert "AWS::BedrockAgentCore::Runtime" in agentcore_tf
    assert "AWS::BedrockAgentCore::RuntimeEndpoint" in agentcore_tf
    assert "agentcore_runtime_container_uri" in root_main_tf


def test_api_gateway_stage_has_access_logs() -> None:
    api_lambda_tf = _read("modules/api_lambda/main.tf")

    assert "access_log_settings" in api_lambda_tf
    assert "format = jsonencode" in api_lambda_tf


def test_api_lambda_role_has_vpc_and_agentcore_invoke_permissions() -> None:
    api_lambda_tf = _read("modules/api_lambda/main.tf")

    assert "AWSLambdaVPCAccessExecutionRole" in api_lambda_tf
    assert "bedrock-agentcore:InvokeAgentRuntime" in api_lambda_tf
