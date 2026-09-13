"""공통 connector 계약. orchestrator는 fetch_batch만 호출한다."""

from __future__ import annotations

from ingest.models import BatchResult, Checkpoint, ObservationRecord, StartMode


class BatchConnector:
    canonical_source_id: str
    provider: str
    source_kind: str
    connector_type: str
    legacy_curation_source: str
    start_mode: StartMode = "fresh_from_origin"
    page_size: int
    bootstrap_max_pages: int
    bootstrap_max_items: int
    max_pages: int
    http_budget: int
    streak_needed: int = 3
    batch_delay_seconds: float = 1.0

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        raise NotImplementedError

    def to_observation(
        self,
        item: dict,
        *,
        permission_status: str,
        enabled: bool,
    ) -> ObservationRecord:
        raise NotImplementedError
