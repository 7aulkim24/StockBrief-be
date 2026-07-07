"""Source document and evidence chunk upsert primitives."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.orm import EvidenceChunk, SourceDocument
from app.services.ingestion.parsing import _clean_provider_text, _sha256


logger = logging.getLogger("app.services.ingestion")


def upsert_source_document(
    session: Session,
    *,
    ticker: str,
    source_type: str,
    source_name: str,
    source_url: str | None,
    external_id: str | None,
    title: str,
    published_at: datetime | None,
    raw_content: str,
    metadata: dict[str, Any],
) -> SourceDocument:
    content_hash = _sha256(raw_content)
    existing = None
    if external_id:
        existing = session.scalars(
            select(SourceDocument).where(
                SourceDocument.source_name == source_name,
                SourceDocument.external_id == external_id,
            )
        ).first()
    if existing is None:
        existing = session.scalars(
            select(SourceDocument).where(SourceDocument.content_hash == content_hash)
        ).first()

    if existing:
        existing.ticker = ticker
        existing.source_type = source_type
        existing.source_url = source_url
        existing.title = title
        existing.published_at = published_at
        existing.fetched_at = datetime.now(timezone.utc)
        existing.raw_content = raw_content
        existing.metadata_ = metadata
        return existing

    source_document = SourceDocument(
        ticker=ticker,
        source_type=source_type,
        source_name=source_name,
        source_url=source_url,
        external_id=external_id,
        title=title,
        published_at=published_at,
        fetched_at=datetime.now(timezone.utc),
        content_hash=content_hash,
        raw_content=raw_content,
        metadata_=metadata,
    )
    session.add(source_document)
    session.flush()
    return source_document

def upsert_evidence_chunk(
    session: Session,
    *,
    source_document: SourceDocument,
    ticker: str,
    evidence_id: str,
    evidence_type: str,
    chunk_text: str,
    source_url: str | None,
    published_at: datetime | None,
    metadata: dict[str, Any],
) -> EvidenceChunk:
    def apply_values(target: EvidenceChunk) -> EvidenceChunk:
        target.ticker = ticker
        target.source_document_id = source_document.id
        target.evidence_type = evidence_type
        target.chunk_text = cleaned_text
        target.source_url = source_url
        target.published_at = published_at
        target.fetched_at = fetched_at
        target.metadata_ = metadata
        return target

    existing = session.scalars(
        select(EvidenceChunk).where(EvidenceChunk.evidence_id == evidence_id)
    ).first()
    fetched_at = datetime.now(timezone.utc)
    cleaned_text = _clean_provider_text(chunk_text) or source_document.title
    if existing:
        return apply_values(existing)

    chunk = EvidenceChunk(
        evidence_id=evidence_id,
        ticker=ticker,
        source_document_id=source_document.id,
        evidence_type=evidence_type,
        chunk_text=cleaned_text,
        source_url=source_url,
        published_at=published_at,
        fetched_at=fetched_at,
        confidence=Decimal("0.9000"),
        metadata_=metadata,
    )
    try:
        with session.begin_nested():
            session.add(chunk)
            session.flush()
        return chunk
    except IntegrityError:
        logger.warning(
            "evidence_chunk_upsert_conflict_recovered evidence_id=%s ticker=%s source_document_id=%s",
            evidence_id,
            ticker,
            source_document.id,
        )
        if chunk in session:
            session.expunge(chunk)
        with session.no_autoflush:
            existing_after_conflict = session.scalars(
                select(EvidenceChunk).where(EvidenceChunk.evidence_id == evidence_id)
            ).first()
        if existing_after_conflict is None:
            raise
        return apply_values(existing_after_conflict)
