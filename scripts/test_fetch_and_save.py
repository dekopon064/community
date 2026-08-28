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


def busan_policy(**overrides: object) -> dict:
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
    policy.update(overrides)
    return policy


def duplicate_outcome() -> dict:
    return {
        "candidate_id": "11111111-1111-1111-1111-111111111111",
        "outcome": "duplicate",
        "superseded_candidate_id": None,
    }


def inserted_outcome() -> dict:
    return {
        "candidate_id": "11111111-1111-1111-1111-111111111111",
        "outcome": "inserted",
        "superseded_candidate_id": None,
    }


def ko_success(content: str, url: str | None) -> tuple[str, str, str]:
    return (content, "success", pipeline.GEMINI_MODEL)


def ja_success(title_ko: str, content_ko: str) -> tuple[str, str, str, str]:
    return ("日本語タイトル", "日本語本文", "success", pipeline.GEMINI_MODEL)


def enqueue_params(candidate: pipeline.YouthcenterCandidate, **kwargs: object) -> dict:
    return pipeline.build_enqueue_params(
        candidate,
        content_ko=kwargs.get("content_ko", candidate.content),
        ai_status_ko=kwargs.get("ai_status_ko", "skipped_no_key"),
        title_ja=kwargs.get("title_ja"),
        content_ja=kwargs.get("content_ja"),
        ai_status_ja=kwargs.get("ai_status_ja"),
        ai_model=kwargs.get("ai_model"),
    )


class FakeRPC:
    def __init__(self, data=None, error=None):
        self._data = data
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(data=self._data)


class FakeSupabase:
    def __init__(
        self,
        data=None,
        error=None,
        *,
        precheck_data: object = False,
        precheck_error=None,
        precheck_queue=None,
    ):
        self.calls: list[tuple[str, dict]] = []
        self._data = data
        self._error = error
        self._precheck_data = precheck_data
        self._precheck_error = precheck_error
        self._precheck_queue = (
            list(precheck_queue) if precheck_queue is not None else None
        )

    def rpc(self, name: str, params: dict):
        self.calls.append((name, dict(params)))
        if name == pipeline.PRECHECK_RPC_NAME:
            if self._precheck_queue is not None:
                if not self._precheck_queue:
                    raise AssertionError("unexpected extra precheck RPC call")
                item = self._precheck_queue.pop(0)
                if isinstance(item, BaseException):
                    return FakeRPC(error=item)
                return FakeRPC(data=item)
            return FakeRPC(self._precheck_data, self._precheck_error)
        return FakeRPC(self._data, self._error)

    def table(self, name: str):  # pragma: no cover - 직접 쓰기 경로가 있으면 실패
        raise AssertionError(f"table access is forbidden: {name}")

    def rpc_names(self) -> list[str]:
        return [name for name, _params in self.calls]

    def calls_named(self, name: str) -> list[dict]:
        return [params for rpc_name, params in self.calls if rpc_name == name]


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
            content_ko="요약된 본문 " * 10,
            ai_status_ko="success",
            title_ja="日本語タイトル",
            content_ja="日本語本文",
            ai_status_ja="success",
            ai_model=pipeline.GEMINI_MODEL,
        )
        self.assertIsNone(params["p_summary_ko"])
        self.assertIsNone(params["p_summary_ja"])

    def test_rpc_params_are_exactly_the_new_sixteen(self) -> None:
        candidate = pipeline.transform_youthcenter_policy(sample_policy())
        params = enqueue_params(
            candidate,
            content_ko=candidate.content,
            ai_status_ko="skipped_no_key",
        )
        self.assertEqual(len(params), 16)
        self.assertEqual(set(params), set(pipeline.ENQUEUE_PARAM_NAMES))
        self.assertEqual(
            tuple(params),
            pipeline.ENQUEUE_PARAM_NAMES,
        )
        self.assertTrue(pipeline.REMOVED_ENQUEUE_PARAM_NAMES.isdisjoint(params))
        self.assertNotIn("p_title", params)
        self.assertNotIn("p_content", params)
        self.assertNotIn("p_summary", params)
        self.assertNotIn("p_ai_status", params)

    def test_rpc_params_exclude_forbidden_fields(self) -> None:
        candidate = pipeline.transform_youthcenter_policy(sample_policy())
        params = enqueue_params(candidate)
        self.assertEqual(set(params), set(pipeline.ENQUEUE_PARAM_NAMES))
        self.assertTrue(pipeline.FORBIDDEN_ENQUEUE_FIELDS.isdisjoint(params))
        self.assertEqual(params["p_source"], "youthcenter")
        self.assertEqual(params["p_source_item_id"], "2026082700001")
        self.assertEqual(params["p_slug"], "policy-2026082700001")
        self.assertIsNone(params["p_ai_model"])
        self.assertEqual(params["p_title_ko"], candidate.title)
        self.assertEqual(params["p_content_ko"], candidate.content)

    def test_title_ko_is_cleaned_html_and_whitespace(self) -> None:
        candidate = pipeline.transform_youthcenter_policy(
            sample_policy(plcyNm="  <b>청년</b>   월세 지원  ")
        )
        params = enqueue_params(candidate)
        self.assertEqual(params["p_title_ko"], "청년 월세 지원")
        self.assertNotIn("<b>", params["p_title_ko"])

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
        params = enqueue_params(
            candidate,
            content_ko=candidate.content,
            ai_status_ko="success",
            title_ja="日本語タイトル",
            content_ja="日本語本文",
            ai_status_ja="success",
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
            summarize_ko=lambda content, url: (content, "skipped_no_key", None),
            translate_ja=ja_success,
        )
        self.assertEqual(stats.transform_errors, 1)
        self.assertEqual(stats.rpc_inserted, 0)
        self.assertTrue(stats.has_errors)

    def test_region_filter_skips_gemini_and_enqueue(self) -> None:
        summarize_ko = MagicMock(return_value=("x", "success", pipeline.GEMINI_MODEL))
        translate_ja = MagicMock(return_value=ja_success("t", "c"))
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
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(stats.region_excluded, 1)
        summarize_ko.assert_not_called()
        translate_ja.assert_not_called()
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
            summarize_ko=ko_success,
            translate_ja=ja_success,
            enqueue=enqueue,
        )
        self.assertEqual(stats.rpc_inserted, 1)
        self.assertEqual(stats.rpc_duplicate, 1)
        self.assertEqual(stats.superseded, 1)
        self.assertFalse(stats.has_errors)

    def test_rpc_failure_sets_nonzero_error_state(self) -> None:
        def enqueue(_supabase, _params):
            raise pipeline.EnqueueError("unexpected enqueue outcome: 'nope'")

        translate_ja = MagicMock()
        stats = pipeline.process_policies(
            FakeSupabase(),
            [sample_policy()],
            summarize_ko=lambda content, url: (content, "error", pipeline.GEMINI_MODEL),
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(stats.rpc_failures, 1)
        self.assertEqual(stats.ai_status_ko_counts["error"], 1)
        self.assertEqual(stats.ai_status_ja_not_called, 1)
        translate_ja.assert_not_called()
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
        self.assertTrue(
            pipeline.REMOVED_ENQUEUE_PARAM_NAMES.isdisjoint(
                pipeline.ENQUEUE_PARAM_NAMES
            )
        )
        self.assertEqual(len(pipeline.ENQUEUE_PARAM_NAMES), 16)
        self.assertNotIn("fallback_raw", source)
        self.assertNotRegex(source, r"\[pipeline\] ai_status:")
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

    def _fetch_and_capture(
        self,
        side_effect: BaseException,
        fetch_fn=None,
    ) -> tuple[RuntimeError, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        if fetch_fn is None:
            fetch_fn = pipeline.fetch_real_policies
        with patch.dict(os.environ, {"YOUTH_API_KEY": YOUTH_API_LEAK_SECRET}):
            with patch.object(pipeline.requests, "get", side_effect=side_effect):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                    stderr
                ):
                    with self.assertRaises(RuntimeError) as ctx:
                        fetch_fn()
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

    def test_page_two_connection_error_does_not_leak_api_key_or_query_url(self) -> None:
        leaky = self._leaky_connection_error()
        self.assertIn(YOUTH_API_LEAK_SECRET, str(leaky))
        self.assertIn("apiKeyNm", str(leaky))

        mock_get = MagicMock(side_effect=leaky)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {"YOUTH_API_KEY": YOUTH_API_LEAK_SECRET}):
            with patch.object(pipeline.requests, "get", mock_get):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                    stderr
                ):
                    with self.assertRaises(RuntimeError) as ctx:
                        pipeline.fetch_youth_api_page(2)
        err = ctx.exception
        visible = stdout.getvalue() + stderr.getvalue() + str(err)
        visible += "".join(traceback.format_exception(err))
        self.assertEqual(str(err), "Youth API request failed")
        self.assertIsNone(err.__cause__)
        self.assertTrue(err.__suppress_context__)
        self._assert_no_youth_api_secret_leak(str(err))
        self._assert_no_youth_api_secret_leak(visible)
        self.assertEqual(mock_get.call_args.kwargs["params"]["pageNum"], 2)
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["pageSize"],
            pipeline.FETCH_PAGE_SIZE,
        )


class PagingCollectionTests(unittest.TestCase):
    def _collect(self, pages: dict[int, list[dict]]) -> tuple[list[dict], pipeline.PipelineStats, list[int]]:
        seen_pages: list[int] = []

        def fetch_page(page_num: int) -> list[dict]:
            seen_pages.append(page_num)
            if page_num not in pages:
                self.fail(f"unexpected page fetch: {page_num}")
            return pages[page_num]

        selected, stats = pipeline.collect_target_policies(fetch_page=fetch_page)
        return selected, stats, seen_pages

    def test_skips_non_target_first_page_then_selects_from_second(self) -> None:
        page1 = [busan_policy(plcyNo=f"b{i}") for i in range(5)]
        target = sample_policy(plcyNo="seoul-1")
        page2 = [target, busan_policy(plcyNo="b-extra")]
        selected, stats, seen_pages = self._collect({1: page1, 2: page2})
        self.assertEqual(seen_pages, [1, 2])
        self.assertEqual(stats.pages_fetched, 2)
        self.assertEqual(stats.collected, 7)
        self.assertEqual(stats.region_excluded, 6)
        self.assertEqual(stats.selected, 1)
        self.assertEqual(stats.stop_reason, "short_page")
        self.assertEqual(selected, [target])

        summarize_ko = MagicMock(return_value=("x", "success", pipeline.GEMINI_MODEL))
        translate_ja = MagicMock(side_effect=ja_success)
        enqueue = MagicMock(return_value=duplicate_outcome())
        process_stats = pipeline.process_policies(
            FakeSupabase(),
            selected,
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
            stats=stats,
        )
        self.assertEqual(summarize_ko.call_count, 1)
        self.assertEqual(translate_ja.call_count, 1)
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(process_stats.processed, 1)
        self.assertEqual(process_stats.collected, 7)

    def test_stops_fetching_when_candidate_cap_is_reached(self) -> None:
        page1 = [sample_policy(plcyNo=f"s{i}") for i in range(5)]
        selected, stats, seen_pages = self._collect({1: page1})
        self.assertEqual(seen_pages, [1])
        self.assertEqual(stats.pages_fetched, 1)
        self.assertEqual(stats.selected, 5)
        self.assertEqual(stats.stop_reason, "candidate_cap")
        self.assertEqual(len(selected), 5)

    def test_stops_on_empty_page(self) -> None:
        page1 = [busan_policy(plcyNo=f"b{i}") for i in range(5)]
        selected, stats, seen_pages = self._collect({1: page1, 2: []})
        self.assertEqual(seen_pages, [1, 2])
        self.assertEqual(stats.stop_reason, "empty_page")
        self.assertEqual(stats.selected, 0)
        self.assertEqual(selected, [])
        self.assertFalse(stats.has_errors)

    def test_stops_on_short_page(self) -> None:
        page1 = [busan_policy(plcyNo=f"b{i}") for i in range(5)]
        page2 = [sample_policy(plcyNo="seoul-short")]
        selected, stats, seen_pages = self._collect({1: page1, 2: page2})
        self.assertEqual(seen_pages, [1, 2])
        self.assertEqual(stats.stop_reason, "short_page")
        self.assertEqual(stats.selected, 1)
        self.assertEqual(len(page2), 1)
        self.assertLess(len(page2), pipeline.FETCH_PAGE_SIZE)

    def test_stops_at_max_pages_without_extra_fetch(self) -> None:
        pages = {
            page_num: [busan_policy(plcyNo=f"p{page_num}-{i}") for i in range(5)]
            for page_num in range(1, pipeline.MAX_FETCH_PAGES + 1)
        }
        selected, stats, seen_pages = self._collect(pages)
        self.assertEqual(seen_pages, list(range(1, pipeline.MAX_FETCH_PAGES + 1)))
        self.assertEqual(stats.pages_fetched, pipeline.MAX_FETCH_PAGES)
        self.assertEqual(stats.stop_reason, "max_pages")
        self.assertEqual(stats.selected, 0)
        self.assertEqual(selected, [])

    def test_in_run_plcy_no_duplicates_are_not_selected_twice(self) -> None:
        shared = sample_policy(plcyNo="same-policy")
        page1 = [
            shared,
            busan_policy(plcyNo="b1"),
            busan_policy(plcyNo="b2"),
            busan_policy(plcyNo="b3"),
            busan_policy(plcyNo="b4"),
        ]
        page2 = [
            sample_policy(plcyNo="same-policy"),
            busan_policy(plcyNo="b5"),
        ]
        selected, stats, seen_pages = self._collect({1: page1, 2: page2})
        self.assertEqual(seen_pages, [1, 2])
        self.assertGreaterEqual(stats.in_run_duplicates, 1)
        self.assertEqual(stats.selected, 1)
        summarize_ko = MagicMock(return_value=("x", "success", pipeline.GEMINI_MODEL))
        translate_ja = MagicMock(side_effect=ja_success)
        enqueue = MagicMock(return_value=duplicate_outcome())
        pipeline.process_policies(
            FakeSupabase(),
            selected,
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
            stats=stats,
        )
        self.assertEqual(summarize_ko.call_count, 1)
        self.assertEqual(translate_ja.call_count, 1)
        self.assertEqual(enqueue.call_count, 1)

    def test_process_policies_caps_ai_and_enqueue_at_five(self) -> None:
        policies = [sample_policy(plcyNo=f"cap-{i}") for i in range(6)]
        summarize_ko = MagicMock(return_value=("x", "success", pipeline.GEMINI_MODEL))
        translate_ja = MagicMock(side_effect=ja_success)
        enqueue = MagicMock(return_value=duplicate_outcome())
        stats = pipeline.process_policies(
            FakeSupabase(),
            policies,
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(summarize_ko.call_count, 5)
        self.assertEqual(translate_ja.call_count, 5)
        self.assertEqual(enqueue.call_count, 5)
        self.assertEqual(stats.processed, 5)
        self.assertEqual(stats.rpc_duplicate, 5)

    def test_rpc_duplicates_count_toward_processing_cap(self) -> None:
        policies = [sample_policy(plcyNo=f"dup-{i}") for i in range(5)]
        summarize_ko = MagicMock(return_value=("x", "success", pipeline.GEMINI_MODEL))
        translate_ja = MagicMock(side_effect=ja_success)
        enqueue = MagicMock(return_value=duplicate_outcome())
        stats = pipeline.process_policies(
            FakeSupabase(),
            policies,
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(stats.processed, 5)
        self.assertEqual(stats.rpc_duplicate, 5)
        self.assertEqual(summarize_ko.call_count, 5)
        self.assertEqual(translate_ja.call_count, 5)
        self.assertEqual(enqueue.call_count, 5)

    def test_zero_selected_warns_and_exits_zero(self) -> None:
        page1 = [busan_policy(plcyNo=f"b{i}") for i in range(5)]

        def fetch_page(page_num: int) -> list[dict]:
            if page_num == 1:
                return page1
            if page_num == 2:
                return []
            self.fail(f"unexpected page fetch: {page_num}")
            return []

        summarize = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()
        stdout = io.StringIO()
        with patch.object(pipeline, "get_supabase_client", return_value=FakeSupabase()):
            with patch.object(pipeline, "fetch_youth_api_page", side_effect=fetch_page):
                with patch.object(pipeline, "summarize_with_gemini", summarize):
                    with patch.object(pipeline, "translate_with_gemini_ja", translate_ja):
                        with patch.object(pipeline, "enqueue_curation_candidate", enqueue):
                            with contextlib.redirect_stdout(stdout):
                                code = pipeline.main()
        self.assertEqual(code, 0)
        self.assertIn(
            "[pipeline] warning: no region-matching policies selected",
            stdout.getvalue(),
        )
        self.assertIn("stop_reason=empty_page", stdout.getvalue())
        summarize.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()

    def test_collect_api_error_does_not_call_gemini_or_enqueue(self) -> None:
        page1 = [
            sample_policy(plcyNo="keep-1"),
            sample_policy(plcyNo="keep-2"),
            busan_policy(plcyNo="b1"),
            busan_policy(plcyNo="b2"),
            busan_policy(plcyNo="b3"),
        ]
        summarize = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()

        def fetch_page(page_num: int) -> list[dict]:
            if page_num == 1:
                return page1
            raise RuntimeError("Youth API request failed")

        with self.assertRaises(RuntimeError) as ctx:
            pipeline.collect_target_policies(fetch_page=fetch_page)
        self.assertEqual(str(ctx.exception), "Youth API request failed")
        summarize.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()

    def test_shared_stats_keep_collection_counts_after_process(self) -> None:
        page1 = [busan_policy(plcyNo=f"b{i}") for i in range(5)]
        page2 = [sample_policy(plcyNo="seoul-keep")]
        selected, stats, _seen = self._collect({1: page1, 2: page2})
        collected_before = stats.collected
        pages_before = stats.pages_fetched
        region_before = stats.region_excluded
        pipeline.process_policies(
            FakeSupabase(),
            selected,
            summarize_ko=lambda content, url: (content, "skipped_no_key", None),
            translate_ja=ja_success,
            enqueue=lambda _supabase, _params: duplicate_outcome(),
            stats=stats,
        )
        self.assertEqual(stats.collected, collected_before)
        self.assertEqual(stats.pages_fetched, pages_before)
        self.assertEqual(stats.region_excluded, region_before)
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.selected, 1)
        self.assertEqual(stats.ai_status_ko_counts["skipped_no_key"], 1)
        self.assertEqual(stats.ai_status_ja_not_called, 1)


class JapaneseParseTests(unittest.TestCase):
    def test_valid_object_returns_trimmed_fields(self) -> None:
        parsed = pipeline.parse_japanese_translation(
            '  {"title_ja": " タイトル ", "content_ja": " 本文 "}  '
        )
        self.assertEqual(parsed, ("タイトル", "本文"))

    def test_one_json_fence_is_unwrapped(self) -> None:
        raw = '```json\n{"title_ja": "タイトル", "content_ja": "本文"}\n```'
        self.assertEqual(
            pipeline.parse_japanese_translation(raw),
            ("タイトル", "本文"),
        )

    def test_extra_keys_are_ignored(self) -> None:
        raw = json.dumps(
            {
                "title_ja": "タイトル",
                "content_ja": "本文",
                "extra": "drop-me",
                "prompt": "secret",
            }
        )
        self.assertEqual(
            pipeline.parse_japanese_translation(raw),
            ("タイトル", "本文"),
        )

    def test_invalid_payloads_are_parse_errors(self) -> None:
        cases = [
            '["title_ja", "content_ja"]',
            '"just a string"',
            "null",
            '{"title_ja": "タイトル"}',
            '{"title_ja": 1, "content_ja": "本文"}',
            '{"title_ja": "タイトル", "content_ja": "  "}',
            "not-json",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertIsNone(pipeline.parse_japanese_translation(raw))


class BilingualFlowTests(unittest.TestCase):
    def test_korean_success_calls_japanese_and_enqueues_sixteen_params(self) -> None:
        enqueue = MagicMock(return_value=inserted_outcome())
        translate_ja = MagicMock(side_effect=ja_success)
        stats = pipeline.process_policies(
            FakeSupabase(),
            [sample_policy()],
            summarize_ko=lambda content, url: ("한국어본문", "success", pipeline.GEMINI_MODEL),
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(stats.rpc_inserted, 1)
        translate_ja.assert_called_once()
        self.assertEqual(translate_ja.call_args.args[0], "청년 월세 지원")
        self.assertEqual(translate_ja.call_args.args[1], "한국어본문")
        params = enqueue.call_args.args[1]
        self.assertEqual(set(params), set(pipeline.ENQUEUE_PARAM_NAMES))
        self.assertEqual(params["p_content_ko"], "한국어본문")
        self.assertEqual(params["p_title_ja"], "日本語タイトル")
        self.assertEqual(params["p_content_ja"], "日本語本文")
        self.assertEqual(params["p_ai_status_ko"], "success")
        self.assertEqual(params["p_ai_status_ja"], "success")
        self.assertIsNone(params["p_summary_ko"])
        self.assertIsNone(params["p_summary_ja"])
        self.assertTrue(pipeline.REMOVED_ENQUEUE_PARAM_NAMES.isdisjoint(params))
        self.assertTrue(pipeline.FORBIDDEN_ENQUEUE_FIELDS.isdisjoint(params))

    def test_korean_failure_skips_japanese_and_still_enqueues(self) -> None:
        enqueue = MagicMock(return_value=inserted_outcome())
        translate_ja = MagicMock()
        original = "설명입니다. 월 20만 원을 지원합니다."
        stats = pipeline.process_policies(
            FakeSupabase(),
            [sample_policy()],
            summarize_ko=lambda content, url: (content, "error", pipeline.GEMINI_MODEL),
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        translate_ja.assert_not_called()
        self.assertEqual(stats.rpc_inserted, 1)
        self.assertEqual(stats.ai_status_ko_counts["error"], 1)
        self.assertEqual(stats.ai_status_ja_not_called, 1)
        params = enqueue.call_args.args[1]
        self.assertEqual(params["p_ai_status_ko"], "error")
        self.assertEqual(pipeline.strip_html(original), params["p_content_ko"])
        self.assertIsNone(params["p_title_ja"])
        self.assertIsNone(params["p_content_ja"])
        self.assertIsNone(params["p_ai_status_ja"])
        self.assertNotEqual(params["p_title_ko"], params["p_title_ja"])

    def test_japanese_empty_and_error_leave_fields_null(self) -> None:
        enqueue = MagicMock(return_value=inserted_outcome())
        for ja_status in ("empty_response", "error"):
            enqueue.reset_mock()
            stats = pipeline.process_policies(
                FakeSupabase(),
                [sample_policy()],
                summarize_ko=ko_success,
                translate_ja=lambda title, content: (None, None, ja_status, pipeline.GEMINI_MODEL),
                enqueue=enqueue,
            )
            params = enqueue.call_args.args[1]
            self.assertIsNone(params["p_title_ja"])
            self.assertIsNone(params["p_content_ja"])
            self.assertEqual(params["p_ai_status_ja"], ja_status)
            self.assertNotEqual(params["p_title_ko"], params["p_title_ja"])
            self.assertNotEqual(params["p_content_ko"], params["p_content_ja"])
            self.assertEqual(stats.ai_status_ja_counts[ja_status], 1)

    def test_parse_error_does_not_copy_korean_into_japanese(self) -> None:
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = SimpleNamespace(
            text='{"title_ja": "", "content_ja": "x"}'
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                title_ja, content_ja, status, model = pipeline.translate_with_gemini_ja(
                    "청년 월세 지원",
                    "한국어본문",
                )
        self.assertIsNone(title_ja)
        self.assertIsNone(content_ja)
        self.assertEqual(status, "parse_error")
        self.assertEqual(model, pipeline.GEMINI_MODEL)
        visible = stdout.getvalue() + stderr.getvalue()
        self.assertIn("parse_error", visible)
        self.assertNotIn("한국어본문", visible)
        self.assertNotIn("청년 월세 지원", visible)
        self.assertNotIn("title_ja", visible)

    def test_region_excluded_policies_call_neither_gemini_nor_rpc(self) -> None:
        summarize_ko = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()
        stats = pipeline.process_policies(
            FakeSupabase(),
            [busan_policy()],
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(stats.region_excluded, 1)
        self.assertEqual(stats.processed, 0)
        summarize_ko.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()


class GeminiLogSafetyTests(unittest.TestCase):
    LEAK = "super-secret-api-key-do-not-log"

    def _assert_safe(self, visible: str) -> None:
        self.assertNotIn(self.LEAK, visible)
        self.assertNotIn("전체 prompt", visible)
        self.assertNotIn("[원문]", visible)
        self.assertNotIn("[title_ko]", visible)
        self.assertNotIn("[content_ko]", visible)
        self.assertNotIn("GEMINI_API_KEY", visible)

    def test_korean_gemini_error_logs_stage_not_payload(self) -> None:
        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = RuntimeError(
            f"quota prompt=[원문] secret={self.LEAK}"
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                content, status, _model = pipeline.summarize_with_gemini(
                    "원문본문",
                    "https://example.go.kr",
                )
        self.assertEqual(status, "error")
        self.assertEqual(content, "원문본문")
        visible = stdout.getvalue() + stderr.getvalue()
        self.assertIn("Gemini KO error: generate_content", visible)
        self.assertNotIn("원문본문", visible)
        self._assert_safe(visible)
        self.assertNotIn("quota", visible)

    def test_japanese_gemini_error_logs_stage_not_payload(self) -> None:
        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = RuntimeError(
            f"bad request body=[content_ko] {self.LEAK}"
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                title_ja, content_ja, status, _model = pipeline.translate_with_gemini_ja(
                    "청년 월세 지원",
                    "한국어본문전체",
                )
        self.assertEqual(status, "error")
        self.assertIsNone(title_ja)
        self.assertIsNone(content_ja)
        visible = stdout.getvalue() + stderr.getvalue()
        self.assertIn("Gemini JA error: generate_content", visible)
        self.assertNotIn("한국어본문전체", visible)
        self.assertNotIn("청년 월세 지원", visible)
        self._assert_safe(visible)

    def test_japanese_parse_error_does_not_log_raw_response(self) -> None:
        raw = '{"title_ja": "leak-title", "content_ja":'
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text=raw)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(pipeline, "_GENAI_AVAILABLE", True), patch.object(
            pipeline, "client", fake_client
        ), patch.object(pipeline, "types", MagicMock()):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                _title, _content, status, _model = pipeline.translate_with_gemini_ja(
                    "청년 월세 지원",
                    "한국어본문",
                )
        self.assertEqual(status, "parse_error")
        visible = stdout.getvalue() + stderr.getvalue()
        self.assertIn("[pipeline] Gemini JA parse_error", visible)
        self.assertNotIn("leak-title", visible)
        self.assertNotIn(raw, visible)
        self.assertNotIn("한국어본문", visible)

    def test_print_stats_splits_ai_status_and_not_called(self) -> None:
        stats = pipeline.PipelineStats()
        stats.ai_status_ko_counts["success"] = 1
        stats.ai_status_ko_counts["error"] = 1
        stats.ai_status_ja_counts["success"] = 1
        stats.ai_status_ja_not_called = 1
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            pipeline.print_stats(stats)
        text = stdout.getvalue()
        self.assertIn("ai_status_ko:", text)
        self.assertIn("ai_status_ja:", text)
        self.assertIn("not_called=1", text)
        self.assertNotRegex(text, r"\[pipeline\] ai_status:")


PRECHECK_LEAK_SECRET = "test-precheck-secret-do-not-leak"
PRECHECK_LEAK_ITEM_ID = "secret-source-item-do-not-log"
PRECHECK_LEAK_HASH = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PRECHECK_LEAK_URL = (
    "https://example.invalid/rest/v1/rpc/is_latest_source_revision"
)
PRECHECK_LEAK_PAYLOAD = (
    '{"p_source":"youthcenter",'
    f'"p_source_item_id":"{PRECHECK_LEAK_ITEM_ID}",'
    f'"p_source_revision_hash":"{PRECHECK_LEAK_HASH}"}}'
)


def leaky_precheck_error() -> RuntimeError:
    return RuntimeError(
        "precheck boom "
        f"secret={PRECHECK_LEAK_SECRET} "
        f"url={PRECHECK_LEAK_URL} "
        f"hash={PRECHECK_LEAK_HASH} "
        f"payload={PRECHECK_LEAK_PAYLOAD}"
    )


class PrecheckHelperTests(unittest.TestCase):
    def test_false_scalar_is_a_normal_result(self) -> None:
        self.assertIs(pipeline.parse_precheck_result(False), False)
        client = FakeSupabase(precheck_data=False)
        self.assertIs(
            pipeline.is_latest_source_revision(
                client,
                pipeline.YOUTHCENTER_SOURCE,
                "item-1",
                PRECHECK_LEAK_HASH,
            ),
            False,
        )

    def test_true_scalar_is_a_normal_result(self) -> None:
        self.assertIs(pipeline.parse_precheck_result(True), True)
        client = FakeSupabase(precheck_data=True)
        self.assertIs(
            pipeline.is_latest_source_revision(
                client,
                pipeline.YOUTHCENTER_SOURCE,
                "item-1",
                PRECHECK_LEAK_HASH,
            ),
            True,
        )

    def test_non_bool_precheck_values_are_errors(self) -> None:
        cases = [None, "false", "true", 0, 1, [], {}, [False], {"ok": False}]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(pipeline.PrecheckError) as ctx:
                    pipeline.parse_precheck_result(value)
                self.assertEqual(
                    str(ctx.exception),
                    "precheck RPC returned a non-boolean result",
                )
                self.assertIsNone(ctx.exception.__cause__)
                self.assertTrue(ctx.exception.__suppress_context__)

    def test_precheck_rpc_sends_exactly_three_params(self) -> None:
        client = FakeSupabase(precheck_data=False)
        pipeline.is_latest_source_revision(
            client,
            pipeline.YOUTHCENTER_SOURCE,
            "item-1",
            PRECHECK_LEAK_HASH,
        )
        self.assertEqual(client.rpc_names(), [pipeline.PRECHECK_RPC_NAME])
        params = client.calls[0][1]
        self.assertEqual(tuple(params), pipeline.PRECHECK_PARAM_NAMES)
        self.assertEqual(set(params), set(pipeline.PRECHECK_PARAM_NAMES))
        self.assertEqual(len(params), 3)
        self.assertNotIn("p_title_ko", params)
        self.assertNotIn("p_raw_payload", params)

    def test_precheck_rpc_error_does_not_leak_secret_url_hash_or_payload(self) -> None:
        leaky = leaky_precheck_error()
        self.assertIn(PRECHECK_LEAK_SECRET, str(leaky))
        self.assertIn(PRECHECK_LEAK_URL, str(leaky))
        self.assertIn(PRECHECK_LEAK_HASH, str(leaky))
        self.assertIn(PRECHECK_LEAK_PAYLOAD, str(leaky))

        client = FakeSupabase(precheck_error=leaky)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(pipeline.PrecheckError) as ctx:
                pipeline.is_latest_source_revision(
                    client,
                    pipeline.YOUTHCENTER_SOURCE,
                    PRECHECK_LEAK_ITEM_ID,
                    PRECHECK_LEAK_HASH,
                )
        err = ctx.exception
        visible = stdout.getvalue() + stderr.getvalue() + str(err)
        visible += "".join(traceback.format_exception(err))
        self.assertEqual(str(err), "precheck RPC failed")
        self.assertIsNone(err.__cause__)
        self.assertTrue(err.__suppress_context__)
        self.assertNotIn(PRECHECK_LEAK_SECRET, visible)
        self.assertNotIn(PRECHECK_LEAK_URL, visible)
        self.assertNotIn(PRECHECK_LEAK_HASH, visible)
        self.assertNotIn(PRECHECK_LEAK_PAYLOAD, visible)
        self.assertNotIn(PRECHECK_LEAK_ITEM_ID, visible)


class PrecheckFlowTests(unittest.TestCase):
    def _capture_process(self, **kwargs):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            stats = pipeline.process_policies(**kwargs)
        return stats, stdout.getvalue(), stderr.getvalue()

    def test_precheck_false_runs_existing_ko_ja_enqueue_path(self) -> None:
        summarize_ko = MagicMock(side_effect=ko_success)
        translate_ja = MagicMock(side_effect=ja_success)
        enqueue = MagicMock(return_value=inserted_outcome())
        stats, _out, _err = self._capture_process(
            supabase=FakeSupabase(precheck_data=False),
            policies=[sample_policy()],
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        self.assertEqual(summarize_ko.call_count, 1)
        self.assertEqual(translate_ja.call_count, 1)
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.precheck_duplicate, 0)
        self.assertEqual(stats.precheck_failure, 0)
        self.assertEqual(stats.rpc_inserted, 1)
        params = enqueue.call_args.args[1]
        self.assertEqual(len(params), 16)
        self.assertEqual(set(params), set(pipeline.ENQUEUE_PARAM_NAMES))

    def test_precheck_true_skips_ko_ja_enqueue_and_processed(self) -> None:
        summarize_ko = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()
        stats, stdout, _err = self._capture_process(
            supabase=FakeSupabase(precheck_data=True),
            policies=[sample_policy()],
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        summarize_ko.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.precheck_duplicate, 1)
        self.assertEqual(stats.precheck_failure, 0)
        self.assertFalse(stats.has_errors)
        self.assertIn("precheck_duplicate slug=policy-2026082700001", stdout)

    def test_second_precheck_exception_fail_closes_entire_run(self) -> None:
        summarize_ko = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()
        client = FakeSupabase(precheck_queue=[False, leaky_precheck_error()])
        stats, stdout, stderr = self._capture_process(
            supabase=client,
            policies=[
                sample_policy(plcyNo="first"),
                sample_policy(plcyNo="second"),
            ],
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
        )
        summarize_ko.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.precheck_duplicate, 0)
        self.assertEqual(stats.precheck_failure, 1)
        self.assertTrue(stats.has_errors)
        self.assertEqual(stderr.strip(), pipeline.PRECHECK_FAILURE_LOG)
        self.assertNotIn("first", stderr)
        self.assertNotIn("second", stderr)
        visible = stdout + stderr
        self.assertNotIn(PRECHECK_LEAK_SECRET, visible)
        self.assertNotIn(PRECHECK_LEAK_URL, visible)
        self.assertNotIn(PRECHECK_LEAK_HASH, visible)
        self.assertNotIn(PRECHECK_LEAK_PAYLOAD, visible)

        page1 = [
            sample_policy(plcyNo="first"),
            sample_policy(plcyNo="second"),
            busan_policy(plcyNo="b1"),
            busan_policy(plcyNo="b2"),
            busan_policy(plcyNo="b3"),
        ]

        def fetch_page(page_num: int) -> list[dict]:
            if page_num == 1:
                return page1
            if page_num == 2:
                return []
            self.fail(f"unexpected page fetch: {page_num}")
            return []

        main_client = FakeSupabase(precheck_queue=[False, leaky_precheck_error()])
        main_stdout = io.StringIO()
        main_stderr = io.StringIO()
        with patch.object(pipeline, "get_supabase_client", return_value=main_client):
            with patch.object(pipeline, "fetch_youth_api_page", side_effect=fetch_page):
                with patch.object(pipeline, "summarize_with_gemini", summarize_ko):
                    with patch.object(pipeline, "translate_with_gemini_ja", translate_ja):
                        with patch.object(
                            pipeline, "enqueue_curation_candidate", enqueue
                        ):
                            with contextlib.redirect_stdout(
                                main_stdout
                            ), contextlib.redirect_stderr(main_stderr):
                                code = pipeline.main()
        self.assertEqual(code, 1)
        self.assertIn("precheck_failure=1", main_stdout.getvalue())
        self.assertIn(pipeline.PRECHECK_FAILURE_LOG, main_stderr.getvalue())
        summarize_ko.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()

    def test_second_non_bool_precheck_fail_closes_entire_run(self) -> None:
        summarize_ko = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()
        for value in (None, "false", 0, 1, ["false"], {"latest": False}):
            summarize_ko.reset_mock()
            translate_ja.reset_mock()
            enqueue.reset_mock()
            with self.subTest(value=value):
                stats, _out, stderr = self._capture_process(
                    supabase=FakeSupabase(precheck_queue=[False, value]),
                    policies=[
                        sample_policy(plcyNo="first"),
                        sample_policy(plcyNo="second"),
                    ],
                    summarize_ko=summarize_ko,
                    translate_ja=translate_ja,
                    enqueue=enqueue,
                )
                summarize_ko.assert_not_called()
                translate_ja.assert_not_called()
                enqueue.assert_not_called()
                self.assertEqual(stats.processed, 0)
                self.assertEqual(stats.rpc_inserted, 0)
                self.assertEqual(stats.precheck_failure, 1)
                self.assertTrue(stats.has_errors)
                self.assertEqual(stderr.strip(), pipeline.PRECHECK_FAILURE_LOG)

    def test_precheck_false_then_enqueue_duplicate_is_rpc_duplicate(self) -> None:
        enqueue = MagicMock(return_value=duplicate_outcome())
        stats, _out, _err = self._capture_process(
            supabase=FakeSupabase(precheck_data=False),
            policies=[sample_policy()],
            summarize_ko=ko_success,
            translate_ja=ja_success,
            enqueue=enqueue,
        )
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.rpc_duplicate, 1)
        self.assertEqual(stats.rpc_inserted, 0)
        self.assertEqual(stats.precheck_duplicate, 0)
        self.assertFalse(stats.has_errors)

    def test_in_run_plcy_no_duplicate_calls_precheck_once(self) -> None:
        shared = sample_policy(plcyNo="same-policy")
        page1 = [
            shared,
            busan_policy(plcyNo="b1"),
            busan_policy(plcyNo="b2"),
            busan_policy(plcyNo="b3"),
            busan_policy(plcyNo="b4"),
        ]
        page2 = [
            sample_policy(plcyNo="same-policy"),
            busan_policy(plcyNo="b5"),
        ]
        seen_pages: list[int] = []

        def fetch_page(page_num: int) -> list[dict]:
            seen_pages.append(page_num)
            return {1: page1, 2: page2}[page_num]

        selected, stats = pipeline.collect_target_policies(fetch_page=fetch_page)
        self.assertEqual(stats.selected, 1)
        self.assertGreaterEqual(stats.in_run_duplicates, 1)
        client = FakeSupabase(precheck_data=False)
        revision_precheck = MagicMock(return_value=False)
        summarize_ko = MagicMock(side_effect=ko_success)
        translate_ja = MagicMock(side_effect=ja_success)
        enqueue = MagicMock(return_value=duplicate_outcome())
        pipeline.process_policies(
            client,
            selected,
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
            revision_precheck=revision_precheck,
            stats=stats,
        )
        self.assertEqual(revision_precheck.call_count, 1)
        self.assertEqual(summarize_ko.call_count, 1)
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(seen_pages, [1, 2])

    def test_precheck_true_does_not_replenish_with_extra_pages_or_sixth(self) -> None:
        page1 = [sample_policy(plcyNo=f"s{i}") for i in range(5)]
        seen_pages: list[int] = []

        def fetch_page(page_num: int) -> list[dict]:
            seen_pages.append(page_num)
            if page_num != 1:
                self.fail(f"unexpected extra page fetch: {page_num}")
            return page1

        summarize = MagicMock()
        translate_ja = MagicMock()
        enqueue = MagicMock()
        client = FakeSupabase(precheck_data=True)
        stdout = io.StringIO()
        with patch.object(pipeline, "get_supabase_client", return_value=client):
            with patch.object(pipeline, "fetch_youth_api_page", side_effect=fetch_page):
                with patch.object(pipeline, "summarize_with_gemini", summarize):
                    with patch.object(pipeline, "translate_with_gemini_ja", translate_ja):
                        with patch.object(
                            pipeline, "enqueue_curation_candidate", enqueue
                        ):
                            with contextlib.redirect_stdout(stdout):
                                code = pipeline.main()
        self.assertEqual(code, 0)
        self.assertEqual(seen_pages, [1])
        self.assertEqual(len(client.calls_named(pipeline.PRECHECK_RPC_NAME)), 5)
        self.assertEqual(client.calls_named(pipeline.ENQUEUE_RPC_NAME), [])
        summarize.assert_not_called()
        translate_ja.assert_not_called()
        enqueue.assert_not_called()
        self.assertIn("processed=0", stdout.getvalue())
        self.assertIn("precheck_duplicate=5", stdout.getvalue())
        self.assertIn("selected=5", stdout.getvalue())

        extra = [sample_policy(plcyNo=f"cap-{i}") for i in range(6)]
        revision_precheck = MagicMock(return_value=True)
        stats = pipeline.process_policies(
            FakeSupabase(),
            extra,
            summarize_ko=summarize,
            translate_ja=translate_ja,
            enqueue=enqueue,
            revision_precheck=revision_precheck,
        )
        self.assertEqual(revision_precheck.call_count, 5)
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.precheck_duplicate, 5)
        summarize.assert_not_called()
        enqueue.assert_not_called()

    def test_processed_precheck_duplicate_and_failure_are_separate(self) -> None:
        revision_precheck = MagicMock(side_effect=[False, True, False])
        enqueue = MagicMock(return_value=inserted_outcome())
        stats, _out, _err = self._capture_process(
            supabase=FakeSupabase(),
            policies=[
                sample_policy(plcyNo="new-1"),
                sample_policy(plcyNo="seen-1"),
                sample_policy(plcyNo="new-2"),
            ],
            summarize_ko=ko_success,
            translate_ja=ja_success,
            enqueue=enqueue,
            revision_precheck=revision_precheck,
        )
        self.assertEqual(stats.processed, 2)
        self.assertEqual(stats.precheck_duplicate, 1)
        self.assertEqual(stats.precheck_failure, 0)
        self.assertEqual(enqueue.call_count, 2)
        self.assertEqual(stats.rpc_inserted, 2)

        fail_enqueue = MagicMock()
        fail_stats, _out, _err = self._capture_process(
            supabase=FakeSupabase(),
            policies=[sample_policy(plcyNo="boom")],
            summarize_ko=ko_success,
            translate_ja=ja_success,
            enqueue=fail_enqueue,
            revision_precheck=MagicMock(
                side_effect=pipeline.PrecheckError("precheck RPC failed")
            ),
        )
        fail_enqueue.assert_not_called()
        self.assertEqual(fail_stats.processed, 0)
        self.assertEqual(fail_stats.precheck_duplicate, 0)
        self.assertEqual(fail_stats.precheck_failure, 1)
        self.assertTrue(fail_stats.has_errors)

    def test_process_keeps_precheck_and_enqueue_rpc_contracts_apart(self) -> None:
        client = FakeSupabase(data=[inserted_outcome()], precheck_data=False)
        stats, _out, _err = self._capture_process(
            supabase=client,
            policies=[
                sample_policy(plcyNo="one"),
                sample_policy(plcyNo="two"),
            ],
            summarize_ko=ko_success,
            translate_ja=ja_success,
        )
        self.assertEqual(stats.rpc_inserted, 2)
        self.assertEqual(
            client.rpc_names(),
            [
                pipeline.PRECHECK_RPC_NAME,
                pipeline.PRECHECK_RPC_NAME,
                pipeline.ENQUEUE_RPC_NAME,
                pipeline.ENQUEUE_RPC_NAME,
            ],
        )
        for params in client.calls_named(pipeline.PRECHECK_RPC_NAME):
            self.assertEqual(tuple(params), pipeline.PRECHECK_PARAM_NAMES)
            self.assertEqual(len(params), 3)
            self.assertTrue(
                pipeline.REMOVED_ENQUEUE_PARAM_NAMES.isdisjoint(params)
            )
            self.assertTrue(pipeline.FORBIDDEN_ENQUEUE_FIELDS.isdisjoint(params))
        for params in client.calls_named(pipeline.ENQUEUE_RPC_NAME):
            self.assertEqual(set(params), set(pipeline.ENQUEUE_PARAM_NAMES))
            self.assertEqual(len(params), 16)

    def test_process_precheck_failure_log_does_not_leak_injected_secrets(self) -> None:
        leaky = leaky_precheck_error()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                stats = pipeline.process_policies(
                    FakeSupabase(precheck_error=leaky),
                    [sample_policy()],
                    summarize_ko=ko_success,
                    translate_ja=ja_success,
                    enqueue=MagicMock(),
                )
            except Exception as exc:  # pragma: no cover - must not leak via raise
                visible = "".join(traceback.format_exception(exc))
                self.fail(visible)
        visible = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(stats.precheck_failure, 1)
        self.assertEqual(stderr.getvalue().strip(), pipeline.PRECHECK_FAILURE_LOG)
        self.assertNotIn(PRECHECK_LEAK_SECRET, visible)
        self.assertNotIn(PRECHECK_LEAK_URL, visible)
        self.assertNotIn(PRECHECK_LEAK_HASH, visible)
        self.assertNotIn(PRECHECK_LEAK_PAYLOAD, visible)
        self.assertNotIn(PRECHECK_LEAK_ITEM_ID, visible)
        self.assertNotIn("precheck boom", visible)

    def test_print_stats_includes_precheck_counters(self) -> None:
        stats = pipeline.PipelineStats()
        stats.processed = 1
        stats.precheck_duplicate = 2
        stats.precheck_failure = 0
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            pipeline.print_stats(stats)
        text = stdout.getvalue()
        self.assertIn("processed=1", text)
        self.assertIn("precheck_duplicate=2", text)
        self.assertIn("precheck_failure=0", text)
        self.assertNotIn(PRECHECK_LEAK_HASH, text)
        self.assertNotIn(PRECHECK_LEAK_PAYLOAD, text)

    def test_pipeline_source_keeps_enqueue_contract_and_no_direct_writes(self) -> None:
        source = pathlib.Path(pipeline.__file__).read_text(encoding="utf-8")
        for pattern in FORBIDDEN_SOURCE_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, source)
        self.assertIn("is_latest_source_revision", source)
        self.assertNotIn("curation_revision_seen", source)
        self.assertEqual(len(pipeline.PRECHECK_PARAM_NAMES), 3)
        self.assertEqual(len(pipeline.ENQUEUE_PARAM_NAMES), 16)
        self.assertNotRegex(source, r"\.upsert\s*\(")


if __name__ == "__main__":
    unittest.main()
