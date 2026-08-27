"""fetch_and_save 단위 테스트. 운영 API·Gemini·Supabase에 연결하지 않는다."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import pathlib
import traceback
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
import urllib3.exceptions as urllib3_exceptions

import fetch_and_save as pipeline

YOUTH_API_LEAK_SECRET = "test-youth-secret-do-not-leak"
YOUTH_API_LEAK_PATH_URL = (
    "/go/ythip/getPlcy"
    f"?apiKeyNm={YOUTH_API_LEAK_SECRET}"
    "&pageNum=1&pageSize=5&pageType=1&rtnType=json"
)
YOUTH_API_LEAK_FULL_URL = (
    f"https://www.youthcenter.go.kr{YOUTH_API_LEAK_PATH_URL}"
)


FORBIDDEN_SOURCE_PATTERNS = (
    ".upsert(",
    "on_conflict",
    '.table("curations")',
    ".table('curations')",
    'TABLE_NAME = "curations"',
)


def sample_policy(**overrides: object) -> dict:
    policy = {
        "plcyNo": "2026082700001",
        "plcyNm": "청년 월세 지원",
        "plcyExplnCn": "설명입니다.",
        "plcySprtCn": "월 20만 원을 지원합니다.",
        "aplyUrlAddr": "https://example.go.kr/apply",
        "refUrlAddr1": "https://example.go.kr/ref1",
        "refUrlAddr2": "https://example.go.kr/ref2",
        "plcyTpNm": "주거",
        "lclsfNm": "생활안정",
        "mclsfNm": "주거비",
        "polyBizSecd": "003002001",
        "zipCd": "003002001",
        "rgLcnCd": "003002001",
        "pvsnInstGroupNm": "서울특별시",
        "cnsgNmor": "서울시",
        "mngtMsonNm": "주거정책과",
        "sprvsnInstNm": "서울특별시",
        "operInstNm": "서울주택도시공사",
        "rgtrInstCdNm": "서울특별시",
        "apiKeyNm": "should-not-be-copied",
        "extraField": "drop-me",
        "pageNum": 1,
    }
    policy.update(overrides)
    return policy


class FakeRPC:
    def __init__(self, data=None, error=None):
        self._data = data
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(data=self._data)


class FakeSupabase:
    def __init__(self, data=None, error=None):
        self.calls: list[tuple[str, dict]] = []
        self._data = data
        self._error = error

    def rpc(self, name: str, params: dict):
        self.calls.append((name, params))
        return FakeRPC(self._data, self._error)

    def table(self, name: str):  # pragma: no cover - 직접 쓰기 경로가 있으면 실패
        raise AssertionError(f"table access is forbidden: {name}")


class RawPayloadTests(unittest.TestCase):
    def test_allowlist_has_exactly_nineteen_keys(self) -> None:
        payload = pipeline.copy_raw_payload(sample_policy())
        self.assertEqual(len(pipeline.RAW_PAYLOAD_KEYS), 19)
        self.assertEqual(list(payload), list(pipeline.RAW_PAYLOAD_KEYS))
        self.assertEqual(set(payload), set(pipeline.RAW_PAYLOAD_KEYS))

    def test_api_key_and_arbitrary_fields_are_removed(self) -> None:
        payload = pipeline.copy_raw_payload(sample_policy())
        self.assertNotIn("apiKeyNm", payload)
        self.assertNotIn("extraField", payload)
        self.assertNotIn("pageNum", payload)
        self.assertNotIn("headers", payload)
        self.assertNotIn("params", payload)


class RevisionHashTests(unittest.TestCase):
    def test_hash_is_stable_across_key_order_and_whitespace(self) -> None:
        first = sample_policy()
        second = sample_policy()
        second["plcyNm"] = "  청년   월세 지원  "
        reordered = {key: first[key] for key in reversed(list(first))}
        source_url = pipeline.select_source_url(first)
        self.assertEqual(
            pipeline.compute_source_revision_hash(first, source_url),
            pipeline.compute_source_revision_hash(reordered, source_url),
        )
        self.assertEqual(
            pipeline.compute_source_revision_hash(first, source_url),
            pipeline.compute_source_revision_hash(second, source_url),
        )

    def test_hash_uses_sorted_deterministic_json(self) -> None:
        policy = sample_policy()
        source_url = pipeline.select_source_url(policy)
        expected_payload = {
            key: pipeline.normalize_revision_text(
                source_url if key == "source_url" else policy.get(key)
            )
            for key in pipeline.REVISION_HASH_FIELDS
        }
        expected = hashlib.sha256(
            json.dumps(
                expected_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        actual = pipeline.compute_source_revision_hash(policy, source_url)
        self.assertEqual(actual, expected)
        self.assertRegex(actual, r"^[0-9a-f]{64}$")

    def test_meaningful_value_change_changes_hash(self) -> None:
        base = sample_policy()
        changed = sample_policy(plcyNm="청년 월세 지원 (변경)")
        source_url = pipeline.select_source_url(base)
        self.assertNotEqual(
            pipeline.compute_source_revision_hash(base, source_url),
            pipeline.compute_source_revision_hash(changed, source_url),
        )


class SourceUrlTests(unittest.TestCase):
    def test_prefers_apply_url_then_reference_urls(self) -> None:
        policy = sample_policy()
        self.assertEqual(
            pipeline.select_source_url(policy),
            "https://example.go.kr/apply",
        )
        policy["aplyUrlAddr"] = "링크 없음"
        self.assertEqual(
            pipeline.select_source_url(policy),
            "https://example.go.kr/ref1",
        )
        policy["refUrlAddr1"] = ""
        self.assertEqual(
            pipeline.select_source_url(policy),
            "https://example.go.kr/ref2",
        )

    def test_missing_or_invalid_url_returns_none(self) -> None:
        policy = sample_policy(
            aplyUrlAddr="",
            refUrlAddr1="링크 없음",
            refUrlAddr2="ftp://example.go.kr/file",
        )
        self.assertIsNone(pipeline.select_source_url(policy))
        empty = sample_policy(aplyUrlAddr=None, refUrlAddr1=None, refUrlAddr2=None)
        self.assertIsNone(pipeline.select_source_url(empty))


class EnqueueContractTests(unittest.TestCase):
    def test_summary_is_not_auto_generated(self) -> None:
        candidate = pipeline.transform_youthcenter_policy(sample_policy())
        params = pipeline.build_enqueue_params(
            candidate,
            content="요약된 본문 " * 10,
            ai_status="success",
            ai_model=pipeline.GEMINI_MODEL,
        )
        self.assertIsNone(params["p_summary"])

    def test_rpc_params_exclude_forbidden_fields(self) -> None:
        candidate = pipeline.transform_youthcenter_policy(sample_policy())
        params = pipeline.build_enqueue_params(
            candidate,
            content=candidate.content,
            ai_status="skipped_no_key",
            ai_model=None,
        )
        self.assertEqual(set(params), set(pipeline.ENQUEUE_PARAM_NAMES))
        self.assertTrue(pipeline.FORBIDDEN_ENQUEUE_FIELDS.isdisjoint(params))
        self.assertEqual(params["p_source"], "youthcenter")
        self.assertEqual(params["p_source_item_id"], "2026082700001")
        self.assertEqual(params["p_slug"], "policy-2026082700001")
        self.assertIsNone(params["p_ai_model"])

    def test_inserted_and_duplicate_responses_are_accepted(self) -> None:
        inserted = pipeline.parse_enqueue_result(
            [
                {
                    "candidate_id": "11111111-1111-1111-1111-111111111111",
                    "outcome": "inserted",
                    "superseded_candidate_id": "22222222-2222-2222-2222-222222222222",
                }
            ]
        )
        duplicate = pipeline.parse_enqueue_result(
            {
                "candidate_id": "11111111-1111-1111-1111-111111111111",
                "outcome": "duplicate",
                "superseded_candidate_id": None,
            }
        )
        self.assertEqual(inserted["outcome"], "inserted")
        self.assertEqual(duplicate["outcome"], "duplicate")

    def test_unexpected_rpc_response_is_an_error(self) -> None:
        with self.assertRaises(pipeline.EnqueueError):
            pipeline.parse_enqueue_result([])
        with self.assertRaises(pipeline.EnqueueError):
            pipeline.parse_enqueue_result(
                [
                    {"candidate_id": "x", "outcome": "inserted"},
                    {"candidate_id": "y", "outcome": "duplicate"},
                ]
            )
        with self.assertRaises(pipeline.EnqueueError):
            pipeline.parse_enqueue_result(
                {"candidate_id": "x", "outcome": "published"}
            )
        with self.assertRaises(pipeline.EnqueueError):
            pipeline.parse_enqueue_result("inserted")

    def test_rpc_failure_is_an_error(self) -> None:
        client = FakeSupabase(error=RuntimeError("boom"))
        with self.assertRaises(pipeline.EnqueueError):
            pipeline.enqueue_curation_candidate(
                client,
                {"p_source": "youthcenter"},
            )

    def test_successful_rpc_uses_enqueue_function_only(self) -> None:
        client = FakeSupabase(
            data=[
                {
                    "candidate_id": "11111111-1111-1111-1111-111111111111",
                    "outcome": "inserted",
                    "superseded_candidate_id": None,
                }
            ]
        )
        candidate = pipeline.transform_youthcenter_policy(sample_policy())
        params = pipeline.build_enqueue_params(
            candidate,
            content=candidate.content,
            ai_status="success",
            ai_model=pipeline.GEMINI_MODEL,
        )
        result = pipeline.enqueue_curation_candidate(client, params)
        self.assertEqual(result["outcome"], "inserted")
        self.assertEqual(client.calls[0][0], "enqueue_curation_candidate")
        self.assertEqual(client.calls[0][1], params)


class PipelineFlowTests(unittest.TestCase):
    def test_missing_source_item_id_is_a_transform_error(self) -> None:
        stats = pipeline.process_policies(
            FakeSupabase(),
            [sample_policy(plcyNo="")],
            summarize=lambda content, url: (content, "skipped_no_key", None),
        )
        self.assertEqual(stats.transform_errors, 1)
        self.assertEqual(stats.rpc_inserted, 0)
        self.assertTrue(stats.has_errors)

    def test_region_filter_skips_gemini_and_enqueue(self) -> None:
        summarize = MagicMock(return_value=("x", "success", pipeline.GEMINI_MODEL))
        enqueue = MagicMock()
        policy = sample_policy(
            polyBizSecd="003002009",
            zipCd="",
            rgLcnCd="",
            pvsnInstGroupNm="부산광역시",
            cnsgNmor="부산시",
            mngtMsonNm="부산시청",
            sprvsnInstNm="부산광역시",
            operInstNm="부산광역시",
            rgtrInstCdNm="부산광역시",
        )
        stats = pipeline.process_policies(
            FakeSupabase(),
            [policy],
            summarize=summarize,
            enqueue=enqueue,
        )
        self.assertEqual(stats.region_excluded, 1)
        summarize.assert_not_called()
        enqueue.assert_not_called()

    def test_process_counts_inserted_duplicate_and_superseded(self) -> None:
        outcomes = [
            {
                "candidate_id": "a",
                "outcome": "inserted",
                "superseded_candidate_id": "old",
            },
            {
                "candidate_id": "a",
                "outcome": "duplicate",
                "superseded_candidate_id": None,
            },
        ]

        def enqueue(_supabase, _params):
            return outcomes.pop(0)

        stats = pipeline.process_policies(
            FakeSupabase(),
            [sample_policy(), sample_policy(plcyNo="2026082700002")],
            summarize=lambda content, url: (content, "success", pipeline.GEMINI_MODEL),
            enqueue=enqueue,
        )
        self.assertEqual(stats.rpc_inserted, 1)
        self.assertEqual(stats.rpc_duplicate, 1)
        self.assertEqual(stats.superseded, 1)
        self.assertFalse(stats.has_errors)

    def test_rpc_failure_sets_nonzero_error_state(self) -> None:
        def enqueue(_supabase, _params):
            raise pipeline.EnqueueError("unexpected enqueue outcome: 'nope'")

        stats = pipeline.process_policies(
            FakeSupabase(),
            [sample_policy()],
            summarize=lambda content, url: (content, "error", pipeline.GEMINI_MODEL),
            enqueue=enqueue,
        )
        self.assertEqual(stats.rpc_failures, 1)
        self.assertEqual(stats.ai_status_counts["error"], 1)
        self.assertTrue(stats.has_errors)


class GeminiStatusTests(unittest.TestCase):
    def test_skipped_when_client_missing(self) -> None:
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", None
        ):
            content, status, model = pipeline.summarize_with_gemini(
                "원문",
                "https://example.go.kr",
            )
        self.assertEqual(content, "원문")
        self.assertEqual(status, "skipped_no_key")
        self.assertIsNone(model)

    def test_success_empty_and_error_status(self) -> None:
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = SimpleNamespace(
            text="  요약  "
        )
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            content, status, model = pipeline.summarize_with_gemini(
                "원문",
                "https://example.go.kr",
            )
        self.assertEqual(content, "요약")
        self.assertEqual(status, "success")
        self.assertEqual(model, pipeline.GEMINI_MODEL)

        fake_client.models.generate_content.return_value = SimpleNamespace(text="  ")
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            content, status, model = pipeline.summarize_with_gemini(
                "원문",
                None,
            )
        self.assertEqual(content, "원문")
        self.assertEqual(status, "empty_response")
        self.assertEqual(model, pipeline.GEMINI_MODEL)

        fake_client.models.generate_content.side_effect = RuntimeError("quota")
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            content, status, model = pipeline.summarize_with_gemini("원문", None)
        self.assertEqual(content, "원문")
        self.assertEqual(status, "error")
        self.assertEqual(model, pipeline.GEMINI_MODEL)


class NoDirectWriteTests(unittest.TestCase):
    def test_source_has_no_curations_write_or_upsert_fallback(self) -> None:
        source = pathlib.Path(pipeline.__file__).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_SOURCE_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, source)
        self.assertIn("enqueue_curation_candidate", source)
        self.assertNotRegex(source, r"\.upsert\s*\(")
        self.assertNotRegex(source, r"on_conflict\s*=")


class YouthApiRequestErrorTests(unittest.TestCase):
    def _leaky_connection_error(self) -> requests.ConnectionError:
        max_retry = urllib3_exceptions.MaxRetryError(
            MagicMock(),
            YOUTH_API_LEAK_PATH_URL,
            Exception("Failed to establish a new connection"),
        )
        return requests.ConnectionError(max_retry)

    def _leaky_timeout(self) -> requests.Timeout:
        return requests.Timeout(
            "HTTPSConnectionPool(host='www.youthcenter.go.kr', port=443): "
            f"Read timed out. (url: {YOUTH_API_LEAK_FULL_URL})"
        )

    def _assert_no_youth_api_secret_leak(self, text: str) -> None:
        self.assertNotIn(YOUTH_API_LEAK_SECRET, text)
        self.assertNotIn("apiKeyNm", text)
        self.assertNotIn(YOUTH_API_LEAK_PATH_URL, text)
        self.assertNotIn(YOUTH_API_LEAK_FULL_URL, text)
        self.assertNotIn("getPlcy?", text)

    def _fetch_and_capture(self, side_effect: BaseException) -> tuple[RuntimeError, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {"YOUTH_API_KEY": YOUTH_API_LEAK_SECRET}):
            with patch.object(pipeline.requests, "get", side_effect=side_effect):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                    stderr
                ):
                    with self.assertRaises(RuntimeError) as ctx:
                        pipeline.fetch_real_policies()
        visible = stdout.getvalue() + stderr.getvalue() + str(ctx.exception)
        visible += "".join(traceback.format_exception(ctx.exception))
        return ctx.exception, visible

    def test_connection_error_does_not_leak_api_key_or_query_url(self) -> None:
        leaky = self._leaky_connection_error()
        self.assertIn(YOUTH_API_LEAK_SECRET, str(leaky))
        self.assertIn("apiKeyNm", str(leaky))

        err, visible = self._fetch_and_capture(leaky)
        self.assertEqual(str(err), "Youth API request failed")
        self.assertIsNone(err.__cause__)
        self.assertTrue(err.__suppress_context__)
        self._assert_no_youth_api_secret_leak(str(err))
        self._assert_no_youth_api_secret_leak(visible)

    def test_timeout_does_not_leak_api_key_or_query_url(self) -> None:
        leaky = self._leaky_timeout()
        self.assertIn(YOUTH_API_LEAK_SECRET, str(leaky))
        self.assertIn("apiKeyNm", str(leaky))

        err, visible = self._fetch_and_capture(leaky)
        self.assertEqual(str(err), "Youth API request failed")
        self.assertIsNone(err.__cause__)
        self.assertTrue(err.__suppress_context__)
        self._assert_no_youth_api_secret_leak(str(err))
        self._assert_no_youth_api_secret_leak(visible)


if __name__ == "__main__":
    unittest.main()
