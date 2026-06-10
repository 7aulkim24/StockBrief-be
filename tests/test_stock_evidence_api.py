from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.orm import EvidenceChunk, FinancialStatement, PriceMetric


PROHIBITED_KOREAN_TERMS = [
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


def test_stock_search_returns_seeded_stocks(seeded_api_client: TestClient) -> None:
    response = seeded_api_client.get("/v1/stocks/search", params={"q": "삼성"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "삼성"
    assert payload["count"] >= 2
    assert {"ticker", "name", "market", "sector", "industry"}.issubset(
        payload["items"][0]
    )


def test_stock_detail_returns_identifiers(seeded_api_client: TestClient) -> None:
    response = seeded_api_client.get("/v1/stocks/005930")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "005930"
    assert payload["name"] == "삼성전자"
    assert {
        (identifier["provider"], identifier["identifier_type"])
        for identifier in payload["identifiers"]
    } == {("OpenDART", "corp_code"), ("OpenDART", "stock_code")}


def test_stock_evidence_returns_all_seeded_evidence_types(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.get("/v1/stocks/005930/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "005930"
    assert payload["message"] is None
    evidence_types = {item["type"] for item in payload["evidence"]}
    assert {"financial", "news", "disclosure", "price"}.issubset(evidence_types)

    for item in payload["evidence"]:
        assert {
            "id",
            "type",
            "title",
            "summary",
            "source_name",
            "source_url",
            "source_identifier",
            "published_at",
            "as_of_date",
            "data_status",
        }.issubset(item)


def test_stock_evidence_type_filter_and_limit(seeded_api_client: TestClient) -> None:
    response = seeded_api_client.get(
        "/v1/stocks/005930/evidence",
        params={"types": "news,price", "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["evidence"]) == 2
    assert {item["type"] for item in payload["evidence"]}.issubset({"news", "price"})


def test_price_evidence_has_source_identifier_when_url_is_missing(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.get(
        "/v1/stocks/005930/evidence",
        params={"types": "price"},
    )

    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert evidence
    assert evidence[0]["source_url"] is None
    assert evidence[0]["source_name"] == "KRX_FALLBACK_MOCK"
    assert evidence[0]["source_identifier"]
    assert evidence[0]["data_status"] == "fallback"


def test_stock_evidence_empty_result_has_clear_message(
    seeded_api_client: TestClient,
    seeded_session: Session,
) -> None:
    seeded_session.execute(
        delete(FinancialStatement).where(FinancialStatement.ticker == "005930")
    )
    seeded_session.execute(delete(PriceMetric).where(PriceMetric.ticker == "005930"))
    seeded_session.execute(delete(EvidenceChunk).where(EvidenceChunk.ticker == "005930"))
    seeded_session.commit()

    response = seeded_api_client.get("/v1/stocks/005930/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"] == []
    assert payload["message"] == "요청한 조건에서 확인 가능한 근거 데이터가 충분하지 않습니다."


def test_recommendation_reason_evidence_ids_link_to_evidence_api(
    seeded_api_client: TestClient,
) -> None:
    candidate = seeded_api_client.get("/v1/recommendations/candidates/005930").json()
    evidence = seeded_api_client.get("/v1/stocks/005930/evidence").json()

    reason_evidence_ids = {
        evidence_id
        for reason in candidate["recommendation_reasons"]
        for evidence_id in reason["evidence_ids"]
    }
    evidence_api_ids = {item["id"] for item in evidence["evidence"]}
    assert reason_evidence_ids
    assert reason_evidence_ids.issubset(evidence_api_ids)


def test_stock_evidence_openapi_documents_response_model(
    seeded_api_client: TestClient,
) -> None:
    response = seeded_api_client.get("/v1/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert (
        "StockSearchResponse"
        in paths["/v1/stocks/search"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
    )
    assert (
        "StockDetailResponse"
        in paths["/v1/stocks/{ticker}"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
    )
    assert (
        "StockEvidenceResponse"
        in paths["/v1/stocks/{ticker}/evidence"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]
    )


def test_stock_evidence_responses_do_not_emit_prohibited_terms(
    seeded_api_client: TestClient,
) -> None:
    responses = [
        seeded_api_client.get("/v1/stocks/search", params={"q": "삼성"}).json(),
        seeded_api_client.get("/v1/stocks/005930").json(),
        seeded_api_client.get("/v1/stocks/005930/evidence").json(),
    ]
    text = _flatten_text(responses)

    for term in PROHIBITED_KOREAN_TERMS:
        assert term not in text

