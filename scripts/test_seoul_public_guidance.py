"""Public retained text/replies with synthetic identifiers; never a live generation."""
import copy,json,socket,unittest
from pathlib import Path
from unittest.mock import patch
from ingest.seoul_content import assemble_seoul_body

FIXTURE=Path(__file__).parent/'testdata/seoul_public_guidance_recorded.json'
def recorded():return json.loads(FIXTURE.read_text(encoding='utf-8'))

class PublicGuidanceTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client','ingest.chatgpt_plan_auth.authenticate_worker'):
            guard=patch(name,side_effect=AssertionError('real connection forbidden'))
            guard.start();self.addCleanup(guard.stop)
    def test_missing_method_still_has_official_guidance(self):
        d=recorded()[0];before=copy.deepcopy(d['facts'])
        self.assertNotIn('[신청 방법]',d['before_ko'])
        body=assemble_seoul_body(d['summary']['content_ko'],d['facts'])
        self.assertIn('[신청 방법]',body)
        self.assertIn('[공식 예약 페이지]('+d['facts']['official_url']+')',body)
        self.assertNotIn('전화 신청',body)
        self.assertIn('02-900-1110',body)
        self.assertIn('2026-10-14 18:01',body)
        self.assertEqual(d['facts'],before)
    def test_current_state_not_added_but_facility_conditions_preserved(self):
        d=recorded()[1]
        self.assertIn('**접수 상태:**',d['before_ko'])
        body=assemble_seoul_body(d['summary']['content_ko'],d['facts'])
        self.assertNotIn('접수 상태',body)
        self.assertIn('09:00~17:00',body)
        self.assertIn('실제 참여 일정은 사전 협의',body)
        self.assertIn('2일 전까지',body)
        self.assertIn('2026-12-31 00:00',body)
        self.assertEqual(body,assemble_seoul_body(body,d['facts']))


    def test_snapshot_labels_and_sentences_but_real_conditions_stay(self):
        from ingest.seoul_public_guidance import without_reception_status,validate_public_guidance
        for state in ('접수 중','예약 마감','접수 종료','접수 마감','신청 시작 전','운영 종료'):
            raw='[일정 안내]\n- **접수 상태:** '+state+'\n신청 마감: 2026-10-14 18:01\n[신청 방법]\n잔여 인원에 한해 현장접수합니다.'
            clean=without_reception_status(raw)
            self.assertNotIn('접수 상태',clean);self.assertIn('18:01',clean)
            self.assertIn('잔여 인원에 한해 현장접수',clean)
            validate_public_guidance(clean,'ko')
        for locale,state,header in [('ko','현재 접수 중입니다.','[신청 방법]'),
                                    ('ja','現在受付中です。','[申請方法]')]:
            suffix='예약은 취소 2일 전까지 가능합니다.' if locale=='ko' else 'キャンセルは2日前まで可能です。'
            text=header+'\n'+state+' '+suffix
            self.assertEqual(without_reception_status(text,locale),header+'\n'+suffix)
            with self.assertRaises(Exception):validate_public_guidance(text,locale)
        unique='기상 악화로 프로그램이 취소되었습니다.\n12월 31일까지 운영 후 종료합니다.\n신청 마감 이후에도 잔여 인원은 현장접수 가능합니다.\n예약 취소는 2일 전까지 해 주세요.\n| 활동 | 안내 |\n| --- | --- |\n| 예약 시스템 교육 | 접수 상태 조회 방법 |'
        self.assertEqual(without_reception_status(unique),unique)
        mixed='- **접수 상태:** 예약 마감, 잔여 인원만 현장 접수 가능합니다.'
        self.assertEqual(without_reception_status(mixed),'잔여 인원만 현장 접수 가능합니다.')
        self.assertEqual(without_reception_status('현재 접수 중이며, 잔여 인원만 현장 접수합니다.'),
                         '잔여 인원만 현장 접수합니다.')
        self.assertEqual(without_reception_status('現在受付中ですが、残りの人数のみ現地受付します。','ja'),
                         '残りの人数のみ現地受付します。')
        normal='[신청 방법]\n신청 전 안내를 읽으세요.\n[주요 내용]\n교육 주제는 접수 상태: 조회 API 활용입니다.'
        validate_public_guidance(normal,'ko')

    def test_unknown_method_url_fallback_and_no_phone_inference(self):
        from ingest.seoul_public_guidance import ensure_application_guidance
        d=recorded()[0];f=copy.deepcopy(d['facts'])
        for value in (None,'','https://example.invalid/book',
                      'https://yeyak.seoul.go.kr.evil.invalid/web/reservation/selectReservView.do?rsv_svc_id=A',
                      'https://user:secret@yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=A',
                      f['official_url']+'&other=1'):
            f['official_url']=value
            body=ensure_application_guidance(d['summary']['content_ko'],f)
            self.assertIn('[신청 방법]',body);self.assertNotIn('[공식 예약 페이지](',body)
            self.assertNotIn('secret',body);self.assertIn('제공 기관에 확인',body)
        f=d['facts']
        for method in ('','문의: 02-900-1110','전화 신청 방법은 안내되어 있지 않습니다.','구체적인 신청 방법은 명시되지 않았습니다.\n참석 불가 시 사전에 연락하세요.'):
            body=ensure_application_guidance(d['summary']['content_ko']+'\n[신청 방법]\n'+method,f)
            self.assertIn('[공식 예약 페이지]('+f['official_url']+')',body)
            self.assertNotIn('전화 신청 가능',body)
            self.assertEqual(body,ensure_application_guidance(body,f))
        linked=d['summary']['content_ko']+'\n[신청 방법]\n[공식 안내]('+f['official_url']+')'
        self.assertEqual(ensure_application_guidance(linked,f),linked)

    def test_explicit_method_description_and_unique_booking_not_overwritten(self):
        from ingest.seoul_public_guidance import ensure_application_guidance
        f=recorded()[0]['facts'];base=recorded()[0]['summary']['content_ko']
        for method in ('전화 예약 후 전체 인원으로 신청하세요. 2일 전까지 취소하세요.',
                       '인터넷 예약은 불가합니다. 현장 접수만 가능합니다.',
                       '센터에 전화하거나 현장 방문하여 인원·일정·프로그램을 협의합니다.',
                       '서울시 공공서비스 예약에서 검색 → 프로그램 선택 → 예약 진행'):
            body=base+'\n[신청 방법]\n'+method
            self.assertEqual(ensure_application_guidance(body,f),body)
        empty=copy.deepcopy(f);empty['application_methods']=['phone']
        body=assemble_seoul_body(base,empty)
        self.assertIn('전화 신청',body);self.assertNotIn('[공식 예약 페이지]',body)

    def test_japanese_omission_and_state_readdition_are_rejected(self):
        from ingest.seoul_public_guidance import validate_public_guidance
        from ingest.ai_errors import AiJobError
        for value in ('[要約]\n紹介\n[主な内容]\n内容',
                      '[要約]\n紹介\n[申請方法]\n\n[主な内容]\n内容',
                      '[要約]\n紹介\n[申請方法]\n公式案内をご確認ください。\n受付状況: 受付中'):
            with self.subTest(value=value),self.assertRaises(AiJobError):
                validate_public_guidance(value,'ja')

    def test_application_day_second_cutoffs_and_internal_status_unchanged(self):
        from datetime import datetime
        from ingest.seoul_content import reception_status
        d=recorded()[0];f=copy.deepcopy(d['facts']);raw=copy.deepcopy(f)
        for instant,expected in [('2026-09-19T12:00:00+09:00','신청 시작 전'),
                                 ('2026-10-01T12:00:00+09:00','접수 중'),
                                 ('2026-10-14T18:02:00+09:00','접수 마감'),
                                 ('2026-10-18T12:00:00+09:00','운영 종료')]:
            self.assertEqual(reception_status(f,datetime.fromisoformat(instant)),expected)
        self.assertIn('2026-10-14 18:01',assemble_seoul_body(d['summary']['content_ko'],f))
        self.assertEqual(f,raw)
        f['periods']['RCPTENDDT'].update(value='2026-10-14',precision='day')
        self.assertEqual(reception_status(f,datetime.fromisoformat('2026-10-14T23:59:59+09:00')),'접수 중')
        self.assertEqual(reception_status(f,datetime.fromisoformat('2026-10-15T00:00:00+09:00')),'접수 마감')

    def test_prompt_selection_only_changes_seoul_instructions(self):
        from ingest.ai_claude import summary_system_prompt,MYSEOUL_SUMMARY_SYSTEM
        from test_reclassification_ai import context
        from ingest.reclassification_ai import classification_input
        prompt=summary_system_prompt('{}',True)
        self.assertIn('without current reception status',prompt)
        self.assertIn('Always retain [신청 방법]',prompt)
        c=context('program','seoul_reservation')
        c['nativeConfirmedFacts']['programFacts']=recorded()[0]['facts']
        self.assertIn('Always retain [신청 방법]',summary_system_prompt(classification_input(c)))
        self.assertEqual(summary_system_prompt('{}','myseoul'),MYSEOUL_SUMMARY_SYSTEM)

    def replay(self,index,classified=False,**kwargs):
        from test_seoul_date_hours_replay import DateHoursReplayTests,synthetic_translation
        from ingest.reclassification_ai import protected_sections
        def entries():
            values=recorded()
            for d in values:
                body=assemble_seoul_body(d['summary']['content_ko'],d['facts'])
                d['translation_input_ko']=body
                d['translation']={'title_ja':'合成案内','content_ja':synthetic_translation(body)}
            return values
        with patch('test_seoul_date_hours_replay.recorded',side_effect=entries):
            return DateHoursReplayTests.replay(self,index,classified,**kwargs)

    def test_retained_summaries_actual_workers_fake_pro_and_fenced_candidates(self):
        for index in (0,1):
            for classified in (False,True):
                with self.subTest(index=index,classified=classified):
                    r,events,out,calls=self.replay(index,classified)
                    self.assertEqual((r.completed,r.failed,r.state_unknown),(1,0,0))
                    self.assertEqual(len(calls),2);self.assertEqual(len(out),1)
                    ko=out[0]['contentKo'];ja=out[0]['contentJa']
                    self.assertNotIn('접수 상태',ko)
                    self.assertNotIn('受付状況',ja);self.assertIn('[申請方法]',ja)
                    self.assertEqual(calls[1]['input'][0]['content'],'title_ko: '+out[0]['titleKo']+'\ncontent_ko:\n'+ko)
                    self.assertEqual(sum(n.startswith('finish_') for n,_ in events),1)
                    if index==0:
                        self.assertIn('[공식 예약 페이지]',ko);self.assertIn('18:01',ko)
                        self.assertNotIn('전화 신청',ko)
                    else:
                        for text in ('09:00~17:00','사전 협의','2일 전','10명이상','개인정보 동의서','주차비','우천'):
                            self.assertIn(text,ko)

    def test_bad_results_terminate_and_unknown_does_not_write_again(self):
        for classified in (False,True):
            for bad in ('[受付状況]\n受付中','- **受付状況:** 受付中'):
                r,e,o,c=self.replay(0,classified,bad_ja=lambda body:body+'\n'+bad)
                # A literal state field is forbidden; never a completed candidate.
                self.assertEqual(r.completed,0)
                self.assertEqual(sum(n=='fail_seoul_ai_no_retry' for n,_ in e),1)
                self.assertEqual(r.failed,1);self.assertEqual(len(c),2)
            r,e,o,c=self.replay(0,classified,bad_ko=lambda body:body+'\n[일정 안내]\n신청기간: 2026-09-20 17:00 ~ 2026-10-14 18:02')
            # Actual deadline conflicts remain blocked before translation.
            self.assertEqual(r.completed,0)
            r,e,o,c=self.replay(0,classified,unknown='completion')
            self.assertEqual(r.state_unknown,1);self.assertEqual(sum(n.startswith('finish_') for n,_ in e),1)
            self.assertEqual(sum(n=='fail_seoul_ai_no_retry' for n,_ in e),0)
            r,e,o,c=self.replay(0,classified,bad_ja=lambda body:body.replace('[申請方法]','[別の案内]'))
            self.assertEqual(r.failed,1);self.assertEqual(r.completed,0)
            self.assertEqual(sum(n.startswith('finish_') for n,_ in e),0)
            r,e,o,c=self.replay(0,classified,bad_ja=lambda body:body.replace('SYNTH_PUBLIC_GUIDANCE','CHANGED_URL'))
            self.assertEqual(r.failed,1);self.assertEqual(r.completed,0)
            r,e,o,c=self.replay(0,classified,bad_ja=lambda body:body+'\n受付状況: 受付中',unknown='failure')
            self.assertEqual(r.state_unknown,1);self.assertEqual(r.completed,0)
            self.assertEqual(sum(n=='fail_seoul_ai_no_retry' for n,_ in e),1)
            r,e,o,c=self.replay(0,classified,skip=True)
            self.assertEqual(c,[]);self.assertEqual(o,[])
            r,e,o,c=self.replay(0,classified,claim_change=lambda context:context.update(revision='b'*64))
            self.assertEqual(r.state_unknown,1);self.assertEqual(c,[])

if __name__=='__main__':unittest.main()
