import pytest

from app.config import Settings, validate_startup_settings
from app.main import create_app


def test_mock_provider_boots_without_chat_configuration() -> None:
    app = create_app(lambda: Settings(chat_provider="mock"))

    assert app is not None


def test_settings_construction_never_raises_for_invalid_chat_config() -> None:
    # Request-time fail-closed (503) depends on being able to construct
    # invalid settings; only app boot must fail fast.
    settings = Settings(chat_provider="bedrock", bedrock_chat_model_id="")

    assert settings.chat_provider == "bedrock"


def test_bedrock_provider_requires_model_id_at_boot() -> None:
    settings = Settings(chat_provider="bedrock", bedrock_chat_model_id="")

    with pytest.raises(ValueError, match="BEDROCK_CHAT_MODEL_ID"):
        validate_startup_settings(settings)


def test_bedrock_provider_requires_max_tokens_in_range_at_boot() -> None:
    settings = Settings(chat_provider="bedrock", bedrock_chat_max_tokens=10)

    with pytest.raises(ValueError, match="BEDROCK_CHAT_MAX_TOKENS"):
        validate_startup_settings(settings)


def test_bedrock_provider_requires_temperature_in_range_at_boot() -> None:
    settings = Settings(chat_provider="bedrock", bedrock_chat_temperature=1.5)

    with pytest.raises(ValueError, match="BEDROCK_CHAT_TEMPERATURE"):
        validate_startup_settings(settings)


def test_agentcore_provider_requires_runtime_target_at_boot() -> None:
    settings = Settings(
        chat_provider="agentcore",
        agentcore_runtime_url="",
        agentcore_runtime_arn="",
    )

    with pytest.raises(ValueError, match="AGENTCORE_RUNTIME_URL or AGENTCORE_RUNTIME_ARN"):
        validate_startup_settings(settings)


def test_agentcore_provider_requires_timeout_in_range_at_boot() -> None:
    settings = Settings(
        chat_provider="agentcore",
        agentcore_runtime_arn="arn:aws:bedrock-agentcore:ap-northeast-2:123456789012:runtime/x",
        agentcore_runtime_timeout_seconds=99.0,
    )

    with pytest.raises(ValueError, match="AGENTCORE_RUNTIME_TIMEOUT_SECONDS"):
        validate_startup_settings(settings)


def test_startup_validation_reports_all_problems_at_once() -> None:
    settings = Settings(
        chat_provider="bedrock",
        bedrock_chat_model_id="",
        bedrock_chat_max_tokens=1,
    )

    with pytest.raises(ValueError) as exc_info:
        validate_startup_settings(settings)

    message = str(exc_info.value)
    assert "BEDROCK_CHAT_MODEL_ID" in message
    assert "BEDROCK_CHAT_MAX_TOKENS" in message


def test_create_app_fails_fast_on_invalid_chat_configuration() -> None:
    with pytest.raises(ValueError, match="BEDROCK_CHAT_MODEL_ID"):
        create_app(lambda: Settings(chat_provider="bedrock", bedrock_chat_model_id=""))


def test_startup_bounds_stay_in_sync_with_provider_constants() -> None:
    from app import config
    from app.services.chat import providers, runtime_provider

    assert config.BEDROCK_MAX_TOKENS_RANGE == (
        providers.MIN_BEDROCK_MAX_TOKENS,
        providers.MAX_BEDROCK_MAX_TOKENS,
    )
    assert config.BEDROCK_TIMEOUT_SECONDS_RANGE == (
        providers.MIN_BEDROCK_TIMEOUT_SECONDS,
        providers.MAX_BEDROCK_TIMEOUT_SECONDS,
    )
    assert config.AGENTCORE_TIMEOUT_SECONDS_RANGE == (
        runtime_provider.MIN_AGENTCORE_TIMEOUT_SECONDS,
        runtime_provider.MAX_AGENTCORE_TIMEOUT_SECONDS,
    )


def test_agentcore_whitespace_runtime_target_fails_at_boot() -> None:
    # Providers strip runtime targets before checking, so whitespace-only
    # values are effectively missing and must fail boot validation too.
    settings = Settings(
        chat_provider="agentcore",
        agentcore_runtime_url="   ",
        agentcore_runtime_arn="   ",
    )

    with pytest.raises(ValueError, match="AGENTCORE_RUNTIME_URL or AGENTCORE_RUNTIME_ARN"):
        validate_startup_settings(settings)


def test_bedrock_whitespace_model_id_fails_at_boot() -> None:
    settings = Settings(chat_provider="bedrock", bedrock_chat_model_id="   ")

    with pytest.raises(ValueError, match="BEDROCK_CHAT_MODEL_ID"):
        validate_startup_settings(settings)
