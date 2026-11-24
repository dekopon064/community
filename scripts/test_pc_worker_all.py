"""Frozen all-queue/chunk/progress contracts. Fake Auth/Pro/RPC; real I/O denied."""
import copy
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from ingest.pc_worker_queue import frozen_queue_targets,QueueSnapshotError
from ingest.pc_worker_existing import ExistingWorkers
from ingest.pc_worker_bridge import PcWorkerControl,ControlError
from ingest.program_ai import ProgramAIAdapter
from test_pc_worker import PROJECT,ORIGIN,KEY,ticket


def item(n,source='seoul_reservation',**change):
    return dict(jobId=f'10000000-0000-4000-8000-{n:012d}',sourceItemId=f'20000000-0000-4000-8000-{n:012d}',
        revision='a'*64,sourceName=source,status='queued',currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None,**change)


class Queue:
    def __init__(self,rows):self.rows=rows;self.reads=[];self.claims=[];self.pass_no=0;self.change=None
    def rpc(self,name,args):
        if name!='admin_review_ai_queue':raise AssertionError('only existing read RPC')
        if self.claims:raise AssertionError('queue must never be reread/refilled after processing starts')
        self.assert_args(args)
        if args['p_offset']==0:self.pass_no+=1
        rows=self.change(self.pass_no,self.rows) if self.change else self.rows
        offset=args['p_offset'];self.reads.append(offset)
        return {'checkedAt':f'changed-read-time-{len(self.reads)}','items':copy.deepcopy(rows[offset:offset+25]),'hasMore':len(rows)>offset+25}
    @staticmethod
    def assert_args(args):
        assert set(args)=={'p_offset','p_limit','p_watch'} and args['p_limit']==25 and args['p_watch']==[]


class FrozenQueueTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client','ingest.chatgpt_plan_auth.authenticate_worker'):
            guard=patch(name,side_effect=AssertionError('real connection forbidden'));guard.start();self.addCleanup(guard.stop)

    def snapshot(self,queue):return frozen_queue_targets(ProgramAIAdapter(queue.rpc),sources=('seoul_reservation','myseoul_program'))

    def test_complete_two_pass_membership_and_empty_or_boundary_sizes(self):
        for n in (0,1,25,26,50,51):
            q=Queue([item(i+1) for i in range(n)]);targets,counts=self.snapshot(q)
            pages=max(1,(n+24)//25)
            self.assertEqual(len(targets),n);self.assertEqual(counts['selected'],n)
            self.assertEqual(q.reads,[25*p for p in range(pages)]*2)
            self.assertEqual(counts['snapshot_read_pages'],pages*2)

    def test_changed_membership_order_or_state_stops_before_any_claim(self):
        for change in ('append','revision','source','status','order'):
            q=Queue([item(1),item(2)])
            def mutate(pass_no,rows):
                if pass_no==1:return rows
                rows=copy.deepcopy(rows)
                if change=='append':rows.append(item(3))
                elif change=='order':rows.reverse()
                else:rows[0][{'source':'sourceName'}.get(change,change)]={'revision':'b'*64,'source':'myseoul_program','status':'claimed'}[change]
                return rows
            q.change=mutate
            with self.assertRaisesRegex(QueueSnapshotError,'queue_snapshot_changed'):self.snapshot(q)
            self.assertEqual(q.claims,[])

    def test_duplicate_shifted_pages_and_malformed_metadata_are_not_silently_accepted(self):
        for rows in ([item(1)]*26,[{**item(1),'jobId':'not-a-job'}],[{k:v for k,v in item(1).items() if k!='jobId'}],
                     [{**item(1),'nextRetryAt':'unverified'}],[{**item(1),'currentRevision':1}]):
            with self.assertRaisesRegex(QueueSnapshotError,'queue_snapshot_invalid'):self.snapshot(Queue(rows))

    def test_snapshot_bound_is_a_stop_not_partial_success(self):
        q=Queue([item(n+1) for n in range(51)])
        with patch('ingest.pc_worker_queue.MAX_SNAPSHOT_PAGES',2):
            with self.assertRaisesRegex(QueueSnapshotError,'queue_snapshot_limit'):self.snapshot(q)
        self.assertEqual(q.reads,[0,25]);self.assertEqual(q.claims,[])

    def test_existing_eligibility_and_target_deduplication_are_preserved(self):
        rows=[item(n+1) for n in range(8)]
        rows[1]['status']='completed';rows[2]['currentRevision']=False;rows[3]['leaseState']='active'
        rows[4]['retryCount']=1;rows[5]['nextRetryAt']='2099-01-01T00:00:00Z';rows[6]['sourceName']='unconnected_source'
        rows[7]['sourceItemId']=rows[0]['sourceItemId']
        targets,counts=self.snapshot(Queue(rows));self.assertEqual([r['jobId'] for r in targets],[rows[0]['jobId']])
        self.assertEqual(counts['state_skipped'],5);self.assertEqual(counts['other_source'],1)

    def run_worker(self,n=51,*,mode=None,mutate_after_start=False,progress=None):
        q=Queue([item(i+1,'myseoul_program' if i%2 else 'seoul_reservation') for i in range(n)])
        before=copy.deepcopy(q.rows);events=[];reports=[];closed=[]
        class Pro:
            def summarize_program_ko(self,*a):events.append('summary')
            summarize_myseoul_ko=summarize_program_ko
            def translate_ja(self,*a):events.append('translation')
            def release_terminated_attempt(self):events.append('release')
        pro=Pro()
        def job(adapter,**args):
            identity=args['source_item_id'];index=next(i for i,r in enumerate(before) if r['sourceItemId']==identity)
            self.assertEqual(args['revision'],before[index]['revision']);self.assertTrue(args['worker_id'].startswith('pc-ai-'))
            self.assertIs(args['no_retry'],True)
            q.claims.append(identity)
            if mutate_after_start and len(q.claims)==1:q.rows.append(item(999))
            row=dict(status='processed',completed=0,failed=0,retried=0,state_unknown=0,failure_scope=None)
            if mode and index==mode[0]:
                if mode[1]=='stale':return SimpleNamespace(**(row|{'status':'ai_no_jobs'}))
                if mode[1]=='unknown':return SimpleNamespace(**(row|{'status':'ai_state_unknown','state_unknown':1}))
                args['summarize_ko']('fake','fake')
                if mode[1]=='item':return SimpleNamespace(**(row|{'failed':1,'failure_scope':'item','termination_confirmed':True}))
                if mode[1]=='common':return SimpleNamespace(**(row|{'failed':1,'failure_scope':'batch'}))
                if mode[1]=='retry':return SimpleNamespace(**(row|{'retried':1}))
            args['summarize_ko']('fake','fake');args['translate_ja']('fake','fake')
            return SimpleNamespace(**(row|{'completed':1}))
        def report(counts):
            reports.append(copy.deepcopy(counts))
            if progress:progress(counts)
        worker=ExistingWorkers(PROJECT,ai_context=lambda:(ProgramAIAdapter(q.rpc),pro,lambda:closed.append(1)),progress=report)
        with patch('ingest.program_ai.process_seoul_program_job',side_effect=job),patch('ingest.myseoul_ai.process_myseoul_job',side_effect=job):
            result=worker(dict(source='all',kind='ai',limit='all'))
        self.assertEqual(closed,[1]);self.assertEqual(q.rows[:len(before)],before)
        return result,q,events,reports

    def test_all_processes_25_25_1_without_refill_and_with_per_item_pair_budget(self):
        result,q,events,reports=self.run_worker(mutate_after_start=True)
        self.assertEqual(result['state'],'completed');self.assertEqual(len(q.claims),51);self.assertNotIn(item(999)['sourceItemId'],q.claims)
        self.assertEqual(events.count('summary'),51);self.assertEqual(events.count('translation'),51)
        self.assertEqual(q.reads,[0,25,50]*2);self.assertEqual(result['counts']['chunks_done'],3)
        self.assertEqual(result['counts']['processed_items'],51);self.assertEqual(result['counts']['unprocessed'],0)
        self.assertEqual({r['chunks_done'] for r in reports if 'chunks_done' in r},{0,1,2,3})
        self.assertEqual(sum(r['counts']['completed'] for r in result['sourceResults']),51)

    def test_acknowledged_seoul_item_failure_releases_pair_and_crosses_chunk_boundary(self):
        result,q,events,reports=self.run_worker(n=26,mode=(24,'item'))
        self.assertEqual(result['state'],'partial');self.assertEqual(len(q.claims),26)
        self.assertEqual(events.count('summary'),26);self.assertEqual(events.count('translation'),25);self.assertEqual(events.count('release'),1)
        self.assertEqual(result['counts']['failed'],1);self.assertEqual(result['counts']['chunks_done'],2)
        self.assertTrue(any(r.get('completed')==24 and r.get('confirmed_failed')==1 for r in reports))
        self.assertEqual(result['counts']['confirmed_failed'],1)

    def test_common_unknown_and_unexpected_retry_stop_future_chunks(self):
        for mode,expected in [((24,'common'),'stopped'),((24,'unknown'),'unknown'),((25,'retry'),'stopped')]:
            result,q,events,_=self.run_worker(mode=mode)
            self.assertEqual(result['state'],expected);self.assertEqual(len(q.claims),mode[0]+1)
            self.assertEqual(result['counts']['unprocessed'],51-len(q.claims));self.assertNotIn('release',events)
            self.assertEqual(result['counts']['confirmed_failed'],0)

    def test_stale_frozen_target_is_skipped_without_claiming_a_new_revision(self):
        result,q,events,_=self.run_worker(n=26,mode=(24,'stale'))
        self.assertEqual(result['state'],'completed');self.assertEqual(result['counts']['unavailable_skipped'],1)
        self.assertEqual(len(q.claims),26);self.assertEqual(events.count('summary'),25)

    def test_progress_record_failure_stops_without_another_item(self):
        def broken(counts):
            if counts.get('processed_items')==25:raise RuntimeError('private failure must not leak')
        result,q,events,_=self.run_worker(progress=broken)
        self.assertEqual(result['state'],'unknown');self.assertEqual(len(q.claims),25);self.assertEqual(events.count('summary'),25)

    def test_snapshot_failure_never_invokes_a_job_or_ai(self):
        q=Queue([item(1)]);q.change=lambda p,r:r if p==1 else [item(2)]
        with patch('ingest.program_ai.process_seoul_program_job',side_effect=AssertionError('AI forbidden')):
            result=ExistingWorkers(PROJECT,ai_context=lambda:(ProgramAIAdapter(q.rpc),object(),lambda:None))(dict(source='all',kind='ai',limit='all'))
        self.assertEqual(result['state'],'stopped');self.assertEqual(result['code'],'queue_snapshot_changed');self.assertEqual(q.claims,[])

    def test_auto_hold_real_worker_with_fake_pro_rpc(self):
        import json
        from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
        from ingest.seoul_content import assemble_seoul_body
        from test_ingest_ai_chatgpt_plan import verified_session, streamed
        from test_ingest_ai_openai import response
        from test_seoul_fact_roles import replay_context, confirmed_case, fake_translation
        from test_chatgpt_plan_probe import FakeClient

        _, template = replay_context(False)
        summary = confirmed_case()['summary']
        ko = assemble_seoul_body(summary['content_ko'], template['facts'])
        ja = {'title_ja':'合成の解説', 'content_ja':fake_translation(ko)}
        pair = streamed([response(json.dumps(v,ensure_ascii=False)) for v in (summary,ja)], model='gpt-6.2-sol').events
        for scenario in ('confirmed', 'translation_duplicate', 'lost_receipt', 'wrong_receipt', 'empty_stream', 'quota', 'wrong_model'):
            with self.subTest(scenario=scenario):
                rows = [item(i, title=f'합성 전시 {i}') for i in range(1,11)]
                queue = Queue(rows)
                claims, saves, holds = [], [], []
                def rpc(name, args):
                    if name == 'admin_review_ai_queue':
                        return queue.rpc(name,args)
                    if name == 'claim_seoul_program_ai_no_retry':
                        src = args['p_source_item_id']
                        row = next(r for r in rows if r['sourceItemId']==src)
                        claims.append(src)
                        ctx = copy.deepcopy(template)
                        ctx.update(sourceItemId=src, revision=row['revision'], jobId=row['jobId'],
                                   workerId=args['p_worker_id'], failurePolicy={'policy':'no_retry','attempt':'f'*64})
                        ctx['filterContext']['workerId'] = ctx['workerId']
                        return [ctx]
                    if name == 'hold_program_ai_response':
                        holds.append(args.copy())
                        if scenario == 'lost_receipt':
                            raise TimeoutError()
                        return dict(outcome='held', jobId=args['p_job_id'], evidence=args['p_evidence'],
                                    revision=args['p_revision'], attempt='wrong' if scenario=='wrong_receipt' else args['p_attempt'])
                    if name == 'fail_seoul_ai_no_retry' and scenario == 'quota':
                        return 'failed'
                    if name.startswith('finish_'):
                        saves.append(args['p_job_id'])
                        return {'outcome':'inserted','candidateId':str(uuid4())}
                    raise AssertionError(name)
                event = [{'type':'response.output_text.delta','delta':'synthetic'}]
                if scenario == 'empty_stream':
                    event = []
                elif scenario == 'quota':
                    event = [{'type':'error','code':'subscription_sharing_usage_limit_exceeded'}]
                elif scenario == 'wrong_model':
                    event = streamed([response(json.dumps(summary))], model='gpt-6.1-sol').events[0]
                fourth = [event]
                translation = scenario == 'translation_duplicate'
                if translation:
                    terminal = next(e for e in pair[1] if e['type']=='response.completed')
                    fourth = [pair[0], [terminal,terminal]]
                first = FakeClient(pair*3 + fourth + pair*6)
                def context():
                    provider = ChatGPTPlanAdapter(session=verified_session('gpt-6.2-sol'),client=first)
                    return ProgramAIAdapter(rpc), provider, provider.close
                worker = ExistingWorkers(PROJECT,ai_context=context)
                control = PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,execute=worker,clock=lambda:1001)
                worker.progress = control.report
                token = control.connect(ticket(control))['token']
                original = dict(source='all',kind='ai',limit='all')
                control.submit(token,ticket(control,'run',cmd=original))
                control.wait()
                run = control.status(token)['run']
                continued = scenario == 'confirmed' or translation
                hold_attempted = translation or scenario in ('confirmed','wrong_receipt','lost_receipt')
                self.assertEqual(len(holds), int(hold_attempted))
                self.assertEqual(len(first.calls), 19 + int(translation) if continued else 7)
                self.assertEqual(claims, [r['sourceItemId'] for r in rows[:10 if continued else 4]])
                self.assertEqual(saves, [r['jobId'] for r in rows[:3]+(rows[4:] if continued else [])])
                counts = run['counts']
                self.assertEqual((counts['completed'],counts['held'],counts['unprocessed']),
                                 (9,1,0) if continued else (3,0,6))
                failure, = run['failures']
                self.assertEqual(failure['sequence'],4)
                if scenario == 'quota':
                    self.assertEqual((run['state'], run['code']), ('stopped','common_failure'))
                else:
                    self.assertEqual(failure['title'],'합성 전시 4')
                    code = ('duplicate_completed_event' if translation else 'unexpected_response_model'
                            if scenario == 'wrong_model' else 'stream_missing_completed')
                    self.assertEqual(failure['response'], {'code':code,'completedSeen':translation or scenario == 'wrong_model'})
                    self.assertEqual(failure['detail']['stage'],'translation' if translation else 'summary')
                    self.assertEqual(failure['flow'],'continued' if continued else 'stopped')
                    self.assertEqual(failure.get('held',False),continued)
                    self.assertEqual(failure['stopStage'],None if continued else 'hold_storage' if hold_attempted else 'summary')
                    self.assertEqual(run['state'],'partial' if continued else 'unknown')
                self.assertNotIn('remainingCount',run)

    def test_progress_is_internal_read_only_status_and_never_restarts_unknown(self):
        release=__import__('threading').Event();control=None
        def execute(command):
            control.report({'selected':51,'processed_items':25,'completed':25});release.wait(1)
            return dict(state='unknown',code='state_unknown',counts={})
        control=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,execute=execute,clock=lambda:1001)
        with self.assertRaises(ValueError):control.report({'selected':1})
        token=control.connect(ticket(control))['token'];signed=ticket(control,'run',cmd=dict(source='all',kind='ai',limit='all'))
        control.submit(token,signed);release.set();control.wait()
        state=control.status(token);self.assertEqual(state['run']['counts']['completed'],25);self.assertTrue(state['busy'])
        with self.assertRaises(ControlError):control.submit(token,ticket(control,'run',cmd=dict(source='all',kind='ai',limit='all')))


if __name__=='__main__':unittest.main()
