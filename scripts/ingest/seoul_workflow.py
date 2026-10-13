"""Bounded, explicit Seoul operations. No scheduling or implicit clients.

Collection planning is pure. Execution requires the explicit atomic new-only
RPC capability; existing observation/update workflows are not reused directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID
from ingest.connectors.seoul_reservation import normalize_seoul_item, SeoulContractError
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.program_db import program_rpc_item
from ingest.seoul_audience import collection_audience

PAGE_SIZE = 50
MAX_PAGES = 1
STORE_BATCH_SIZE = 40
QUEUE_PAGE_SIZE = 25


@dataclass(frozen=True)
class CollectionPlan:
    batches: tuple
    counters: dict


def plan_collection(rows: list[dict], *, existing_keys: frozenset[str], natural_end: bool) -> CollectionPlan:
    if type(rows) is not list or len(rows) > PAGE_SIZE or type(existing_keys) is not frozenset or type(natural_end) is not bool:
        raise ValueError('seoul_collection_limits_invalid')
    counts = dict(scanned=len(rows), culture_count=0, target=0, other_category=0, existing_skipped=0,
                  audience_excluded=0, audience_excluded_by_reason={}, audience_exclusions=[],
                  failed=0, new_planned=0, new_saved=0, review_waiting=None,
                  ai_waiting=None, unprocessed=0, ai_calls=0,
                  coverage='listing_natural_end' if natural_end else 'bounded_page_only', item_errors=[])
    new, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            counts['failed'] += 1
            counts['item_errors'].append(dict(row_index=index,stage='row_normalization',error_code='seoul_item_invalid'))
            continue
        if row.get('MAXCLASSNM') != '문화체험':
            counts['other_category'] += 1
            continue
        counts['culture_count'] += 1
        audience = collection_audience(row.get('USETGTINFO'))
        if not audience.selected:
            counts['audience_excluded'] += 1
            reasons = counts['audience_excluded_by_reason']
            reasons[audience.reason] = reasons.get(audience.reason, 0) + 1
            counts['audience_exclusions'].append(dict(row_index=index, reason=audience.reason))
            continue
        counts['target'] += 1
        if row.get('SVCID') in existing_keys:
            counts['existing_skipped'] += 1
            continue
        try:
            record = normalize_seoul_item(row)
            if record.external_key in seen:
                raise ValueError('duplicate_in_scan')
            seen.add(record.external_key)
            program_rpc_item(record)  # Validate the existing payload, not a new DB schema.
            new.append(record)
        except (TypeError, ValueError, SeoulContractError) as exc:
            counts['failed'] += 1
            from ingest.seoul_diagnostics import failure_diagnostic
            diagnostic=failure_diagnostic(None,exc,stage='row_normalization')
            counts['item_errors'].append(dict(row_index=index,**diagnostic))
    counts['new_planned'] = counts['unprocessed'] = len(new)
    # A per-batch checkpoint is assigned only after that batch is acknowledged;
    # no global checkpoint can skip an unacknowledged second batch.
    batches = tuple(tuple(new[i:i+STORE_BATCH_SIZE]) for i in range(0, len(new), STORE_BATCH_SIZE))
    return CollectionPlan(batches, counts)


def require_new_only_collection_contract(adapter=None) -> None:
    if adapter is None:
        raise ValueError('seoul_atomic_new_only_observation_contract_required')
    adapter.require_contract()


def process_seoul_collection(store, adapter, connector) -> dict:
    """Explicit bounded scan. RPC outcomes, not preflight reads, count inserts.

    A partial page is reread from the origin on the next explicit run; the
    insert-only server skips acknowledged items. No automatic write retry.
    """
    from ingest.rpc_errors import RpcAmbiguous
    if connector.page_size != PAGE_SIZE or connector.max_pages != MAX_PAGES:
        raise ValueError('seoul_collection_limits_invalid')
    require_new_only_collection_contract(adapter)  # before lease or HTTP
    run = store.start_ingest_run('seoul_reservation', lease_seconds=120)
    if run.skipped:
        return dict(status='skipped', reason=run.skip_reason, scanned=0, ai_calls=0)
    counts = dict(status='failed', scanned=0, culture_count=0, target=0, other_category=0, existing_skipped=0,
                  audience_excluded=0, audience_excluded_by_reason={}, audience_exclusions=[],
                  failed=0, new_planned=0, new_saved=0, review_waiting=0, ai_waiting=0,
                  unprocessed=0, ai_calls=0, coverage='bounded_page_only', state_unknown=False)
    batches_ok = 0
    stage = None
    try:
        page = connector.fetch_batch(None)
        stage = 'planning'
        plan = plan_collection(list(page.items), existing_keys=frozenset(), natural_end=page.natural_end)
        counts.update(plan.counters, review_waiting=0, ai_waiting=0)
        # An entirely filtered page still acknowledges only its bounded scan.
        batches = plan.batches or ((),)
        offset = 0
        for records in batches:
            stage = 'new_only_store'
            result = adapter.observe(run.run_id, list(records), {'kind': 'seoul-new-only-page',
                'page': 1, 'targetOffset': offset + len(records), 'scanned': len(page.items)})
            for row in result:
                if row['outcome'] == 'existing_skipped': counts['existing_skipped'] += 1
                else:
                    counts['new_saved'] += 1
                    counts['review_waiting'] += int(row['reviewWaiting'])
                    counts['ai_waiting'] += int(row['aiWaiting'])
            counts['unprocessed'] -= len(records)
            offset += len(records); batches_ok += 1
        complete = page.natural_end and not page.progress.get('total_changed') and not counts['failed']
        status = 'complete' if complete else 'incomplete'
        reason = 'natural_end' if complete else 'invalid_items' if counts['failed'] else 'listing_changed' if page.progress.get('total_changed') else 'page_limit'
        stage = 'finish_run'
        store.finish_ingest_run(run.run_id, status=status, stop_reason=reason,
            http_request_count=connector.http.request_count, bootstrap_complete=complete, batches_ok=batches_ok)
        counts.update(status=status, reason=reason)
    except RpcAmbiguous as exc:
        from ingest.seoul_diagnostics import failure_diagnostic
        counts.update(status='state_unknown', state_unknown=True, diagnostic=failure_diagnostic(connector, exc, stage=stage))
        # Neither retry nor finish-run write follows an unknown write outcome.
    except Exception as exc:
        from ingest.seoul_diagnostics import failure_diagnostic
        counts.update(status='failed', reason='collection_failed', diagnostic=failure_diagnostic(connector, exc, stage=stage))
        try:
            store.finish_ingest_run(run.run_id, status='failed', stop_reason='collection_failed',
                http_request_count=connector.http.request_count, bootstrap_complete=False, batches_ok=batches_ok)
        except Exception as finish_exc:
            counts.update(status='state_unknown', state_unknown=True,
                          finish_diagnostic=failure_diagnostic(connector, finish_exc, stage='finish_run'))
    return counts


def bounded_queue_targets(adapter: ProgramAIAdapter, *, max_jobs: int, queue_pages: int) -> tuple[list[dict], dict]:
    if type(max_jobs) is not int or not 1 <= max_jobs <= QUEUE_PAGE_SIZE or type(queue_pages) is not int or not 1 <= queue_pages <= 5:
        raise ValueError('seoul_ai_limits_required')
    targets, seen = [], set()
    counts = dict(scanned=0, eligible=0, selected=0, other_source=0, state_skipped=0,
                  completed=0, failed=0, unavailable_skipped=0, state_unknown=0,
                  unprocessed=0, automatic_retries=0, publish=False)
    for page in range(queue_pages):
        response = adapter.invoke('admin_review_ai_queue', {'p_offset':page*QUEUE_PAGE_SIZE,'p_limit':QUEUE_PAGE_SIZE,'p_watch':[]})
        if (not isinstance(response,dict) or type(response.get('items')) is not list
                or len(response['items'])>QUEUE_PAGE_SIZE or type(response.get('hasMore')) is not bool):
            raise ValueError('seoul_queue_response_invalid')
        for item in response['items']:
            counts['scanned'] += 1
            if not isinstance(item,dict):
                raise ValueError('seoul_queue_response_invalid')
            if item.get('sourceName')!='seoul_reservation':
                counts['other_source'] += 1
                continue
            if (item.get('status')!='queued' or item.get('currentRevision') is not True
                    or item.get('leaseState')!='none' or type(item.get('retryCount')) is not int
                    or item['retryCount']!=0 or item.get('nextRetryAt') is not None):
                counts['state_skipped'] += 1
                continue
            UUID(item['sourceItemId'])
            if not re.fullmatch('[a-f0-9]{64}',item['revision']):
                raise ValueError('seoul_queue_response_invalid')
            key=(item['sourceItemId'],item['revision'])
            if key in seen:
                continue
            seen.add(key);counts['eligible']+=1
            if len(targets)<max_jobs:
                targets.append(item)
        if not response['hasMore']:
            break
    counts['selected']=len(targets)
    counts['unprocessed']=counts['eligible']-len(targets)
    return targets,counts


def process_seoul_queue(adapter: ProgramAIAdapter, *, max_jobs: int, queue_pages: int,
                        summarize_ko, translate_ja, worker_id: str, no_retry: bool = False) -> dict:
    if type(no_retry) is not bool:
        raise ValueError('seoul_ai_failure_policy_invalid')
    targets,counts=bounded_queue_targets(adapter,max_jobs=max_jobs,queue_pages=queue_pages)
    for index,item in enumerate(targets):
        # The existing claim authoritatively rechecks facts/filters, revisions,
        # active attempts and duplicate candidates. A queue read is no claim.
        result=process_seoul_program_job(adapter,source_item_id=item['sourceItemId'],revision=item['revision'],
            summarize_ko=summarize_ko,translate_ja=translate_ja,worker_id=worker_id,no_retry=no_retry)
        counts['completed']+=result.completed
        counts['failed']+=result.failed+result.retried
        counts['unavailable_skipped']+=int(result.status=='ai_no_jobs')
        counts['state_unknown']+=result.state_unknown or int(result.status=='ai_state_unknown')
        if result.status=='ai_state_unknown' or result.failed or result.retried:
            counts['unprocessed']+=len(targets)-index-1
            break  # Never call another provider or write after ambiguity.
    return counts
