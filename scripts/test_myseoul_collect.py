"""Internal list-reader contract and synthetic detail HTML; no live reads."""
import contextlib
import io
import json
import unittest
from unittest.mock import Mock
from ingest.http_client import HttpClient
from ingest.myseoul_collect import HTTP_LIMIT, ListPage, collect_myseoul, list_entries
from test_myseoul_program import detail, url, Response
from ingest.connectors.myseoul_program import detail_identity
import run_myseoul_collect as cli


def item(n, status="신청중"):
    return {"url": url(program=f"{n:032X}"), "status": status}


def key(n):
    c,p,_,_=detail_identity(item(n)["url"])
    return c+":"+p


class FakeRPC:
    def __init__(self):
        self.pending={};self.sources=set();self.run=0;self.calls=[];self.observed=[]

    def __call__(self,name,args):
        self.calls.append((name,args))
        if name=="start_ingest_run":
            self.run+=1;self.selected=[];self.pages=0;self.new=0;self.known=0;self.failed=0;self.processed=0
            return [{"run_id":str(self.run),"skipped":False}]
        if name=="discover_myseoul_list_page":
            entries=args["p_entries"];count=0;self.pages+=1
            for e in entries:
                exists=e["key"] in self.sources or e["key"] in self.pending
                count+=not exists;self.known+=exists
                if e["key"] not in self.sources:
                    self.pending.setdefault(e["key"],{**e,"run":self.run,"attempts":0})
                    self.pending[e["key"]]["state"]=e["state"]
            self.new+=count
            return {"allNew":count==10}
        if name=="myseoul_pending_details":
            self.selected=sorted([e for k,e in self.pending.items() if k not in self.sources and e["state"]!="closed"],key=lambda e:(e["run"]==self.run,e["attempts"],e["key"]))[:10]
            return [{"key":e["key"],"url":e["url"]} for e in self.selected]
        if name=="observe_myseoul_program":
            p=args["p_items"][0];self.sources.add(p["external_key"]);self.observed.append(p["external_key"])
            return [{"revision":p["revision_hash"]}]
        if name=="record_myseoul_detail_attempt":
            e=self.pending[args["p_key"]];e["attempts"]+=1
            if args["p_outcome"]=="detail_failed":self.failed+=1
            else:self.processed+=1
            return {"outcome":args["p_outcome"]}
        if name=="finish_myseoul_list_collection":
            remaining=sum(k not in self.sources and e["state"]!="closed" for k,e in self.pending.items())
            return {"status":"failed" if args["p_failed"] else "incomplete" if self.failed or remaining else "complete",
                    "summary":{"coverage":"program_list_first_two_pages","source_complete":False,"new":self.new,"known":self.known,"processed":self.processed,"failed":self.failed,"pending_remaining":remaining}}
        raise AssertionError("unexpected recheck/claim/provider RPC")


def run(pages,rpc=None,fail_keys=()):
    rpc=rpc or FakeRPC();calls=[]
    def transport(target,**kwargs):
        calls.append(target)
        if isinstance(target,int):return pages[target]
        c,p,_,_=detail_identity(target)
        if c+":"+p in fail_keys:raise RuntimeError("PRIVATE_SENTINEL")
        return Response(detail())
    http=HttpClient(budget=HTTP_LIMIT,max_attempts=1,transport=transport)
    def reader(client,page,size):
        if size!=10 or client.request_count>=client.budget:raise AssertionError("reader budget")
        client.request_count+=1
        result=client.transport(page)
        if isinstance(result,Exception):raise result
        return result
    return collect_myseoul(http,rpc,read_page=reader),rpc,calls


class CollectionTests(unittest.TestCase):
    def test_all_new_reads_two_pages_and_caps_ten_details(self):
        result,rpc,calls=run({1:ListPage(1,30,[item(n) for n in range(1,11)],True),2:ListPage(2,30,[item(n) for n in range(11,21)],True)})
        self.assertEqual(calls[:2],[1,2]);self.assertNotIn(3,calls)
        self.assertEqual(len(calls),12);self.assertEqual(len(rpc.observed),10)
        self.assertEqual(result["summary"]["pending_remaining"],10)
        self.assertFalse(result["summary"]["source_complete"])

    def test_carried_ids_processed_without_rediscovery_and_before_new(self):
        _,rpc,_=run({1:ListPage(1,20,[item(n) for n in range(1,11)],True),2:ListPage(2,20,[item(n) for n in range(11,21)],True)})
        before=len(rpc.observed)
        result,_,calls=run({1:ListPage(1,10,[item(1)]+[item(n) for n in range(31,40)],True)},rpc)
        self.assertEqual(rpc.observed[before:],[key(n) for n in range(11,21)])
        self.assertEqual(len(calls),11);self.assertEqual(result["summary"]["pending_remaining"],9)

    def test_three_known_does_not_skip_remaining_ids(self):
        rpc=FakeRPC();rpc.sources.update(key(n) for n in (1,2,3))
        result,rpc,calls=run({1:ListPage(1,10,[item(n) for n in range(1,11)],True)},rpc)
        self.assertEqual(result["summary"]["new"],7)
        self.assertEqual(calls[0],1);self.assertNotIn(2,calls)
        self.assertEqual(len(set(rpc.observed)),7)

    def test_short_first_and_empty_are_valid_no_second(self):
        for total in (0,3):
            result,_,calls=run({1:ListPage(1,total,[item(n) for n in range(1,total+1)],True)})
            self.assertNotIn(2,calls);self.assertEqual(result["status"],"complete")

    def test_all_existing_no_detail_and_pending_counts_as_known(self):
        rpc=FakeRPC();rpc.sources.update(key(n) for n in range(1,11))
        result,_,calls=run({1:ListPage(1,62,[item(n) for n in range(1,11)],True)},rpc)
        self.assertEqual(calls,[1]);self.assertEqual(result["summary"]["processed"],0)
        rpc=FakeRPC();rpc.pending[key(1)]={**list_entries(ListPage(1,1,[item(1)],True),1)[0],"run":0,"attempts":0}
        result,_,calls=run({1:ListPage(1,62,[item(n) for n in range(1,11)],True)},rpc)
        self.assertNotIn(2,calls);self.assertEqual(result["summary"]["known"],1)

    def test_clear_closed_skipped_unknown_not_assumed_closed(self):
        result,rpc,calls=run({1:ListPage(1,3,[item(1,"신청종료"),item(2,"."),item(3,"신청중 / 마감 확인 필요")],True)})
        self.assertEqual(rpc.observed,[key(2),key(3)]);self.assertEqual(len(calls),3)

    def test_failures_count_in_ten_and_no_same_run_retry(self):
        result,rpc,calls=run({1:ListPage(1,20,[item(n) for n in range(1,11)],True),2:ListPage(2,20,[item(n) for n in range(11,21)],True)},fail_keys=(key(1),))
        self.assertEqual(len(calls),12);self.assertEqual(result["summary"]["failed"],1)
        self.assertEqual(len(set(calls)),12);self.assertEqual(result["summary"]["pending_remaining"],11)

    def test_incomplete_first_not_short_success(self):
        for page in (ListPage(1,20,[item(1)],True),ListPage(1,0,[],False),ListPage(1,1,[item(1),item(1)],True)):
            with self.assertRaisesRegex(RuntimeError,"^myseoul_collection_failed$"):run({1:page})

    def test_incomplete_second_preserves_first_discovery(self):
        rpc=FakeRPC()
        with self.assertRaises(RuntimeError):run({1:ListPage(1,20,[item(n) for n in range(1,11)],True),2:ListPage(2,20,[],False)},rpc)
        self.assertEqual(len(rpc.pending),10);self.assertEqual(len(rpc.observed),0)

    def test_changed_total_or_overlapping_second_is_failure(self):
        for second in (ListPage(2,21,[item(n) for n in range(11,21)],True),ListPage(2,20,[item(n) for n in range(10,20)],True)):
            with self.assertRaises(RuntimeError):run({1:ListPage(1,20,[item(n) for n in range(1,11)],True),2:second})

    def test_identity_url_rejected_before_observation(self):
        for href in ("https://example.invalid/foo",item(1)["url"]+"&actor=secret"):
            with self.assertRaises(RuntimeError):run({1:ListPage(1,1,[{"url":href,"status":"신청중"}],True)})

    def test_unknown_write_not_replayed_and_secret_not_exposed(self):
        rpc=FakeRPC()
        def wrapped(name,args):
            if name=="observe_myseoul_program":raise RuntimeError("PRIVATE_SENTINEL")
            return rpc(name,args)
        with self.assertRaisesRegex(RuntimeError,"^myseoul_collection_failed$") as caught:run({1:ListPage(1,1,[item(1)],True)},wrapped)
        self.assertNotIn("PRIVATE_SENTINEL",str(caught.exception));self.assertEqual(len(rpc.pending),1)

    def test_disabled_zero_requests(self):
        reader=Mock();http=HttpClient(budget=12,max_attempts=1,transport=Mock())
        result=collect_myseoul(http,Mock(return_value=[{"skipped":True,"skip_reason":"source_disabled"}]),read_page=reader)
        self.assertEqual(result["requests"],0);reader.assert_not_called()

    def test_default_reader_disabled_source_skips_before_http(self):
        rpc=Mock();transport=Mock()
        rpc.return_value=[{"skipped":True,"skip_reason":"source_disabled"}]
        self.assertEqual(collect_myseoul(HttpClient(budget=12,max_attempts=1,transport=transport),rpc)["requests"],0)
        transport.assert_not_called()

    def test_reader_cannot_silently_exceed_page_request_budget(self):
        rpc=FakeRPC();http=HttpClient(budget=12,max_attempts=1,transport=Mock())
        def reader(client,page,size):
            client.request_count+=2
            return ListPage(1,0,[],True)
        with self.assertRaisesRegex(RuntimeError,"^myseoul_collection_failed$"):
            collect_myseoul(http,rpc,read_page=reader)
        self.assertFalse(any(name=="discover_myseoul_list_page" for name,_ in rpc.calls))

    def test_cli_default_manifest_and_execute_callback(self):
        out=io.StringIO();callback=Mock()
        with contextlib.redirect_stdout(out):self.assertEqual(cli.main(["--project-ref","abcdefghijklmnopqrst"],execute=callback),0)
        data=json.loads(out.getvalue());self.assertEqual(data["details_max"],10);self.assertEqual(data["recheck_slots"],0)
        self.assertTrue(data["public_list_reader_ready"]);callback.assert_not_called()
        callback.return_value={"status":"complete","requests":0}
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cli.main(["--project-ref","abcdefghijklmnopqrst","--execute"],execute=callback),0)
        callback.assert_called_once()


if __name__=="__main__":unittest.main()
