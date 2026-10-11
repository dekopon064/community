"""Promotional questions are observed candidates, not participation requirements."""
import copy
import json
import socket
import unittest
from unittest.mock import Mock, patch

from ingest.myseoul_content import participation_constraints
from ingest.myseoul_ai import myseoul_input,generate_myseoul_output,process_myseoul_job
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import protected_information,process_reclassified_job
from test_myseoul_schedule_blocks import recorded_context,reviewed_detail,RECORDED_SUMMARY,FAKE_JA

QUESTION = '요즘 필수라는 AI 툴과 실무 엑셀, 나도 잘 다룰 수 있을까 고민되시나요?'
BENEFIT = '업무 효율을 200% 올려주는 생성형 AI 활용법부터 실무 필수 엑셀 & 스마트 협업 툴까지 한 번에 배워보세요.🚀'


class ParticipationPromotionTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def test_clear_interest_questions_are_optional_but_ambiguous_copy_is_retained(self):
        optional = [QUESTION,'엑셀이 어려워 고민되시나요?', 'AI를 배우고 싶지만 막막한가요？']
        preserved = ['필수 교육인가요?', '배우고 싶다는 생각이 듭니다.',
                     '교육 조건을 알고 싶어 고민되시나요?', '신청이 가능한지 궁금하시나요?',
                     '한국어가 어려운 분인가요?', '초보자만 배우기 어렵나요?']
        f = {'conditions':optional+preserved}
        before = copy.deepcopy(f)
        self.assertEqual(participation_constraints(f),preserved)
        self.assertEqual(f,before)

    def test_actual_and_mixed_restrictions_survive_question_and_benefit_copy(self):
        conditions = [
            '외국인만 참가할 수 있다는 조건이 어렵나요?',
            'D-2 비자가 필수라는 점 때문에 고민되시나요?',
            '19세 이상만 신청할 수 있어 고민되시나요?',
            '성남시 주민 전용이라 고민되시나요?',
            '보호자 동반이 필수인데 어렵나요?',
            '노트북 지참이 필수라 고민되시나요?',
            '재료비 2,000원은 환불되지 않습니다. 고민되시나요?',
            '한국어를 할 수 있어야 합니다. 어렵나요?',
            QUESTION+' 보호자 동반이 필요합니다.',
            '역량을 200% 높이지만 참가자는 외국인으로 제한합니다.',
            '역량을 200% 높이는 교육은 준비가 필수입니다.',
        ]
        self.assertEqual(participation_constraints({'conditions':conditions}),conditions)

    def test_typed_reviewed_fields_are_not_filtered_and_duplicates_are_stable(self):
        f={'conditions':[QUESTION,BENEFIT], 'age':[QUESTION], 'companion':[BENEFIT],
           'language':['한국어로 진행'], 'residence':'성남시 주민',
           'qualification_note':'외국인 전용'}
        before=copy.deepcopy(f)
        expected=[QUESTION,BENEFIT,'한국어로 진행','성남시 주민','외국인 전용']
        self.assertEqual(participation_constraints(f),expected)
        self.assertEqual(participation_constraints(f),expected)
        self.assertEqual(f,before)

    def test_native_assembly_preserves_real_conditions_beside_promotion(self):
        c=recorded_context()
        condition='외국인만 참가 가능하며 노트북 지참 필수'
        c['facts']['conditions']=[QUESTION,BENEFIT,condition]
        before=copy.deepcopy(c)
        ja=Mock(return_value=('合成研修',FAKE_JA+'\n外国人のみ参加可能。ノートパソコンの持参必須。',
                              'success','fake-translation'))
        output=generate_myseoul_output(c,summarize_ko=Mock(return_value=(RECORDED_SUMMARY,'success','recorded-response')),
                                      translate_ja=ja)
        self.assertIn('참가 조건: '+condition,output['contentKo'])
        self.assertNotIn(QUESTION,output['contentKo'])
        self.assertEqual(ja.call_args.args[1],output['contentKo'])
        self.assertEqual(c,before)

    def test_reclassified_fake_candidate_preserves_input_and_restrictions(self):
        from test_reclassification_ai import context as classified_context
        c=classified_context('program')
        native=recorded_context()['facts']
        condition='외국인만 참가 가능하며 노트북 지참 필수'
        native['conditions']=[QUESTION,BENEFIT,condition]
        c['nativeConfirmedFacts']['programFacts']=native
        c['facts'].update(delivery='offline',scope='unknown',evidence='',deadlineOn='2026-10-20')
        c['filters']['delivery']={'status':'known','value':'onsite'}
        c['filters']['location']={'status':'known','value':{'scope':'specific','venues':[
            {'province':'11','district':None,'facility':'','address':''}]}}
        c['filters']['application']['value'].update(start=copy.deepcopy(native['periods']['application'][0]['endpoints'][0]),
            end=copy.deepcopy(native['periods']['application'][0]['endpoints'][1]))
        before=copy.deepcopy(c)
        calls=[]
        output={}
        def rpc(name,args):
            calls.append(name)
            if name=='claim_reclassified_content_ai': return copy.deepcopy(c)
            if name=='finish_reclassified_content_ai':
                self.assertEqual(args['p_classification_version'],c['classificationVersion'])
                self.assertEqual(args['p_revision'],c['revision'])
                output.update(args['p_output'])
                return {'outcome':'inserted','candidateId':c['sourceItemId']}
            raise AssertionError('unexpected fake RPC')
        ko=Mock(return_value=(RECORDED_SUMMARY,'success','recorded-response'))
        ja=Mock(return_value=('合成研修',FAKE_JA+'\n外国人のみ参加可能。ノートパソコンの持参必須。',
                              'success','fake-translation'))
        result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],
            classification_version=c['classificationVersion'],worker_id=c['workerId'],summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,1)
        self.assertEqual(calls,['claim_reclassified_content_ai','finish_reclassified_content_ai'])
        self.assertIn(condition,protected_information(c))
        self.assertNotIn(QUESTION,output['contentKo'])
        self.assertIn(condition,output['contentKo'])
        self.assertEqual(ja.call_args.args[1],output['contentKo'])
        self.assertEqual(json.loads(ko.call_args.args[0])['nativeConfirmedFacts'],c['nativeConfirmedFacts'])
        self.assertEqual(c,before)

    def test_recorded_question_and_benefit_are_not_participation_requirements(self):
        c = recorded_context()
        c['facts']['conditions'] = [QUESTION,BENEFIT]
        before = copy.deepcopy(c)
        self.assertEqual(participation_constraints(c['facts']),[])
        self.assertEqual(c,before)
        # Preserve original candidates in the existing model input contract.
        self.assertEqual(json.loads(myseoul_input(c))['currentFacts']['conditions'],[QUESTION,BENEFIT])

    def test_recorded_summary_fake_translation_and_rpc_complete_without_question(self):
        c = recorded_context()
        c['facts']['conditions'] = [QUESTION,BENEFIT]
        c['facts']['description'] = QUESTION+'\n'+BENEFIT+'\n'+c['facts']['description']
        c['observedFacts'] = copy.deepcopy(c['facts'])
        before = copy.deepcopy(c)
        names=[]
        output={}
        def rpc(name,args):
            names.append(name)
            if name=='claim_myseoul_program_ai': return [copy.deepcopy(c)]
            if name=='admin_myseoul_program_detail': return reviewed_detail(c)
            if name=='finish_myseoul_program_ai':
                for key,value in {'p_job_id':c['jobId'],'p_revision':c['revision'],
                    'p_facts_version':c['factsVersion'],'p_worker_id':c['workerId'],
                    'p_claimed_at':c['claimedAt'],'p_lease_until':c['leaseUntil']}.items():
                    self.assertEqual(args[key],value)
                output.update(args['p_output'])
                return {'outcome':'inserted','candidateId':c['sourceItemId']}
            if name=='fail_myseoul_program_ai': return 'failed'
            raise AssertionError('unexpected fake RPC')
        ko=Mock(return_value=(RECORDED_SUMMARY,'success','recorded-response'))
        ja=Mock(return_value=('合成研修',FAKE_JA,'success','fake-translation'))
        result=process_myseoul_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],
            worker_id=c['workerId'],summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,1)
        self.assertEqual(names,['claim_myseoul_program_ai','admin_myseoul_program_detail','finish_myseoul_program_ai'])
        self.assertEqual((ko.call_count,ja.call_count),(1,1))
        self.assertNotIn(QUESTION,output['contentKo'])
        self.assertNotIn('참가 조건:',output['contentKo'])
        self.assertNotIn('200%',output['contentKo'])
        self.assertEqual(ja.call_args.args[1],output['contentKo'])
        self.assertEqual(c,before)
        for value in ['10월 27일','10월 30일','11월 3일','25명','수강료: 무료']:
            self.assertIn(value,output['contentKo'])


if __name__=='__main__':
    unittest.main()
