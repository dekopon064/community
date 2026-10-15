"""Synthetic current values, no operating identifiers or credentials."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from ingest.seoul_review_connections import propose_connections, same_period_supported
from ingest.content_filters import field
from plan_seoul_review_connections import plan_rows
from test_seoul_evidence_connections import packets


def detail():
    packet = copy.deepcopy(packets()[0]['item'])
    facts = packet['program_facts']
    facts['missing'] = ['body_period_needs_confirmation']
    facts['conflicts'] = []
    facts['description'] = '문화 공예 체험입니다.\n신청기간: 2026년 9월 28일 ~ 10월 27일'
    facts['period_evidence'] = ['2026년 9월 28일 ~ 10월 27일']
    facts['periods']['RCPTBGNDT']['value'] = '2026-09-28T10:00:00+09:00'
    facts['periods']['RCPTENDDT']['value'] = '2026-10-27T13:00:00+09:00'
    return {'id': '30000000-0000-4000-8000-000000000001', 'revision': 'a'*64, 'version': 'b'*64,
            'factsVersion': 3, 'status': 'open', 'aiStatus': 'blocked',
            'facts': facts, 'result': {'reasons': ['body_period_needs_confirmation']},
            'editableFields': ['periods', 'delivery_mode', 'activity_region', 'content_kind'],
            'filterInfo': {'data': packet['filterFacts']['data'], 'filterVersion': 5, 'origins': {}}}


def ui_detail():
    d = detail()
    d.update(schema='program-scope-v1-local', profile='program_capital_v1_local',
             source={'name':'seoul_reservation','title':'합성 기간 재확인','url':d['facts']['official_url'],'body':d['facts']['description']},
             observedFacts=copy.deepcopy(d['facts']),history=[])
    d['result'].update(decision='review_required',disposition='observe_only')
    d['filterInfo'].update(schema='content-filters-v1',revision=d['revision'],missing=['location'],origins={})
    return d


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start(); self.addCleanup(guard.stop)

    def test_supported_date_roles_and_same_time_precision(self):
        d = detail(); before = copy.deepcopy(d)
        self.assertTrue(same_period_supported(d['facts']))
        self.assertEqual(d, before)
        d['facts']['description'] += ' 13:00'
        d['facts']['period_evidence'][0] += ' 13:00'
        self.assertTrue(same_period_supported(d['facts']))
        d['facts']['periods']['RCPTENDDT']['value'] = '2026-10-27T14:00:00+09:00'
        self.assertFalse(same_period_supported(d['facts']))

    def test_real_conflicts_missing_year_roles_and_stale_evidence_block(self):
        for replace in ('신청기간: 2026년 9월 29일 ~ 10월 27일',
                        '운영기간: 2026년 9월 28일 ~ 10월 27일',
                        '신청기간: 9월 28일 ~ 10월 27일',
                        '신청기간: 2026년 9월 28일(금) ~ 10월 27일',
                        '신청기간: 2026년 2월 30일 ~ 10월 27일',
                        '신청기간: 2026년 9월 28일 ~ 10월 27일 또는 11월 1일'):
            d = detail(); d['facts']['description'] = replace
            with self.subTest(replace=replace): self.assertFalse(same_period_supported(d['facts']))
        for conflict in ('body_api_period_conflict','period_order_conflict','date_weekday_conflict'):
            d = detail(); d['facts']['conflicts'] = [conflict]
            self.assertFalse(same_period_supported(d['facts']))

    def test_unknowns_only_operator_and_known_values_are_preserved(self):
        d = detail(); d['facts']['description'] = '문화 공예 체험을 진행합니다.\n장소: 서울 도봉구 합성공원'
        for k in ('delivery_mode','activity_region','content_kind'): d['facts'][k] = 'unknown'
        for k in ('delivery','location','topic'): d['filterInfo']['data'][k] = field()
        before = copy.deepcopy(d)
        proposed = propose_connections(d)
        self.assertEqual(proposed['facts_patch']['delivery_mode'], 'offline')
        self.assertEqual(proposed['filters_patch']['topic'], field('culture_experience'))
        self.assertEqual(d, before)
        d['filterInfo']['origins']['topic'] = 'operator'
        self.assertNotIn('topic', propose_connections(d)['filters_patch'])
        self.assertNotIn('delivery_mode', propose_connections(d, operator_fields=['delivery_mode'])['facts_patch'])
        d['filterInfo']['data']['topic'] = field('other')
        self.assertNotIn('topic', propose_connections(d)['filters_patch'])

    def test_meeting_place_does_not_fill_location_or_change_actual_flags(self):
        d = detail(); d['facts']['description'] = '문화 공예 체험을 진행합니다.\n만나는 장소: 서울 도봉구 합성공원'
        d['filterInfo']['data']['location'] = field(); d['facts']['activity_evidence'] = []
        self.assertNotIn('location', propose_connections(d)['filters_patch'])
        self.assertNotIn('missing', propose_connections(d)['facts_patch'])

    def test_deduplicate_and_mismatched_context_never_used(self):
        d = detail(); r = {'id': d['id'], 'detail': d}
        self.assertEqual(plan_rows([r,r])['count'], 1)
        stale = copy.deepcopy(r); stale['detail']['version'] = 'c'*64
        with self.assertRaises(ValueError): plan_rows([r,stale])
        for state in ('claimed','completed'):
            d['aiStatus'] = state
            self.assertEqual(propose_connections(d)['facts_patch'], {})


if __name__ == '__main__':
    import sys
    if '--export-ui' in sys.argv: print(json.dumps(ui_detail(), ensure_ascii=False))
    elif '--export' in sys.argv: print(json.dumps(detail(), ensure_ascii=False))
    else: unittest.main()
