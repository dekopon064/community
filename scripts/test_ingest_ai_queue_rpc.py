"""AI-only enqueue/revision RPC wrapper tests. 실제 Supabase를 쓰지 않는다."""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from typing import Any

from ingest.ai_queue_rpc import (
    ENQUEUE_PARAM_NAMES,
    ENQUEUE_RPC_NAME,
    PRECHECK_PARAM_NAMES,
    PRECHECK_RPC_NAME,
    enqueue_curation_candidate,
    is_latest_source_revision,
    parse_enqueue_result,
    parse_precheck_result,
)
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout


class FakeRpc:
    def __init__(self, data: Any = None, error: BaseException | None = None) -> None:
        self.data = data
        self.error = error
        self.names: list[str] = []
        self.params: list[dict[str, Any]] = []

    def rpc(self, name: str, params: dict[str, Any]) -> FakeRpc:
        self.names.append(name)
        self.params.append(params)
        return self

    def execute(self) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return SimpleNamespace(data=self.data)


def _valid_enqueue_params() -> dict[str, Any]:
    return {
        "p_source": "youthcenter",
        "p_source_item_id": "p1",
        "p_source_revision_hash": "abc",
        "p_slug": "policy-p1",
        "p_title_ko": "제목",
        "p_content_ko": "본문",
        "p_raw_payload": {"plcyNo": "p1"},
        "p_ai_status_ko": "success",
        "p_category": "기타",
        "p_summary_ko": None,
        "p_source_url": "https://example.invalid",
        "p_ai_model": "claude-sonnet-5",
        "p_title_ja": "タイトル",
        "p_content_ja": "本文",
        "p_summary_ja": None,
        "p_ai_status_ja": "success",
    }


class QueueRpcTests(unittest.TestCase):
    def test_malformed_enqueue_is_ambiguous(self) -> None:
        with self.assertRaises(RpcAmbiguous):
            parse_enqueue_result([])
        with self.assertRaises(RpcAmbiguous):
            parse_enqueue_result({"outcome": "inserted"})
        with self.assertRaises(RpcAmbiguous):
            parse_enqueue_result("inserted")

    def test_non_bool_precheck_is_ambiguous(self) -> None:
        with self.assertRaises(RpcAmbiguous):
            parse_precheck_result("true")
        with self.assertRaises(RpcAmbiguous):
            parse_precheck_result(1)

    def test_enqueue_success_and_timeout(self) -> None:
        client = FakeRpc(data={"outcome": "inserted", "candidate_id": "c1"})
        row = enqueue_curation_candidate(client, _valid_enqueue_params())
        self.assertEqual(row["outcome"], "inserted")
        self.assertEqual(client.names, [ENQUEUE_RPC_NAME])
        self.assertEqual(set(client.params[0]), set(ENQUEUE_PARAM_NAMES))
        self.assertNotIn("facts", client.params[0])
        self.assertNotIn("p_facts", client.params[0])

        timed = FakeRpc(error=TimeoutError())
        with self.assertRaises(RpcTimeout):
            enqueue_curation_candidate(timed, _valid_enqueue_params())

    def test_enqueue_ambiguous_does_not_retry(self) -> None:
        client = FakeRpc(error=RuntimeError("socket closed"))
        with self.assertRaises(RpcAmbiguous):
            enqueue_curation_candidate(client, _valid_enqueue_params())
        self.assertEqual(len(client.names), 1)

    def test_facts_in_params_rejected_before_rpc(self) -> None:
        client = FakeRpc(data={"outcome": "inserted", "candidate_id": "c1"})
        params = _valid_enqueue_params()
        params["facts"] = {"audience": "x"}
        with self.assertRaises(RpcAmbiguous):
            enqueue_curation_candidate(client, params)
        self.assertEqual(client.names, [])

    def test_revision_true_false_and_timeout(self) -> None:
        latest = FakeRpc(data=True)
        stale = FakeRpc(data=False)
        self.assertTrue(
            is_latest_source_revision(latest, "youthcenter", "p1", "hash")
        )
        self.assertFalse(
            is_latest_source_revision(stale, "youthcenter", "p1", "hash")
        )
        self.assertEqual(latest.names, [PRECHECK_RPC_NAME])
        self.assertEqual(tuple(latest.params[0]), PRECHECK_PARAM_NAMES)
        timed = FakeRpc(error=TimeoutError())
        with self.assertRaises(RpcTimeout):
            is_latest_source_revision(timed, "youthcenter", "p1", "hash")

    def test_wrapper_does_not_import_fetch_and_save(self) -> None:
        import ingest.ai_queue_rpc as module

        source = inspect.getsource(module)
        self.assertNotIn("import fetch_and_save", source)
        self.assertNotIn("from fetch_and_save", source)
        self.assertNotIn("import google", source)
        self.assertNotIn("from google", source)
        self.assertNotIn("google.genai", source)
        self.assertNotIn("import genai", source)


if __name__ == "__main__":
    unittest.main()
