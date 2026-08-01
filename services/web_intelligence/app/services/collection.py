"""Collection service orchestrating fetch, parse, dedup, and store."""
import uuid
from datetime import datetime

from app.collectors.fetch_client import FetchClient, FetchResult
from app.domain.enums import CollectionRunStatus, DataQualityStatus
from app.domain.models import ApprovedSource, CollectionRun, RawSnapshot
from app.logging import get_logger
from app.metrics.metrics import CollectionMetrics, MetricsCollector
from app.parsers.base_parser import ParserRegistry
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.intelligence_repository import IntelligenceRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.services.data_quality import DataQualityEvaluator
from app.services.deduplication import DeduplicationService
from app.storage.snapshot_storage import SnapshotStorage

logger = get_logger(__name__)


class CollectionService:
    """Orchestrates the collection pipeline for a single source."""

    def __init__(
        self,
        fetch_client: FetchClient,
        parser_registry: ParserRegistry,
        snapshot_repo: SnapshotRepository,
        intelligence_repo: IntelligenceRepository,
        run_repo: CollectionRunRepository,
        dedup_service: DeduplicationService,
        storage: SnapshotStorage,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self.fetch_client = fetch_client
        self.parser_registry = parser_registry
        self.snapshot_repo = snapshot_repo
        self.intelligence_repo = intelligence_repo
        self.run_repo = run_repo
        self.dedup_service = dedup_service
        self.storage = storage
        self.metrics = metrics or MetricsCollector()
        self.quality_evaluator = DataQualityEvaluator()

    async def collect_source(self, source: ApprovedSource, url: str | None = None) -> CollectionRun:
        """Collect from a single approved source."""
        run_id = str(uuid.uuid4())
        target_url = url or source.base_url

        run = CollectionRun(
            id=run_id,
            source_id=source.id,
            status=CollectionRunStatus.RUNNING,
            pages_requested=1,
        )
        await self.run_repo.save(run)

        collection_metrics = CollectionMetrics()

        logger.info(
            "collection_started",
            run_id=run_id,
            source_id=source.id,
            url=target_url,
        )

        try:
            # 1. Fetch
            from app.domain.enums import SourceType
            fetch_result = await self.fetch_client.fetch(
                target_url,
                user_agent=source.user_agent,
                request_interval_seconds=source.request_interval_seconds,
                maximum_requests_per_hour=source.maximum_requests_per_hour,
                allow_file_urls=(source.source_type == SourceType.LOCAL_HTML_FIXTURE),
            )

            # 2. Store raw snapshot
            storage_path = self.storage.store(fetch_result.content)
            content_hash = self.storage.compute_hash(fetch_result.content)

            snapshot = RawSnapshot(
                id=str(uuid.uuid4()),
                source_id=source.id,
                requested_url=target_url,
                canonical_url=fetch_result.url,
                http_status=fetch_result.status_code,
                content_type=fetch_result.content_type or "unknown",
                content_hash=content_hash,
                raw_content_location=storage_path,
                response_headers=fetch_result.headers,
                fetch_duration_ms=fetch_result.duration_ms,
                collection_run_id=run_id,
                data_quality_status=fetch_result.data_quality_status,
                error_code=None,
                error_message=fetch_result.error,
            )
            await self.snapshot_repo.save(snapshot)

            if fetch_result.error:
                logger.warning(
                    "fetch_error",
                    run_id=run_id,
                    source_id=source.id,
                    error=fetch_result.error,
                    status=fetch_result.status_code,
                )
                collection_metrics.fetch_failure_count += 1
                run = run.model_copy(update={
                    "status": CollectionRunStatus.FAILED,
                    "completed_at": datetime.utcnow(),
                    "pages_failed": 1,
                    "failure_reason": fetch_result.error,
                })
                await self.run_repo.save(run)
                collection_metrics.log_summary(run_id, source.id)
                return run

            collection_metrics.fetch_success_count += 1
            collection_metrics.total_latency_ms += fetch_result.duration_ms

            # 3. Parse
            parser = self.parser_registry.get(source.parser_name)
            if parser is None:
                error_msg = f"Parser '{source.parser_name}' not found in registry"
                logger.error("parser_not_found", run_id=run_id, parser_name=source.parser_name)
                run = run.model_copy(update={
                    "status": CollectionRunStatus.FAILED,
                    "completed_at": datetime.utcnow(),
                    "pages_succeeded": 1,
                    "failure_reason": error_msg,
                })
                await self.run_repo.save(run)
                collection_metrics.log_summary(run_id, source.id)
                return run

            html_content = fetch_result.content.decode("utf-8", errors="replace")
            parse_result = parser.parse(
                html_content, target_url, snapshot.id, source.id
            )

            # Update snapshot with parser info
            snapshot = snapshot.model_copy(update={
                "parser_version": parse_result.parser_version,
                "data_quality_status": parse_result.data_quality_status,
            })
            await self.snapshot_repo.save(snapshot)

            if parse_result.data_quality_status in (
                DataQualityStatus.PARSER_MISMATCH,
                DataQualityStatus.EMPTY_CONTENT,
            ):
                logger.warning(
                    "parser_failure",
                    run_id=run_id,
                    source_id=source.id,
                    status=parse_result.data_quality_status.value,
                    error=parse_result.error_message,
                )
                collection_metrics.parser_failure_count += 1
                run = run.model_copy(update={
                    "status": CollectionRunStatus.PARTIAL,
                    "completed_at": datetime.utcnow(),
                    "pages_succeeded": 1,
                    "failure_reason": parse_result.error_message,
                })
                await self.run_repo.save(run)
                collection_metrics.log_summary(run_id, source.id)
                return run

            # 4. Deduplicate and save records
            records_inserted = 0
            records_updated = 0
            duplicates_ignored = 0

            for record in parse_result.records:
                # Propagate data quality from parse result to each record
                record = record.model_copy(update={
                    "data_quality_status": parse_result.data_quality_status,
                })
                processed_record, is_new, was_updated = await self.dedup_service.process_record(record)
                if is_new:
                    # Record already persisted inside process_record — do not double-save
                    records_inserted += 1
                    collection_metrics.records_created += 1
                elif was_updated:
                    records_updated += 1
                    collection_metrics.records_created += 1  # Content change tracked as update
                else:
                    duplicates_ignored += 1
                    collection_metrics.duplicates_ignored += 1

            run = run.model_copy(update={
                "status": CollectionRunStatus.COMPLETED,
                "completed_at": datetime.utcnow(),
                "pages_succeeded": 1,
                "records_extracted": len(parse_result.records),
                "records_inserted": records_inserted,
                "records_updated": records_updated,
                "duplicates_ignored": duplicates_ignored,
            })
            await self.run_repo.save(run)

            logger.info(
                "collection_completed",
                run_id=run_id,
                source_id=source.id,
                records_extracted=len(parse_result.records),
                records_inserted=records_inserted,
                records_updated=records_updated,
                duplicates_ignored=duplicates_ignored,
            )

        except Exception as e:
            logger.exception("collection_unexpected_error", run_id=run_id, source_id=source.id)
            run = run.model_copy(update={
                "status": CollectionRunStatus.FAILED,
                "completed_at": datetime.utcnow(),
                "failure_reason": str(e),
            })
            await self.run_repo.save(run)

        collection_metrics.log_summary(run_id, source.id)
        return run
