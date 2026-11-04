"""Exercise real validators, a fake Pro response, and the scoped correction worker."""
import json
import unittest

from ingest.ai_errors import AiJobError
from ingest.ai_provider import create_provider_adapter
from ingest.myseoul_content import validate_summary_period
from ingest.program_ai import ProgramAIAdapter, program_input
from ingest.rpc_errors import RpcAmbiguous
from ingest.seoul_ai_correction import process_correction
from ingest.seoul_content import assemble_seoul_body, validate_public_body, validation_view
from ingest.translation_validation import _dates_and_times
from test_ingest_ai_chatgpt_plan import streamed, verified_session
from test_ingest_ai_openai import response
from test_seoul_content import synthetic_facts
from test_seoul_fact_roles import confirmed_case, fake_translation

ID = '00000000-0000-4000-8000-000000000001'


class CorrectionTests(unittest.TestCase):
    def test_source_embeds_do_not_reach_the_schedule_parser_or_public_body(self):
        f = synthetic_facts()
        f['description'] = '<iframe src="https://example.test"></iframe><script>ignored()</script>\n' + f['description']
        packet = json.loads(program_input(dict(facts=f, observedFacts=f, factsVersion=1)))
        self.assertNotIn('<iframe', packet['currentFacts']['description'])
        self.assertNotIn('ignored()', packet['currentFacts']['description'])
        self.assertIn('<iframe', f['description'])
        with self.assertRaises(AiJobError):
            validate_public_body('<iframe src="https://example.test"></iframe>')

    def test_24_is_a_closing_endpoint_only(self):
        f = synthetic_facts()
        f['description'] += '\n- 레이저 운영시간 : 20:00~24:00 / 4시간 연속 점등'
        view = validation_view(f)
        self.assertEqual(view['facility_hours_evidence'][-1]['clocks'], [[20, 0], [24, 0]])
        self.assertEqual(_dates_and_times('レーザー点灯時間 20時00分～24時00分')[-1], ('time', 24, 0))
        for rejected in ('회차: 20:00~24:00', '레이저 운영시간: 24:00~20:00', '레이저 운영시간: 20:00~24:30'):
            with self.subTest(rejected=rejected), self.assertRaises(AiJobError):
                _dates_and_times(rejected)

    def test_operating_days_have_their_own_evidence(self):
        f = synthetic_facts()
        line = '\n매주 금,토,일,월요일 체험 프로그램 신청 가능합니다.'
        f['description'] += '\n4. 주의사항 [운영일 안내]' + line
        view = validation_view(f)
        self.assertEqual(view['operating_day_evidence'],
                         ['체험 가능 요일: 금요일, 토요일, 일요일, 월요일'])
        validate_summary_period('체험 일정: 월요일', '', view)
        with self.assertRaises(AiJobError):
            validate_summary_period('체험 일정: 화요일', '', view)
        f['description'] = f['description'].replace('[운영일 안내]', '[접수 안내]')
        self.assertNotIn('operating_day_evidence', validation_view(f))
        with self.assertRaises(AiJobError):
            validate_summary_period('체험 일정: 월요일', '', validation_view(f))

    def run_correction(self, replacement, *, unknown=False, missing_translation=False):
        recorded = confirmed_case()
        summary = recorded['summary']
        ko = assemble_seoul_body(summary['content_ko'], recorded['facts'])
        good = fake_translation(ko)
        before = '10:30'
        draft = dict(ko=summary['content_ko'], koFacts=summary['facts'], model='gpt-6.1-sol',
                     ja=good.replace('| 10:00 |', '| 10:30 |', 1), jaTitle='合成の解説')
        field, evidence, value = 'ja', '開始 10:00', '10:00'
        if missing_translation:
            draft.pop('ja'); draft.pop('jaTitle')
            before, field = '| 09:00 |', 'ko'
            draft['ko'] = draft['ko'].replace('| 10:00 |', before, 1)
        events = []
        def rpc(name, args):
            events.append((name,args))
            if name == 'claim_seoul_ai_correction':
                return dict(id=ID, worker='fake', field=field, before=before, value=value, evidence=evidence,
                            output=draft, facts=recorded['facts'], title=recorded['title'])
            return args['p_result']
        client = streamed([response(json.dumps({'replacement':replacement}))])
        provider = create_provider_adapter('chatgpt_plan',None,client=client,plan_session=verified_session())
        self.addCleanup(provider.close)
        suggest = provider.correct_seoul_excerpt
        if unknown:
            def suggest(**kwargs): raise RpcAmbiguous()
            with self.assertRaises(RpcAmbiguous):
                process_correction(ProgramAIAdapter(rpc),ID,'fake',suggest)
            self.assertEqual(len(events),1)
            return None, None
        result = process_correction(ProgramAIAdapter(rpc),ID,'fake',suggest)
        self.assertEqual(len(client.calls),1)
        self.assertEqual(len(events),2)
        return result, events[-1][1]['p_candidate']

    def test_one_excerpt_corrected_and_validated(self):
        status, output = self.run_correction('10:00')
        self.assertEqual(status,'validated')
        self.assertIn('| 10:00 |',output['contentJa'])
        self.assertNotIn('| 10:30 |',output['contentJa'])

    def test_invalid_or_unverified_changes_remain_private(self):
        self.assertEqual(self.run_correction('10:00\nnew section'), ('invalid_suggestion',None))
        self.assertEqual(self.run_correction('10:00〜10:30'), ('validation_failed',None))
        self.run_correction('', unknown=True)

    def test_korean_only_result_cannot_create_bilingual_candidate(self):
        self.assertEqual(self.run_correction('| 10:00 |', missing_translation=True), ('translation_missing',None))


if __name__ == '__main__':
    unittest.main()

