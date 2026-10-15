"""Audit-derived shapes with wholly synthetic facts/Auth/RPC; no live I/O."""
import copy
import socket
import json
import sys
import unittest
from dataclasses import replace
from unittest.mock import patch

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import program_rpc_item
from ingest.program_scope import extract_program_facts, assess_seoul_program, _label_values, LOCATION_LABELS
from ingest.content_filters import extract_filter_facts, field, confirmed_filter_values
from test_seoul_reservation import row, NOW


def synthetic_packets():
    variants=[('numbered', '문화 체험과 공예품 만들기를 진행합니다.\n3. 진행장소: 합성배움관', {}),
              ('long_topic', ('안내 자료입니다.\n'*100)+'문화 체험을 진행합니다.\n장소: 서울 마포구 합성배움관', {}),
              ('announced', row()['DTLCONT'], {'SVCSTATNM':'안내중'}),
              ('privacy', '공예 문화 체험을 진행합니다.\n장소: 서울 마포구 합성배움관\n자료는 기관 내부 자료 작성 및 홍보에 활용합니다.', {}),
              ('missing', '', {}),
              ('conflict', '문화 체험을 진행합니다.\n장소: 서울 마포구 합성배움관\n운영기간: 2026.10.03 ~ 2026.11.26', {})]
    return [{'name':name,'item':program_rpc_item(normalize_seoul_item(row(sid='SYNTH_LINK_'+name,
        DTLCONT=body,PLACENM='합성배움관',AREANM='마포구',**extra)))} for name,body,extra in variants]


class ValueLinkTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network_forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def packet(self, body, **kwargs):
        rec=normalize_seoul_item(row(DTLCONT=body, **kwargs))
        return rec,program_rpc_item(rec)

    def test_numbered_location_links_same_observation_to_facts_and_filter(self):
        for label in ['3. 진행장소 : 합성배움관','② 체험장소: 합성배움관','□ 교육 장소\n합성배움관','| 장소 | 합성배움관 |']:
            with self.subTest(label=label):
                rec,p=self.packet('문화 체험을 통해 공예품 만들기를 진행합니다.\n'+label,PLACENM='합성배움관',AREANM='마포구')
                f=p['program_facts'];d=p['filterFacts']['data']
                self.assertEqual((f['delivery_mode'],f['activity_region']),('offline','capital'))
                self.assertEqual(d['delivery'],field('onsite'))
                self.assertEqual(d['location']['value']['venues'][0]['district'],'마포구')
                e=p['filterFacts']['evidence']['location']
                self.assertIn(e['excerpt'],str(rec.normalized_payload['provider_fields']))

    def test_no_place_from_booking_address_meeting_or_provider_name_alone(self):
        for line in ['온라인 예약 안내: 합성배움관','기관 주소: 서울 마포구','집결장소: 서울 마포구 정류장','장소: 미정','장소: 부산 체험관']:
            with self.subTest(line=line):
                _,p=self.packet('문화 체험을 안내합니다. 참가 조건을 확인해 주세요.\n'+line,PLACENM='합성배움관',AREANM='마포구')
                self.assertNotEqual(p['filterFacts']['data']['location']['status'],'known')
                if '부산' in line:self.assertEqual(p['program_facts']['activity_region'],'noncapital')

    def test_long_and_angle_source_keeps_short_exact_topic_evidence(self):
        for body in [('합성 안내입니다.\n'*100)+'문화 체험과 공예품 만들기를 진행합니다.', '<합성반>\n문화 체험과 공예품 만들기를 진행합니다.']:
            rec,p=self.packet(body)
            self.assertEqual(p['filterFacts']['data']['topic'],field('culture_experience'))
            e=p['filterFacts']['evidence']['topic']
            self.assertLessEqual(len(e['excerpt']),1000);self.assertNotRegex(e['excerpt'],r'[<>]')
            self.assertIn(e['excerpt'],rec.normalized_payload['program_text'])

    def test_topic_ambiguity_and_negative_are_not_hidden_by_excerpt(self):
        for body in ['문화 체험은 아님. 주민 교류 활동을 진행합니다.','문화 체험은 아님. 안내 자료입니다.','문화 체험은 하지 않습니다.','문화 체험과 주민 교류 활동을 함께 합니다.','교육 내용: 확인 필요\n문화 체험을 진행합니다.']:
            _,p=self.packet(body)
            self.assertEqual(p['filterFacts']['data']['topic']['status'],'unknown')

    def test_privacy_material_is_not_institutional_program_purpose(self):
        _,p=self.packet('공예 문화 체험을 진행하는 성인 프로그램입니다.\n관련 자료는 기관 내부 자료 작성 및 공식 홍보에 활용합니다.')
        self.assertEqual(p['program_facts']['content_kind'],'program')
        self.assertIn('기관 내부 자료',p['program_facts']['description'])
        for purpose in ['기관 내부 직원 교육','기관 운영지원','사업주 전용 지원']:
            _,p=self.packet(purpose+' 사업입니다. 공예 문화 체험을 진행합니다.')
            self.assertEqual(p['program_facts']['content_kind'],'institutional_business')

    def test_announced_is_known_but_not_open_or_guessed_started(self):
        rec,p=self.packet(row()['DTLCONT'],SVCSTATNM='안내중',RCPTBGNDT='2026-10-02 10:00:00')
        self.assertEqual(p['program_facts']['source_status'],'announced')
        a=assess_seoul_program(rec,now=NOW)
        self.assertNotIn('source_status_unknown',a.reason_codes)
        self.assertIn('application_not_started',a.reason_codes)
        self.assertEqual(confirmed_filter_values(p['program_facts'])['application']['sourceStatus'],'not_started')
        # Dates/application are projected by the protected server after storage.
        self.assertEqual(p['filterFacts']['data']['application']['status'],'unknown')
        self.assertEqual(rec.normalized_payload['provider_fields']['SVCSTATNM'],'안내중')
        self.assertEqual(p['program_facts']['periods']['RCPTBGNDT']['value'],'2026-10-02T10:00:00+09:00')
        for value in ['접수종료','예약마감','새로운 알 수 없는 상태']:
            rec=normalize_seoul_item(row(SVCSTATNM=value))
            f=extract_program_facts(rec)
            self.assertNotEqual(f.source_status,'open')
            if value.startswith('새로운'):self.assertIn('source_status_unknown',assess_seoul_program(rec,now=NOW).reason_codes)

    def test_real_conflicts_and_missing_description_survive(self):
        for body,code in [('', 'program_description_missing'),('문화 체험 프로그램입니다.\n운영기간: 2026.10.03 ~ 2026.11.26','body_api_period_conflict'),('문화 체험 프로그램입니다.\n개인 신청불가. 학교만 신청 가능','individual_participation_excluded')]:
            rec=normalize_seoul_item(row(DTLCONT=body))
            self.assertIn(code,assess_seoul_program(rec,now=NOW).reason_codes)

    def test_extraction_never_mutates_record_or_existing_operator_state(self):
        rec=normalize_seoul_item(row(DTLCONT='문화 체험 프로그램입니다.\n3. 진행장소: 합성배움관',PLACENM='합성배움관',AREANM='마포구'))
        before=copy.deepcopy(rec.normalized_payload)
        old={'factsVersion':8,'filterVersion':5,'revision':rec.revision_hash,'history':['operator'],'candidate':['preserve']}
        saved=copy.deepcopy(old);program_rpc_item(rec)
        self.assertEqual(rec.normalized_payload,before);self.assertEqual(old,saved)

    def test_announced_does_not_hide_explicit_closure_conflict(self):
        rec=normalize_seoul_item(row(SVCSTATNM='안내중',DTLCONT=row()['DTLCONT']+'<p>현재 예약마감</p>'))
        self.assertIn('source_status_conflict',assess_seoul_program(rec,now=NOW).reason_codes)

    def test_pre_reception_never_becomes_open_and_date_conflicts_remain(self):
        from ingest.seoul_content import reception_status
        for start in ['2026-09-01 10:00:00','2026-10-02 10:00:00']:
            rec,p=self.packet('문화 체험을 진행하는 성인 프로그램입니다.\n장소: 서울 마포구 합성배움관',
                              SVCSTATNM='안내중',RCPTBGNDT=start)
            a=assess_seoul_program(rec,now=NOW)
            self.assertEqual(a.decision,'not_currently_available')
            self.assertEqual(a.reason_codes,('application_not_started',))
            self.assertEqual(reception_status(p['program_facts'],NOW),'접수 전')
            for overrides,code in [({'RCPTBGNDT':'2026-11-01 10:00:00'},'period_order_conflict'),
                                   ({'DTLCONT':'문화 체험 프로그램입니다.\n접수기간: 2026.09.02 ~ 2026.10.30'},'body_api_period_conflict')]:
                bad=normalize_seoul_item(row(SVCSTATNM='안내중',**overrides))
                self.assertIn(code,assess_seoul_program(bad,now=NOW).reason_codes)

    def test_announced_current_facts_reach_fake_worker_without_rewriting(self):
        from test_program_ai import context, providers, bind_program_filters, ID, REV
        from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
        c=context();c['facts']['source_status']='announced';bind_program_filters(c)
        before=copy.deepcopy(c);ko,ja,inputs=providers(c);calls=[]
        def rpc(name,args):
            calls.append((name,copy.deepcopy(args)))
            if name.startswith('claim_'):return [c]
            if name.startswith('finish_'):return {'candidateId':ID,'outcome':'inserted'}
            raise AssertionError('unapproved fake RPC')
        out=process_seoul_program_job(ProgramAIAdapter(rpc),source_item_id=ID,revision=REV,summarize_ko=ko,translate_ja=ja)
        self.assertEqual(out.completed,1);self.assertEqual(len(inputs),1)
        self.assertEqual([x[0] for x in calls],['claim_seoul_program_ai','finish_seoul_program_ai'])
        self.assertEqual(c,before)

    def test_announced_common_fake_pro_native_and_reclassified_flow(self):
        from test_seoul_workflow import SeoulWorkflowTests
        from test_seoul_content import synthetic_facts
        facts=synthetic_facts();facts['source_status']='announced'
        for classified in (False,True):
            case=SeoulWorkflowTests()
            try:
                with patch('test_seoul_workflow.synthetic_facts',side_effect=lambda:copy.deepcopy(facts)):
                    result,events,client=case.run_worker(classified=classified)
                self.assertEqual(result.completed,1)
                self.assertEqual(len(client.calls),2)
                self.assertEqual(sum(name.startswith('finish_') for name,_ in events),1)
                self.assertFalse(any('publish' in name or 'approve' in name for name,_ in events))
            finally:case.doCleanups()


if __name__=='__main__':
    if '--export' in sys.argv:print(json.dumps(synthetic_packets(),ensure_ascii=False))
    else:unittest.main()
