"""Thin explicit dispatch to existing collection and AI functions. Never a shell."""
from contextlib import redirect_stdout
import io
import json
import os
from types import SimpleNamespace
from uuid import uuid4

from ingest.pc_worker_bridge import command
from ingest.pc_worker_sources import SOURCES,collection_sources

COUNT_KEYS = frozenset({'scanned','target','existing_skipped','new_saved','review_waiting','ai_waiting',
    'failed','invalid_id_count','status_excluded','audience_excluded','request_count','requests','selected',
    'completed','unavailable_skipped','state_skipped','state_unknown','unprocessed','other_source','eligible',
    'inserted','updated','unchanged','excluded','created','skipped','total','duplicates','review','ai',
    'discovered','new','known','closed_skipped','processed','pending_remaining','carried_selected','list_pages',
    'processed_items','chunks_total','chunks_done','snapshot_read_pages'})


def outcome(value):
    if not isinstance(value,dict):raise ValueError('invalid_worker_result')
    counts={k:v for k,v in value.items() if k in COUNT_KEYS and type(v) is int and v>=0}
    if isinstance(value.get('summary'),dict):
        counts.update({k:v for k,v in value['summary'].items() if k in COUNT_KEYS and type(v) is int and v>=0})
    unknown=bool(value.get('state_unknown')) or value.get('status')=='state_unknown'
    stopped=bool(value.get('batch_stopped')) or value.get('status') in {'partial','truncated','incomplete'}
    complete=value.get('status') in {'complete','completed','skipped'} or ('completed' in value and not unknown and not stopped and not value.get('failed'))
    partial=bool(value.get('failed')) and bool(value.get('completed'))
    state='unknown' if unknown else 'stopped' if stopped else 'partial' if partial else 'completed' if complete else 'failed'
    reason=value.get('stop_reason')
    code='state_unknown' if unknown else reason if stopped and reason in {'common_failure','retry_registered','provider_not_reusable'} else 'batch_stopped' if stopped else 'completed' if complete else 'worker_failed'
    return dict(state=state,code=code,counts=counts)


class BoundedOutput(io.StringIO):
    def write(self,value):
        if self.tell()+len(value)>1024*1024:raise ValueError('worker_output_bound')
        return super().write(value)


class ExistingWorkers:
    def __init__(self,project,*,collect=None,ai_context=None,progress=None):
        self.project,self.collect,self.ai_context=project,collect,ai_context
        self.progress=progress or (lambda counts:None)

    def __call__(self,value):
        value=command(value)
        try:
            if value['kind']=='collect':
                return self._collect_selected(value['source'])
            else:
                if any(row['ai'] not in {'seoul_program_v1','myseoul_program_v1'} for row in SOURCES.values()):
                    return dict(state='failed',code='contract_unavailable',counts={})
                adapter,provider,close=(self.ai_context or self._ai_context)()
                try:
                    result=self._ai_all(adapter,provider,value['limit'])
                finally:close()
            return result
        except Exception as error:
            code=getattr(error,'code','')
            if code in {'queue_snapshot_changed','queue_snapshot_invalid','queue_snapshot_limit'}:
                return dict(state='stopped',code=code,counts={})
            if code in {'missing_ai_provider','invalid_ai_provider','explicit_chatgpt_plan_required'}:
                return dict(state='failed',code='contract_unavailable',counts={})
            if code in {'chatgpt_plan_reauthentication_required','chatgpt_plan_login_requires_terminal','chatgpt_plan_permission_missing'}:
                return dict(state='auth_required',code='reauth_required',counts={})
            if code in {'plan_secure_store_unsupported','plan_secure_store_unavailable','plan_refresh_result_unknown'}:
                return dict(state='auth_required',code='auth_unavailable',counts={})
            return dict(state='unknown',code='state_unknown',counts={})

    def _collect_selected(self,selected):
        sources=collection_sources(selected)
        if any(SOURCES[source]['collector'] not in {'seoul_culture_v1','myseoul_v1'} for source in sources):
            return dict(state='failed',code='contract_unavailable',counts={})
        rows=[];counts=dict(selected_sources=len(sources),completed_sources=0,unprocessed_sources=len(sources))
        for source in sources:
            try:result=outcome((self.collect or self._collect)(source))
            except Exception:result=dict(state='unknown',code='state_unknown',counts={})
            rows.append(dict(source=source,**result));counts['unprocessed_sources']-=1
            for key,value in result['counts'].items():counts[key]=counts.get(key,0)+value
            if result['state']=='completed':counts['completed_sources']+=1
            if result['state']!='completed':
                return dict(state=result['state'],code=result['code'],counts=counts,sourceResults=rows)
        return dict(state='completed',code='completed',counts=counts,sourceResults=rows)

    def _ai_all(self,adapter,provider,limit):
        from ingest.seoul_workflow import bounded_queue_targets,process_ready_targets,QUEUE_PAGE_SIZE
        from ingest.pc_worker_queue import frozen_queue_targets
        from ingest.program_ai import process_seoul_program_job
        from ingest.myseoul_ai import process_myseoul_job
        if limit=='all':targets,counts=frozen_queue_targets(adapter,sources=tuple(SOURCES),progress=self.progress)
        else:targets,counts=bounded_queue_targets(adapter,max_jobs=limit,queue_pages=1,source=tuple(SOURCES))
        counts.update(items=[],batch_stopped=False,stop_reason=None,processed_items=0,
            chunks_total=(len(targets)+QUEUE_PAGE_SIZE-1)//QUEUE_PAGE_SIZE,chunks_done=0)
        def report(part=None):
            current={key:value for key,value in counts.items() if key in COUNT_KEYS and type(value) is int}
            if part is not None:
                for key in ('completed','failed','unavailable_skipped','state_unknown'):current[key]+=part[key]
                current['processed_items']+=len(part.get('items',[]))
            current['unprocessed']=len(targets)-current['processed_items']
            self.progress(current)
        report()
        def policy(item):
            seoul=SOURCES[item['sourceName']]['ai']=='seoul_program_v1'
            return seoul,provider.summarize_program_ko if seoul else provider.summarize_myseoul_ko,provider.translate_ja
        def process(item):
            seoul,summarize,translate=policy(item)
            run=process_seoul_program_job if seoul else process_myseoul_job
            return run(adapter,source_item_id=item['sourceItemId'],revision=item['revision'],
                summarize_ko=summarize,translate_ja=translate,worker_id='pc-ai-'+uuid4().hex,
                **({'no_retry':True} if seoul else {}))
        # Every chunk consumes only the already fixed membership. Never refill or
        # requery a shrinking offset queue after claims have begun.
        for start in range(0,len(targets),QUEUE_PAGE_SIZE):
            part=dict(completed=0,failed=0,unavailable_skipped=0,state_unknown=0,unprocessed=0)
            try:
                process_ready_targets(targets[start:start+QUEUE_PAGE_SIZE],part,process,policy_for=policy,after_each=report)
            except Exception:
                part.update(batch_stopped=True,stop_reason='state_unknown')
                part['state_unknown']+=1
            for key in ('completed','failed','unavailable_skipped','state_unknown'):counts[key]+=part[key]
            counts['items'].extend(part.get('items',[]));counts['processed_items']=len(counts['items'])
            counts['unprocessed']=len(targets)-counts['processed_items']
            if part.get('batch_stopped'):
                counts.update(batch_stopped=True,stop_reason=part['stop_reason']);break
            counts['chunks_done']+=1;report()
        result=counts
        rows=[]
        for source in SOURCES:
            items=[item for item in result['items'] if item['sourceName']==source]
            if not items:continue
            row=dict(completed=sum(i['completed'] for i in items),failed=sum(i['failed']+i['retried'] for i in items),
                     state_unknown=sum(i['stateUnknown'] for i in items))
            if result['batch_stopped'] and source==result['items'][-1]['sourceName']:
                row.update(batch_stopped=True,stop_reason=result['stop_reason'])
            rows.append(dict(source=source,**outcome(row)))
        return dict(**outcome(result),sourceResults=rows)

    def _collect(self,source):
        collector=SOURCES[source]['collector']
        if collector=='seoul_culture_v1':
            # Reuse the exact bounded 2,000-row/two-HTTP/new-only CLI, without shell/subprocess.
            from run_seoul_program_collection import main
            output=BoundedOutput()
            with redirect_stdout(output):main(['--project-ref',self.project,'--execute'])
            lines=output.getvalue().strip().splitlines()
            return json.loads(lines[-1]) if lines else None
        if collector=='myseoul_v1':
            from run_myseoul_collect import execute_collection
            return execute_collection(SimpleNamespace(project_ref=self.project))
        raise ValueError('unsupported_collector')

    def _ai_context(self):
        # Only an explicit, verified AI click reaches these imports/credentials.
        from ingest.ai_provider import require_ai_provider,require_provider_key,ProviderError,create_provider_adapter,close_provider_adapter
        from ingest.chatgpt_plan_auth import authenticate_worker
        from ingest.chatgpt_plan_sessions import PlanSessionManager
        from ingest.program_ai import ProgramAIAdapter
        from ingest.supabase_store import create_ingest_client
        name=require_ai_provider()
        if name!='chatgpt_plan':raise ProviderError('explicit_chatgpt_plan_required')
        key=require_provider_key(name)
        manager=PlanSessionManager()
        class ReuseOnly:
            def acquire(self):return manager.acquire(allow_login=False)
        session=authenticate_worker(manager=ReuseOnly())
        provider=create_provider_adapter(name,key,plan_session=session)
        try:
            url=os.environ.get('SUPABASE_URL','')
            if url.rstrip('/')!=f'https://{self.project}.supabase.co':raise ValueError('wrong_project')
            client=create_ingest_client(url,os.environ.get('SUPABASE_SERVICE_KEY',''))
            return ProgramAIAdapter.from_supabase(client),provider,lambda:close_provider_adapter(provider)
        except Exception:
            close_provider_adapter(provider);raise
