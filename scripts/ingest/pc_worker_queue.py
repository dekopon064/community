"""Read-only finite membership confirmation before the first AI claim.

The existing offset RPC has no transaction snapshot token. Two matching full
reads detect observed paging changes; they are not an MVCC snapshot. No queue
read happens after membership is frozen, and every claim still checks the server.
"""
from datetime import datetime
import json
import re
from uuid import UUID
from ingest.seoul_workflow import QUEUE_PAGE_SIZE,ready_queue_page

MAX_SNAPSHOT_PAGES=200  # 5,000 queue rows; never silently truncate or loop forever.
FIELDS=('jobId','sourceItemId','revision','sourceName','status','currentRevision','leaseState','retryCount','nextRetryAt')


class QueueSnapshotError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def frozen_queue_targets(adapter,*,sources,progress=lambda counts:None):
    reads=0
    def read():
        nonlocal reads
        rows=[];jobs=set();targets=[];seen=set()
        counts=dict(scanned=0,other_source=0,state_skipped=0,eligible=0,selected=0,
            completed=0,failed=0,unavailable_skipped=0,state_unknown=0,unprocessed=0)
        for page in range(MAX_SNAPSHOT_PAGES):
            response=adapter.invoke('admin_review_ai_queue',{'p_offset':page*QUEUE_PAGE_SIZE,'p_limit':QUEUE_PAGE_SIZE,'p_watch':[]})
            reads+=1
            try:
                eligible,page_counts=ready_queue_page(response,sources)
                if response['hasMore'] and not response['items']:raise ValueError()
                for item in response['items']:
                    row={key:item[key] for key in FIELDS}
                    job=str(UUID(row['jobId']));UUID(row['sourceItemId'])
                    if (job in jobs or not re.fullmatch('[a-f0-9]{64}',row['revision'])
                        or not isinstance(row['sourceName'],str) or not re.fullmatch('[a-z_]{1,40}',row['sourceName'])
                        or row['status'] not in {'queued','claimed','failed','completed','cancelled'}
                        or type(row['currentRevision']) is not bool or row['leaseState'] not in {'none','active','expired','unknown'}
                        or type(row['retryCount']) is not int or row['retryCount']<0):raise ValueError()
                    if row['nextRetryAt'] is not None:
                        if not isinstance(row['nextRetryAt'],str) or len(row['nextRetryAt'])>64:raise ValueError()
                        if datetime.fromisoformat(row['nextRetryAt'].replace('Z','+00:00')).tzinfo is None:raise ValueError()
                    jobs.add(job);rows.append(row)
                for name,value in page_counts.items():counts[name]+=value
                for item in eligible:
                    key=(item['sourceName'],str(UUID(item['sourceItemId'])),item['revision'])
                    if key not in seen:
                        seen.add(key);targets.append({key:item[key] for key in FIELDS})
            except (ValueError,TypeError,KeyError,AttributeError):
                raise QueueSnapshotError('queue_snapshot_invalid') from None
            progress({'snapshot_read_pages':reads})
            if not response['hasMore']:
                counts.update(eligible=len(targets),selected=len(targets),snapshot_read_pages=reads)
                return json.dumps(rows,sort_keys=True,separators=(',',':')),targets,counts
        raise QueueSnapshotError('queue_snapshot_limit')
    fingerprint,targets,counts=read()
    current,_,_=read()
    if fingerprint!=current:raise QueueSnapshotError('queue_snapshot_changed')
    counts['snapshot_read_pages']=reads
    return targets,counts
