"""Synthetic formatted worker -> injected Pro stream -> fenced fake candidate.

--fixture exports only synthetic source/facts/output for UI integration tests.
No credentials, live authentication, database or provider transports.
"""
import copy
import json
import socket
import sys
import unittest
from unittest.mock import patch

from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
from ingest.ai_claude import SUMMARY_SCHEMA, BODY_FORMAT_RULES, SUMMARY_SYSTEM, MYSEOUL_SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM, translation_system_prompt
from ingest.myseoul_ai import process_myseoul_job
from ingest.program_ai import ProgramAIAdapter
from ingest.rpc_errors import RpcTimeout
from test_myseoul_ai import context, ID, JOB
from test_ingest_ai_chatgpt_plan import verified_session, streamed
from test_ingest_ai_openai import response

SOURCE = '''합성 문서 실습 안내입니다. 실제 기관이나 콘텐츠가 아닙니다.
문서를 작성한 뒤 제출하는 순서로 실습합니다. 마실 물을 준비합니다.
보호자 동반 필수. 선착순 30명.
교육 일정
1회차: 10월 3일 10:00~11:30
2회차: 10월 10일 14:00~15:30
수강료 10,000원, 재료비 2,000원.
'''
KO = '''[한 줄 요약]
문서 작성과 제출을 배우는 합성 실습입니다.

[주요 내용]
문서 작성과 제출을 실습합니다. **보호자 동반 필수**입니다.

| 회차 | 날짜 | 시간 | 활동 |
| --- | --- | --- | --- |
| 1회 | 10월 3일 | 10:00~11:30 | 문서 작성 |
| 2회 | 10월 10일 | 14:00~15:30 | 문서 제출 |

- 준비물: 마실 물

1. 문서를 작성합니다.
2. 작성한 문서를 제출합니다.
'''
JA = '''[要約]
文書の作成と提出を学ぶ合成の実習です。

[対象]
大人と子どもの家族

[日程案内]
- **申請期間:** 2026年10月1日～2026年10月2日
- **実施期間:** 2026年10月3日～2026年10月10日
- **実施日程:** 第1回: 10月3日10時00分～11時30分 / 第2回: 10月10日14時00分～15時30分

[主な内容]
文書の作成と提出を実習します。**保護者同伴が必須**です。

| 回 | 日付 | 時間 | 活動 |
| --- | --- | --- | --- |
| 1回 | 10月3日 | 10時00分～11時30分 | 文書の作成 |
| 2回 | 10月10日 | 14時00分～15時30分 | 文書の提出 |

- 持ち物: 飲料水

1. 文書を作成します。
2. 作成した文書を提出します。

- **場所:** ソウルの合成教室
- **費用:** 受講料: 10,000ウォン; 材料費: 2,000ウォン
- **募集人数:** 先着30名

[申請方法]
オンライン申請
- **申請リンク:** https://synthetic.invalid/apply?id=1
'''


def synthetic_context():
    c = context()
    c['title'] = '합성 문서 실습 프로그램'
    f = c['facts']
    f.update(description=SOURCE, target='성인과 어린이 가족', conditions=['보호자 동반 필수'],
        age=[], companion=[], language=[], residence='', qualification_note='',
        venue='서울 합성 교육실', capacity_raw=['선착순 30명'], capacity_value=30,
        fees=[{'component':'tuition','evidence':['10,000원']}, {'component':'materials','evidence':['2,000원']}],
        session_evidence=['1회차: 10월 3일 10:00~11:30', '2회차: 10월 10일 14:00~15:30'],
        meeting_evidence=[], application_methods=['온라인 신청'],
        application_links=['https://synthetic.invalid/apply?id=1'],
        official_url='https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?cntr_no='+'A'*32+'&prgrm_no='+'B'*32+'&lang=ko')
    for key, values in (('application', ('2026-10-01','2026-10-02')), ('operation', ('2026-10-03','2026-10-10'))):
        f['periods'][key] = [{'status':'ok', 'endpoints':[{'value':v,'precision':'day'} for v in values]}]
    c['observedFacts'] = copy.deepcopy(f)
    c['observedFacts']['description'] = ''
    return c


def run_fixture(*, ko=KO, ja=JA, unknown=False, fixture_context=None, summary_facts=None):
    c = copy.deepcopy(fixture_context) if fixture_context is not None else synthetic_context()
    payload = {'content_ko':ko,'facts':summary_facts if summary_facts is not None else
        {k:'' for k in SUMMARY_SCHEMA['properties']['facts']['required']}}
    client = streamed([response(json.dumps(payload, ensure_ascii=False)),
        response(json.dumps({'title_ja':'合成文書実習プログラム','content_ja':ja}, ensure_ascii=False))])
    calls, candidates = [], []
    def rpc(name, args):
        calls.append((name, copy.deepcopy(args)))
        if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
        if name == 'admin_myseoul_program_detail':
            return {'id':ID,'revision':c['revision'],'schema':c['schema'],'profile':c['profile'],
                'factsVersion':c['factsVersion'],'status':'resolved','aiStatus':'claimed',
                'source':{'name':c['source'],'title':c['title'],'url':c['facts']['official_url']},
                'facts':c['facts'],'observedFacts':c['observedFacts'],
                'result':{'scope':'included','quality':'sufficient','public_category':'program',
                    'application':'closed','decision':'in_scope','reasons':[]}}
        if name == 'finish_myseoul_program_ai':
            if unknown: raise RpcTimeout()
            candidates.append(args['p_output'])
            return {'outcome':'inserted','candidateId':JOB}
        if name == 'fail_myseoul_program_ai': return 'failed'
        raise AssertionError(name)
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        adapter = ChatGPTPlanAdapter(client=client, session=verified_session())
        try:
            result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=c['revision'],
                worker_id=c['workerId'], summarize_ko=adapter.summarize_myseoul_ko, translate_ja=adapter.translate_ja)
        finally:
            adapter.close()
    return c, result, calls, client, candidates


class PipelineTests(unittest.TestCase):
    def test_final_formatted_worker_input_and_fake_candidate(self):
        c, result, calls, client, candidates = run_fixture()
        self.assertEqual(result.completed, 1)
        self.assertEqual(len(client.calls), 2)
        output = candidates[0]
        self.assertIn('| 회차 | 날짜 | 시간 | 활동 |', output['contentKo'])
        self.assertIn('- **신청기간:** 2026-10-01 ~ 2026-10-02', output['contentKo'])
        self.assertIn('1. 문서를 작성합니다.', output['contentKo'])
        self.assertEqual(output['summaryKo'], '문서 작성과 제출을 배우는 합성 실습입니다.')
        self.assertEqual(output['contentJa'].strip(), JA.strip())
        self.assertEqual(c, synthetic_context())
        sent = client.calls[1]['input'][0]['content']
        self.assertEqual(sent, f"title_ko: {c['title']}\ncontent_ko:\n{output['contentKo']}")
        for param, key in (('p_revision','revision'),('p_facts_version','factsVersion'),
                           ('p_claimed_at','claimedAt'),('p_lease_until','leaseUntil')):
            self.assertEqual(calls[-1][1][param], c[key])
        self.assertEqual(set(output), {'titleKo','summaryKo','contentKo','titleJa','summaryJa','contentJa','aiModel'})

    def test_table_schedule_conflict_stops_before_translation(self):
        _, result, calls, client, candidates = run_fixture(ko=KO.replace('14:00~15:30', '10:00~11:30'))
        self.assertEqual(result.failed, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(candidates, [])
        self.assertFalse(any(name.startswith('finish_') for name, _ in calls))

    def test_translation_row_swap_and_eligibility_loss_fail_without_retry(self):
        for ja in (JA.replace('14時00分～15時30分 |', '10時00分～11時30分 |'),
                   JA.replace('保護者同伴が必須', '保護者同伴は任意'),
                   JA.replace('受講料: 10,000ウォン; 材料費: 2,000ウォン', '受講料: 2,000ウォン; 材料費: 10,000ウォン')):
            with self.subTest(ja=ja):
                _, result, calls, client, candidates = run_fixture(ja=ja)
                self.assertEqual(result.failed, 1)
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(candidates, [])

    def test_unknown_finish_is_not_retried(self):
        _, result, calls, client, candidates = run_fixture(unknown=True)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(sum(name.startswith('finish_') for name, _ in calls), 1)
        self.assertFalse(any(name.startswith('fail_') for name, _ in calls))

    def test_common_rules_load_once_per_prompt_for_all_providers(self):
        for instructions in (SUMMARY_SYSTEM, MYSEOUL_SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM, translation_system_prompt()):
            self.assertEqual(instructions.count(BODY_FORMAT_RULES.strip()), 1)


if __name__ == '__main__':
    if '--fixture' in sys.argv:
        c, result, calls, client, candidates = run_fixture()
        if result.completed != 1:
            raise RuntimeError('synthetic candidate did not complete')
        print(json.dumps({'syntheticOnly':True,'source':SOURCE,'facts':c['facts'],
            'output':candidates[0], 'calls':len(client.calls), 'fence':calls[-1][1]}, ensure_ascii=False))
    else:
        unittest.main()
