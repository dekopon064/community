"""Explicit reviewed schedule notation, strict value/ordinal comparisons only."""
import unittest
from ingest.ai_errors import AiJobError
from ingest.translation_validation import _validate_cell, validate_translation_fidelity


SOURCES = (
    '1차 50명 : 2026년 10월 25일(일) 14:00-16:00 (예정)',
    '1st 50people : October 25, 2026 (Sunday), 2:00–4:00 PM (subject to change)',
    '1-р ээлж 50 хүн : 2026 оны 10-р сарын 25 (ням), 14:00–16:00 (хугацаа өөрчлөгдөж магадгүй)',
    '第一场（50人）：2026年10月25日（周日）14:00-16:00（已安排）',
)
TARGET = '第1回50名: 2026年10月25日（日）14時00分～16時00分（予定）'


class MultilingualCellTests(unittest.TestCase):
    def test_explicit_dates_clocks_people_and_session_ids_match_without_source_mutation(self):
        before = SOURCES
        for source in SOURCES:
            with self.subTest(source=source):
                _validate_cell(source, TARGET)
        self.assertEqual(SOURCES, before)

    def test_every_supported_notation_rejects_changed_or_omitted_values(self):
        changed = (TARGET.replace('第1回','第2回'), TARGET.replace('50名','51名'),
                   TARGET.replace('2026年','2027年'), TARGET.replace('10月','11月'),
                   TARGET.replace('25日','26日'), TARGET.replace('14時00分','13時00分'),
                   TARGET.replace('16時00分','17時00分'), TARGET.replace('50名',''),
                   TARGET.replace('2026年10月25日',''), TARGET.replace('第1回',''),
                   TARGET.replace('14時00分～16時00分',''))
        for source in SOURCES:
            for target in changed:
                with self.subTest(source=source, target=target), self.assertRaises(AiJobError):
                    _validate_cell(source, target)

    def test_ordinal_and_total_session_count_are_independent(self):
        _validate_cell('1회차: 총 3회 교육', '第1回: 全3回の研修')
        _validate_cell('총 3회 교육', '全3回の研修')
        _validate_cell('3회 수업', '全3回の授業')
        for target in ('第3回: 全1回の研修','第2回: 全3回の研修','第1回: 全2回の研修'):
            with self.subTest(target=target), self.assertRaises(AiJobError):
                _validate_cell('1회차: 총 3회 교육', target)

    def test_am_pm_noon_and_midnight_are_not_interchangeable(self):
        for source, target in (
            ('1st 10people: January 5, 2027, 9:30-11:00 AM', '第1回10名: 2027年1月5日9時30分～11時00分'),
            ('1st 10people: January 5, 2027, 12:00-1:00 PM', '第1回10名: 2027年1月5日12時00分～13時00分'),
            ('1st 10people: January 5, 2027, 12:00-1:00 AM', '第1回10名: 2027年1月5日0時00分～1時00分'),
        ):
            _validate_cell(source, target)
            with self.assertRaises(AiJobError):
                _validate_cell(source, target.replace('2027年','2028年'))
        with self.assertRaises(AiJobError):
            _validate_cell(SOURCES[1].replace('PM','AM'), TARGET)

    def test_invalid_explicit_source_dates_and_clocks_fail_closed(self):
        for source in (SOURCES[1].replace('October 25','February 30'),
                       SOURCES[1].replace('2:00','13:00'), SOURCES[1].replace('4:00','4:70'),
                       SOURCES[2].replace('10-р сарын 25','13-р сарын 25')):
            with self.subTest(source=source), self.assertRaises(AiJobError):
                _validate_cell(source, TARGET)

    def test_unknown_date_syntax_is_not_inferred(self):
        for source in (SOURCES[1].replace('October 25, 2026','Oct 25, 2026'),
                       SOURCES[1].replace(', 2026',''), SOURCES[2].replace('сарын','unknown')):
            with self.subTest(source=source), self.assertRaises(AiJobError):
                _validate_cell(source, TARGET)

    def test_list_and_table_values_cannot_move_between_records(self):
        ko = '- '+SOURCES[1]+'\n- '+SOURCES[2].replace('1-р ээлж','2-р ээлж').replace('25 (ням)','26 (даваа)')
        ja = '- '+TARGET+'\n- '+TARGET.replace('第1回','第2回').replace('25日（日）','26日（月）')
        validate_translation_fidelity('합성',ko,'合成',ja)
        with self.assertRaises(AiJobError):
            validate_translation_fidelity('합성',ko,'合成','\n'.join(reversed(ja.splitlines())))
        ko_table = '| 회차 | 일정 |\n| --- | --- |\n| 1회 | '+SOURCES[1]+' |'
        ja_table = '| 回 | 日程 |\n| --- | --- |\n| 第1回 | '+TARGET+' |'
        validate_translation_fidelity('합성',ko_table,'合成',ja_table)
        with self.assertRaises(AiJobError):
            validate_translation_fidelity('합성',ko_table,'合成',ja_table.replace('50名','51名'))

    def test_units_costs_restrictions_and_opaque_urls_remain_protected(self):
        _validate_cell('1회차: 50명 수강료 10,000원, 보호자 동반 필수',
                       '第1回: 50名 受講料10,000ウォン、保護者同伴必須')
        for target in ('第1回: 50歳 受講料10,000ウォン、保護者同伴必須',
                       '第1回: 50名 受講料2,000ウォン、保護者同伴必須',
                       '第1回: 50名 受講料10,000ウォン、保護者同伴任意'):
            with self.subTest(target=target), self.assertRaises(AiJobError):
                _validate_cell('1회차: 50명 수강료 10,000원, 보호자 동반 필수', target)
        url = 'https://synthetic.invalid/Ａ?x=１'
        _validate_cell(url, url)
        with self.assertRaises(AiJobError):
            _validate_cell(url, 'https://synthetic.invalid/A?x=1')
        for url in ('https://synthetic.invalid/a?value=50people',
                    'https://synthetic.invalid/a?t=2:00-4:00PM'):
            _validate_cell(url, url)
            with self.assertRaises(AiJobError):
                _validate_cell(url, url+'&extra=1')


if __name__ == '__main__':
    unittest.main()
