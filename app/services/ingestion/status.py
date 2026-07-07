"""Ingestion run status summaries and stale run reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orm import EvidenceChunk, IngestionRun, SourceDocument
from app.services.ingestion.event_helpers import (
    _event_bool,
    _event_providers,
    _event_tickers,
    _unique_providers,
    _unique_tickers,
)
from app.services.ingestion.parsing import _ensure_aware_datetime, _isoformat
from app.services.ingestion.request import _positive_int


def get_ingestion_status(event: dict[str, object] | None = None) -> dict[str, Any]:
    request = event or {}
    # Lazy lookup keeps app.services.ingestion.get_session_factory patchable.
    from app.services import ingestion as _ingestion_pkg

    with _ingestion_pkg.get_session_factory()() as session:
        return summarize_ingestion_status(
            session,
            tickers=_event_tickers(request),
            providers=_event_providers(request),
            limit=_status_limit(request.get("limit")),
        )

def reconcile_stale_ingestion_runs(event: dict[str, object] | None = None) -> dict[str, Any]:
    request = event or {}
    # Lazy lookup keeps app.services.ingestion.get_session_factory patchable.
    from app.services import ingestion as _ingestion_pkg

    with _ingestion_pkg.get_session_factory()() as session:
        return reconcile_stale_started_runs(
            session,
            max_age_minutes=_stale_run_max_age_minutes(request.get("max_age_minutes")),
            tickers=_event_tickers(request),
            providers=_event_providers(request),
            limit=_reconcile_limit(request.get("limit")),
            dry_run=_event_bool(request.get("dry_run"), default=True),
        )

def summarize_ingestion_status(
    session: Session,
    *,
    tickers: list[str] | None = None,
    providers: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    normalized_tickers = _unique_tickers(tickers or [])
    normalized_providers = _unique_providers(providers or [])
    run_statement = (
        select(IngestionRun)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.run_id.desc())
        .limit(limit)
    )
    if normalized_tickers:
        run_statement = run_statement.where(
            IngestionRun.target_scope["ticker"].as_string().in_(normalized_tickers)
        )
    if normalized_providers:
        run_statement = run_statement.where(IngestionRun.provider.in_(normalized_providers))
    runs = session.scalars(run_statement).all()
    evidence_statement = (
        select(EvidenceChunk, SourceDocument)
        .join(SourceDocument, SourceDocument.id == EvidenceChunk.source_document_id)
        .order_by(EvidenceChunk.fetched_at.desc(), EvidenceChunk.evidence_id.desc())
        .limit(limit)
    )
    if normalized_tickers:
        evidence_statement = evidence_statement.where(EvidenceChunk.ticker.in_(normalized_tickers))
    if normalized_providers:
        evidence_statement = evidence_statement.where(
            SourceDocument.source_name.in_(normalized_providers)
        )
    latest_evidence = session.execute(evidence_statement).all()
    return {
        "ok": True,
        "summary": {
            "run_status_counts": _run_status_counts(runs),
            "recent_run_count": len(runs),
            "latest_evidence_count": len(latest_evidence),
            "ticker_filter": normalized_tickers,
            "provider_filter": normalized_providers,
        },
        "recent_runs": [_run_status_dict(run) for run in runs],
        "latest_evidence": [
            _evidence_status_dict(chunk=chunk, source=source)
            for chunk, source in latest_evidence
        ],
    }

def reconcile_stale_started_runs(
    session: Session,
    *,
    max_age_minutes: int = 60,
    tickers: list[str] | None = None,
    providers: list[str] | None = None,
    limit: int = 50,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = _ensure_aware_datetime(now or datetime.now(timezone.utc))
    cutoff = observed_at - timedelta(minutes=max_age_minutes)
    normalized_tickers = _unique_tickers(tickers or [])
    normalized_providers = _unique_providers(providers or [])
    statement = (
        select(IngestionRun)
        .where(
            IngestionRun.status == "started",
            IngestionRun.started_at <= cutoff,
        )
        .order_by(IngestionRun.started_at.asc(), IngestionRun.run_id.asc())
        .limit(limit)
    )
    if normalized_tickers:
        statement = statement.where(
            IngestionRun.target_scope["ticker"].as_string().in_(normalized_tickers)
        )
    if normalized_providers:
        statement = statement.where(IngestionRun.provider.in_(normalized_providers))
    stale_runs = session.scalars(statement).all()
    if not dry_run:
        for run in stale_runs:
            run.status = "failed"
            run.completed_at = observed_at
            run.error_summary = {
                "code": "stale_started_run_reconciled",
                "max_age_minutes": max_age_minutes,
                "reconciled_at": _isoformat(observed_at),
            }
        session.commit()
        for run in stale_runs:
            session.refresh(run)
    return {
        "ok": True,
        "dry_run": dry_run,
        "max_age_minutes": max_age_minutes,
        "cutoff_started_before": _isoformat(cutoff),
        "ticker_filter": normalized_tickers,
        "provider_filter": normalized_providers,
        "stale_count": len(stale_runs),
        "updated_count": 0 if dry_run else len(stale_runs),
        "stale_runs": [
            _stale_run_dict(run=run, observed_at=observed_at)
            for run in stale_runs
        ],
    }

def _status_limit(value: object) -> int:
    limit = _positive_int(value, default=10)
    return min(limit, 50)

def _reconcile_limit(value: object) -> int:
    limit = _positive_int(value, default=50)
    return min(limit, 100)

def _stale_run_max_age_minutes(value: object) -> int:
    return max(_positive_int(value, default=60), 1)

def _run_status_counts(runs: list[IngestionRun]) -> dict[str, int]:
    counts = {
        "started": 0,
        "succeeded": 0,
        "partial_failed": 0,
        "failed": 0,
    }
    for run in runs:
        counts[run.status] = counts.get(run.status, 0) + 1
    return counts

def _run_status_dict(run: IngestionRun) -> dict[str, Any]:
    target_scope = dict(run.target_scope or {})
    return {
        "run_id": run.run_id,
        "provider": run.provider,
        "job_type": run.job_type,
        "status": run.status,
        "ticker": target_scope.get("ticker"),
        "source_date": target_scope.get("source_date"),
        "started_at": _isoformat(run.started_at),
        "completed_at": _isoformat(run.completed_at),
        "result_counts": dict(run.result_counts or {}),
        "error_summary": run.error_summary,
    }

def _stale_run_dict(
    *,
    run: IngestionRun,
    observed_at: datetime,
) -> dict[str, Any]:
    target_scope = dict(run.target_scope or {})
    started_at = _ensure_aware_datetime(run.started_at)
    age_seconds = int((observed_at - started_at).total_seconds())
    return {
        "run_id": run.run_id,
        "provider": run.provider,
        "job_type": run.job_type,
        "status": run.status,
        "ticker": target_scope.get("ticker"),
        "source_date": target_scope.get("source_date"),
        "started_at": _isoformat(run.started_at),
        "completed_at": _isoformat(run.completed_at),
        "age_seconds": age_seconds,
        "error_summary": run.error_summary,
    }

def _evidence_status_dict(
    *,
    chunk: EvidenceChunk,
    source: SourceDocument,
) -> dict[str, Any]:
    return {
        "evidence_id": chunk.evidence_id,
        "ticker": chunk.ticker,
        "evidence_type": chunk.evidence_type,
        "source_name": source.source_name,
        "source_type": source.source_type,
        "source_identifier": source.external_id,
        "published_at": _isoformat(chunk.published_at or source.published_at),
        "fetched_at": _isoformat(chunk.fetched_at),
    }
