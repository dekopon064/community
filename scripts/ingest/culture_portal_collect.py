"""Freeze unfinished festivals, then collect in confirmed 20-item runs."""
from datetime import date, datetime
from time import monotonic
from zoneinfo import ZoneInfo
from uuid import UUID

from ingest.connectors.seoul_culture_portal import (
    SOURCE, MAX_LIST_PAGES, PAGE_SIZE, assess, parse_detail, read_html, read_list_entries,
)
from ingest.http_client import HttpStatusError

BATCH_SIZE = 20
LEASE_SECONDS = 900
RUN_SECONDS = 840  # Margin before the existing DB lease expires.
HTTP_LIMIT = MAX_LIST_PAGES * (PAGE_SIZE + 2)  # Two list passes + bounded details.


class PortalStop(RuntimeError):
    pass


def _start(rpc):
    rows = rpc('start_ingest_run', {'p_source_id': SOURCE, 'p_lease_seconds': LEASE_SECONDS})
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        raise PortalStop('portal_start_unknown')
    if rows[0].get('skipped') is True:
        return None, rows[0].get('skip_reason')
    run = rows[0].get('run_id')
    try: UUID(run)
    except (ValueError,TypeError,AttributeError): raise PortalStop('portal_start_unknown') from None
    return run, None


def _snapshot(http, today, check_time):
    entries, seen = [], set()
    for page in range(1, MAX_LIST_PAGES + 1):
        check_time()
        rows = read_list_entries(http,page,today)
        for row in rows:
            if row['url'] in seen: raise PortalStop('portal_list_changed')
            seen.add(row['url']); entries.append(row)
        if len(rows) < PAGE_SIZE: return entries
    raise PortalStop('portal_list_safety_limit')


def _ended(entry, today):
    try:
        end = date.fromisoformat(entry['end'])
        start = date.fromisoformat(entry['start'])
        return start <= end < today
    except (ValueError,TypeError): return False


def collect_culture_portal(http, rpc, *, today=None, clock=monotonic):
    if http.budget != HTTP_LIMIT or http.max_attempts != 1 or http.request_count != 0:
        raise ValueError('portal_request_budget_required')
    today = today or datetime.now(ZoneInfo('Asia/Seoul')).date()
    contract = rpc('culture_portal_collection_contract', {})
    if not isinstance(contract,dict) or contract.get('contract') != 'seoul-culture-portal-v1':
        raise RuntimeError('portal_contract_unavailable')
    run, skipped = _start(rpc)
    if run is None: return dict(status='skipped',requests=0,reason=skipped,source_complete=False)
    run_started, run_requests = clock(), 0
    counts = dict(discovered=0, selected=0, ended_skipped=0, new_saved=0, existing_skipped=0,
                  review_waiting=0, changes_recorded=0, excluded=0, failed=0,
                  processed_items=0, chunks_total=0, chunks_done=0)
    results, chunks, targets = [], [], []
    snapshot_complete = False

    def check_time():
        if clock() - run_started >= RUN_SECONDS: raise PortalStop('portal_run_time_limit')

    def report(status, **extra):
        return dict(status=status,requests=http.request_count,**counts,items=results,chunks=chunks,
                    unprocessed=max(0,len(targets)-counts['processed_items']) if snapshot_complete else None,
                    snapshot_complete=snapshot_complete,source_complete=False,
                    coverage='unfinished_festival_snapshot',as_of=today.isoformat(),**extra)

    def finish(status, processed):
        check_time()
        reply=rpc('finish_ingest_run',dict(p_run_id=run,p_status=status,
            p_stop_reason='portal_snapshot_chunk',p_http_request_count=http.request_count-run_requests,
            p_bootstrap_complete=False,p_batches_ok=processed))
        if not isinstance(reply,list) or len(reply)!=1 or not isinstance(reply[0],dict) or reply[0].get('status')!=status:
            raise PortalStop('portal_finish_unknown')

    try:
        # Freeze before writes. Matching scans detect offset shifts/deletions/additions.
        entries = _snapshot(http,today,check_time)
        if entries != _snapshot(http,today,check_time): raise PortalStop('portal_list_changed')
        snapshot_complete = True
        counts['discovered'] = len(entries)
        targets = [e for e in entries if not _ended(e,today)]
        counts['ended_skipped'] = len(entries)-len(targets)
        counts['selected'] = len(targets)
        counts['chunks_total'] = (len(targets)+BATCH_SIZE-1)//BATCH_SIZE
        if not targets: finish('complete',0)
        for offset in range(0,len(targets),BATCH_SIZE):
            if offset:
                run, skipped = _start(rpc)
                if run is None:
                    return report('incomplete',batch_stopped=True,stop_reason='portal_next_run_unavailable')
                run_started, run_requests = clock(), http.request_count
            failed_before = counts['failed']
            detail_requests = http.request_count
            batch = targets[offset:offset+BATCH_SIZE]
            for entry in batch:
                check_time()
                url = entry['url']
                failure_code = None
                try:
                    event = parse_detail(read_html(http,url),url)
                    review = assess(event)
                except HttpStatusError as error:
                    if error.status not in {404,410}: raise
                    failure_code = 'detail_unavailable'
                except ValueError:
                    failure_code = 'detail_structure_changed'
                if failure_code:
                    reply=rpc('record_culture_portal_fetch_failure',{'p_run_id':run,'p_url':url,'p_code':failure_code})
                    if reply!='recorded': raise PortalStop('portal_failure_record_unknown')
                    counts['failed']+=1;counts['processed_items']+=1
                    results.append(dict(url=url,outcome=failure_code));continue
                check_time()
                reply=rpc('observe_culture_portal_event',{'p_run_id':run,'p_event':event,'p_review':review})
                if not isinstance(reply,dict) or reply.get('revision')!=event['revision_hash'] or reply.get('outcome') not in {
                    'new_review','duplicate_skipped','unchanged','change_review','scope_excluded'}:
                    raise PortalStop('portal_observation_unknown')
                results.append(dict(key=event['external_key'],**reply))
                outcome=reply['outcome']
                counts['processed_items']+=1
                counts['new_saved']+=outcome=='new_review'
                counts['review_waiting']+=reply.get('reviewQueued') is True
                counts['changes_recorded']+=outcome=='change_review'
                counts['existing_skipped']+=outcome in {'duplicate_skipped','unchanged'}
                counts['excluded']+=outcome=='scope_excluded'
            batch_failed=counts['failed']-failed_before
            finish('incomplete' if batch_failed else 'complete',len(batch)-batch_failed)
            counts['chunks_done']+=1
            chunks.append(dict(number=counts['chunks_done'],selected=len(batch),failed=batch_failed,
                               detail_requests=http.request_count-detail_requests,finished=True))
    except Exception as error:
        # Unknown writes/finishes are never retried, reclaimed or auto-reconciled.
        reason='http_'+str(error.status) if isinstance(error,HttpStatusError) else str(error) if isinstance(error,PortalStop) else 'state_unknown'
        return report('state_unknown',state_unknown=1,batch_stopped=True,stop_reason=reason)
    result=report('incomplete' if counts['failed'] else 'complete')
    result['source_complete']=counts['failed']==0
    return result
