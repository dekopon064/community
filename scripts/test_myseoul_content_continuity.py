"""Synthetic regressions for facts lost between review, summary and translation."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from ingest.ai_errors import AiJobError
from ingest.myseoul_ai import myseoul_input, generate_myseoul_output, fact_sections
from ingest.reclassification_ai import classification_input, protected_information
from test_myseoul_ai import context, providers
from test_reclassification_ai import context as classified_context
from ingest.myseoul_content import validate_summary_period, deduplicate_summary_fees, validate_assembled_fees


class ContentContinuityTests(unittest.TestCase):
    def test_recorded_plan_fee_sentence_is_removed(self):
        # Exact wording from the already completed synthetic Pro summary.
        sentence = '수강료는 10,000원이며, 재료비 2,000원이 별도로 있습니다.'
        self.assertEqual(deduplicate_summary_fees(sentence,
            '비용: 수강료: 10,000원; 재료비: 2,000원'), '')

    def test_fee_simple_variations_and_equal_amount_different_components(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원'
        for sentence in ('수강료는 10,000원입니다.', '재료비는 별도로 2,000원입니다.',
                         '재료비 2,000원이 별도로 있습니다.', '재료비는 2,000원이며 별도입니다.',
                         '재료비가 2,000원입니다.'):
            with self.subTest(sentence=sentence):
                self.assertEqual(deduplicate_summary_fees(sentence, activity), '')
        self.assertEqual(deduplicate_summary_fees('수강료 3,000원이며 재료비 3,000원입니다.',
            '비용: 수강료: 3,000원; 재료비: 3,000원'), '')
        with self.assertRaises(AiJobError):
            deduplicate_summary_fees('입장료 3,000원입니다.', '비용: 재료비: 3,000원')

    def test_fee_conditions_unknown_amount_and_wrong_currency_stay_distinct(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원'
        for sentence in ('재료비 2,000원은 환불되지 않습니다.',
                         '거주 요건 충족자는 수강료를 50% 할인받습니다.',
                         '재료비는 현금으로만 납부합니다.', '수강료는 1인당 10,000원입니다.',
                         '수강료는 10,000원이며 교재가 포함됩니다.',
                         '수강료 10,000원 또는 재료비 2,000원입니다.'):
            with self.subTest(sentence=sentence):
                self.assertEqual(deduplicate_summary_fees(sentence, activity), sentence)
                validate_assembled_fees('[주요 내용]\n'+sentence+'\n'+activity, activity)
        for sentence in ('재료비 2,000엔입니다.', '재료비 2,000달러입니다.'):
            with self.subTest(sentence=sentence), self.assertRaises(AiJobError):
                deduplicate_summary_fees(sentence, activity)
        for sentence in ('수강료는 1인당 20,000원입니다.', '재료비를 3,000원 납부합니다.'):
            with self.subTest(sentence=sentence), self.assertRaises(AiJobError):
                deduplicate_summary_fees(sentence, activity)
        self.assertEqual(deduplicate_summary_fees('활동입니다.', '비용: '), '활동입니다.')
        with self.assertRaises(AiJobError):
            deduplicate_summary_fees('재료비 2,000원입니다.', '비용: ')

    def test_final_guard_checks_all_sections_without_deleting_conditions(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원'
        for prefix in ('[한 줄 요약]', '[신청 방법]', '[주요 내용]'):
            with self.subTest(section=prefix), self.assertRaises(AiJobError):
                validate_assembled_fees(prefix+'\n수강료는 10,000원입니다.\n'+activity, activity)
        with self.assertRaises(AiJobError):
            validate_assembled_fees(activity+'\n'+activity, activity)

    def test_native_final_guard_stops_translation_if_cleanup_regresses(self):
        c = context()
        c['facts']['fees'] = [{'component':'tuition','evidence':['10,000원']},
                              {'component':'materials','evidence':['2,000원']}]
        before = copy.deepcopy(c)
        ko = Mock(return_value=('[한 줄 요약]\n교육입니다.\n[주요 내용]\n'
            '수강료는 10,000원이며, 재료비 2,000원이 별도로 있습니다.', 'success', 'fake'))
        ja = Mock()
        with patch('ingest.myseoul_ai.deduplicate_summary_fees', side_effect=lambda main, _:main):
            with self.assertRaises(AiJobError) as failure:
                generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        self.assertEqual(failure.exception.code, 'ai_schema_error')
        ja.assert_not_called()
        self.assertEqual(c, before)

    def test_fee_only_prose_is_removed_without_changing_activity_or_conditions(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원'
        main = ('디지털 사무 도구를 실습합니다. 수강료는 10,000원이며, 재료비는 별도로 2,000원입니다. '
                '마실 물을 준비하세요.\nF-2 비자 소지자만 신청할 수 있습니다.')
        result = deduplicate_summary_fees(main, activity)
        self.assertNotIn('수강료', result)
        self.assertNotIn('재료비', result)
        for text in ['디지털 사무 도구를 실습합니다.', '마실 물을 준비하세요.',
                     'F-2 비자 소지자만 신청할 수 있습니다.']:
            self.assertIn(text, result)
        self.assertEqual(deduplicate_summary_fees(result, activity), result)

    def test_fee_equivalent_units_and_labeled_clauses_preserve_components(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원; 기타 비용: 1,000원'
        for main in ('수강료는 1만원이며, 재료비는 2천원입니다.',
                     '수강료: 10,000원, 재료비: 2,000원',
                     '비용: 수강료: 10,000원; 재료비: 2,000원',
                     '기타비용은 1,000원입니다.'):
            with self.subTest(main=main):
                self.assertEqual(deduplicate_summary_fees(main, activity), '')
        self.assertEqual(deduplicate_summary_fees('수강료는 무료이며, 입장료는 3,000원입니다.',
            '비용: 수강료: 무료; 입장료: 3,000원'), '')

    def test_fee_qualifications_and_mixed_activity_are_not_deleted(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원'
        for main in ('수강료는 10,000원이며 보호자 동반이 필요합니다.',
                     '재료비는 2,000원이며 취소 시 환불되지 않습니다.',
                     '수강료는 10,000원이며 거주 요건 충족자는 50% 할인됩니다.',
                     '재료비는 별도로 2,000원이며 현금으로만 납부합니다.',
                     '1인당 수강료는 10,000원입니다.',
                     '수강료는 10,000원(교재 포함)입니다.'):
            with self.subTest(main=main):
                self.assertEqual(deduplicate_summary_fees(main, activity), main)
        # Removing simple prose keeps the full qualified authoritative fee row.
        main = '수강료는 10,000원입니다.'
        self.assertEqual(deduplicate_summary_fees(main, '비용: 수강료: 1인당 10,000원'), '')

    def test_conflicting_fee_prose_is_rejected_before_deduplication(self):
        activity = '비용: 수강료: 10,000원; 재료비: 2,000원'
        for main in ('수강료는 2,000원이며 재료비는 10,000원입니다.',
                     '수강료는 무료입니다.', '재료비는 3,000원입니다.',
                     '입장료는 10,000원입니다.', '수강료: 10,000원; 재료비: 3,000원'):
            with self.subTest(main=main), self.assertRaises(AiJobError):
                deduplicate_summary_fees(main, activity)
        with self.assertRaises(AiJobError):
            deduplicate_summary_fees('수강료는 0원입니다.', '비용: 수강료: 무료')

    def test_native_fee_deduplication_reaches_translation_without_mutating_facts(self):
        c = context()
        c['facts']['fees'] = [{'component':'tuition','evidence':['10,000원']},
                              {'component':'materials','evidence':['2,000원']}]
        before = copy.deepcopy(c)
        _, ja = providers(c)
        ja = Mock(side_effect=ja)
        ko = Mock(return_value=('[한 줄 요약]\n교육입니다.\n[주요 내용]\n'
            '디지털 교육입니다. 수강료는 10,000원이며, 재료비는 별도로 2,000원입니다. '
            '마실 물을 준비하세요.', 'success', 'fake'))
        out = generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        self.assertEqual(c, before)
        self.assertEqual(out['contentKo'].count('수강료'), 1)
        self.assertEqual(out['contentKo'].count('재료비'), 1)
        self.assertIn('비용: 수강료: 10,000원; 재료비: 2,000원', out['contentKo'])
        self.assertIn('마실 물을 준비하세요.', out['contentKo'])
        self.assertEqual(ja.call_args.args[1], out['contentKo'])
        self.assertEqual(ko.call_count, 1)
        self.assertEqual(ja.call_count, 1)

    def test_reclassified_native_fee_deduplication_keeps_protected_records(self):
        from ingest.reclassification_ai import process_reclassified_job
        from ingest.program_ai import ProgramAIAdapter
        from test_reclassification_ai import ID, REV
        c = classified_context('program')
        native = context()['facts']
        c['nativeConfirmedFacts']['programFacts'] = native
        before = copy.deepcopy(c)
        events = []
        def rpc(name, args):
            events.append((name, args))
            if name == 'claim_reclassified_content_ai': return c
            if name == 'finish_reclassified_content_ai': return {'outcome':'inserted','candidateId':ID}
            return {'status':'active'}
        ko = Mock(return_value=('[한 줄 요약]\n합성 교육\n[주요 내용]\n'
            '교육 활동입니다. 수강료는 무료이며, 입장료는 3,000원입니다. '
            '환불 조건은 원문을 확인하세요.\n[신청 방법]\n공식 안내 확인', 'success', 'fake'))
        def ja(title, content):
            self.assertNotIn('수강료는 무료이며', content)
            self.assertIn('환불 조건은 원문을 확인하세요.', content)
            self.assertIn(protected_information(c), content)
            import re
            return '合成', '[要約]\n合成\n[主な内容]\n'+ ' '.join(re.findall(r'\d[\d,]*', content)), 'success', 'fake'
        result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV,
            classification_version=1, worker_id='synthetic-worker', summarize_ko=ko, translate_ja=ja)
        self.assertEqual(result.completed, 1)
        self.assertEqual(c, before)
        self.assertEqual([name for name,_ in events], ['claim_reclassified_content_ai','finish_reclassified_content_ai'])
        # Fee-only major content still has a real section: insert the protected
        # block there once, without dropping it or appending a second copy.
        events.clear()
        ko.return_value = ('[한 줄 요약]\n합성 교육\n[주요 내용]\n'
            '수강료는 무료이며, 입장료는 3,000원입니다.\n[신청 방법]\n공식 안내 확인', 'success', 'fake')
        def fee_only_ja(title, content):
            from ingest.myseoul_ai_support import section_body
            from ingest.ai_worker import KO_SECTION_HEADERS
            self.assertEqual(section_body(content, '[주요 내용]', KO_SECTION_HEADERS), protected_information(c))
            self.assertEqual(content.count(protected_information(c)), 1)
            self.assertNotIn('수강료는 무료이며', content)
            import re
            return '合成', '[要約]\n合成\n[主な内容]\n'+ ' '.join(re.findall(r'\d[\d,]*', content)), 'success', 'fake'
        result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV,
            classification_version=1, worker_id='synthetic-worker', summarize_ko=ko, translate_ja=fee_only_ja)
        self.assertEqual(result.completed, 1)
        self.assertEqual(c, before)

    def schedule_facts(self, start='2027-02-03', end='2027-02-17', evidence=None):
        c = context()
        f = c['facts']
        f['periods']['operation'] = [{'status': 'ok', 'endpoints': [
            {'value': start, 'precision': 'day'}, {'value': end, 'precision': 'day'}]}]
        f['session_evidence'] = evidence or ['2월 3일, 2월 10일, 2월 17일 09:30~11:00, 총 3회']
        f['meeting_evidence'] = []
        return f

    def test_session_year_omission_and_reviewed_operation_year_are_compatible(self):
        f = self.schedule_facts()
        before = copy.deepcopy(f)
        for year in ('', '2027년 '):
            with self.subTest(year=year):
                validate_summary_period('실제 수업: '+year+
                    '2월 3일, 2월 10일, 2월 17일 각 09:30~11:00, 총 3회',
                    fact_sections(f)['[일정 안내]'], f)
        self.assertEqual(f, before)
        self.assertNotIn('2027년', fact_sections(f)['[일정 안내]'])
        f['session_evidence'] = []
        f['description'] = '교육 일정: 2월 3일, 2월 10일, 2월 17일 09:30~11:00, 총 3회'
        validate_summary_period('실제 수업: 2027년 2월 10일 09:30~11:00',
            fact_sections(f)['[일정 안내]'], f)

    def test_true_session_conflicts_still_fail_including_no_count_label(self):
        f = self.schedule_facts()
        for line in ('2028년 2월 3일', '2027년 2월 4일', '2027년 3월 3일',
                     '2월 3일 09:45~11:00', '2월 3일 09:30~12:00',
                     '2월 3일, 총 4회', '2월 3일(월)'):
            with self.subTest(line=line), self.assertRaises(AiJobError):
                validate_summary_period('실제 수업: '+line, fact_sections(f)['[일정 안내]'], f)

    def test_cross_year_sessions_bind_year_to_date_not_year_set(self):
        f = self.schedule_facts('2026-12-30', '2027-01-06',
            ['12월 30일, 1월 6일 09:30~11:00, 총 2회'])
        correct = '진행 일정: 2026년 12월 30일, 2027년 1월 6일 09:30~11:00, 총 2회'
        validate_summary_period(correct, fact_sections(f)['[일정 안내]'], f)
        swapped = correct.replace('2026년 12월', '2027년 12월').replace('2027년 1월', '2026년 1월')
        with self.assertRaises(AiJobError):
            validate_summary_period(swapped, fact_sections(f)['[일정 안내]'], f)
        f['session_evidence'] = ['2026년 12월 30일, 2027년 1월 6일 09:30~11:00, 총 2회']
        validate_summary_period(correct, fact_sections(f)['[일정 안내]'], f)
        with self.assertRaises(AiJobError):
            validate_summary_period(swapped, fact_sections(f)['[일정 안내]'], f)

    def test_explicit_evidence_year_cannot_be_overridden_by_operation_year(self):
        f = self.schedule_facts(evidence=['2028년 2월 3일 09:30~11:00, 총 3회'])
        for year in (2027, 2028):
            with self.subTest(year=year), self.assertRaises(AiJobError):
                validate_summary_period(f'진행 일정: {year}년 2월 3일 09:30~11:00, 총 3회',
                    fact_sections(f)['[일정 안내]'], f)
        f = self.schedule_facts(evidence=['2027년 2월 3일 09:30~11:00, 총 3회'])
        validate_summary_period('진행 일정: 2027년 2월 3일 09:30~11:00, 총 3회',
            fact_sections(f)['[일정 안내]'], f)

    def test_unknown_or_ambiguous_operation_year_is_not_invented(self):
        for bounds in ([], [{'status': 'unknown', 'endpoints': []}],
                       self.schedule_facts('2026-01-01', '2028-12-31')['periods']['operation']):
            f = self.schedule_facts()
            f['periods']['operation'] = bounds
            with self.subTest(bounds=bounds), self.assertRaises(AiJobError):
                validate_summary_period('진행 일정: 2027년 2월 3일', '', f)
            validate_summary_period('진행 일정: 2월 3일', '', f)

    def test_operation_bounds_disambiguate_leap_date_without_adding_dates(self):
        f = self.schedule_facts('2027-12-01', '2028-03-01', ['2월 29일'])
        validate_summary_period('진행 일정: 2028년 2월 29일', '', f)
        with self.assertRaises(AiJobError):
            validate_summary_period('진행 일정: 2027년 2월 29일', '', f)
        f['periods']['operation'] = []
        f['session_evidence'] = ['2027년 2월 29일']
        with self.assertRaises(AiJobError):
            validate_summary_period('진행 일정: 2027년 2월 29일', '', f)

    def test_current_capacity_enters_input_not_old_observation(self):
        c = context()
        c['facts']['capacity_raw'] = ['선착순 25명']
        c['facts']['capacity_value'] = 25
        c['observedFacts']['capacity_raw'] = ['10명']
        packet = json.loads(myseoul_input(c))
        self.assertEqual(packet['currentFacts']['capacity_raw'], ['선착순 25명'])
        self.assertEqual(packet['currentFacts']['capacity_value'], 25)
        self.assertIn('capacity_raw', packet['operatorSupplementedFields'])
        self.assertNotIn('observedFacts', packet)

    def test_explicit_description_sessions_survive_empty_extracted_sessions(self):
        c = context()
        c['facts']['session_evidence'] = []
        c['facts']['description'] = ('합성 교육 안내입니다.\n'
            '교육 일정: 10월 3일(토), 10월 10일(토), 10월 17일(토), 총 3회\n'
            '접수 발표: 9월 30일')
        text = fact_sections(c['facts'])['[일정 안내]']
        self.assertIn('10월 10일', text)
        self.assertIn('총 3회', text)
        self.assertNotIn('접수 발표', text)
        self.assertNotIn('00:00', text)

    def test_promotional_percent_optional_and_confirmed_limits_are_assembled(self):
        c = context()
        c['facts']['conditions'] = ['업무 효율을 173% 올려주는 활용 교육']
        before = copy.deepcopy(c)
        ko, ja = providers(c)
        ko = Mock(return_value=('[한 줄 요약]\n교육입니다.\n[주요 내용]\n교육과 문화 활동입니다.', 'success', 'fake'))
        out = generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        self.assertNotIn('173%', out['contentKo'])
        self.assertEqual(c, before)
        c['facts']['conditions'] = ['회차당 10명, 18세 이상']
        # Confirmed limits are supplied by body assembly, not required twice in
        # generated main prose. Translation must receive the completed body.
        ko, ja = providers(c)
        ja = Mock(side_effect=ja)
        ko = Mock(return_value=('[한 줄 요약]\n교육입니다.\n[주요 내용]\n교육입니다.', 'success', 'fake'))
        out = generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        self.assertIn('회차당 10명, 18세 이상',out['contentKo'])
        self.assertIn('회차당 10명, 18세 이상',ja.call_args.args[1])

    def test_capacity_only_in_generated_audience_is_preserved_in_assembled_body(self):
        c=context();c['facts']['capacity_raw']=['선착순 25명'];c['facts']['capacity_value']=25
        ko,ja=providers(c)
        ja=Mock(side_effect=ja)
        ko=Mock(return_value=('[한 줄 요약]\n교육입니다.\n[대상]\n선착순 25명입니다.\n'
            '[주요 내용]\n디지털 사무 교육입니다.','success','fake'))
        out=generate_myseoul_output(c,summarize_ko=ko,translate_ja=ja)
        self.assertIn('모집 인원: 선착순 25명',out['contentKo'])
        self.assertIn('모집 인원: 선착순 25명',ja.call_args.args[1])

    def test_conflicting_generated_schedule_stops_before_translation(self):
        c = context()
        ko = Mock(return_value=('[한 줄 요약]\n교육입니다.\n[기간·상태]\n'
            '진행 일정: 10월 4일(일), 총 9회\n[주요 내용]\n교육입니다.', 'success', 'fake'))
        ja = Mock()
        with self.assertRaises(AiJobError):
            generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        ja.assert_not_called()

    def test_capacity_cannot_be_satisfied_by_a_date_or_wrong_unit(self):
        c = context()
        c['facts']['capacity_raw'] = ['25명']
        c['facts']['capacity_value'] = 25
        ko = Mock(return_value=('[한 줄 요약]\n교육입니다.\n[주요 내용]\n25세 대상 교육입니다.', 'success', 'fake'))
        ja = Mock()
        with self.assertRaises(AiJobError):
            generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        ja.assert_not_called()

    def test_reclassified_input_and_protected_capacity_and_sessions(self):
        c = classified_context('program')
        c['nativeConfirmedFacts']['programFacts'].update(
            capacity_raw=['선착순 25명'], capacity_value=25,
            session_evidence=['10월 3일, 10월 10일, 총 2회'])
        packet = json.loads(classification_input(c))
        self.assertEqual(packet['nativeConfirmedFacts']['programFacts']['capacity_value'], 25)
        self.assertIn('선착순 25명', protected_information(c))
        self.assertIn('10월 10일', protected_information(c))

    def test_explicit_application_operation_swap_is_rejected(self):
        c = context()
        parts = fact_sections(c['facts'])
        period = parts['[일정 안내]']
        application = period.splitlines()[0].split(': ', 1)[1]
        operation = period.splitlines()[1].split(': ', 1)[1]
        ko = Mock(return_value=('[한 줄 요약]\n체험\n[기간·상태]\n신청기간: ' + operation +
            '\n진행기간: '+application+'\n[주요 내용]\n체험', 'success', 'fake'))
        ja = Mock()
        with self.assertRaises(AiJobError):
            generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        ja.assert_not_called()

    def test_fee_roles_cannot_be_swapped_and_extra_capacity_rejected(self):
        c = context()
        for main in ['수강료: 3,000원\n입장료: 무료', '정원 999명']:
            ko = Mock(return_value=('[한 줄 요약]\n체험\n[주요 내용]\n'+main, 'success', 'fake'))
            ja = Mock()
            with self.assertRaises(AiJobError):
                generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
            ja.assert_not_called()

    def test_restriction_and_mixed_benefit_condition_are_not_dropped(self):
        from ingest.myseoul_content import participation_constraints
        c = context()
        c['facts']['conditions'] = ['F-2 비자 필수, 보호자 없이 참가 불가',
            '거주 요건 충족자는 재료비 50% 할인', '업무 효율을 117% 올리는 교육']
        self.assertEqual(participation_constraints(c['facts'])[:2], c['facts']['conditions'][:2])
        self.assertNotIn(c['facts']['conditions'][2], participation_constraints(c['facts']))

    def test_full_native_reclassified_facts_keep_sessions_not_promotion(self):
        from test_reclassification_ai import ClassificationAITests
        c=classified_context('program')
        native=context()['facts']
        native['conditions']=['업무 효율을 173% 올려주는 활용 교육','보호자 없이 참가 불가']
        native['capacity_raw']=['선착순 25명'];native['capacity_value']=25
        c['nativeConfirmedFacts']['programFacts']=native
        verified=protected_information(c)
        self.assertNotIn('173%',verified)
        self.assertIn('보호자 없이 참가 불가',verified)
        self.assertIn('선착순 25명',verified)
        self.assertIn('진행기간:',verified)
        result,events,_=ClassificationAITests().run_job(c)
        self.assertEqual(result.completed,1)
        self.assertNotIn('173%',events[-1][1]['p_output']['contentKo'])

    def test_reclassified_summary_conflict_stops_before_translation(self):
        from ingest.reclassification_ai import process_reclassified_job
        from ingest.program_ai import ProgramAIAdapter
        from test_reclassification_ai import ID,REV
        c=classified_context('program');c['nativeConfirmedFacts']['programFacts']=context()['facts']
        events=[]
        def rpc(name,args):
            events.append(name)
            return c if name=='claim_reclassified_content_ai' else {'status':'active'}
        for prose in ['진행 일정: 10월 4일, 총 9회','신청기간: 2099-10-02 ~ 2099-10-15']:
            ja=Mock()
            ko=Mock(return_value=('[한 줄 요약]\n합성\n[기간·상태]\n'+prose+'\n[주요 내용]\n합성 활동','success','fake'))
            result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=ID,revision=REV,
                classification_version=1,worker_id='synthetic-worker',summarize_ko=ko,translate_ja=ja)
            self.assertEqual(result.completed,0)
            ja.assert_not_called()
        self.assertNotIn('finish_reclassified_content_ai',events)


if __name__ == '__main__':
    unittest.main()
