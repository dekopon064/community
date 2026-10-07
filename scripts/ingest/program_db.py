"""Program RPC payload/adapter. No registry, environment loading or API/AI I/O.

The caller supplies a server RPC transport explicitly. Observation batches use
the existing run lease; Seoul is disabled in SQL until a separate rollout.
"""
from __future__ import annotations

from typing import Any, Callable

from ingest.models import ObservationRecord
from ingest.program_scope import extract_program_facts
from ingest.content_filters import SCHEMA, extract_filter_facts


def program_rpc_item(record: ObservationRecord) -> dict[str, Any]:
    payload = record.normalized_payload or {}
    if payload.get("source_id") != "seoul_reservation":
        raise ValueError("program_source_not_supported")
    facts = extract_program_facts(record).to_payload()
    facts.update(periods=payload.get("dates", {}),
                 official_url=payload.get("source_url") or "",
                 description=payload.get("program_text", ""))
    item = record.to_rpc_item()
    # Decisions/job plans are computed by the protected SQL evaluator.
    item.update(disposition="observe_only", jobs=[], relationships=[], program_facts=facts)
    filters = extract_filter_facts("seoul_reservation", payload, facts)
    item["filterContract"] = SCHEMA
    if filters is not None:
        item["filterFacts"] = filters
    return item


class ProgramObservationAdapter:
    def __init__(self, rpc: Callable[[str, dict[str, Any]], Any]):
        self.rpc = rpc

    def observe(self, run_id: str, records: list[ObservationRecord], checkpoint: dict[str, Any] | None):
        if not 1 <= len(records) <= 40:
            raise ValueError("program_batch_size_invalid")
        # Never interpolate or log request credentials/transport exceptions.
        try:
            return self.rpc("observe_seoul_program", {
                "p_run_id": run_id, "p_items": [program_rpc_item(r) for r in records],
                "p_next_checkpoint": checkpoint,
            })
        except Exception:
            raise RuntimeError("program_observation_failed") from None
