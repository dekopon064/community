"""Observed source phrases and candidate layout, reconstructed worker inputs.

No original model response, real job, credentials or network client is used.
"""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_seoul_per_session_replay as replay
from ingest.seoul_content import assemble_seoul_body, public_audience
from ingest.seoul_fact_roles import optional_section
from ingest.seoul_condition_display import covered_condition
from ingest.seoul_condition_layout import project_layout
from ingest.seoul_candidate_review import SeoulCandidateReview
from ingest.ai_errors import ValidationError
from ingest.program_scope import extract_program_facts


AGE = '예술에 관심있는 일반 시민 (7세 이상)'
AUDIENCE = '예술에 관심 있는 7세 이상이면 참여할 수 있습니다.'
FIRST = '(1회차) 13시 30분 - 14시 15분'
SECOND = '(2회차) 14시 45분 - 15시 30분'
BOOK = '동반 예약의 경우, 1인당 1예약 필수입니다.'
ABSENT = '사전 취소 없이 불참할 경우, 이후 프로그램 신청이 제한될 수 있습니다.'
CANCEL = '원활한 진행을 위해 불참 시 최소 2일 전까지 예약을 취소해 주시기 바랍니다.'
NOTICE = '구체적인 신청 방법은 공식 안내에서 확인해 주세요.'
CONTACT = '문의: 02-6952-4907(평일 09:00~17:00).'
TITLE = '티코스터 제작, 다도 체험 워크숍'
TABLE = ('| 날짜 | 회차 | 시간 |\n| --- | --- | --- |\n'
         '| 2026년 11월 22일(일) | 1회차 | 13:30~14:15 |\n'
         '| 2026년 11월 22일(일) | 2회차 | 14:45~15:30 |')
ARRIVAL = '예약한 시간까지 반드시 도착해 주세요.\n시작 5분 전까지 도착하지 않으면 담당자가 연락할 수 있습니다.'
EXHIBIT = '연계 작품은 12월 13일까지 서울창포원 일대에서 전시됩니다.'
SUMMARY = ('[한 줄 요약]\n볏짚을 엮어 티코스터를 만들고 다도를 체험합니다.\n'
           '[대상]\n[일정 안내]\n' + TABLE + '\n' + ARRIVAL + '\n'
           '[주요 내용]\n볏짚으로 티코스터를 직접 만듭니다.\n' + EXHIBIT + '\n'
           '[신청 방법]\n' + NOTICE + '\\\n동반 예약도 1인당 1예약이 필수입니다.\n'
           '불참할 경우 최소 2일 전까지 예약을 취소해 주세요.\n'
           '사전 취소 없이 불참하면 이후 프로그램 신청이 제한될 수 있습니다.\n' + CONTACT)
DESCRIPTION = '\n'.join([TITLE, EXHIBIT, '✅ 일시 : 11월 22일(일) *약 45분 소요', FIRST, SECOND,
                          '✅ 장소 : 서울시 도봉구 평화문화진지 공유공방 1', '✅ 대상 : ' + AGE,
                          '4. 주의사항 ○ ' + BOOK, ARRIVAL, CANCEL, ABSENT, CONTACT])
def workshop():
    data, ctx = replay.recorded_case()
    facts = ctx['facts']
    facts.update(target_raw='제한없음(7세 이상)', description=DESCRIPTION,
                 conditions=[FIRST, SECOND, '✅ 대상 : ' + AGE, '4. 주의사항 ○ ' + BOOK, ABSENT],
                 activity_evidence=['서울시 도봉구 평화문화진지 공유공방 1'],
                 residence_evidence=[AGE], application_methods=[],
                 official_url='https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=SYNTHETIC')
    for key, day in [('RCPTBGNDT', '10-27'), ('RCPTENDDT', '11-22'),
                     ('SVCOPNBGNDT', '11-22'), ('SVCOPNENDDT', '11-22')]:
        value = '2026-' + day + 'T00:00:00+09:00'
        facts['periods'][key].update(raw=value, value=value)
    filters = ctx['filterContext']['data']
    for role, key in [('start','RCPTBGNDT'), ('end','RCPTENDDT')]:
        filters['application']['value'][role]['value'] = facts['periods'][key]['value']
    data['summary'] = {'content_ko': SUMMARY, 'facts': dict(audience=AGE, geo_age_income='7세 이상',
                          amount_period_deadline='무료, 11월 22일', how_to_apply='동반 예약도 1인당 1예약')}
    data['translation']['title_ja'] = 'ティーコースター制作・茶道体験'
    return data, ctx


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.getaddrinfo', 'ingest.supabase_store.create_ingest_client'):
            guard = patch(name, side_effect=AssertionError('offline fixture only'))
            guard.start()
            self.addCleanup(guard.stop)
        self.facts = workshop()[1]['facts']

    def test_body(self):
        body = assemble_seoul_body(SUMMARY, self.facts)
        self.assertEqual(optional_section(body, '[대상]').strip(), AUDIENCE)
        self.assertIn(TABLE, body)
        self.assertNotIn(FIRST, body)
        self.assertNotIn(SECOND, body)
        self.assertIn('약 45분', body)
        for value in (NOTICE, '1인당 1예약', '2일 전까지', '제한될 수 있습니다', '공식 예약 페이지'):
            self.assertEqual(body.count(value), 1, value)
            self.assertIn(value, optional_section(body, '[신청 방법]'))
        self.assertIn('2026-10-27 00:00 ~ 2026-11-22 00:00', body)
        self.assertNotIn('진행기간:** 2026-11-22 00:00', body)
        for value in (ARRIVAL, EXHIBIT, '공유공방 1', CONTACT):
            self.assertIn(value, body)
        for value in ('거주 조건 근거', '✅', '4. 주의사항', '○'):
            self.assertNotIn(value, body)
        self.assertEqual(assemble_seoul_body(body, self.facts), body)

    def test_source_extraction(self):
        facts = self.facts
        payload = dict(provider_fields={'USETGTINFO': facts['target_raw'], 'PAYATNM': '무료'},
                       program_text=DESCRIPTION, title=TITLE, dates=facts['periods'],
                       source_url=facts['official_url'], source_status='open')
        extracted = extract_program_facts(SimpleNamespace(normalized_payload=payload, body_usable=True, has_source_url=True))
        self.assertEqual(list(extracted.conditions), facts['conditions'])
        self.assertEqual(list(extracted.residence_evidence), [AGE])

    def test_qualifiers(self):
        f = self.facts
        f['residence_evidence'].append('도봉구 거주자만 신청 가능. 단, 학생증 제출 필수')
        f['residence_evidence'].insert(0, '일반 시민')
        body = assemble_seoul_body(SUMMARY, f)
        self.assertIn(f['residence_evidence'][-1], optional_section(body, '[대상]'))
        self.assertNotIn('대상:** 일반 시민', body)
        self.assertFalse(covered_condition(BOOK + ' 단, 단체 제외.', SUMMARY))
        self.assertFalse(covered_condition(ABSENT, ABSENT.replace('될 수 있습니다', '됩니다')))
        self.assertFalse(covered_condition(CANCEL, CANCEL.replace('2일', '3일')))
        self.assertIn('참가 조건: 보호자 동반 필수', public_audience(f, ['보호자 동반 필수']))
        self.assertEqual(project_layout('공유공방 1', ['공유공방 1']), ['공유공방 1'])
        for changed in (TABLE.replace('14:45', '14:40'), TABLE.replace('2회차', '1회차')):
            with self.assertRaises(ValidationError):
                assemble_seoul_body(SUMMARY.replace(TABLE, changed), f)
            out = assemble_seoul_body(SUMMARY.replace(TABLE, changed), f, review=SeoulCandidateReview(None))
            self.assertIn(SECOND, optional_section(out, '[일정 안내]'))

    def test_existing_rows_and_missing_deadline(self):
        f = self.facts
        old_rows = '\n'.join(['- **대상:** ' + f['target_raw'],
                              *['- **참가 조건:** ' + value for value in f['conditions']],
                              '- **거주 조건 근거:** ' + AGE])
        summary = SUMMARY.replace('[대상]', '[대상]\n' + old_rows)
        summary = summary.replace(old_rows, '예술에 관심 있는 7세 이상 시민이 참여할 수 있습니다.\n' + old_rows)
        summary = summary.replace('불참할 경우 최소 2일 전까지 예약을 취소해 주세요.\n', '')
        link = '[공식 예약 페이지](' + f['official_url'] + ')'
        body = assemble_seoul_body(summary + '\n' + NOTICE + '\n' + link + '\n' + link, f)
        self.assertEqual(optional_section(body, '[대상]'), AUDIENCE)
        method = optional_section(body, '[신청 방법]')
        for value in (NOTICE, link, '2일 전까지', '1인당 1예약', '신청이 제한될 수 있습니다'):
            self.assertEqual(method.count(value), 1, value)

    def test_following_exception_stays_with_deadline(self):
        f = self.facts
        note = '단, 단체는 담당자와 협의해야 합니다.'
        f['description'] = f['description'].replace(CANCEL, CANCEL + '\n' + note)
        body = assemble_seoul_body(SUMMARY, f)
        self.assertIn(CANCEL + ' ' + note, optional_section(body, '[신청 방법]'))

    def test_one_sided_exception_and_conflicting_age(self):
        f = self.facts
        f['conditions'][3] += ' 단, 단체는 사전에 담당자와 협의해야 합니다.'
        f['description'] = f['description'].replace('4. 주의사항 ○ ' + BOOK, f['conditions'][3])
        method = optional_section(assemble_seoul_body(SUMMARY, f), '[신청 방법]')
        self.assertIn('단, 단체는 사전에 담당자와 협의해야 합니다.', method)
        f['target_raw'] = '제한없음(9세 이상)'
        audience = optional_section(assemble_seoul_body(SUMMARY, f), '[대상]')
        self.assertIn('9세 이상', audience)
        self.assertIn('7세 이상', audience)
        self.assertNotIn(AUDIENCE, audience)

    def test_mandatory_accompaniment_is_not_equivalent_to_age_alone(self):
        sentence = '예술에 관심 있는 7세 이상 시민이 참여할 수 있습니다. 단, 보호자 동반이 필수입니다.'
        body = assemble_seoul_body(SUMMARY.replace('[대상]', '[대상]\n' + sentence), self.facts)
        self.assertIn('보호자 동반이 필수입니다.', optional_section(body, '[대상]'))

    def test_midnight_session_does_not_hide_real_midnight(self):
        f = self.facts
        midnight = '(1회차) 0시 00분 - 0시 45분'
        f['description'] = f['description'].replace(FIRST, midnight)
        f['conditions'][0] = midnight
        body = assemble_seoul_body(SUMMARY.replace('13:30~14:15', '00:00~00:45'), f)
        self.assertIn('| 1회차 | 00:00~00:45 |', body)
        self.assertIn('진행기간:** 2026-11-22 00:00 ~ 2026-11-22 00:00', body)
        self.assertIn('2026-10-27 00:00 ~ 2026-11-22 00:00', body)

    def test_fake_worker_routes(self):
        from test_seoul_date_hours_replay import DateHoursReplayTests
        translate = replay.fake_translation
        def japanese(body):
            # Deterministic test responses only. Preserve the link target.
            for ko, ja in ((AUDIENCE, '芸術に興味のある7歳以上の方が参加できます。'),
                           ('동반 예약도 1인당 1예약이 필수입니다.', '同伴者と予約する場合も、1人につき1件の予約が必要です。'),
                           ('불참할 경우 최소 2일 전까지 예약을 취소해 주세요.',
                            '欠席する場合は、少なくとも2日前までに予約をキャンセルしてください。'),
                           ('사전 취소 없이 불참하면 이후 프로그램 신청이 제한될 수 있습니다.',
                            '事前にキャンセルせずに欠席した場合、以後の申込みが制限されることがあります。'),
                           (ARRIVAL, '予約した時間までにお越しください。\n開始5分前までに到着していない場合、担当者から連絡することがあります。'),
                           (EXHIBIT, '関連作品は12月13日までソウルチャンポウォン一帯で展示されます。'),
                           ('볏짚을 엮어 티코스터를 만들고 다도를 체험합니다.', '稲わらでコースターを作り、茶道を体験します。'),
                           ('볏짚으로 티코스터를 직접 만듭니다.', '稲わらを編んでコースターを作ります。'),
                           ('공식 예약 페이지', '公式予約ページ'), ('서울시 도봉구 평화문화진지 공유공방 1','ソウル市トボン区 平和文化陣地 共有工房1'),
                           (NOTICE, '具体的な申込方法は公式案内でご確認ください。'),
                           (CONTACT, '問い合わせ：02-6952-4907（平日09:00~17:00）。'),
                           ('약 45분', '約45分'), ('일자','日付'), ('날짜','日付'),
                           ('시간 |','時間 |'), ('(일)','(日)'), ('소요 시간', '所要時間'), ('오프라인','対面'), ('장소','場所')):
                body = body.replace(ko, ja)
            return translate(body)
        data, ctx = workshop()
        expected = assemble_seoul_body(SUMMARY, self.facts)
        entry = dict(title=TITLE, facts=self.facts, filters=ctx['filterContext']['data'],
                     summary=data['summary'], translation_input_ko=expected,
                     translation={'title_ja': data['translation']['title_ja'], 'content_ja': japanese(expected)})
        immutable = copy.deepcopy(self.facts)
        for classified in (False, True):
            with self.subTest(classified=classified), patch('test_seoul_date_hours_replay.recorded', return_value=[entry]), patch(
                    'test_seoul_date_hours_replay.synthetic_translation', japanese):
                result, calls, outputs, requests = DateHoursReplayTests.replay(self, 0, classified)
                self.assertEqual(result.completed, 1, calls[-1][0])
                output, = outputs
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[1]['input'][0]['content'].split('content_ko:\n',1)[1],output['contentKo'])
                ja = output['contentJa']
                self.assertIn('[対象]\n芸術に興味のある7歳以上の方が参加できます。', ja)
                schedule = ja.split('[日程案内]')[1].split('[主な内容]')[0]
                for value in ('13:30~14:15','14:45~15:30'):
                    self.assertEqual(ja.count(value), 1)
                    self.assertTrue(any(value in row and row.startswith('|') for row in schedule.splitlines()))
                for value in ('1人につき1件の予約','少なくとも2日前まで','以後の申込みが制限されることがあります','公式予約ページ'):
                    self.assertEqual(ja.count(value), 1, value)
                    self.assertIn(value, ja.split('[申請方法]')[1])
                self.assertEqual(ja.count('約45分'), 1)
                self.assertEqual(output['contentKo'], assemble_seoul_body(SUMMARY, self.facts))
                self.assertEqual(sum(name.startswith('finish_') for name, _ in calls), 1)
        self.assertEqual(self.facts, immutable)
