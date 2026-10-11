"""Synthetic public body assembly; all sockets and candidate writes are fake."""
import copy
import re
import socket
import unittest
from unittest.mock import Mock, patch

from ingest.ai_worker import KO_SECTION_HEADERS
from ingest.myseoul_ai import generate_myseoul_output
from ingest.myseoul_ai_support import section_body
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job
from ingest.myseoul_content import merge_reviewed_sections
from ingest.ai_errors import AiJobError
from test_myseoul_ai import context, providers
from test_reclassification_ai import context as classified_context, ID, REV


class PublicFactLayoutTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_native_method_keeps_unique_contact_without_repeating_fact_rows(self):
        c = context()
        method = ' / '.join(c['facts']['application_methods'])
        ko = Mock(return_value=('[한 줄 요약]\n합성 체험\n[주요 내용]\n가족 체험입니다.\n'
            '[신청 방법]\n신청 방법: '+method+'\n신청 후 합성 담당자에게 확인 번호를 알려주세요.\n'
            '[합성 문의](https://synthetic.invalid/contact?kind=family)',
            'success', 'fake-model'))
        _, ja = providers(c)
        out = generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        application = section_body(out['contentKo'], '[신청 방법]', KO_SECTION_HEADERS)
        self.assertIn('신청 후 합성 담당자에게 확인 번호를 알려주세요.', application)
        self.assertIn('[합성 문의](https://synthetic.invalid/contact?kind=family)', application)
        self.assertEqual(application.count(method), 1)

    def classified_run(self, c, text):
        calls = []
        def rpc(name, args):
            calls.append((name, copy.deepcopy(args)))
            if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
            if name == 'finish_reclassified_content_ai': return {'outcome':'inserted', 'candidateId':ID}
            return {'status':'active'}
        ko = Mock(return_value=(text, 'success', 'fake-model'))
        ja = Mock(side_effect=lambda title, body: ('合成案内',
            '[要約]\n合成\n[主な内容]\n合成体験 '+ ' '.join(re.findall(r'\d[\d,]*', body)),
            'success', 'fake-model'))
        before = copy.deepcopy(c)
        result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV,
            classification_version=1, worker_id='synthetic-worker', summarize_ko=ko, translate_ja=ja)
        self.assertEqual(c, before)
        return result, calls, ko, ja

    def test_classified_appendix_does_not_land_under_application(self):
        c = classified_context('program')
        c['nativeConfirmedFacts']['programFacts'].update(capacity_raw=['선착순 12명'])
        result, calls, ko, ja = self.classified_run(c,
            '[한 줄 요약]\n합성 체험\n[주요 내용]\n가족 체험입니다.\n'
            '[신청 방법]\n합성 신청 방법\n신청 후 확인 번호를 알려주세요.')
        self.assertEqual(result.completed, 1)
        body = calls[-1][1]['p_output']['contentKo']
        self.assertNotIn('확인한 분류·참가 안내', body)
        application = section_body(body, '[신청 방법]', KO_SECTION_HEADERS)
        self.assertEqual(application.count('합성 신청 방법'), 1)
        self.assertIn('신청 후 확인 번호를 알려주세요.', application)
        for label in ('분류:', '진행 방식:', '비용:', '모집 인원:', '신청기간:', '참가 조건:'):
            self.assertNotIn(label, application)
        self.assertIn('12명', section_body(body, '[대상]', KO_SECTION_HEADERS))
        self.assertIn('2099-10-15', section_body(body, '[일정 안내]', KO_SECTION_HEADERS))
        self.assertIn('10,000원', section_body(body, '[주요 내용]', KO_SECTION_HEADERS))
        self.assertEqual(ja.call_args.args[1], body)
        self.assertEqual((ko.call_count, ja.call_count), (1, 1))
        self.assertEqual([n for n, _ in calls], ['claim_reclassified_content_ai', 'finish_reclassified_content_ai'])
        self.assertEqual(calls[-1][1]['p_classification_version'], c['classificationVersion'])

    def test_exact_rows_are_merged_once_without_removing_refund_or_guardian_conditions(self):
        reviewed = {'[주요 내용]':'- **비용:** 수강료: 1,000원; 재료비: 1,000원',
                    '[신청 방법]':'- **신청 방법:** 방문\n- **신청 링크:** https://synthetic.invalid/apply?id=2'}
        source = ('[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n'
                  '- **비용:** 수강료: 1,000원; 재료비: 1,000원\n방문\n'
                  'https://synthetic.invalid/apply?id=2\n재료비는 환불되지 않습니다.\n'
                  '보호자가 함께 신청해야 합니다.\n문의: 합성 담당자에게 연락하세요.')
        out = merge_reviewed_sections(source, reviewed)
        self.assertEqual(out.count('수강료: 1,000원'), 1)
        self.assertEqual(out.count('재료비: 1,000원'), 1)
        self.assertEqual(out.count('https://synthetic.invalid/apply?id=2'), 1)
        for condition in ('재료비는 환불되지 않습니다.', '보호자가 함께 신청해야 합니다.',
                          '문의: 합성 담당자에게 연락하세요.'):
            self.assertIn(condition, out)
        self.assertEqual(merge_reviewed_sections(out, reviewed), out)

    def test_multiline_schedule_table_and_source_slash_are_preserved_on_repeat(self):
        table = '| 회차 | 활동 |\n| --- | --- |\n| 1회차 | 읽기 / 쓰기 |'
        reviewed = {'[일정 안내]':'진행기간: 2099-10-01 ~ 2099-10-03\n\n'+table}
        source = '[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n전화 후 방문합니다.'
        out = merge_reviewed_sections(source, reviewed)
        self.assertEqual(out.count(table), 1)
        self.assertEqual(merge_reviewed_sections(out, reviewed), out)

    def test_existing_inline_section_header_contract_keeps_content_and_contact_link(self):
        source = ('[한 줄 요약] 합성 체험\n[주요 내용] 문서를 작성합니다.\n'
                  '[신청 방법] 전화로 신청하세요.\n[합성 문의](https://synthetic.invalid/contact)')
        out = merge_reviewed_sections(source, {'[신청 방법]':'신청 방법: 전화'})
        self.assertIn('[한 줄 요약]\n합성 체험', out)
        self.assertIn('문서를 작성합니다.', out)
        self.assertIn('전화로 신청하세요.', out)
        self.assertIn('[합성 문의](https://synthetic.invalid/contact)', out)

    def test_unrecognized_prose_and_indented_condition_are_kept(self):
        source = ('[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n'
                  '- 신청 방법: 방문\n  보호자가 함께 신청해야 합니다.\n비용 환불 문의는 신청 후 가능합니다.')
        out = merge_reviewed_sections(source, {'[신청 방법]':'신청 방법: 방문'})
        self.assertIn('- 신청 방법: 방문\n  보호자가 함께 신청해야 합니다.', out)
        self.assertIn('비용 환불 문의는 신청 후 가능합니다.', out)

    def test_internal_checklist_rejects_before_translation_and_finish(self):
        for tail in ('확인한 분류·참가 안내\n분류: 프로그램', '분류: 프로그램'):
            c = classified_context('program')
            result, calls, ko, ja = self.classified_run(c,
                '[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n'+tail)
            self.assertEqual(result.completed, 0)
            ja.assert_not_called()
            self.assertFalse(any(n.startswith('finish_') for n, _ in calls))
            self.assertEqual(result.retried, 0)

    def test_native_wrong_fee_or_schedule_in_application_cannot_be_hidden_by_merge(self):
        for row in ('수강료: 99,000원', '신청기간: 2099-10-01 ~ 2099-10-03'):
            c = context()
            ko = Mock(return_value=('[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n'+row,
                                    'success', 'fake-model'))
            ja = Mock()
            with self.assertRaises(AiJobError):generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
            ja.assert_not_called()

    def test_different_method_link_and_value_are_not_assumed_equal(self):
        source = ('[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n'
                  '전화: https://synthetic.invalid/apply?id=3\n방문: https://synthetic.invalid/apply?id=4')
        reviewed = {'[신청 방법]':'방문\n신청 링크: https://synthetic.invalid/apply?id=3'}
        out = merge_reviewed_sections(source, reviewed)
        self.assertIn('전화: https://synthetic.invalid/apply?id=3', out)
        self.assertIn('방문: https://synthetic.invalid/apply?id=4', out)

    def test_reclassified_empty_fees_do_not_invent_fee_or_bypass_conflict_checks(self):
        c = classified_context('program')
        native = context()['facts']
        native['fees'] = []
        c['nativeConfirmedFacts']['programFacts'] = native
        result, calls, _, _ = self.classified_run(c,
            '[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n합성 신청 방법')
        self.assertEqual(result.completed, 1)
        self.assertNotIn('비용:', calls[-1][1]['p_output']['contentKo'])
        for fee in ('수강료: 무료', '수강료: 1,000원'):
            result, calls, _, ja = self.classified_run(c,
                '[한 줄 요약]\n합성\n[주요 내용]\n체험합니다.\n[신청 방법]\n'+fee)
            self.assertEqual(result.completed, 0)
            ja.assert_not_called()
            self.assertFalse(any(n.startswith('finish_') for n, _ in calls))


if __name__ == '__main__':
    unittest.main()
