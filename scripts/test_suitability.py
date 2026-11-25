"""Offline boundary tests for Drive, signed click, subscription stream and RPC."""
import json
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
from ingest.ai_provider import create_provider_adapter
from ingest.chatgpt_plan_protocol import PROGRAM_PLAN_MODEL
from ingest.pc_worker_bridge import PcWorkerControl, command, ControlError
from ingest.pc_worker_existing import ExistingWorkers
from ingest.suitability import classify_run, confirmed_policy, DOCUMENT, PolicyUnavailable
from test_pc_worker import ticket, KEY, ACTOR, PROJECT, ORIGIN
from test_ingest_ai_chatgpt_plan import streamed, verified_session
from test_ingest_ai_openai import response

SOURCE = '옛 성곽을 따라 걸으며 지역 생활사를 배웁니다.'
RESULT = dict(group='keep',clause='K02',reason='지역 역사 해설에 참여합니다.',quote=SOURCE,question='',note='')
CLICK = dict(kind='suitability',source='all',limit='all')


def policy():
    lines = ['마치모아 콘텐츠 적합성 기준','버전: 1.0','확정일: 2026-11-13',
             '적합 K02 지역 역사 해설','제외 E01','확인 필요','수정 제안','미확정 시험 내용']
    return {'documentId':DOCUMENT,'body':{'content':[{'paragraph':{'elements':[{'textRun':{'content':s}}]}} for s in lines]}}


class Rpc:
    def __init__(self, bodies):
        self.items = [dict(id=str(uuid4()),title='합성 콘텐츠',body=b) for b in bodies]
        self.claimed = []
        self.done = []
        self.calls = []
        self.receipt = True

    def invoke(self,name,args):
        self.calls.append(name)
        if name=='suitability_freeze': return None
        if name=='suitability_start': return True
        if name=='suitability_claim':
            if self.items:
                item=self.items.pop(0)
                self.claimed.append(item)
                return item
            return None
        if name=='suitability_release_unsent':
            self.items.insert(0,self.claimed.pop())
            return None
        if name=='suitability_save':
            if self.receipt:self.done.append(args['p_decision'])
            return self.receipt
        if name=='suitability_report':return {'items':[{'state':'done'} for _ in self.done]}
        raise AssertionError(name)


class SuitabilityTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo'):
            guard=patch(name,side_effect=AssertionError('offline only'))
            guard.start()
            self.addCleanup(guard.stop)

    def run_with(self,db,provider,drive=lambda:confirmed_policy(policy())):
        return classify_run(str(uuid4()),lambda:db,provider,lambda _:None,drive)

    def test_signed_click_one_call_and_no_candidate(self):
        db=Rpc([SOURCE,''])
        client=streamed([response(json.dumps(RESULT,ensure_ascii=False))],model=PROGRAM_PLAN_MODEL)
        adapter=create_provider_adapter('chatgpt_plan',None,program=True,client=client,
                                        plan_session=verified_session(PROGRAM_PLAN_MODEL))
        worker=ExistingWorkers(PROJECT)
        worker.suitability=lambda rid:classify_run(rid,lambda:db,lambda:adapter,lambda _:None,
                                                    lambda:confirmed_policy(policy()))
        ctrl=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,execute=worker,clock=lambda:1000)
        session=ctrl.connect(ticket(ctrl))['token']
        rid=str(uuid4())
        grant=ticket(ctrl,'run',request_id=rid,cmd=CLICK)
        with self.assertRaises(ControlError):
            ctrl.submit(session,ticket(ctrl,'run',actor=str(uuid4()),cmd=CLICK))
        ctrl.submit(session,grant)
        ctrl.thread.join(5)
        self.assertEqual(ctrl.submit(session,grant)['run']['state'],'completed')
        self.assertEqual([row['group'] for row in db.done],['keep','check'])
        self.assertEqual(len(client.calls),1)
        self.assertEqual(client.calls[0]['text']['format']['name'],'machimoa_suitability')
        self.assertNotIn('미확정 시험 내용',client.calls[0]['instructions'])
        self.assertEqual(db.calls.count('suitability_freeze'),1)

    def test_missing_drive_or_draft_stops_before_pro(self):
        db=Rpc([SOURCE]); provider=Mock()
        for error in [PermissionError(),PolicyUnavailable()]:
            self.assertEqual(self.run_with(db,provider,Mock(side_effect=error))['code'],'policy_unavailable')
        provider.assert_not_called()
        self.assertNotIn('suitability_claim',db.calls)
        doc=policy();doc['body']['content'][2]['paragraph']['elements'][0]['textRun']['content']='상태: 초안'
        with self.assertRaises(PolicyUnavailable):confirmed_policy(doc)

    def test_unconfirmed_reply_and_unconfirmed_save_no_retry(self):
        for mode in ('disconnected','lost_receipt','bad_quote'):
            db=Rpc([SOURCE,SOURCE]); model=Mock()
            model.classify_suitability.return_value=dict(RESULT)
            if mode=='disconnected':model.classify_suitability.side_effect=TimeoutError()
            elif mode=='bad_quote':model.classify_suitability.return_value['quote']='원문에 없는 내용'
            else:db.receipt=False
            result=self.run_with(db,lambda:model)
            self.assertEqual(result['code'],'suitability_unconfirmed')
            self.assertEqual(len(db.claimed),1)
            self.assertEqual(model.classify_suitability.call_count,1)

    def test_drive_reads_named_document_without_suggestions(self):
        from ingest.suitability import read_policy
        from google.auth.credentials import AnonymousCredentials
        with patch('google.auth.default',return_value=(AnonymousCredentials(),None)) as auth, \
                patch('google.auth.transport.requests.AuthorizedSession.get') as get:
            get.return_value.json.return_value=policy()
            result=read_policy()
            self.assertEqual(result['version'],'1.0')
            self.assertNotIn('미확정 시험 내용',result['text'])
            self.assertTrue(get.call_args.args[0].endswith('/'+DOCUMENT))
            self.assertEqual(get.call_args.kwargs['params']['suggestionsViewMode'],'PREVIEW_WITHOUT_SUGGESTIONS')
            self.assertEqual(auth.call_args.kwargs['scopes'],['https://www.googleapis.com/auth/documents.readonly'])

    def test_cached_items_do_not_open_pro(self):
        model=Mock()
        self.assertEqual(self.run_with(Rpc([]),model)['state'],'completed')
        model.assert_not_called()

    def test_missing_pro_login_keeps_unsent_item_available(self):
        db=Rpc([SOURCE])
        result=self.run_with(db,Mock(side_effect=PermissionError()))
        self.assertEqual(result['state'],'auth_required')
        self.assertEqual(len(db.items),1)
        self.assertFalse(db.claimed)

    def test_command_is_explicit_and_bounded(self):
        for change in ({'limit':1},{'source':'myseoul_program'},{'kind':'suitability_and_ai'}):
            with self.assertRaises(ControlError):command({**CLICK,**change})
