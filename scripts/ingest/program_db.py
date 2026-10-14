"""Program RPC payload/adapter. No registry, environment loading or API/AI I/O.

The caller supplies a server RPC transport explicitly. Observation batches use
the existing run lease; Seoul is disabled in SQL until a separate rollout.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from ingest.models import ObservationRecord
from ingest.program_scope import extract_program_facts
from ingest.content_filters import SCHEMA, extract_filter_facts
from ingest.rpc_errors import RpcAmbiguous, RpcError

# Existing new-only RPC limit on octet_length(p_items::text).
NEW_ONLY_BATCH_BYTES = 1_000_000


def new_only_payload_bytes(items) -> int:
    return len(json.dumps(items, ensure_ascii=False, allow_nan=False).encode('utf-8'))


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


class ProgramNewOnlyObservationAdapter:
    """Separate opt-in RPC; the existing refresh observation contract is intact."""
    def __init__(self, rpc: Callable[[str, dict[str, Any]], Any]):
        self.rpc = rpc

    def require_contract(self):
        contract = self.rpc('seoul_collection_contract', {})
        if contract != {'contract': 'seoul-new-only-v1', 'maxBatch': 40, 'category': '문화체험'}:
            raise ValueError('seoul_atomic_new_only_observation_contract_required')

    def observe(self, run_id: str, records: list[ObservationRecord], checkpoint: dict | None):
        if len(records) > 40:
            raise ValueError('program_batch_size_invalid')
        from ingest.seoul_audience import collection_audience
        if any(not collection_audience((record.normalized_payload or {}).get('provider_fields', {}).get('USETGTINFO')).selected for record in records):
            raise ValueError('seoul_collection_audience_not_selected')
        from ingest.connectors.seoul_reservation import COLLECTION_STATUSES
        if any((record.normalized_payload or {}).get('provider_fields', {}).get('SVCSTATNM') not in COLLECTION_STATUSES for record in records):
            raise ValueError('seoul_collection_status_not_selected')
        items = [program_rpc_item(r) for r in records]
        if new_only_payload_bytes(items) > NEW_ONLY_BATCH_BYTES:
            raise ValueError('program_batch_bytes_invalid')
        try:
            result = self.rpc('observe_seoul_program_new_only', {
                'p_run_id': run_id, 'p_items': items,
                'p_next_checkpoint': checkpoint,
            })
        except RpcError: raise
        except Exception: raise RpcAmbiguous() from None
        if type(result) is not list or len(result) != len(records):
            raise RpcAmbiguous()
        from uuid import UUID
        import re
        for index, (record, row) in enumerate(zip(records, result)):
            if (type(row) is not dict or type(row.get('inputIndex')) is not int or row['inputIndex'] != index
                    or row.get('externalKey') != record.external_key
                    or row.get('outcome') not in ('new_saved', 'existing_skipped')
                    or type(row.get('revision')) is not str or not re.fullmatch('[a-f0-9]{64}', row['revision'])):
                raise RpcAmbiguous()
            try: UUID(row['id'])
            except (ValueError, TypeError, KeyError): raise RpcAmbiguous() from None
            if row['outcome'] == 'new_saved' and (row['revision'] != record.revision_hash
                    or type(row.get('reviewWaiting')) is not bool or type(row.get('aiWaiting')) is not bool):
                raise RpcAmbiguous()
        return result
