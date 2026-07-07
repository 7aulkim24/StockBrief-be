from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.orm import EvidenceChunk, SourceDocument
from app.services.candidate_service import CandidateService


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _add_source_and_chunk(
    session: Session,
    *,
    ticker: str,
    source_type: str,
    evidence_id: str,
    published_at: datetime | None,
    source_published_at: datetime | None,
    external_id: str,
    mock: bool = False,
) -> None:
    source = SourceDocument(
        ticker=ticker,
        source_type=source_type,
        source_name="OpenDART_MOCK" if mock else "OpenDART",
        source_url=f"https://example.com/{external_id}",
        external_id=external_id,
        title=f"{ticker} {source_type} {external_id}",
        published_at=source_published_at,
        fetched_at=source_published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_hash=external_id,
        raw_content="{}",
        metadata_={"fixture": "candidate_evidence_summary"},
    )
    session.add(source)
    session.flush()
    session.add(
        EvidenceChunk(
            evidence_id=evidence_id,
            ticker=ticker,
            source_document_id=source.id,
            evidence_type=source_type,
            chunk_text=f"{ticker} {source_type} chunk",
            source_url=source.source_url,
            published_at=published_at,
            fetched_at=published_at or source.fetched_at,
            confidence=Decimal("0.9000"),
            metadata_={"fixture": "candidate_evidence_summary"},
        )
    )


def test_candidate_evidence_summaries_counts_news_and_disclosure_per_ticker(
    seeded_session: Session,
) -> None:
    ticker_a = "005930"
    ticker_b = "000660"

    # ticker_a already has 1 provider-fixture news + 1 disclosure from conftest.
    # Add one more news to make counts asymmetric and a later "latest" timestamp.
    _add_source_and_chunk(
        seeded_session,
        ticker=ticker_a,
        source_type="news",
        evidence_id="ev_extra_news_005930",
        published_at=datetime(2026, 6, 10, 9, tzinfo=timezone.utc),
        source_published_at=datetime(2026, 6, 10, 9, tzinfo=timezone.utc),
        external_id="extra-news-005930",
    )
    # ticker_b gets an extra disclosure only.
    _add_source_and_chunk(
        seeded_session,
        ticker=ticker_b,
        source_type="disclosure",
        evidence_id="ev_extra_disclosure_000660",
        published_at=datetime(2026, 6, 11, 9, tzinfo=timezone.utc),
        source_published_at=datetime(2026, 6, 11, 9, tzinfo=timezone.utc),
        external_id="extra-disclosure-000660",
    )
    seeded_session.commit()

    service = CandidateService(seeded_session)
    summaries = service._candidate_evidence_summaries([ticker_a, ticker_b])

    assert summaries[ticker_a].news_count == 2
    assert summaries[ticker_a].disclosure_count == 1
    assert _as_utc(summaries[ticker_a].latest_at) == datetime(2026, 6, 10, 9, tzinfo=timezone.utc)

    assert summaries[ticker_b].news_count == 1
    assert summaries[ticker_b].disclosure_count == 2
    assert _as_utc(summaries[ticker_b].latest_at) == datetime(2026, 6, 11, 9, tzinfo=timezone.utc)


def test_candidate_evidence_summaries_empty_ticker_list_returns_empty_dict(
    seeded_session: Session,
) -> None:
    service = CandidateService(seeded_session)

    assert service._candidate_evidence_summaries([]) == {}


def test_candidate_evidence_summaries_ticker_with_no_evidence_has_zero_counts(
    seeded_session: Session,
) -> None:
    service = CandidateService(seeded_session)

    summaries = service._candidate_evidence_summaries(["005930", "999999"])

    assert summaries["999999"].news_count == 0
    assert summaries["999999"].disclosure_count == 0
    assert summaries["999999"].latest_at is None


def test_candidate_evidence_summaries_excludes_mock_evidence_ids(
    seeded_session: Session,
) -> None:
    ticker = "005930"
    _add_source_and_chunk(
        seeded_session,
        ticker=ticker,
        source_type="news",
        evidence_id="ev_mock_005930_news",
        published_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        source_published_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        external_id="mock-news-005930",
        mock=True,
    )
    seeded_session.commit()

    service = CandidateService(seeded_session)
    summary = service._candidate_evidence_summaries([ticker])[ticker]

    # The mock-prefixed evidence_id must not affect counts or "latest".
    assert _as_utc(summary.latest_at) != datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_candidate_evidence_summaries_uses_bulk_query_not_per_ticker(
    seeded_session: Session,
) -> None:
    tickers = ["005930", "000660"]
    service = CandidateService(seeded_session)

    engine = seeded_session.get_bind()
    statements: list[str] = []

    def count_statement(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        service._candidate_evidence_summaries(tickers)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    select_statements = [
        statement for statement in statements if "evidence_chunks" in statement
    ]
    assert len(select_statements) == 1
