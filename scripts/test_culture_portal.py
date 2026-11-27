"""Fake HTTP/RPC only; public sample files are replayed, never refetched."""
import copy
import json
import socket
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ingest.connectors.seoul_culture_portal import *
from ingest.culture_portal_collect import collect_culture_portal, HTTP_LIMIT
from ingest.http_client import HttpClient, HttpRequestFailed, HttpStatusError, ResponseTooLarge

FIXTURES=Path(__file__).parent/'fixtures/culture_portal'
NOW=date(2026,11,12)
URL=BASE+DETAIL+'?cultcode=160138&menuNo=200010'
RUN='00000000-0000-4000-8000-000000000001'


def html(*,body='전통 공예 체험과 공연을 진행합니다. 사전 예약 후 참여하세요.',fee='5,000원',hours='11:00~19:30',alt='',audience='누구나',category='축제-문화/예술',key='160138'):
    from html import escape
    values={'장소':'서울 구로구 잔디광장','기간':'2026-11-14 ~ 2026-11-15','시간':hours,'대상':audience,'요금':fee}
    pairs=''.join(f'<li><div class="type-th"><span>{k}</span></div><div class="type-td"><span>{escape(v)}</span></div></li>' for k,v in values.items())
    return f'<div id="print"><div class="event-title"><p class="type">{category}</p><h2>합성 문화 행사 {key}</h2></div><div class="type-box"><ul>{pairs}</ul></div><section><h3>상세보기</h3><div class="culture-content"><p>{body}</p><img alt="{escape(alt)}" src="/poster.png"></div></section><div>주변관광지 무료 24시간 지역 행사</div></div>'


def event(**kw):return parse_detail(html(**kw),URL)


class Response:
    def __init__(self,body,status=200,kind='text/html'):
        self.body=body.encode() if isinstance(body,str) else body
        self.status_code=status;self.headers={'Content-Type':kind};self.closed=False
    def iter_content(self,chunk_size):yield self.body
    def close(self):self.closed=True


class Fake:
    def __init__(self,keys=('160138',),*,fail=None,status=200):self.calls=[];self.http_calls=[];self.keys=keys;self.fail=fail;self.status=status
    def send(self,url,**kw):
        self.http_calls.append((url,kw))
        if url.endswith(LIST_JSON):
            page=int(kw['data']['pageIndex'])
            rows=[dict(cultcode=int(k),subjcodeGroup='FESTIVAL',strtdate='2026-11-14',endDate='2026-11-15') for k in self.keys[(page-1)*10:page*10]]
            return Response(json.dumps(dict(resultList=rows,pageQueryString=urlencode(kw['data']))),kind='application/json')
        return Response(html(key=parse_qs(urlsplit(url).query)['cultcode'][0]),status=self.status)
    def rpc(self,name,args):
        self.calls.append((name,copy.deepcopy(args)))
        if name==self.fail:return None
        if name=='culture_portal_collection_contract':return dict(contract=CONTRACT,mode='review_only')
        if name=='start_ingest_run':return [dict(run_id=RUN,skipped=False)]
        if name=='observe_culture_portal_event':return dict(outcome='new_review',revision=args['p_event']['revision_hash'],matches=[],reviewQueued=True)
        if name=='record_culture_portal_fetch_failure':return 'recorded'
        if name=='finish_ingest_run':return [dict(status=args['p_status'])]
        raise AssertionError('unapproved RPC '+name)
    def run(self):return collect_culture_portal(HttpClient(budget=HTTP_LIMIT,max_attempts=1,transport=self.send),self.rpc,today=NOW)


class PortalTests(unittest.TestCase):
    def setUp(self):
        deny=patch.object(socket.socket,'connect',side_effect=AssertionError('real network forbidden'));deny.start();self.addCleanup(deny.stop)
    def test_official_saved_detail(self):
        result=parse_detail((FIXTURES/'official-detail-160138.html').read_text(encoding='utf8'),URL)
        self.assertEqual(result['title'],'2026 복작복작 오늘전통축제')
        self.assertIn('공연과 체험',result['description'])
        self.assertNotIn('주변관광지',result['description'])
        self.assertEqual(next(e['value'] for e in result['evidence'] if e['field']=='fee'),'무료')
        self.assertEqual(assess(result)['scope'],'culture_experience')
    def test_real_dynamic_html_is_not_empty_success(self):
        with self.assertRaises(ValueError):parse_list((FIXTURES/'official-list.html').read_text(encoding='utf8'))
    def test_saved_json_query_and_categories(self):
        raw=(FIXTURES/'official-list.json').read_text(encoding='utf8')
        http=HttpClient(budget=22,max_attempts=1,transport=lambda *a,**k:Response(raw,kind='application/json'))
        rows=read_list(http,1,NOW,date(2026,12,13))
        self.assertEqual(len(rows),10);self.assertIn(URL,rows)
    def test_wrong_scope_page_or_nonfestival_rejected(self):
        for change in ('scope','page','category'):
            f=Fake();original=f.send
            def send(url,**kw):
                r=original(url,**kw);d=json.loads(r.body)
                if change=='scope':d['pageQueryString']=d['pageQueryString'].replace('FESTIVAL','SHOW')
                elif change=='page':d['pageQueryString']=d['pageQueryString'].replace('pageIndex=1','pageIndex=2')
                else:d['resultList'][0]['subjcodeGroup']='SHOW'
                return Response(json.dumps(d),kind='application/json')
            f.send=send
            self.assertEqual(f.run()['status'],'state_unknown')
            self.assertFalse(any(n=='observe_culture_portal_event' for n,a in f.calls))
    def test_paid_and_free_both_cultural(self):
        for fee in ('무료','5,000원','프로그램별 상이'):
            self.assertEqual(assess(event(fee=fee))['scope'],'culture_experience')
    def test_title_only_does_not_include(self):
        self.assertEqual(assess(event(body='세부 정보를 확인하세요.'))['scope'],'unconfirmed')
    def test_facility_only_explicit_exclusion(self):
        self.assertEqual(assess(event(body='상설 시설 이용 안내. 특별 프로그램은 없습니다.'))['scope'],'out_of_scope')
    def test_botanic_cultural_program_not_excluded_by_place(self):
        self.assertEqual(assess(event(body='식물원 야간 음악 공연과 문화 체험입니다. 사전 예약 필요.'))['scope'],'culture_experience')
    def test_free_does_not_mean_no_booking(self):
        r=assess(event(body='문화 공연과 체험을 진행합니다.',fee='무료'))
        self.assertIn('portal_booking_unknown',r['reasons'])
    def test_dorim_hours_conflict_keeps_both_values(self):
        r=assess(event(alt='운영 시간 11:00~19:00'))
        issue=next(i for i in r['issues'] if i['code']=='portal_information_conflict')
        self.assertEqual(issue['field'],'hours');self.assertIn('11:00~19:30',issue['evidence']);self.assertIn('운영 시간 11:00~19:00',issue['evidence'])
    def test_tourist_not_inferred_to_resident(self):
        self.assertIn('portal_eligibility_unknown',assess(event(audience='방한 외국인 관광객'))['reasons'])
    def test_subprograms_are_not_flattened(self):
        r=assess(event(body='전통 체험. 프로그램별 사전 예약 및 대상 상이. 어린이 공예와 성인 강연.'))
        self.assertIn('portal_program_conditions',r['reasons']);self.assertEqual(r['ai_status'],'blocked')
    def test_missing_fields_review_not_error(self):
        r=assess(parse_detail(html().replace('<span>5,000원</span>',''),URL))
        self.assertTrue(any(i['field']=='fee' for i in r['issues']))
    def test_alts_are_unverified_and_nearby_is_excluded(self):
        e=event(alt='무료 사전 예약')
        self.assertEqual(e['evidence'][-1]['origin'],'image_alt_unverified')
        self.assertNotIn('24시간',json.dumps(e,ensure_ascii=False))
    def test_revision_changes_with_conditions_not_layout(self):
        self.assertEqual(parse_detail(html(),URL)['revision_hash'],parse_detail(html().replace('<p>','<p class="style">'),URL)['revision_hash'])
        self.assertNotEqual(event(fee='무료')['revision_hash'],event()['revision_hash'])
    def test_reservation_link_is_not_assumed_same_whole_festival(self):
        e=event(body='문화 행사 체험 <a href="https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=S260923112047091255">공예 프로그램 예약</a>')
        self.assertEqual(e['reservation_links'][0]['key'],'S260923112047091255')
    def test_url_allowlist(self):
        for url in ('http://culture.seoul.go.kr'+DETAIL+'?cultcode=1',BASE+DETAIL+'?cultcode=1&cultcode=2','https://127.0.0.1/a',BASE+DETAIL+'?cultcode=1&token=secret'):
            with self.assertRaises(ValueError):detail_identity(url)
    def test_http_redirect_size_and_mime(self):
        for response,exception in [(Response('',302),HttpStatusError),(Response('',kind='application/pdf'),HttpRequestFailed),(Response(b'x'*1000001),ResponseTooLarge)]:
            with self.assertRaises(exception):read_html(HttpClient(budget=22,max_attempts=1,transport=lambda *a,**kw:response),URL)
            self.assertTrue(response.closed)
    def test_no_retry_settings(self):
        with self.assertRaises(ValueError):collect_culture_portal(HttpClient(budget=22,max_attempts=2),Fake().rpc)
    def test_regular_flow_review_only(self):
        f=Fake();r=f.run();self.assertEqual(r['status'],'complete');self.assertEqual(r['new_saved'],1)
        self.assertEqual(r['requests'],3);self.assertTrue(r['source_complete'])
        self.assertFalse(any('ai' in n or 'candidate' in n for n,a in f.calls))
        self.assertFalse(f.http_calls[0][1]['allow_redirects'])
    def test_item_404_recorded_then_next(self):
        f=Fake(('160138','160151'),status=404);r=f.run()
        self.assertEqual(r['failed'],2);self.assertEqual(r['status'],'incomplete')
    def test_auth_usage_or_common_http_stop(self):
        for status in (401,403,429,500):
            f=Fake(('160138','160151'),status=status);r=f.run();self.assertEqual(r['status'],'state_unknown');self.assertEqual(len(f.http_calls),3)
    def test_unknown_write_stops_and_never_replays(self):
        for failure in ('observe_culture_portal_event','record_culture_portal_fetch_failure'):
            f=Fake(('160138','160151'),fail=failure,status=404 if 'failure' in failure else 200);r=f.run()
            self.assertEqual(r['status'],'state_unknown');self.assertEqual(len(f.http_calls),3)
            self.assertEqual(sum(n==failure for n,a in f.calls),1)
    def test_contract_missing_no_http(self):
        f=Fake(fail='culture_portal_collection_contract')
        with self.assertRaises(RuntimeError):f.run()
        self.assertEqual(f.http_calls,[])
    def test_all_pages_process_twenty_twenty_remainder(self):
        f=Fake(tuple(str(160000+i) for i in range(47)));r=f.run()
        self.assertEqual(r['selected'],47);self.assertEqual(r['requests'],57)
        self.assertEqual([c['selected'] for c in r['chunks']],[20,20,7])
        self.assertTrue(all(c['detail_requests']<=20 for c in r['chunks']))
        self.assertTrue(r['source_complete']);self.assertEqual(r['unprocessed'],0)
        self.assertEqual(sum(n=='start_ingest_run' for n,a in f.calls),3)
        self.assertEqual(sum(n=='finish_ingest_run' for n,a in f.calls),3)
    def test_changed_held_item_is_not_reported_as_queued(self):
        f=Fake();original=f.rpc
        def rpc(n,a):
            r=original(n,a)
            if n=='observe_culture_portal_event':r.update(outcome='change_review',reviewQueued=False)
            return r
        f.rpc=rpc;r=f.run();self.assertEqual(r['changes_recorded'],1);self.assertEqual(r['review_waiting'],0)
    def test_unknown_finish_stops(self):
        f=Fake(fail='finish_ingest_run');r=f.run()
        self.assertEqual(r['status'],'state_unknown');self.assertEqual(r['new_saved'],1)
    def test_disabled_source_no_http(self):
        f=Fake();orig=f.rpc;f.rpc=lambda n,a:[dict(skipped=True,skip_reason='source_disabled')] if n=='start_ingest_run' else orig(n,a)
        self.assertEqual(f.run()['status'],'skipped');self.assertEqual(f.http_calls,[])
    def test_collection_catalog_does_not_expand_ai_sources(self):
        from ingest.pc_worker_sources import SOURCES,collection_sources
        self.assertIn(SOURCE,collection_sources('all'));self.assertEqual(SOURCES[SOURCE]['ai'],'review_only')
    def test_cli_default_does_not_load_credentials(self):
        import run_culture_portal_collect
        self.assertEqual(run_culture_portal_collect.main(['--project-ref','a'*20],execute=lambda x:self.fail('must not execute')),0)

    def test_dates_include_long_running_today_and_distant_future(self):
        f=Fake(tuple(str(160000+i) for i in range(6)));original=f.send
        dates=[('2026-01-01','2026-11-11'),('2026-01-01','2026-11-12'),
               ('2026-01-01','2027-01-01'),('2027-12-18','2028-02-09'),
               ('2026-11-14',None),('2027-01-01','2026-01-01')]
        def send(url,**kw):
            response=original(url,**kw)
            if url.endswith(LIST_JSON):
                self.assertEqual(kw['data']['edate'],'9999-12-31')
                self.assertEqual(kw['data']['sdate'],'2026-11-12')
                data=json.loads(response.body)
                for row,(start,end) in zip(data['resultList'],dates):row.update(strtdate=start,endDate=end)
                return Response(json.dumps(data),kind='application/json')
            return response
        f.send=send;r=f.run()
        self.assertEqual(r['ended_skipped'],1);self.assertEqual(r['selected'],5)
        self.assertNotIn('160000',[x['key'] for x in r['items']]);self.assertTrue(r['source_complete'])

    def test_zero_and_exact_twenty_boundaries(self):
        for size,sizes,pages in ((0,[],[1,1]),(20,[20],[1,2,3,1,2,3]),(40,[20,20],[1,2,3,4,5,1,2,3,4,5])):
            f=Fake(tuple(str(160000+i) for i in range(size)));r=f.run()
            self.assertEqual([c['selected'] for c in r['chunks']],sizes)
            self.assertEqual([int(k['data']['pageIndex']) for u,k in f.http_calls if u.endswith(LIST_JSON)],pages)
            self.assertTrue(r['source_complete']);self.assertEqual(r['processed_items'],size)

    def test_changed_or_repeated_list_stops_before_observations(self):
        for mode in ('shift','repeat'):
            f=Fake(tuple(str(160000+i) for i in range(21)));original=f.send;list_calls=[]
            def send(url,**kw):
                response=original(url,**kw)
                if not url.endswith(LIST_JSON):return response
                list_calls.append(1);data=json.loads(response.body)
                if mode=='repeat' and len(list_calls)==2:data['resultList'][0]['cultcode']=160000
                if mode=='shift' and len(list_calls)==4:data['resultList'][0]['cultcode']=170000
                return Response(json.dumps(data),kind='application/json')
            f.send=send;r=f.run()
            self.assertEqual(r['stop_reason'],'portal_list_changed');self.assertFalse(r['source_complete'])
            self.assertFalse(any(n=='observe_culture_portal_event' for n,a in f.calls))

    def test_frozen_membership_does_not_add_later_arrival(self):
        f=Fake(tuple(str(160000+i) for i in range(21)));original=f.rpc
        def rpc(n,a):
            result=original(n,a)
            if n=='observe_culture_portal_event':f.keys=(*f.keys,'179999')
            return result
        f.rpc=rpc;r=f.run()
        self.assertEqual(r['processed_items'],21);self.assertEqual(r['chunks_done'],2)
        self.assertNotIn('179999',[x['key'] for x in r['items']])

    def test_individual_failure_continues_across_batch_boundary(self):
        f=Fake(tuple(str(160000+i) for i in range(41)));original=f.send
        def send(url,**kw):
            response=original(url,**kw)
            if 'cultcode=160019&' in url:response.status_code=404
            return response
        f.send=send;r=f.run()
        self.assertEqual(r['processed_items'],41);self.assertEqual(r['chunks_done'],3)
        self.assertEqual(r['failed'],1);self.assertEqual(r['new_saved'],40)
        self.assertEqual(r['status'],'incomplete');self.assertFalse(r['source_complete'])
        self.assertEqual([a['p_status'] for n,a in f.calls if n=='finish_ingest_run'],['incomplete','complete','complete'])

    def test_common_error_in_next_batch_preserves_confirmed_counts(self):
        f=Fake(tuple(str(160000+i) for i in range(41)));original=f.send
        def send(url,**kw):
            response=original(url,**kw)
            if 'cultcode=160020&' in url:response.status_code=429
            return response
        f.send=send;r=f.run()
        self.assertEqual(r['new_saved'],20);self.assertEqual(r['chunks_done'],1)
        self.assertEqual(r['unprocessed'],21);self.assertEqual(r['stop_reason'],'http_429')
        self.assertFalse(r['source_complete'])

    def test_finish_unknown_does_not_acquire_next_batch(self):
        f=Fake(tuple(str(160000+i) for i in range(41)),fail='finish_ingest_run');r=f.run()
        self.assertEqual(r['new_saved'],20);self.assertEqual(r['chunks_done'],0)
        self.assertEqual(r['stop_reason'],'portal_finish_unknown')
        self.assertEqual(sum(n=='start_ingest_run' for n,a in f.calls),1)

    def test_second_batch_ambiguous_write_never_replays_or_finishes(self):
        f=Fake(tuple(str(160000+i) for i in range(43)));original=f.rpc
        def rpc(n,a):
            result=original(n,a)
            if n=='observe_culture_portal_event' and a['p_event']['external_key']=='160020':return None
            return result
        f.rpc=rpc;r=f.run()
        self.assertEqual(r['new_saved'],20);self.assertEqual(r['chunks_done'],1)
        self.assertEqual(r['unprocessed'],23);self.assertEqual(r['stop_reason'],'portal_observation_unknown')
        self.assertEqual(sum(n=='finish_ingest_run' for n,a in f.calls),1)
        self.assertEqual(sum(n=='observe_culture_portal_event' for n,a in f.calls),21)

    def test_bad_page_three_does_not_write_partial_first_twenty(self):
        f=Fake(tuple(str(160000+i) for i in range(43)));original=f.send
        def send(url,**kw):
            result=original(url,**kw)
            if url.endswith(LIST_JSON) and kw['data']['pageIndex']=='3':result.status_code=503
            return result
        f.send=send;r=f.run()
        self.assertEqual(r['stop_reason'],'http_503');self.assertIsNone(r['unprocessed'])
        self.assertFalse(r['snapshot_complete']);self.assertEqual(r['new_saved'],0)
        self.assertFalse(any(n=='observe_culture_portal_event' for n,a in f.calls))

    def test_next_lease_unavailable_is_not_complete(self):
        f=Fake(tuple(str(160000+i) for i in range(41)));original=f.rpc;started=[]
        def rpc(n,a):
            response=original(n,a)
            if n=='start_ingest_run':
                started.append(1)
                if len(started)>1:return [dict(skipped=True,skip_reason='lease_held')]
            return response
        f.rpc=rpc;r=f.run()
        self.assertEqual(r['status'],'incomplete');self.assertEqual(r['unprocessed'],21)
        self.assertEqual(r['chunks_done'],1);self.assertFalse(r['source_complete'])

    def test_safety_and_time_limits_never_claim_complete(self):
        f=Fake(tuple(str(160000+i) for i in range(30)))
        with patch('ingest.culture_portal_collect.MAX_LIST_PAGES',2):r=f.run()
        self.assertEqual(r['stop_reason'],'portal_list_safety_limit');self.assertFalse(r['source_complete'])
        self.assertEqual(r['new_saved'],0)
        f=Fake()
        r=collect_culture_portal(HttpClient(budget=HTTP_LIMIT,max_attempts=1,transport=f.send),f.rpc,today=NOW,clock=iter([0,841]).__next__)
        self.assertEqual(r['stop_reason'],'portal_run_time_limit');self.assertEqual(f.http_calls,[])

    def test_explicit_rerun_skips_confirmed_records(self):
        saved={};f=Fake(tuple(str(160000+i) for i in range(25)));original=f.rpc
        def rpc(n,a):
            response=original(n,a)
            if n=='observe_culture_portal_event':
                e=a['p_event'];identity=(e['external_key'],e['revision_hash'])
                if identity in saved:response.update(outcome='unchanged',reviewQueued=False)
                else:saved[identity]=copy.deepcopy(e)
            return response
        f.rpc=rpc;first=f.run();second=f.run()
        self.assertEqual(first['new_saved'],25);self.assertEqual(second['new_saved'],0)
        self.assertEqual(second['existing_skipped'],25);self.assertEqual(len(saved),25)

    def test_each_batch_finish_precedes_next_start(self):
        f=Fake(tuple(str(160000+i) for i in range(43)));original=f.rpc
        active=False;observations=0;serial=0
        def rpc(n,a):
            nonlocal active,observations,serial
            response=original(n,a)
            if n=='start_ingest_run':
                self.assertFalse(active);active=True;observations=0;serial+=1
                response[0]['run_id']=f'00000000-0000-4000-8000-{serial:012d}'
            if n in ('observe_culture_portal_event','finish_ingest_run'):
                self.assertTrue(active);self.assertEqual(a['p_run_id'],f'00000000-0000-4000-8000-{serial:012d}')
            if n=='observe_culture_portal_event':observations+=1;self.assertLessEqual(observations,20)
            if n=='finish_ingest_run':active=False
            return response
        f.rpc=rpc;r=f.run();self.assertEqual(serial,3);self.assertFalse(active);self.assertTrue(r['source_complete'])


if __name__=='__main__':unittest.main()
