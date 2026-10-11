"""Generated Markdown comparisons: synthetic inputs, no provider or database."""
import socket
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.translation_validation import validate_translation_fidelity
from ingest.body_markdown import comparison_text, read_body, format_reviewed_block, require_plain_summary
from ingest.myseoul_content import deduplicate_summary_fees, validate_assembled_fees
from ingest.ai_claude import validate_summary_payload, validate_translation_payload, SUMMARY_SCHEMA


class MarkdownFidelityTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def check(self, ko, ja):
        validate_translation_fidelity('합성 안내', ko, '合成案内', ja)

    def test_bold_role_swaps_do_not_hide_behind_same_numbers(self):
        with self.assertRaises(AiJobError):
            self.check('**수강료:** 10,000원\n**재료비:** 2,000원',
                       '**受講料:** 2,000ウォン\n**材料費:** 10,000ウォン')

    def test_table_period_roles_cannot_be_swapped(self):
        with self.assertRaises(AiJobError):
            self.check('| 항목 | 기간 |\n| --- | --- |\n| 신청기간 | 2026-10-01 ~ 2026-10-02 |\n| 진행기간 | 2026-11-01 ~ 2026-11-02 |',
                       '| 項目 | 期間 |\n| --- | --- |\n| 申請期間 | 2026年11月1日～2026年11月2日 |\n| 実施期間 | 2026年10月1日～2026年10月2日 |')

    def test_session_dates_and_clocks_cannot_swap_rows(self):
        with self.assertRaises(AiJobError):
            self.check('| 회차 | 날짜 | 시간 |\n| --- | --- | --- |\n| 1회 | 10월 3일 | 10:00 |\n| 2회 | 10월 10일 | 14:00 |',
                       '| 回 | 日付 | 時間 |\n| --- | --- | --- |\n| 1回 | 10月3日 | 14時00分 |\n| 2回 | 10月10日 | 10時00分 |')

    def test_ordered_steps_cannot_disappear(self):
        with self.assertRaises(AiJobError):
            self.check('1. 신청서를 작성합니다.\n2. 제출합니다.', '1. 申請書を作成します。')

    def test_good_bold_lists_tables_and_synonyms(self):
        cases = (
            ('- **수강료:** 1천원\n- **재료비:** 2,000원', '- **授業料:** 1,000ウォン\n- **材料費:** 2,000ウォン'),
            ('- **집결 시간:** 09:45', '- **集合時間:** 午前9時45分'),
            ('- 3시간 실습', '- 180分間の実習'),
            ('- **18세 이상**', '- **18歳以上**'),
            ('1. 신청서를 작성합니다.\n2. 제출합니다.', '1. 申請書を作成します。\n2. 提出します。'),
            ('| 항목 | 비용 |\n| --- | --- |\n| 수강료 | 무료 |\n| 재료비 | 2,000원 |',
             '| 項目 | 費用 |\n| --- | --- |\n| 授業料 | 無料 |\n| 材料費 | 2,000ウォン |'),
            ('| 회차 | 날짜 | 시간 |\n| --- | --- | --- |\n| 1회 | 10월 3일 | 10:00 |\n| 2회 | 10월 10일 | 14:00 |',
             '| 回 | 日付 | 時間 |\n| --- | --- | --- |\n| 1回 | 10月3日 | 10時00分 |\n| 2回 | 10月10日 | 午後2時 |'),
        )
        for ko, ja in cases:
            with self.subTest(ko=ko): self.check(ko, ja)

    def test_shape_and_role_changes_fail(self):
        ko = '| 과정 | 수강료 | 재료비 |\n| --- | --- | --- |\n| 1반 | 1,000원 | 1,000원 |\n| 2반 | 2,000원 | 3,000원 |'
        ja = '| クラス | 受講料 | 材料費 |\n| --- | --- | --- |\n| クラス1 | 1,000ウォン | 1,000ウォン |\n| クラス2 | 2,000ウォン | 3,000ウォン |'
        self.check(ko, ja)
        for bad in (ja.replace('受講料 | 材料費', '材料費 | 受講料'),
                    ja.replace('| クラス2 | 2,000ウォン | 3,000ウォン |', ''),
                    ja + '\n| クラス3 | 2,000ウォン | 3,000ウォン |',
                    ja.replace('クラス1', 'クラス2').replace('クラス2 | 2,000', 'クラス1 | 2,000')):
            with self.subTest(bad=bad), self.assertRaises(AiJobError): self.check(ko, bad)
        for ko, bad in (('- **18세 이상**', '- **18歳以下**'),
                        ('- 보호자 동반 필수', '- 保護者同伴は任意'),
                        ('- 참가 불가', '- 参加できます'),
                        ('1. 제출\n2. 확인', '2. 提出\n1. 確認'),
                        ('- 30명', '- 30歳'),
                        ('- **신청기간:** 10월 1일 ~ 10월 2일', '- **申請期間:** 2026年10月1日～2026年10月2日'),
                        ('**수강료:** 무료', '**受講料:** 1,000ウォン')):
            with self.subTest(ko=ko), self.assertRaises(AiJobError): self.check(ko, bad)

    def test_opaque_urls_and_escaped_pipes(self):
        ko = '| 과정 | 신청 |\n| --- | --- |\n| 안내 \\| 추가 | [신청](https://synthetic.invalid/apply?id=Ａ1) |'
        ja = '| コース | 申請 |\n| --- | --- |\n| 案内 \\| 補足 | [申請](https://synthetic.invalid/apply?id=Ａ1) |'
        self.check(ko, ja)
        with self.assertRaises(AiJobError): self.check(ko, ja.replace('Ａ1', 'A1'))
        self.assertEqual(len(read_body(ko).tables[0].rows[0]), 2)

    def test_invalid_generated_markup_fails_and_plain_prose_stays_plain(self):
        for body in ('| 항목 | 값 |\n| --- | --- |\n| 누락 |',
                     '| 항목 | 값 |\n| --- | --- |\n| 빈 값 | |',
                     '```json\n{}\n```', '`신청기간: 2026-10-01`', '## 주요 내용', '<script>alert(1)</script>',
                     '![새 이미지](https://synthetic.invalid/image.png)', '**10,000**원'):
            with self.subTest(body=body), self.assertRaises(AiJobError): read_body(body)
        body = '일반 설명입니다.\n조건은 원문에서 확인합니다.'
        self.assertEqual(comparison_text(body), body)
        self.assertEqual(read_body(body).tables, ())

    def test_summary_title_and_facts_remain_plain_json_fields(self):
        payload = {'content_ko':'[한 줄 요약]\n일반 요약\n[주요 내용]\n- 실습',
                   'facts':{k:'' for k in SUMMARY_SCHEMA['properties']['facts']['required']}}
        self.assertEqual(validate_summary_payload(payload), payload['content_ko'])
        for body in ('**강조**', '- 목록', '[신청](https://synthetic.invalid)', '## 제목'):
            with self.subTest(body=body), self.assertRaises(AiJobError): require_plain_summary(body)
        payload['facts']['audience'] = '**새 서식**'
        with self.assertRaises(AiJobError): validate_summary_payload(payload)
        with self.assertRaises(AiJobError): validate_translation_payload({'title_ja':'**見出し**','content_ja':'本文'})
        with self.assertRaises(AiJobError): validate_translation_payload({'title_ja':'案内','content_ja':'本文','reason':'extra'})

    def test_fee_grammar_preserves_conditions_and_never_deletes_table_cells(self):
        activity = format_reviewed_block('비용: 수강료: 10,000원; 재료비: 2,000원')
        for sentence in ('**수강료는 10,000원입니다.**', '- 수강료는 10,000원이며 재료비 2,000원이 별도로 있습니다.'):
            self.assertEqual(deduplicate_summary_fees(sentence, activity), '')
        for sentence in ('- 재료비 2,000원은 환불되지 않습니다.',
                         '- 수강료는 1인당 10,000원입니다.',
                         '**수강료는 10,000원이며 교재가 포함됩니다.**',
                         '- 재료비는 현금으로만 납부합니다.'):
            self.assertEqual(deduplicate_summary_fees(sentence, activity), sentence)
        table = '| 항목 | 금액 | 조건 |\n| --- | --- | --- |\n| 재료비 | 2,000원 | 환불 불가 |'
        self.assertEqual(deduplicate_summary_fees(table, activity), table)
        validate_assembled_fees(table + '\n' + activity, activity)
        pure = '| 항목 | 금액 |\n| --- | --- |\n| 재료비 | 2,000원 |'
        with self.assertRaises(AiJobError): validate_assembled_fees(pure + '\n' + activity, activity)
        wrong = table.replace('2,000원', '10,000원')
        with self.assertRaises(AiJobError): deduplicate_summary_fees(wrong, activity)

    def test_reviewed_formatting_keeps_values_and_is_idempotent(self):
        source = '신청기간: 2026-10-01 ~ 2026-10-02\n비용: 수강료: 무료\n신청 링크: https://synthetic.invalid/?id=1'
        styled = format_reviewed_block(source)
        self.assertEqual(comparison_text(styled), source)
        self.assertEqual(format_reviewed_block(styled), styled)
        self.assertEqual(format_reviewed_block('설명만 있는 문단'), '설명만 있는 문단')


if __name__ == '__main__':
    unittest.main()
