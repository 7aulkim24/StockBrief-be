from datetime import datetime, timezone
from threading import Barrier, Lock, Thread

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.orm import Base, IngestionRun
from app.services.ingestion_idempotency import IngestionIdempotencyService


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_compute_input_hash_is_stable_for_key_order() -> None:
    left = {"provider": "OpenDART", "ticker": "005930", "date": "2026-06-18"}
    right = {"date": "2026-06-18", "ticker": "005930", "provider": "OpenDART"}

    assert IngestionIdempotencyService.compute_input_hash(left) == (
        IngestionIdempotencyService.compute_input_hash(right)
    )


def test_start_run_persists_started_state_and_json_scope(db_session: Session) -> None:
    service = IngestionIdempotencyService(db_session)
    input_hash = service.compute_input_hash({"ticker": "005930"})

    run = service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash=input_hash,
    )

    assert run.status == "started"
    assert run.target_scope == {"ticker": "005930"}
    assert run.result_counts == {}
    assert run.completed_at is None


def test_run_id_is_unique(db_session: Session) -> None:
    input_hash = "hash-1"
    db_session.add(
        IngestionRun(
            run_id="naver-20260618-005930",
            job_type="news",
            provider="NAVER",
            target_scope={"ticker": "005930"},
            status="started",
            input_hash=input_hash,
            started_at=datetime.now(timezone.utc),
            result_counts={},
        )
    )
    db_session.commit()

    db_session.add(
        IngestionRun(
            run_id="naver-20260618-005930",
            job_type="news",
            provider="NAVER",
            target_scope={"ticker": "005930"},
            status="started",
            input_hash="hash-2",
            started_at=datetime.now(timezone.utc),
            result_counts={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_active_input_hash_is_unique_across_different_run_ids(db_session: Session) -> None:
    db_session.add(
        IngestionRun(
            run_id="opendart-20260618-005930-a",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            status="started",
            input_hash="same-hash",
            started_at=datetime.now(timezone.utc),
            result_counts={},
        )
    )
    db_session.commit()

    db_session.add(
        IngestionRun(
            run_id="opendart-20260618-005930-b",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            status="started",
            input_hash="same-hash",
            started_at=datetime.now(timezone.utc),
            result_counts={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_terminal_failed_input_hash_can_be_reused(db_session: Session) -> None:
    db_session.add(
        IngestionRun(
            run_id="opendart-20260618-005930-a",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            status="failed",
            input_hash="same-hash",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            result_counts={},
        )
    )
    db_session.commit()

    service = IngestionIdempotencyService(db_session)
    run = service.start_or_restart_run(
        run_id="opendart-20260618-005930-b",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )

    assert run.run_id == "opendart-20260618-005930-b"
    assert run.status == "started"


def test_duplicate_detection_only_counts_succeeded_runs(db_session: Session) -> None:
    service = IngestionIdempotencyService(db_session)
    input_hash = service.compute_input_hash({"ticker": "005930"})
    run = service.start_run(
        run_id="krx-20260618-005930",
        job_type="price",
        provider="KRX",
        target_scope={"ticker": "005930"},
        input_hash=input_hash,
    )

    assert service.is_duplicate(run_id=run.run_id, input_hash=input_hash) is False

    service.mark_succeeded(run=run, result_counts={"inserted": 1, "updated": 0})

    assert service.is_duplicate(run_id=run.run_id, input_hash="other") is True
    assert service.is_duplicate(run_id="other", input_hash=input_hash) is True


def test_failed_run_can_be_restarted_with_same_run_id(db_session: Session) -> None:
    service = IngestionIdempotencyService(db_session)
    run = service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="old-hash",
    )
    service.mark_failed(run=run, error_summary={"code": "provider_timeout"})

    restarted = service.start_or_restart_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930", "source_date": "2026-06-18"},
        input_hash="new-hash",
    )

    assert restarted.id == run.id
    assert restarted.status == "started"
    assert restarted.input_hash == "new-hash"
    assert restarted.completed_at is None
    assert restarted.error_summary is None
    assert restarted.result_counts == {}


def test_succeeded_run_replays_instead_of_restarting(db_session: Session) -> None:
    service = IngestionIdempotencyService(db_session)
    run = service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )
    service.mark_succeeded(run=run, result_counts={"inserted": 1})

    replayed = service.start_or_restart_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )

    assert replayed.id == run.id
    assert replayed.status == "succeeded"
    assert replayed.result_counts == {"inserted": 1}


def test_succeeded_run_with_different_input_hash_is_not_restarted(
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)
    run = service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="original-hash",
    )
    service.mark_succeeded(run=run, result_counts={"inserted": 1})

    with pytest.raises(ValueError, match="ingestion_run_already_active"):
        service.start_or_restart_run(
            run_id="opendart-20260618-005930",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930", "source_date": "2026-06-18"},
            input_hash="changed-hash",
        )

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.input_hash == "original-hash"
    assert run.result_counts == {"inserted": 1}


def test_succeeded_run_replays_when_input_hash_matches_different_run_id(
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)
    run = service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )
    service.mark_succeeded(run=run, result_counts={"inserted": 1})

    replayed = service.start_or_restart_run(
        run_id="manual-rerun-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )

    assert replayed.id == run.id
    assert replayed.run_id == "opendart-20260618-005930"
    assert replayed.status == "succeeded"
    assert len(db_session.scalars(select(IngestionRun)).all()) == 1


def test_active_run_with_same_input_hash_blocks_different_run_id(
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)
    service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )

    with pytest.raises(ValueError, match="ingestion_run_already_active:opendart-20260618-005930"):
        service.start_or_restart_run(
            run_id="manual-rerun-005930",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            input_hash="same-hash",
        )


def test_active_run_cannot_be_restarted(db_session: Session) -> None:
    service = IngestionIdempotencyService(db_session)
    service.start_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="old-hash",
    )

    with pytest.raises(ValueError, match="ingestion_run_already_active"):
        service.start_or_restart_run(
            run_id="opendart-20260618-005930",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            input_hash="new-hash",
        )


def test_insert_race_recovers_to_existing_succeeded_run(
    monkeypatch,
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)

    def fake_start_run(**kwargs):
        db_session.add(
            IngestionRun(
                run_id=kwargs["run_id"],
                job_type=kwargs["job_type"],
                provider=kwargs["provider"],
                target_scope=kwargs["target_scope"],
                status="succeeded",
                input_hash=kwargs["input_hash"],
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                result_counts={"inserted": 1},
            )
        )
        db_session.commit()
        raise IntegrityError("insert", {}, Exception("unique violation"))

    monkeypatch.setattr(service, "start_run", fake_start_run)

    recovered = service.start_or_restart_run(
        run_id="opendart-20260618-005930",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )

    assert recovered.status == "succeeded"
    assert recovered.result_counts == {"inserted": 1}


def test_insert_race_recovers_to_existing_active_run_guard(
    monkeypatch,
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)

    def fake_start_run(**kwargs):
        db_session.add(
            IngestionRun(
                run_id=kwargs["run_id"],
                job_type=kwargs["job_type"],
                provider=kwargs["provider"],
                target_scope=kwargs["target_scope"],
                status="started",
                input_hash=kwargs["input_hash"],
                started_at=datetime.now(timezone.utc),
                result_counts={},
            )
        )
        db_session.commit()
        raise IntegrityError("insert", {}, Exception("unique violation"))

    monkeypatch.setattr(service, "start_run", fake_start_run)

    with pytest.raises(ValueError, match="ingestion_run_already_active"):
        service.start_or_restart_run(
            run_id="opendart-20260618-005930",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            input_hash="same-hash",
        )


def test_concurrent_same_run_id_and_hash_converges_to_one_active_run(
    monkeypatch,
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'ingestion-race.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    barrier = Barrier(2)
    insert_lock = Lock()
    results: list[str] = []
    errors: list[str] = []

    def worker() -> None:
        with Session(engine) as session:
            service = IngestionIdempotencyService(session)
            original_start_run = service.start_run

            def racing_start_run(**kwargs):
                barrier.wait(timeout=3)
                with insert_lock:
                    existing = session.scalars(
                        select(IngestionRun).where(
                            IngestionRun.run_id == kwargs["run_id"]
                        )
                    ).first()
                    if existing is None:
                        return original_start_run(**kwargs)
                raise IntegrityError("insert", {}, Exception("unique violation"))

            monkeypatch.setattr(service, "start_run", racing_start_run)

            try:
                run = service.start_or_restart_run(
                    run_id="opendart-20260618-005930",
                    job_type="disclosure",
                    provider="OpenDART",
                    target_scope={"ticker": "005930"},
                    input_hash="same-hash",
                )
                results.append(run.status)
            except ValueError as exc:
                errors.append(str(exc))

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert results == ["started"]
    assert errors == ["ingestion_run_already_active:opendart-20260618-005930"]

    with Session(engine) as session:
        runs = session.scalars(select(IngestionRun)).all()
        assert len(runs) == 1
        assert runs[0].run_id == "opendart-20260618-005930"
        assert runs[0].status == "started"
        assert runs[0].input_hash == "same-hash"


def test_input_hash_insert_race_recovers_to_existing_succeeded_run(
    monkeypatch,
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)

    def fake_start_run(**kwargs):
        db_session.add(
            IngestionRun(
                run_id="opendart-20260618-005930-existing",
                job_type=kwargs["job_type"],
                provider=kwargs["provider"],
                target_scope=kwargs["target_scope"],
                status="succeeded",
                input_hash=kwargs["input_hash"],
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                result_counts={"inserted": 1},
            )
        )
        db_session.commit()
        raise IntegrityError("insert", {}, Exception("active input_hash unique violation"))

    monkeypatch.setattr(service, "start_run", fake_start_run)

    recovered = service.start_or_restart_run(
        run_id="opendart-20260618-005930-requested",
        job_type="disclosure",
        provider="OpenDART",
        target_scope={"ticker": "005930"},
        input_hash="same-hash",
    )

    assert recovered.run_id == "opendart-20260618-005930-existing"
    assert recovered.status == "succeeded"


def test_input_hash_insert_race_recovers_to_existing_active_run_guard(
    monkeypatch,
    db_session: Session,
) -> None:
    service = IngestionIdempotencyService(db_session)

    def fake_start_run(**kwargs):
        db_session.add(
            IngestionRun(
                run_id="opendart-20260618-005930-existing",
                job_type=kwargs["job_type"],
                provider=kwargs["provider"],
                target_scope=kwargs["target_scope"],
                status="started",
                input_hash=kwargs["input_hash"],
                started_at=datetime.now(timezone.utc),
                result_counts={},
            )
        )
        db_session.commit()
        raise IntegrityError("insert", {}, Exception("active input_hash unique violation"))

    monkeypatch.setattr(service, "start_run", fake_start_run)

    with pytest.raises(
        ValueError,
        match="ingestion_run_already_active:opendart-20260618-005930-existing",
    ):
        service.start_or_restart_run(
            run_id="opendart-20260618-005930-requested",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            input_hash="same-hash",
        )


def test_status_transitions_record_completion_payloads(db_session: Session) -> None:
    service = IngestionIdempotencyService(db_session)
    run = service.start_run(
        run_id="score-20260618",
        job_type="score",
        provider="StockBrief",
        target_scope={"as_of": "2026-06-18"},
        input_hash="score-hash",
    )

    service.mark_partial_failed(
        run=run,
        result_counts={"inserted": 2, "failed": 1},
        error_summary={"code": "provider_timeout"},
    )

    assert run.status == "partial_failed"
    assert run.completed_at is not None
    assert run.result_counts == {"inserted": 2, "failed": 1}
    assert run.error_summary == {"code": "provider_timeout"}

    service.mark_failed(run=run, error_summary={"code": "replay_failed"})

    assert run.status == "failed"
    assert run.error_summary == {"code": "replay_failed"}


# ---------------------------------------------------------------------------
# Issue #130 — IntegrityError 복구 경로 경고 로그 검증
# ---------------------------------------------------------------------------


def test_integrity_error_recovery_emits_warning_log(
    monkeypatch,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """동일 run_id 경합 복구 시 WARNING 로그에 run_id와 input_hash가 포함된다."""
    import logging

    service = IngestionIdempotencyService(db_session)

    def fake_start_run(**kwargs):
        db_session.add(
            IngestionRun(
                run_id=kwargs["run_id"],
                job_type=kwargs["job_type"],
                provider=kwargs["provider"],
                target_scope=kwargs["target_scope"],
                status="succeeded",
                input_hash=kwargs["input_hash"],
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                result_counts={"inserted": 1},
            )
        )
        db_session.commit()
        raise IntegrityError("insert", {}, Exception("unique violation"))

    monkeypatch.setattr(service, "start_run", fake_start_run)

    with caplog.at_level(logging.WARNING, logger="app.services.ingestion_idempotency"):
        service.start_or_restart_run(
            run_id="opendart-20260618-005930",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            input_hash="conflict-hash",
        )

    assert any("ingestion_run_integrity_conflict_recovered" in r.message for r in caplog.records)
    assert any("opendart-20260618-005930" in r.message for r in caplog.records)
    assert any("conflict-hash" in r.message for r in caplog.records)
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1


def test_input_hash_integrity_error_recovery_emits_warning_log(
    monkeypatch,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """다른 run_id의 input_hash 경합 복구 시에도 WARNING 로그가 발생한다."""
    import logging

    service = IngestionIdempotencyService(db_session)

    def fake_start_run(**kwargs):
        db_session.add(
            IngestionRun(
                run_id="opendart-20260618-005930-existing",
                job_type=kwargs["job_type"],
                provider=kwargs["provider"],
                target_scope=kwargs["target_scope"],
                status="succeeded",
                input_hash=kwargs["input_hash"],
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                result_counts={"inserted": 1},
            )
        )
        db_session.commit()
        raise IntegrityError("insert", {}, Exception("active input_hash unique violation"))

    monkeypatch.setattr(service, "start_run", fake_start_run)

    with caplog.at_level(logging.WARNING, logger="app.services.ingestion_idempotency"):
        service.start_or_restart_run(
            run_id="opendart-20260618-005930-requested",
            job_type="disclosure",
            provider="OpenDART",
            target_scope={"ticker": "005930"},
            input_hash="shared-hash",
        )

    assert any("ingestion_run_integrity_conflict_recovered" in r.message for r in caplog.records)
    assert any("opendart-20260618-005930-requested" in r.message for r in caplog.records)
    assert any("shared-hash" in r.message for r in caplog.records)
