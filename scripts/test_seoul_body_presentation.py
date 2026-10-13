"""Recorded summary replay, synthetic fences/fake translations/RPC; no network."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from ingest.ai_errors import AiJobError
from ingest.seoul_content import assemble_seoul_body
import test_seoul_per_session_replay as worker_fixture

FIXTURE = Path(__file__).parent / 'testdata/seoul_body_presentation_recorded.json'


def recorded():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


class SeoulBodyPresentationTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client','ingest.chatgpt_plan_auth.authenticate_worker'):
            guard=patch(target,side_effect=AssertionError('real connection forbidden'))
            guard.start();self.addCleanup(guard.stop)

    def test_recorded_duplicate_and_midnight_reproduction_and_cleanup(self):
        d=recorded(); f=d['context']['facts']; before=copy.deepcopy(f)
        self.assertGreater(d['before_ko'].count('성인 및 가족'),1)
        self.assertGreater(d['before_ko'].count('용산가족공원 관리사무소 앞'),1)
        self.assertIn('00:00 ~',d['before_ko'])
        body=assemble_seoul_body(d['summary']['content_ko'],f)
        self.assertEqual(body.count('성인 및 가족'),1)
        self.assertEqual(body.count('용산가족공원 관리사무소 앞'),1)
        self.assertEqual(body.count('20명'),1)
        self.assertNotIn('00:00',body)
        self.assertNotIn('**진행 일정:**',body)
        self.assertNotIn('- - ',body)
        self.assertIn('| 2026년 10월 31일(토) | 14:00~15:20 |',body)
        self.assertIn('**시작 5분 전까지 도착**',body)
        self.assertIn('5일 전',body);self.assertIn('2일 전',body)
        self.assertIn('50% 미만',body);self.assertIn('익월 예약이 불가',body)
        self.assertIn('33℃ 이상',body);self.assertIn('-12℃ 이하',body)
        self.assertIn('70% 이상',body);self.assertIn('150㎍/㎥',body)
        self.assertEqual(f,before)
        self.assertEqual(body,assemble_seoul_body(body,f))

    def test_mixed_venue_and_target_instructions_are_not_deleted(self):
        d=recorded(); f=d['context']['facts']; source=d['summary']['content_ko']
        for sentence in ('집결장소는 용산가족공원 관리사무소 앞이며 보호자 동반이 필요합니다.',
                         '장소: 용산가족공원 관리사무소 앞, 우천 시 실내로 변경됩니다.'):
            body=assemble_seoul_body(source.replace('집결장소는 용산가족공원 관리사무소 앞입니다.',sentence),f)
            self.assertIn(sentence,body)
        mixed='- 성인 및 가족, 보호자 동반 필수'
        self.assertIn(mixed,assemble_seoul_body(source.replace('- 성인 및 가족',mixed),f))

    def test_other_date_capacity_venue_and_checkin_are_not_case_constants(self):
        d=recorded();f=copy.deepcopy(d['context']['facts']);source=d['summary']['content_ko']
        f['description']=f['description'].replace('10월 31일','11월 7일').replace('20명','24명').replace('9가족','6가족').replace('시작 5분전','시작 8분전')
        f['conditions']=[v.replace('20명','24명').replace('9가족','6가족') for v in f['conditions']]
        f['activity_evidence']=['합성공원 안내소 앞']
        for key in ('SVCOPNBGNDT','SVCOPNENDDT'):f['periods'][key]['value']='2026-11-07T00:00:00+09:00'
        source=source.replace('2026년 10월 31일','2026년 11월 7일').replace('20명','24명').replace('9가족','6가족').replace('시작 5분 전','시작 8분 전').replace('용산가족공원 관리사무소 앞','합성공원 안내소 앞')
        before=copy.deepcopy(f);body=assemble_seoul_body(source,f)
        self.assertEqual(body.count('24명'),1);self.assertIn('6가족',body)
        self.assertEqual(body.count('합성공원 안내소 앞'),1)
        self.assertIn('시작 8분 전',body);self.assertIn('**진행기간:** 2026-11-07',body)
        self.assertNotIn('00:00',body);self.assertNotIn('**진행 일정:**',body)
        self.assertEqual(f,before)

    def test_wrong_date_time_count_or_checkin_is_rejected_before_cleanup(self):
        d=recorded();source=d['summary']['content_ko'];f=d['context']['facts']
        for old,new in [('14:00~15:20','14:00~16:20'),('2026년 10월 31일','2027년 10월 31일'),
                        ('20명','21명'),('9가족','8가족'),('5분 전','10분 전'),('5분 전','5분 후')]:
            with self.subTest(new=new),self.assertRaises(AiJobError):
                assemble_seoul_body(source.replace(old,new),f)

    def test_real_midnight_nonzero_seconds_overnight_and_missing_evidence_stay(self):
        d=recorded();base=d['context']['facts']; source=d['summary']['content_ko']
        # Display projection must never change stored precision or time gates.
        for description in ('운영일시: 10월 31일 00:00~01:20',
                            '운영일시: 10월 31일 23:00~00:00','운영일시: 10월 31일 23:00~01:00',
                            '운영일시: 10월 31일', '일정은 별도 안내합니다.'):
            f=copy.deepcopy(base);f['description']=description
            f['conditions']=[]
            minimal='[한 줄 요약]\n합성 체험입니다.\n[주요 내용]\n전통기구를 체험합니다.'
            body=assemble_seoul_body(minimal,f)
            self.assertIn('00:00 ~',body)
        for value in ('2026-10-31T00:00:01+09:00','2026-11-01T00:00:00+09:00'):
            f=copy.deepcopy(base);f['periods']['SVCOPNENDDT']['value']=value
            body=assemble_seoul_body(source,f)
            self.assertIn('00:00',body)
        f=copy.deepcopy(base);f['periods']['RCPTENDDT']['value']='2026-10-30T00:00:00+09:00'
        body=assemble_seoul_body(source,f)
        self.assertIn('2026-10-30 00:00',body)
        self.assertIn('**진행기간:** 2026-10-31\n',body)

    def test_unique_checkin_is_retained_without_repeating_table(self):
        d=recorded();f=d['context']['facts'];source=d['summary']['content_ko']
        missing=source.replace('**시작 5분 전까지 도착**해야 하며, 시간을 준수해 주세요.','')
        body=assemble_seoul_body(missing,f)
        self.assertNotIn('**진행 일정:**',body)
        self.assertIn('**집결 안내:** 시간 꼭! 준수, 시작 5분전 도착요망',body)
        self.assertEqual(body,assemble_seoul_body(body,f))
        # Unknown compound instructions are kept, not partly deleted by numbers.
        f=copy.deepcopy(f);f['description']=f['description'].replace('시간 꼭! 준수, 시작 5분전 도착요망','보호자 동반 필수')
        body=assemble_seoul_body(source,f)
        self.assertIn('보호자 동반 필수',body)
        self.assertIn('**진행 일정:**',body)

    def test_indented_target_qualifier_and_opaque_url_survive(self):
        d=recorded();source=d['summary']['content_ko'];f=d['context']['facts']
        source=source.replace('- 성인 및 가족','- 성인 및 가족\n  보호자 동반 필수')
        source=source.replace('[신청 방법]','https://synthetic.invalid/용산가족공원?time=00:00\n\n[신청 방법]')
        body=assemble_seoul_body(source,f)
        self.assertIn('- 성인 및 가족\n  보호자 동반 필수',body)
        self.assertIn('https://synthetic.invalid/용산가족공원?time=00:00',body)

    def run_workers(self,summary=None,change=None):
        latest=recorded();original_case=worker_fixture.recorded_case
        def case(classified=False):
            data,c=original_case(classified)
            data.update(summary=latest['summary'],translation=latest['previous_translation'])
            if summary is not None:data['summary']={**data['summary'],'content_ko':summary}
            return data,c
        outputs=[]
        for classified in (False,True):
            with patch.object(worker_fixture,'recorded_case',side_effect=case), patch.object(
                    worker_fixture,'fake_translation',return_value=latest['fake_translation_cleaned']['content_ja']):
                outputs.append(worker_fixture.run_recorded(self,classified=classified,change=change))
        return outputs

    def test_actual_summary_both_pro_workers_translate_clean_body_and_fake_finish(self):
        for result,calls,output,requests,data in self.run_workers():
            self.assertEqual(result.completed,1)
            self.assertEqual(len(requests),2)
            self.assertEqual(sum(n.startswith('finish_') for n,_ in calls),1)
            body=output['contentKo']
            self.assertEqual(body.count('20명'),1)
            self.assertEqual(body.count('용산가족공원 관리사무소 앞'),1)
            self.assertNotIn('00:00',body)
            self.assertNotIn('**진행 일정:**',body)
            self.assertEqual(requests[1]['input'][0]['content'],'title_ko: '+output['titleKo']+'\ncontent_ko:\n'+body)
            self.assertEqual(output['contentJa'],recorded()['fake_translation_cleaned']['content_ja'])
            self.assertNotEqual(output['contentJa'],data['translation']['content_ja'])
            self.assertEqual(set(output),{'titleKo','titleJa','summaryKo','summaryJa','contentKo','contentJa','aiModel'})

    def test_bad_summary_stops_before_translation_and_fake_candidate(self):
        d=recorded()
        for old,new in [('14:00~15:20','14:00~16:20'),('20명','21명'),('5분 전','10분 전')]:
            for result,calls,output,requests,_ in self.run_workers(d['summary']['content_ko'].replace(old,new)):
                self.assertEqual(result.completed,0);self.assertEqual(output,{})
                self.assertEqual(len(requests),1)
                self.assertFalse(any(n.startswith('finish_') for n,_ in calls))

    def test_bad_fake_translation_never_completes(self):
        for result,calls,output,requests,_ in self.run_workers(change=lambda d:{**d,'content_ja':d['content_ja'].replace('20名','21名')}):
            self.assertEqual(result.completed,0);self.assertEqual(output,{})
            self.assertEqual(len(requests),2)
            self.assertFalse(any(n.startswith('finish_') for n,_ in calls))

    def test_shared_instructions_reach_both_adapters_with_unchanged_cost_guard(self):
        from ingest.ai_claude import ClaudeAdapter,CLAUDE_JOB_USD_CAP,SEOUL_SCHEDULE_DISPLAY_RULES
        from ingest.ai_openai import OpenAIAdapter,GPT_JOB_USD_CAP
        from ingest.program_ai import program_input
        from test_ingest_ai_claude import FakeClient as ClaudeClient,_message
        from test_ingest_ai_openai import FakeClient as OpenAIClient,response
        d=recorded();c=d['context'];body=assemble_seoul_body(d['summary']['content_ko'],c['facts'])
        translation={'title_ja':d['previous_translation']['title_ja'],'content_ja':worker_fixture.fake_translation(body)}
        for kind in ('anthropic','openai'):
            client=ClaudeClient() if kind=='anthropic' else OpenAIClient()
            adapter=ClaudeAdapter(client=client) if kind=='anthropic' else OpenAIAdapter(client=client)
            if kind=='anthropic':
                client.messages.messages=[_message(json.dumps(d['summary'],ensure_ascii=False)),_message(json.dumps(translation,ensure_ascii=False))]
            else:
                client.responses.results=[response(json.dumps(d['summary'],ensure_ascii=False)),response(json.dumps(translation,ensure_ascii=False))]
            adapter.summarize_program_ko(program_input(c),c['facts']['official_url'],c['title'])
            adapter.translate_ja(c['title'],body)
            requests=client.messages.create_calls if kind=='anthropic' else client.responses.requests
            self.assertEqual(len(requests),2)
            instructions=requests[0].get('system',requests[0].get('instructions'))
            self.assertIn(SEOUL_SCHEDULE_DISPLAY_RULES.strip(),instructions)
            # A fake counted overflow still stops before any generation.
            blocked=ClaudeClient() if kind=='anthropic' else OpenAIClient()
            channel=blocked.messages if kind=='anthropic' else blocked.responses
            channel.count_values[0]=100000
            adapter=ClaudeAdapter(client=blocked) if kind=='anthropic' else OpenAIAdapter(client=blocked)
            with self.assertRaises(AiJobError):adapter.summarize_program_ko(program_input(c),None,c['title'])
            self.assertEqual(channel.create_calls if kind=='anthropic' else channel.requests,[])
        self.assertEqual(CLAUDE_JOB_USD_CAP,.10);self.assertEqual(GPT_JOB_USD_CAP,.10)


if __name__=='__main__': unittest.main()
