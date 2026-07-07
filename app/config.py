import math
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Chat provider bounds validated both at app boot (fail fast) and at request
# time (fail closed). test_config_validation pins these against the provider
# module constants so the two layers cannot drift apart.
BEDROCK_MAX_TOKENS_RANGE = (64, 1200)
BEDROCK_TIMEOUT_SECONDS_RANGE = (1.0, 30.0)
AGENTCORE_TIMEOUT_SECONDS_RANGE = (1.0, 30.0)


class Settings(BaseSettings):
    app_env: str = Field(default="local", validation_alias="APP_ENV")
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    service_name: str = Field(default="stockbrief-api", validation_alias="SERVICE_NAME")
    service_version: str = Field(default="0.1.0", validation_alias="SERVICE_VERSION")
    api_base_path: str = Field(default="/v1", validation_alias="API_BASE_PATH")
    database_url: str = Field(
        default="",
        validation_alias="DATABASE_URL",
    )
    database_secret_arn: str = Field(default="", validation_alias="DATABASE_SECRET_ARN")
    database_host: str = Field(default="", validation_alias="DATABASE_HOST")
    database_port: int = Field(default=5432, validation_alias="DATABASE_PORT")
    database_name: str = Field(default="stockbrief", validation_alias="DATABASE_NAME")
    database_sslmode: str = Field(default="require", validation_alias="DATABASE_SSLMODE")
    database_pool_size: int = Field(default=5, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, validation_alias="DATABASE_MAX_OVERFLOW")
    database_pool_recycle_seconds: int = Field(default=1800, validation_alias="DATABASE_POOL_RECYCLE_SECONDS")
    database_pool_timeout_seconds: int = Field(default=30, validation_alias="DATABASE_POOL_TIMEOUT_SECONDS")
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    opendart_api_key: str = Field(default="", validation_alias="OPENDART_API_KEY")
    naver_client_id: str = Field(default="", validation_alias="NAVER_CLIENT_ID")
    naver_client_secret: str = Field(default="", validation_alias="NAVER_CLIENT_SECRET")
    krx_api_key: str = Field(default="", validation_alias="KRX_API_KEY")
    krx_api_key_header: str = Field(default="AUTH_KEY", validation_alias="KRX_API_KEY_HEADER")
    krx_daily_url: str = Field(default="", validation_alias="KRX_DAILY_URL")
    krx_kospi_daily_url: str = Field(
        default="https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
        validation_alias="KRX_KOSPI_DAILY_URL",
    )
    krx_kosdaq_daily_url: str = Field(
        default="https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
        validation_alias="KRX_KOSDAQ_DAILY_URL",
    )
    external_api_secret_arn: str = Field(default="", validation_alias="EXTERNAL_API_SECRET_ARN")
    ingestion_raw_bucket: str = Field(default="", validation_alias="INGESTION_RAW_BUCKET")
    cognito_user_pool_id: str = Field(default="", validation_alias="COGNITO_USER_POOL_ID")
    cognito_app_client_id: str = Field(default="", validation_alias="COGNITO_APP_CLIENT_ID")
    cognito_issuer: str = Field(default="", validation_alias="COGNITO_ISSUER")
    cognito_jwks_url: str = Field(default="", validation_alias="COGNITO_JWKS_URL")
    chat_provider: Literal["mock", "bedrock", "agentcore"] = Field(default="mock", validation_alias="CHAT_PROVIDER")
    bedrock_chat_model_id: str = Field(default="apac.amazon.nova-micro-v1:0", validation_alias="BEDROCK_CHAT_MODEL_ID")
    bedrock_chat_region: str = Field(default="", validation_alias="BEDROCK_CHAT_REGION")
    bedrock_chat_max_tokens: int = Field(default=700, validation_alias="BEDROCK_CHAT_MAX_TOKENS")
    bedrock_chat_temperature: float = Field(default=0.2, validation_alias="BEDROCK_CHAT_TEMPERATURE")
    bedrock_chat_timeout_seconds: float = Field(default=8.0, validation_alias="BEDROCK_CHAT_TIMEOUT_SECONDS")
    agentcore_runtime_url: str = Field(default="", validation_alias="AGENTCORE_RUNTIME_URL")
    agentcore_runtime_arn: str = Field(default="", validation_alias="AGENTCORE_RUNTIME_ARN")
    agentcore_runtime_region: str = Field(default="", validation_alias="AGENTCORE_RUNTIME_REGION")
    agentcore_runtime_qualifier: str = Field(default="DEFAULT", validation_alias="AGENTCORE_RUNTIME_QUALIFIER")
    agentcore_runtime_timeout_seconds: float = Field(default=8.0, validation_alias="AGENTCORE_RUNTIME_TIMEOUT_SECONDS")
    agentcore_runtime_max_turns: int = Field(default=4, validation_alias="AGENTCORE_RUNTIME_MAX_TURNS")
    agentcore_runtime_use_dev_model: bool = Field(default=False, validation_alias="AGENTCORE_RUNTIME_USE_DEV_MODEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


def validate_startup_settings(settings: Settings) -> None:
    """Fail fast at app boot when the chat provider is misconfigured.

    Settings construction itself never raises — request-time handlers rely on
    constructing invalid settings to exercise the fail-closed 503 path. This
    check runs once in create_app so a broken deployment is caught at cold
    start instead of on the first chat request.
    """
    problems: list[str] = []

    if settings.chat_provider == "bedrock":
        # Providers strip these values before checking, so whitespace-only
        # strings are effectively missing — mirror that here.
        if not settings.bedrock_chat_model_id.strip():
            problems.append("chat_provider=bedrock requires BEDROCK_CHAT_MODEL_ID")
        min_tokens, max_tokens = BEDROCK_MAX_TOKENS_RANGE
        if not min_tokens <= settings.bedrock_chat_max_tokens <= max_tokens:
            problems.append(
                f"BEDROCK_CHAT_MAX_TOKENS must be between {min_tokens} and {max_tokens}"
            )
        if not (
            math.isfinite(settings.bedrock_chat_temperature)
            and 0.0 <= settings.bedrock_chat_temperature <= 1.0
        ):
            problems.append("BEDROCK_CHAT_TEMPERATURE must be between 0.0 and 1.0")
        min_timeout, max_timeout = BEDROCK_TIMEOUT_SECONDS_RANGE
        if not (
            math.isfinite(settings.bedrock_chat_timeout_seconds)
            and min_timeout <= settings.bedrock_chat_timeout_seconds <= max_timeout
        ):
            problems.append(
                f"BEDROCK_CHAT_TIMEOUT_SECONDS must be between {min_timeout:g} and {max_timeout:g}"
            )

    if settings.chat_provider == "agentcore":
        if (
            not settings.agentcore_runtime_url.strip()
            and not settings.agentcore_runtime_arn.strip()
        ):
            problems.append(
                "chat_provider=agentcore requires AGENTCORE_RUNTIME_URL or AGENTCORE_RUNTIME_ARN"
            )
        min_timeout, max_timeout = AGENTCORE_TIMEOUT_SECONDS_RANGE
        if not (
            math.isfinite(settings.agentcore_runtime_timeout_seconds)
            and min_timeout
            <= settings.agentcore_runtime_timeout_seconds
            <= max_timeout
        ):
            problems.append(
                f"AGENTCORE_RUNTIME_TIMEOUT_SECONDS must be between {min_timeout:g} and {max_timeout:g}"
            )

    if problems:
        raise ValueError("invalid startup configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
