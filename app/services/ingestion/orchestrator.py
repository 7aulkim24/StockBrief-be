"""Provider ingestion batch orchestration and persistence."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.orm import Disclosure, FinancialStatement, NewsItem, PriceMetric, Stock
from app.services.external.clients import (
    KRX_PROVIDER,
    NAVER_PROVIDER,
    OPENDART_PROVIDER,
    KrxClient,
    NaverNewsClient,
    OpenDartClient,
)
from app.services.external.types import ExternalApiResult
from app.services.ingestion.archiver import PayloadArchiver, _archiver_from_settings
from app.services.ingestion.event_helpers import (
    _job_type,
    _provider_payload_version,
    _unique_tickers,
    build_request_hash,
    build_run_id,
)
from app.services.ingestion.krx_technicals import _refresh_krx_technical_metrics
from app.services.ingestion.parsing import (
    _clean_provider_text,
    _combined_opendart_result,
    _compact_source_date,
    _financial_statement_values,
    _iter_dicts,
    _normalize_krx_price_item,
    _opendart_disclosure_window,
    _opendart_financial_years,
    _parse_rfc2822,
    _parse_yyyymmdd,
    _sha256,
    _string_or_none,
)
from app.services.ingestion.persistence import upsert_evidence_chunk
from app.services.ingestion.readiness import hydrate_external_api_settings
from app.services.ingestion.request import (
    SUPPORTED_PROVIDERS,
    ProviderIngestionRequest,
    TickerIngestionResult,
    _positive_int,
    _request_limit_violations,
    _request_limits,
    _result_dict,
)
from app.services.ingestion_idempotency import IngestionIdempotencyService


def _upsert_source_document(session: Session, **kwargs: Any):
    """Resolve through the package namespace at call time.

    Tests monkeypatch ``app.services.ingestion.upsert_source_document``; a
    direct import would bypass that patch, so look the function up lazily.
    """
    from app.services import ingestion as _ingestion_pkg

    return _ingestion_pkg.upsert_source_document(session, **kwargs)


class UnregisteredTickerError(ValueError):
    """Raised when an ingestion run targets a ticker missing from the stock universe."""

class ProviderIngestionService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        archiver: PayloadArchiver | None = None,
    ) -> None:
        self.session = session
        self.settings = hydrate_external_api_settings(settings or get_settings())
        self.idempotency = IngestionIdempotencyService(session)
        self.archiver = archiver or _archiver_from_settings(self.settings)

    def run_provider_batch(self, request: ProviderIngestionRequest) -> dict[str, Any]:
        if request.provider not in SUPPORTED_PROVIDERS:
            return {
                "ok": False,
                "error": "unsupported_provider",
                "supported_providers": list(SUPPORTED_PROVIDERS),
            }
        tickers = _unique_tickers(request.tickers)
        if not tickers:
            return {"ok": False, "error": "tickers_required"}
        limit_violations = _request_limit_violations(request)
        if limit_violations:
            return {
                "ok": False,
                "error": "request_limit_exceeded",
                "violations": limit_violations,
                "limits": _request_limits(),
            }

        results = [self._run_ticker(request=request, ticker=ticker) for ticker in tickers]
        failed = [item for item in results if item.status in {"failed", "partial_failed"}]
        return {
            "ok": not failed,
            "provider": request.provider,
            "source_date": request.source_date,
            "results": [_result_dict(item) for item in results],
        }

    def _run_ticker(self, *, request: ProviderIngestionRequest, ticker: str) -> TickerIngestionResult:
        run_id = build_run_id(
            provider=request.provider,
            source_date=request.source_date,
            ticker=ticker,
        )
        if request.run_id:
            run_id = f"{request.run_id}-{ticker}"
        input_hash = build_request_hash(
            provider=request.provider,
            ticker=ticker,
            source_date=request.source_date,
            request_params={
                "page_count": request.page_count,
                "news_display": request.news_display,
                "payload_version": _provider_payload_version(request.provider),
                "run_id": request.run_id,
            },
        )

        try:
            run = self.idempotency.start_or_restart_run(
                run_id=run_id,
                job_type=_job_type(request.provider),
                provider=request.provider,
                target_scope={
                    "ticker": ticker,
                    "source_date": request.source_date,
                },
                input_hash=input_hash,
            )
        except ValueError as exc:
            return TickerIngestionResult(
                ticker=ticker,
                run_id=run_id,
                status="failed",
                result_counts={},
                error_summary={"code": exc.__class__.__name__, "message": str(exc)},
            )
        except Exception as exc:
            self.session.rollback()
            return TickerIngestionResult(
                ticker=ticker,
                run_id=run_id,
                status="failed",
                result_counts={},
                error_summary={"code": exc.__class__.__name__, "message": str(exc)},
            )

        if run.status == self.idempotency.SUCCEEDED_STATUS:
            return TickerIngestionResult(
                ticker=ticker,
                run_id=run_id,
                status="replayed",
                result_counts={"inserted": 0, "updated": 0, "skipped": 1},
            )

        try:
            external_result = self._fetch_provider_result(request=request, ticker=ticker)
            raw_archive_uri = self.archiver.archive(
                run_id=run_id,
                provider=request.provider,
                ticker=ticker,
                payload=external_result.payload,
            )
            result_counts = self._persist_result(
                ticker=ticker,
                provider=request.provider,
                result=external_result,
                raw_archive_uri=raw_archive_uri,
            )
            if external_result.data_status == "fallback":
                completed = self.idempotency.mark_partial_failed(
                    run=run,
                    result_counts=result_counts,
                    error_summary={
                        "code": "provider_fallback",
                        "missing_data": external_result.missing_data,
                    },
                )
            elif (
                request.provider == OPENDART_PROVIDER
                and external_result.missing_data
            ):
                completed = self.idempotency.mark_partial_failed(
                    run=run,
                    result_counts=result_counts,
                    error_summary={
                        "code": "opendart_partial_provider_fallback",
                        "missing_data": external_result.missing_data,
                    },
                )
            elif (
                request.provider == KRX_PROVIDER
                and result_counts["inserted"] + result_counts["updated"] == 0
            ):
                completed = self.idempotency.mark_partial_failed(
                    run=run,
                    result_counts=result_counts,
                    error_summary={
                        "code": "krx_price_rows_not_persisted",
                        "result_counts": result_counts,
                    },
                )
            else:
                completed = self.idempotency.mark_succeeded(
                    run=run,
                    result_counts=result_counts,
                )
            return TickerIngestionResult(
                ticker=ticker,
                run_id=run_id,
                status=completed.status,
                result_counts=result_counts,
                raw_archive_uri=raw_archive_uri,
                error_summary=completed.error_summary,
            )
        except Exception as exc:
            self.session.rollback()
            failed = self.idempotency.mark_failed_by_run_id(
                run_id=run_id,
                error_summary={"code": exc.__class__.__name__, "message": str(exc)},
            )
            return TickerIngestionResult(
                ticker=ticker,
                run_id=run_id,
                status=failed.status,
                result_counts={},
                error_summary=failed.error_summary,
            )

    def _fetch_provider_result(
        self,
        *,
        request: ProviderIngestionRequest,
        ticker: str,
    ) -> ExternalApiResult:
        stock = self.session.get(Stock, ticker)
        if stock is None:
            # Fail before any provider call: guessing market/company_name for
            # an unknown ticker produced silent skips that were untraceable.
            raise UnregisteredTickerError(
                f"ticker {ticker} is not registered in the stock universe"
            )
        if request.provider == OPENDART_PROVIDER:
            client = OpenDartClient(settings=self.settings, session=self.session)
            disclosure_window = _opendart_disclosure_window(request.source_date)
            disclosures = client.list_disclosures(
                ticker=ticker,
                page_count=request.page_count,
                bgn_de=disclosure_window["bgn_de"],
                end_de=disclosure_window["end_de"],
            )
            financials = client.list_financial_statements(
                ticker=ticker,
                business_years=_opendart_financial_years(request.source_date),
            )
            return _combined_opendart_result(disclosures, financials)
        if request.provider == KRX_PROVIDER:
            return KrxClient(settings=self.settings, session=self.session).daily_trading(
                ticker=ticker,
                base_date=_compact_source_date(request.source_date),
                market=stock.market,
            )
        return NaverNewsClient(settings=self.settings, session=self.session).search_news(
            ticker=ticker,
            company_name=stock.company_name,
            display=request.news_display,
        )

    def _persist_result(
        self,
        *,
        ticker: str,
        provider: str,
        result: ExternalApiResult,
        raw_archive_uri: str | None,
    ) -> dict[str, int]:
        if result.data_status == "fallback":
            return {"inserted": 0, "updated": 0, "skipped": 1}
        if provider == OPENDART_PROVIDER:
            disclosure_counts = self._persist_disclosures(
                ticker=ticker,
                result=result,
                raw_archive_uri=raw_archive_uri,
            )
            financial_counts = self._persist_financial_statements(
                ticker=ticker,
                result=result,
                raw_archive_uri=raw_archive_uri,
            )
            return {
                key: disclosure_counts[key] + financial_counts[key]
                for key in disclosure_counts
            }
        if provider == KRX_PROVIDER:
            return self._persist_krx_prices(
                ticker=ticker,
                result=result,
                raw_archive_uri=raw_archive_uri,
            )
        return self._persist_news(
            ticker=ticker,
            result=result,
            raw_archive_uri=raw_archive_uri,
        )

    def _persist_disclosures(
        self,
        *,
        ticker: str,
        result: ExternalApiResult,
        raw_archive_uri: str | None,
    ) -> dict[str, int]:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for item in _iter_dicts(result.payload.get("list")):
            receipt_no = str(item.get("rcept_no") or "").strip()
            if not receipt_no:
                counts["skipped"] += 1
                continue
            title = str(item.get("report_nm") or receipt_no).strip()
            source_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"
            source_document = _upsert_source_document(
                self.session,
                ticker=ticker,
                source_type="disclosure",
                source_name=OPENDART_PROVIDER,
                source_url=source_url,
                external_id=receipt_no,
                title=title,
                published_at=_parse_yyyymmdd(item.get("rcept_dt")),
                raw_content=json.dumps(item, ensure_ascii=False, sort_keys=True),
                metadata={
                    "provider": OPENDART_PROVIDER,
                    "raw_archive_uri": raw_archive_uri,
                },
            )
            upsert_evidence_chunk(
                self.session,
                source_document=source_document,
                ticker=ticker,
                evidence_id=f"ev_opendart_{ticker}_{receipt_no}",
                evidence_type="disclosure",
                chunk_text=title,
                source_url=source_url,
                published_at=_parse_yyyymmdd(item.get("rcept_dt")),
                metadata={
                    "provider": OPENDART_PROVIDER,
                    "receipt_no": receipt_no,
                    "raw_archive_uri": raw_archive_uri,
                },
            )
            existing = self.session.scalars(
                select(Disclosure).where(
                    Disclosure.provider == OPENDART_PROVIDER,
                    Disclosure.receipt_no == receipt_no,
                )
            ).first()
            payload = dict(item)
            payload["raw_archive_uri"] = raw_archive_uri
            if existing:
                existing.ticker = ticker
                existing.title = title
                existing.disclosure_type = str(item.get("rm") or item.get("report_nm") or "unknown")
                existing.published_at = _parse_yyyymmdd(item.get("rcept_dt")) or datetime.now(timezone.utc)
                existing.source_url = source_url
                existing.source_document_id = source_document.id
                existing.raw_payload = payload
                counts["updated"] += 1
            else:
                self.session.add(
                    Disclosure(
                        ticker=ticker,
                        provider=OPENDART_PROVIDER,
                        receipt_no=receipt_no,
                        title=title,
                        disclosure_type=str(item.get("rm") or item.get("report_nm") or "unknown"),
                        published_at=_parse_yyyymmdd(item.get("rcept_dt")) or datetime.now(timezone.utc),
                        source_url=source_url,
                        source_document_id=source_document.id,
                        raw_payload=payload,
                    )
                )
                counts["inserted"] += 1
        self.session.flush()
        return counts

    def _persist_financial_statements(
        self,
        *,
        ticker: str,
        result: ExternalApiResult,
        raw_archive_uri: str | None,
    ) -> dict[str, int]:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for item in _iter_dicts(result.payload.get("financial_statements")):
            fiscal_year = _positive_int(item.get("bsns_year"), default=0)
            fs_div = str(item.get("fs_div") or "").strip() or "unknown"
            if fiscal_year <= 0:
                counts["skipped"] += 1
                continue
            grouped.setdefault((fiscal_year, fs_div), []).append(item)

        for (fiscal_year, fs_div), rows in grouped.items():
            values = _financial_statement_values(rows)
            if not values:
                counts["skipped"] += 1
                continue
            stock = self.session.get(Stock, ticker)
            company_name = stock.company_name if stock else ticker
            raw_content = json.dumps(rows, ensure_ascii=False, sort_keys=True)
            source_document = _upsert_source_document(
                self.session,
                ticker=ticker,
                source_type="financial",
                source_name=OPENDART_PROVIDER,
                source_url=None,
                external_id=f"OpenDART:financial:{ticker}:{fiscal_year}:FY:{fs_div}",
                title=f"{company_name} OpenDART {fiscal_year} FY financial statement",
                published_at=datetime(fiscal_year, 12, 31, tzinfo=timezone.utc),
                raw_content=raw_content,
                metadata={
                    "provider": OPENDART_PROVIDER,
                    "fs_div": fs_div,
                    "raw_archive_uri": raw_archive_uri,
                },
            )
            existing = self.session.scalars(
                select(FinancialStatement).where(
                    FinancialStatement.ticker == ticker,
                    FinancialStatement.fiscal_year == fiscal_year,
                    FinancialStatement.fiscal_period == "FY",
                )
            ).first()
            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.period_end_date = date(fiscal_year, 12, 31)
                existing.source_document_id = source_document.id
                counts["updated"] += 1
                continue
            self.session.add(
                FinancialStatement(
                    ticker=ticker,
                    fiscal_year=fiscal_year,
                    fiscal_period="FY",
                    period_end_date=date(fiscal_year, 12, 31),
                    source_document_id=source_document.id,
                    **values,
                )
            )
            counts["inserted"] += 1
        self.session.flush()
        return counts

    def _persist_krx_prices(
        self,
        *,
        ticker: str,
        result: ExternalApiResult,
        raw_archive_uri: str | None,
    ) -> dict[str, int]:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        base_date = str(result.payload.get("base_date") or "").strip()
        touched = False
        for item in _iter_dicts(result.payload.get("OutBlock_1")):
            normalized = _normalize_krx_price_item(item, base_date=base_date)
            if normalized is None or normalized["ticker"] != ticker:
                counts["skipped"] += 1
                continue
            stock = self.session.get(Stock, ticker)
            trade_date = normalized["trade_date"]
            if stock is None or trade_date is None:
                counts["skipped"] += 1
                continue

            raw_content = json.dumps(item, ensure_ascii=False, sort_keys=True)
            _upsert_source_document(
                self.session,
                ticker=ticker,
                source_type="price",
                source_name=KRX_PROVIDER,
                source_url=None,
                external_id=f"KRX:price:{ticker}:{trade_date.isoformat()}",
                title=f"{stock.company_name} KRX daily price {trade_date.isoformat()}",
                published_at=datetime.combine(trade_date, datetime.min.time(), tzinfo=timezone.utc),
                raw_content=raw_content,
                metadata={
                    "provider": KRX_PROVIDER,
                    "raw_archive_uri": raw_archive_uri,
                },
            )
            existing = self.session.scalars(
                select(PriceMetric).where(
                    PriceMetric.ticker == ticker,
                    PriceMetric.trade_date == trade_date,
                )
            ).first()
            if existing:
                existing.close_price = normalized["close_price"]
                existing.volume = normalized["volume"]
                existing.trading_value = normalized["trading_value"]
                existing.market_cap = normalized["market_cap"]
                existing.change_rate = normalized["change_rate"]
                existing.source = KRX_PROVIDER
                counts["updated"] += 1
                touched = True
            else:
                self.session.add(
                    PriceMetric(
                        ticker=ticker,
                        trade_date=trade_date,
                        close_price=normalized["close_price"],
                        volume=normalized["volume"],
                        trading_value=normalized["trading_value"],
                        market_cap=normalized["market_cap"],
                        change_rate=normalized["change_rate"],
                        source=KRX_PROVIDER,
                    )
                )
                counts["inserted"] += 1
                touched = True
        self.session.flush()
        if touched:
            skip_reason = _refresh_krx_technical_metrics(self.session, ticker=ticker)
            if skip_reason is not None:
                counts["technical_metrics_skipped"] = 1
            self.session.flush()
        return counts

    def _persist_news(
        self,
        *,
        ticker: str,
        result: ExternalApiResult,
        raw_archive_uri: str | None,
    ) -> dict[str, int]:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for item in _iter_dicts(result.payload.get("items")):
            source_url = str(item.get("originallink") or item.get("link") or "").strip()
            if not source_url:
                counts["skipped"] += 1
                continue
            title = _clean_provider_text(item.get("title")) or source_url
            published_at = _parse_rfc2822(item.get("pubDate"))
            source_document = _upsert_source_document(
                self.session,
                ticker=ticker,
                source_type="news",
                source_name=NAVER_PROVIDER,
                source_url=source_url,
                external_id=_sha256(source_url),
                title=title,
                published_at=published_at,
                raw_content=json.dumps(item, ensure_ascii=False, sort_keys=True),
                metadata={
                    "provider": NAVER_PROVIDER,
                    "raw_archive_uri": raw_archive_uri,
                },
            )
            upsert_evidence_chunk(
                self.session,
                source_document=source_document,
                ticker=ticker,
                evidence_id=f"ev_naver_news_{ticker}_{_sha256(source_url)}",
                evidence_type="news",
                chunk_text=_clean_provider_text(item.get("description")) or title,
                source_url=source_url,
                published_at=published_at,
                metadata={
                    "provider": NAVER_PROVIDER,
                    "raw_archive_uri": raw_archive_uri,
                },
            )
            existing = self.session.scalars(
                select(NewsItem).where(NewsItem.source_url == source_url)
            ).first()
            payload = dict(item)
            payload["raw_archive_uri"] = raw_archive_uri
            if existing:
                existing.ticker = ticker
                existing.provider = NAVER_PROVIDER
                existing.title = title
                existing.summary = _string_or_none(item.get("description"))
                existing.publisher = _string_or_none(item.get("publisher"))
                existing.published_at = published_at
                existing.source_document_id = source_document.id
                existing.raw_payload = payload
                counts["updated"] += 1
            else:
                self.session.add(
                    NewsItem(
                        ticker=ticker,
                        provider=NAVER_PROVIDER,
                        title=title,
                        summary=_string_or_none(item.get("description")),
                        publisher=_string_or_none(item.get("publisher")),
                        published_at=published_at,
                        source_url=source_url,
                        source_document_id=source_document.id,
                        raw_payload=payload,
                    )
                )
                counts["inserted"] += 1
        self.session.flush()
        return counts

def handle_ingestion_event(event: dict[str, object]) -> dict[str, Any]:
    # Resolve via the package namespace so monkeypatching
    # app.services.ingestion.{get_session_factory,ProviderIngestionService}
    # keeps taking effect after the package split.
    from app.services import ingestion as _ingestion_pkg

    request = ProviderIngestionRequest.from_event(event)
    with _ingestion_pkg.get_session_factory()() as session:
        result = _ingestion_pkg.ProviderIngestionService(session).run_provider_batch(request)
    if event.get("raise_on_failure") is True and result.get("ok") is False:
        raise RuntimeError(f"ingestion_batch_failed:{result.get('provider')}")
    return result
