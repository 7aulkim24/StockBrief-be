from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.main import app
from app.orm import EvidenceChunk, FinancialStatement, PriceMetric, RecommendationScore
from app.services.chat import ChatProviderUnavailable, chat_provider_for


PROHIBITED_KOREAN_OUTPUT_TERMS = [
    "매수",
    "매도",
    "목표가",
    "진입가",
    "손절가",
    "수익 보장",
]


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    if isinstance(value, str):
        return value
    return ""


def test_chat_allowed_answer_uses_candidate_evidence_and_risks(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.post(
        "/v1/chat",
        json={"ticker": "005930", "message": "왜 추천됐나요?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["message"] == "mock Agent 응답을 반환했습니다."
    data = payload["data"]
    assert data["safety"]["policy_action"] == "ALLOW"
    assert "추천 후보 점수" in data["answer"]
    assert "주요 추천 이유" in data["answer"]
    assert "연결된 근거 요약" in data["answer"]
    assert "리스크/확인 필요 사항" in data["answer"]
    assert data["citations"]
    assert {"id", "source_type", "title", "url", "published_at"}.issubset(
        data["citations"][0]
    )
    assert any(citation["published_at"] for citation in data["citations"])


def test_chat_mock_provider_preserves_existing_contract(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.post(
        "/v1/chat",
        json={"ticker": "005930", "message": "왜 추천됐나요?"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "mock Agent 응답을 반환했습니다."


def test_chat_bedrock_provider_fails_closed_until_enabled(
    seeded_api_client: TestClient,
) -> None:
    def override_settings() -> Settings:
        return Settings(chat_provider="bedrock")

    app.dependency_overrides[get_settings] = override_settings
    try:
        response = seeded_api_client.post(
            "/v1/chat",
            json={"ticker": "005930", "message": "왜 추천됐나요?"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "CHAT_PROVIDER_UNAVAILABLE"
    assert "Bedrock chat provider is not enabled" in payload["error"]["message"]


def test_chat_provider_factory_failure_returns_fail_closed_response(
    seeded_api_client: TestClient,
    monkeypatch,
) -> None:
    def unavailable_provider_factory(name: str):
        raise ChatProviderUnavailable(f"Unsupported chat provider: {name}")

    monkeypatch.setattr(
        "app.routes.chat.chat_provider_for",
        unavailable_provider_factory,
    )

    response = seeded_api_client.post(
        "/v1/chat",
        json={"ticker": "005930", "message": "왜 추천됐나요?"},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "CHAT_PROVIDER_UNAVAILABLE"
    assert "Unsupported chat provider" in payload["error"]["message"]


def test_chat_provider_factory_rejects_unknown_provider() -> None:
    try:
        chat_provider_for("unknown")
    except ChatProviderUnavailable as exc:
        assert "Unsupported chat provider" in str(exc)
    else:
        raise AssertionError("unknown chat provider should fail closed")


def test_chat_redirects_trade_decision_request(seeded_api_client: TestClient) -> None:
    response = seeded_api_client.post(
        "/v1/chat",
        json={"ticker": "005930", "message": "이 종목 매수해도 돼?"},
    )

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]
    assert data["safety"]["policy_action"] == "REDIRECT"
    assert "직접 답하지 않습니다" in data["answer"]
    assert data["citations"]


def test_chat_redirects_target_entry_and_stop_requests(
    seeded_api_client: TestClient,
) -> None:
    messages = [
        "목표가 알려줘",
        "진입가와 손절가를 정해줘",
    ]

    for message in messages:
        response = seeded_api_client.post(
            "/v1/chat",
            json={"ticker": "005930", "message": message},
        )

        assert response.status_code == 200
        assert response.json()["data"]["safety"]["policy_action"] == "REDIRECT"


def test_chat_blocks_or_redirects_return_certainty_request(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.post(
        "/v1/chat",
        json={"ticker": "005930", "message": "수익 보장되는지 확실하게 말해줘"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["safety"]["policy_action"] in {"BLOCK", "REDIRECT"}
    assert "답할 수 없습니다" in payload["data"]["answer"]


def test_chat_says_evidence_is_insufficient_when_evidence_is_weak(
    seeded_api_client: TestClient,
    seeded_session: Session,
) -> None:
    score = seeded_session.scalars(
        select(RecommendationScore).where(RecommendationScore.ticker == "005930")
    ).one()
    score.evidence_level = "weak"
    score.evidence_count = 1
    seeded_session.execute(
        delete(FinancialStatement).where(FinancialStatement.ticker == "005930")
    )
    seeded_session.execute(delete(PriceMetric).where(PriceMetric.ticker == "005930"))
    seeded_session.execute(delete(EvidenceChunk).where(EvidenceChunk.ticker == "005930"))
    seeded_session.commit()

    response = seeded_api_client.post(
        "/v1/chat",
        json={"ticker": "005930", "message": "왜 추천됐나요?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["safety"]["policy_action"] == "ALLOW"
    assert "근거가 부족" in payload["data"]["answer"]
    assert payload["data"]["citations"] == []


def test_chat_response_does_not_emit_prohibited_korean_terms(
    seeded_api_client: TestClient,
) -> None:
    responses = [
        seeded_api_client.post(
            "/v1/chat",
            json={"ticker": "005930", "message": "왜 추천됐나요?"},
        ).json(),
        seeded_api_client.post(
            "/v1/chat",
            json={"ticker": "005930", "message": "목표가 알려줘"},
        ).json(),
        seeded_api_client.post(
            "/v1/chat",
            json={"ticker": "005930", "message": "수익 보장 가능해?"},
        ).json(),
    ]
    text = _flatten_text(responses)

    for term in PROHIBITED_KOREAN_OUTPUT_TERMS:
        assert term not in text


def test_chat_openapi_documents_response_model(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.get("/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()["paths"]["/v1/chat"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert "ChatContractResponse" in schema["$ref"]
