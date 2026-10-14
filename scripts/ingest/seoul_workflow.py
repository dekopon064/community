"""Bounded, explicit Seoul operations. No scheduling or implicit clients.

Collection planning is pure. Execution requires the explicit atomic new-only
RPC capability; existing observation/update workflows are not reused directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from ingest.connectors.seoul_reservation import (
    normalize_seoul_item, SeoulContractError, KST, COLLECTION_STATUSES,
    CULTURE_PAGE_SIZE, CULTURE_MAX_PAGES, require_culture_reader, read_culture_collection,
    seoul_item_id, invalid_id_error,
)
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.program_db import program_rpc_item, new_only_payload_bytes, NEW_ONLY_BATCH_BYTES
from ingest.seoul_audience import collection_audience

PAGE_SIZE = CULTURE_PAGE_SIZE
MAX_PAGES = CULTURE_MAX_PAGES
MAX_SCAN_ITEMS = PAGE_SIZE * MAX_PAGES
STORE_BATCH_SIZE = 40
QUEUE_PAGE_SIZE = 25


@dataclass(frozen=True)
class CollectionPlan:
    batches: tuple
    counters: dict


def plan_collection(rows: list[dict], *, existing_keys: frozenset[str], natural_end: bool) -> CollectionPlan:
    if type(rows) is not list or len(rows) > MAX_SCAN_ITEMS or type(existing_keys) is not frozenset or type(natural_end) is not bool:
        raise ValueError('seoul_collection_limits_invalid')
    counts = dict(scanned=len(rows), culture_count=0, target=0, other_category=0, existing_skipped=0,
                  invalid_id_count=0,
                  status_excluded=0, status_excluded_by_reason={}, status_exclusions=[],
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
        try:
            sid = seoul_item_id(row)
        except SeoulContractError:
            counts['invalid_id_count'] += 1
            counts['failed'] += 1
            counts['item_errors'].append(invalid_id_error(index, index // PAGE_SIZE + 1))
            continue
        if row.get('MAXCLASSNM') != '문화체험':
            counts['other_category'] += 1
            continue
        counts['culture_count'] += 1
        status = row.get('SVCSTATNM')
        if not isinstance(status, str) or status not in COLLECTION_STATUSES:
            reason = status if isinstance(status, str) and status in ('접수종료', '예약마감', '예약일시중지') else 'status_unknown'
            counts['status_excluded'] += 1
            reasons = counts['status_excluded_by_reason']
            reasons[reason] = reasons.get(reason, 0) + 1
            counts['status_exclusions'].append(dict(row_index=index, reason=reason))
            continue
        audience = collection_audience(row.get('USETGTINFO'))
        if not audience.selected:
            counts['audience_excluded'] += 1
            reasons = counts['audience_excluded_by_reason']
            reasons[audience.reason] = reasons.get(audience.reason, 0) + 1
            counts['audience_exclusions'].append(dict(row_index=index, reason=audience.reason))
            continue
        counts['target'] += 1
        if sid in existing_keys:
            counts['existing_skipped'] += 1
            continue
        try:
            record = normalize_seoul_item(row)
            if record.external_key in seen:
                raise ValueError('duplicate_in_scan')
            seen.add(record.external_key)
            payload_bytes = new_only_payload_bytes([program_rpc_item(record)])
            if payload_bytes > NEW_ONLY_BATCH_BYTES:
                raise SeoulContractError('seoul_store_item_too_large')
            start = record.normalized_payload['dates']['RCPTBGNDT']
            if start['status'] != 'ok':
                raise SeoulContractError('seoul_reception_start_invalid')
            # A day precision value is used as a calendar ordering key only;
            # its raw/day value remains unchanged in the stored observation.
            key = datetime.fromisoformat(start['value'])
            if key.tzinfo is None:
                key = key.replace(tzinfo=KST)
            new.append((key, record, payload_bytes - 2))  # Exclude the outer [] for packing.
        except (TypeError, ValueError, SeoulContractError) as exc:
            counts['failed'] += 1
            from ingest.seoul_diagnostics import failure_diagnostic
            diagnostic=failure_diagnostic(None,exc,stage='row_normalization')
            counts['item_errors'].append(dict(row_index=index,**diagnostic))
    new.sort(key=lambda entry: entry[1].external_key)
    new.sort(key=lambda entry: entry[0], reverse=True)
    counts['new_planned'] = counts['unprocessed'] = len(new)
    # A per-batch checkpoint is assigned only after that batch is acknowledged;
    # no global checkpoint can skip an unacknowledged second batch.
    batches, batch, batch_bytes = [], [], 2
    for _, record, item_bytes in new:
        extra_bytes = item_bytes + (2 if batch else 0)  # JSON comma + space.
        if batch and (len(batch) == STORE_BATCH_SIZE or batch_bytes + extra_bytes > NEW_ONLY_BATCH_BYTES):
            batches.append(tuple(batch))
            batch, batch_bytes, extra_bytes = [], 2, item_bytes
        batch.append(record)
        batch_bytes += extra_bytes
    if batch:
        batches.append(tuple(batch))
    return CollectionPlan(tuple(batches), counts)


def require_new_only_collection_contract(adapter=None) -> None:
    if adapter is None:
        raise ValueError('seoul_atomic_new_only_observation_contract_required')
    adapter.require_contract()


def process_seoul_collection(store, adapter, connector) -> dict:
    """Explicit bounded scan. RPC outcomes, not preflight reads, count inserts.

    After partial storage, the complete bounded listing is reread from the
    origin on the next explicit run; the insert-only server skips acknowledged
    items. Old checkpoints never determine the next API page. No write retry.
    """
    from ingest.rpc_errors import RpcAmbiguous
    require_culture_reader(connector)
    require_new_only_collection_contract(adapter)  # before lease or HTTP
    run = store.start_ingest_run('seoul_reservation', lease_seconds=120)
    if run.skipped:
        return dict(status='skipped', reason=run.skip_reason, scanned=0, ai_calls=0)
    counts = dict(status='failed', scanned=0, culture_count=0, target=0, other_category=0, existing_skipped=0,
                  invalid_id_count=0, item_errors=[],
                  status_excluded=0, status_excluded_by_reason={}, status_exclusions=[],
                  audience_excluded=0, audience_excluded_by_reason={}, audience_exclusions=[],
                  failed=0, new_planned=0, new_saved=0, review_waiting=0, ai_waiting=0,
                  unprocessed=0, ai_calls=0, coverage='bounded_page_only', state_unknown=False)
    batches_ok = 0
    stage = None
    try:
        page = read_culture_collection(connector)
        counts.update(total_count=page.progress['total_count'], pages=page.progress['page_num'])
        stage = 'planning'
        plan = plan_collection(list(page.items), existing_keys=frozenset(), natural_end=page.natural_end)
        counts.update(plan.counters, review_waiting=0, ai_waiting=0)
        # An entirely filtered page still acknowledges only its bounded scan.
        batches = plan.batches or ((),)
        offset = 0
        for records in batches:
            stage = 'new_only_store'
            result = adapter.observe(run.run_id, list(records), {'kind': 'seoul-new-only-page',
                'page': page.progress['page_num'], 'targetOffset': offset + len(records), 'scanned': len(page.items)})
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
        if stage is None:
            counts['scanned'] = counts['diagnostic'].get('scanned_rows', 0)
            counts['total_count'] = counts['diagnostic'].get('total_count')
            counts['item_errors'] = list(connector.identity_errors)
            counts['invalid_id_count'] = counts['failed'] = len(connector.identity_errors)
        try:
            store.finish_ingest_run(run.run_id, status='failed', stop_reason='collection_failed',
                http_request_count=connector.http.request_count, bootstrap_complete=False, batches_ok=batches_ok)
        except Exception as finish_exc:
            counts.update(status='state_unknown', state_unknown=True,
                          finish_diagnostic=failure_diagnostic(connector, finish_exc, stage='finish_run'))
    counts['request_count'] = connector.http.request_count
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
    counts.update(items=[], batch_stopped=False, stop_reason=None)
    for index,item in enumerate(targets):
        # The existing claim authoritatively rechecks facts/filters, revisions,
        # active attempts and duplicate candidates. A queue read is no claim.
        result=process_seoul_program_job(adapter,source_item_id=item['sourceItemId'],revision=item['revision'],
            summarize_ko=summarize_ko,translate_ja=translate_ja,worker_id=worker_id,no_retry=no_retry)
        counts['completed']+=result.completed
        counts['failed']+=result.failed+result.retried
        counts['unavailable_skipped']+=int(result.status=='ai_no_jobs')
        counts['state_unknown']+=result.state_unknown or int(result.status=='ai_state_unknown')
        counts['items'].append(dict(sourceItemId=item['sourceItemId'], revision=item['revision'],
            status=result.status, completed=result.completed, failed=result.failed,
            stateUnknown=result.state_unknown, errorCode=getattr(result,'error_code',None),
            failureScope=getattr(result,'failure_scope',None),
            failureStage=getattr(result,'failure_stage',None),
            diagnostic=getattr(result,'diagnostic',None)))
        stop = ('state_unknown' if result.status=='ai_state_unknown' or result.state_unknown else
                'retry_registered' if result.retried else
                'common_failure' if result.failed else None)
        if (no_retry and result.failed == 1 and not result.retried and not result.state_unknown
                and result.status == 'processed' and getattr(result,'failure_scope',None)=='item'):
            # Only an acknowledged terminal failure releases the per-item Pro
            # pair budget. Never reset a blocked provider or an uncertain attempt.
            owner = getattr(summarize_ko,'__self__',None)
            try:
                release = getattr(owner,'release_terminated_attempt',None)
                if release is not None:
                    if getattr(translate_ja,'__self__',None) is not owner:
                        raise ValueError('provider_pair_mismatch')
                    release()
                stop = None
            except Exception:
                stop = 'provider_not_reusable'
        if stop:
            counts.update(batch_stopped=True, stop_reason=stop)
            counts['unprocessed']+=len(targets)-index-1
            break  # Never call another provider or write after ambiguity/common failure.
    return counts
