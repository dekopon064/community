"""SupabaseIngestStore fake-RPC tests. 실제 Supabase에 연결하지 않는다."""

from __future__ import annotations

import traceback
import unittest
from types import SimpleNamespace
from typing import Any, Callable

from ingest.models import Checkpoint, ObservationRecord
from ingest.rpc_errors import RpcAmbiguous, RpcFailure, RpcTimeout
from ingest.store import LeaseLost
from ingest.supabase_store import (
    CLAIM_PROCESSING_JOBS,
    COMPLETE_PROCESSING_JOB,
    FAIL_PROCESSING_JOB,
    FINISH_INGEST_RUN,
    GET_INGEST_SOURCE,
    INGEST_RPC_TIMEOUT_SECONDS,
    RECONCILE_QUEUED_AI_JOB,
    RESOLVE_INGEST_REVIEW_DECISION,
    START_INGEST_RUN,
    UPSERT_SOURCE_OBSERVATIONS,
    SupabaseIngestStore,
    ingest_client_options,
)

SECRET_MARKER = "svc-secret-marker-DoNotLog"
URL_QUERY_MARKER = "apiKeyNm=secret-query-marker"
RPC_PAYLOAD_MARKER = "rpc-payload-marker-XYZ"
RESPONSE_BODY_MARKER = "response-body-marker-ABC"
CONTENT_BODY_MARKER = "content-body-plain-text-MARKER"


class TimeoutException(Exception):
    pass


class FakeRpc:
    def __init__(self, execute: Callable[[], Any]) -> None:
        self._execute = execute

    def execute(self) -> Any:
        return self._execute()


class FakeClient:
    def __init__(self, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> None:
        self.handlers = handlers
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.table_calls: list[str] = []

    def rpc(self, name: str, params: dict[str, Any] | None = None) -> FakeRpc:
        payload = dict(params or {})
        self.calls.append((name, payload))

        def execute() -> Any:
            result = self.handlers[name](payload)
            if isinstance(result, BaseException):
                raise result
            return SimpleNamespace(data=result)

        return FakeRpc(execute)

    def table(self, name: str) -> None:
        self.table_calls.append(name)
        raise AssertionError("table DML is not allowed")


def _record() -> ObservationRecord:
    return ObservationRecord(
        external_key="p1",
        revision_hash="a" * 64,
        disposition="target",
        min_fields={"title": "t"},
        normalized_payload={"plain_text": CONTENT_BODY_MARKER},
        source_created_at=None,
        source_created_raw=None,
        source_created_parse_status="missing",
        source_updated_at=None,
        source_updated_raw=None,
        source_updated_parse_status="missing",
        has_source_url=True,
        body_usable=True,
        attachment_present=False,
        attachment_length=0,
        is_data_url=False,
    )


def _claimed_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "job_id": "11111111-1111-1111-1111-111111111111",
        "source_item_id": "22222222-2222-2222-2222-222222222222",
        "source_id": "youthcenter_policy",
        "external_key": "p1",
        "revision_hash": "a" * 64,
        "processing_stage": "ai_enrichment",
        "curation_source": "youthcenter",
        "normalized_payload": {"plain_text": "ok"},
        "disposition": "target",
    }
    row.update(overrides)
    return row


def _exc_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


class ClientOptionTests(unittest.TestCase):
    def test_timeout_is_thirty_seconds(self) -> None:
        self.assertEqual(INGEST_RPC_TIMEOUT_SECONDS, 30)
        captured: dict[str, Any] = {}

        class Recorder:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        ingest_client_options(Recorder)
        self.assertEqual(captured["postgrest_client_timeout"], 30)

    def test_pinned_sdk_timeout_contract(self) -> None:
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        pinned = [
            line.strip()
            for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertIn("supabase==2.31.0", pinned)
        try:
            import supabase
            from supabase import ClientOptions
        except ImportError:
            self.skipTest("supabase package not installed")
        module_file = getattr(supabase, "__file__", None)
        if module_file is None:
            self.skipTest("local supabase/ folder shadowed the SDK")
        module_path = __import__("pathlib").Path(module_file).as_posix()
        if "site-packages" not in module_path:
            self.skipTest("installed supabase SDK not on path")
        self.assertEqual(supabase.__version__, "2.31.0")
        options = ClientOptions(postgrest_client_timeout=30)
        self.assertEqual(options.postgrest_client_timeout, 30)


class SupabaseIngestStoreRpcTests(unittest.TestCase):
    def test_rpc_names_and_params_and_happy_paths(self) -> None:
        client = FakeClient(
            {
                GET_INGEST_SOURCE: lambda _p: [
                    {
                        "source_id": "youthcenter_policy",
                        "enabled": True,
                        "permission_status": "testing_only",
                        "legacy_curation_source": "youthcenter",
                    }
                ],
                START_INGEST_RUN: lambda _p: [
                    {
                        "run_id": "33333333-3333-3333-3333-333333333333",
                        "bootstrap_complete": False,
                        "committed_checkpoint": None,
                        "skipped": False,
                        "skip_reason": None,
                    }
                ],
                UPSERT_SOURCE_OBSERVATIONS: lambda _p: [
                    {
                        "input_index": 0,
                        "external_key": "p1",
                        "outcome": "new",
                        "duplicate_in_batch": False,
                    },
                    {
                        "input_index": 1,
                        "external_key": "p1",
                        "outcome": "unchanged",
                        "duplicate_in_batch": True,
                    },
                ],
                FINISH_INGEST_RUN: lambda _p: [
                    {"status": "complete", "stop_reason": "empty_batch"}
                ],
                CLAIM_PROCESSING_JOBS: lambda _p: [_claimed_row()],
                COMPLETE_PROCESSING_JOB: lambda _p: "completed",
                FAIL_PROCESSING_JOB: lambda _p: "queued",
            }
        )
        store = SupabaseIngestStore(client)
        source = store.get_source("youthcenter_policy")
        self.assertEqual(source["source_id"], "youthcenter_policy")
        started = store.start_ingest_run("youthcenter_policy", lease_seconds=120)
        self.assertEqual(started.run_id, "33333333-3333-3333-3333-333333333333")
        results = store.upsert_source_observations(
            "youthcenter_policy",
            started.run_id,
            [_record(), _record()],
            Checkpoint.for_rest_page(2),
        )
        self.assertEqual([row.input_index for row in results], [0, 1])
        self.assertTrue(results[1].skipped_streak)
        self.assertTrue(results[1].duplicate_in_batch)
        finished = store.finish_ingest_run(
            started.run_id,
            status="complete",
            stop_reason="empty_batch",
            http_request_count=1,
        )
        self.assertEqual(finished.status, "complete")
        jobs = store.claim_processing_jobs(
            "ai_enrichment", limit=1, worker_id="ingest-ai-worker"
        )
        self.assertEqual(len(jobs), 1)
        store.complete_processing_job(jobs[0].job_id, worker_id="ingest-ai-worker")
        self.assertEqual(
            store.fail_processing_job(
                jobs[0].job_id, worker_id="ingest-ai-worker", error_code="x"
            ),
            "queued",
        )
        names = [name for name, _params in client.calls]
        self.assertEqual(
            names,
            [
                GET_INGEST_SOURCE,
                START_INGEST_RUN,
                UPSERT_SOURCE_OBSERVATIONS,
                FINISH_INGEST_RUN,
                CLAIM_PROCESSING_JOBS,
                COMPLETE_PROCESSING_JOB,
                FAIL_PROCESSING_JOB,
            ],
        )
        self.assertEqual(client.calls[0][1], {"p_source_id": "youthcenter_policy"})
        self.assertEqual(client.calls[1][1]["p_lease_seconds"], 120)
        self.assertEqual(client.table_calls, [])
        self.assertNotIn("set_source_permission", names)
        self.assertNotIn("publish_curation_candidate", names)
        self.assertEqual(UPSERT_SOURCE_OBSERVATIONS, "upsert_source_observations_v3")
        self.assertNotIn(RESOLVE_INGEST_REVIEW_DECISION, names)
        self.assertNotIn(RECONCILE_QUEUED_AI_JOB, names)
        self.assertTrue(all("lookup" not in name for name in names))
        self.assertEqual(client.calls[2][0], "upsert_source_observations_v3")
        item_payload = client.calls[2][1]["p_items"][0]
        self.assertIn("external_key", item_payload)
        self.assertIn("revision_hash", item_payload)
        self.assertNotIn("source_item_id", item_payload)

    def test_claim_empty_list_is_success(self) -> None:
        client = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p: []})
        jobs = SupabaseIngestStore(client).claim_processing_jobs(
            "ai_enrichment", worker_id="w"
        )
        self.assertEqual(jobs, [])
        self.assertEqual(len(client.calls), 1)

    def test_claim_null_dict_string_and_missing_field_are_ambiguous(self) -> None:
        cases = (None, {"job_id": "x"}, "jobs")
        missing = [_claimed_row()]
        del missing[0]["external_key"]
        cases = cases + (missing, [_claimed_row(job_id=None)])
        for data in cases:
            client = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p, payload=data: payload})
            store = SupabaseIngestStore(client)
            with self.assertRaises(RpcAmbiguous):
                store.claim_processing_jobs("ai_enrichment", worker_id="w")
            self.assertEqual(len(client.calls), 1)

    def test_complete_exact_completed_and_one_unwrap(self) -> None:
        for data in (
            "completed",
            ["completed"],
            [{"complete_processing_job": "completed"}],
        ):
            client = FakeClient({COMPLETE_PROCESSING_JOB: lambda _p, payload=data: payload})
            SupabaseIngestStore(client).complete_processing_job("j", worker_id="w")
            self.assertEqual(len(client.calls), 1)

    def test_complete_malformed_is_ambiguous_once(self) -> None:
        cases = (
            None,
            [],
            {},
            "queued",
            ["completed", "completed"],
            {RESPONSE_BODY_MARKER: "completed"},
            [1],
        )
        for data in cases:
            client = FakeClient({COMPLETE_PROCESSING_JOB: lambda _p, payload=data: payload})
            store = SupabaseIngestStore(client)
            with self.assertRaises(RpcAmbiguous) as caught:
                store.complete_processing_job("j", worker_id="w")
            self.assertEqual(len(client.calls), 1)
            self.assertNotIn(RESPONSE_BODY_MARKER, str(caught.exception))
            self.assertNotIn(RESPONSE_BODY_MARKER, _exc_text(caught.exception))

    def test_fail_accepts_only_queued_or_failed(self) -> None:
        for data in ("queued", "failed", ["queued"], ["failed"]):
            client = FakeClient({FAIL_PROCESSING_JOB: lambda _p, payload=data: payload})
            status = SupabaseIngestStore(client).fail_processing_job(
                "j", worker_id="w", error_code="x"
            )
            self.assertIn(status, {"queued", "failed"})
        client = FakeClient({FAIL_PROCESSING_JOB: lambda _p: "completed"})
        with self.assertRaises(RpcAmbiguous):
            SupabaseIngestStore(client).fail_processing_job(
                "j", worker_id="w", error_code="x"
            )

    def test_finish_empty_and_malformed_fail(self) -> None:
        for data in ([], None, {}, [{"status": "complete"}], [{"stop_reason": "x"}]):
            client = FakeClient({FINISH_INGEST_RUN: lambda _p, payload=data: payload})
            with self.assertRaises(RpcAmbiguous):
                SupabaseIngestStore(client).finish_ingest_run(
                    "r",
                    status="complete",
                    stop_reason="empty_batch",
                    http_request_count=0,
                )

    def test_timeout_is_not_retried_and_scrubs_secrets(self) -> None:
        secret = (
            f"{SECRET_MARKER} {URL_QUERY_MARKER} {RPC_PAYLOAD_MARKER} "
            f"{RESPONSE_BODY_MARKER} {CONTENT_BODY_MARKER}"
        )
        client = FakeClient(
            {COMPLETE_PROCESSING_JOB: lambda _p: TimeoutException(secret)}
        )
        store = SupabaseIngestStore(client)
        with self.assertRaises(RpcTimeout) as caught:
            store.complete_processing_job("j", worker_id="w")
        self.assertEqual(len(client.calls), 1)
        exc = caught.exception
        text = _exc_text(exc)
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        for marker in (
            SECRET_MARKER,
            URL_QUERY_MARKER,
            RPC_PAYLOAD_MARKER,
            RESPONSE_BODY_MARKER,
            CONTENT_BODY_MARKER,
        ):
            self.assertNotIn(marker, str(exc))
            self.assertNotIn(marker, repr(exc))
            self.assertNotIn(marker, text)

    def test_each_method_calls_rpc_once(self) -> None:
        client = FakeClient(
            {
                GET_INGEST_SOURCE: lambda _p: TimeoutException("x"),
                START_INGEST_RUN: lambda _p: TimeoutException("x"),
                UPSERT_SOURCE_OBSERVATIONS: lambda _p: TimeoutException("x"),
                FINISH_INGEST_RUN: lambda _p: TimeoutException("x"),
                CLAIM_PROCESSING_JOBS: lambda _p: TimeoutException("x"),
                COMPLETE_PROCESSING_JOB: lambda _p: TimeoutException("x"),
                FAIL_PROCESSING_JOB: lambda _p: TimeoutException("x"),
            }
        )
        store = SupabaseIngestStore(client)
        calls = [
            lambda: store.get_source("youthcenter_policy"),
            lambda: store.start_ingest_run("youthcenter_policy"),
            lambda: store.upsert_source_observations(
                "youthcenter_policy", "r", [_record()], None
            ),
            lambda: store.finish_ingest_run(
                "r", status="failed", stop_reason="x", http_request_count=0
            ),
            lambda: store.claim_processing_jobs("ai_enrichment", worker_id="w"),
            lambda: store.complete_processing_job("j", worker_id="w"),
            lambda: store.fail_processing_job("j", worker_id="w", error_code="x"),
        ]
        for index, call in enumerate(calls):
            with self.assertRaises(RpcTimeout):
                call()
            self.assertEqual(len(client.calls), index + 1)

    def test_permission_and_publish_are_not_called(self) -> None:
        client = FakeClient({})
        store = SupabaseIngestStore(client)
        with self.assertRaises(RpcFailure):
            store.set_source_permission(
                "youthcenter_policy",
                "approved_noncommercial",
                reason="x",
                evidence_note=None,
                actor="test",
            )
        self.assertEqual(client.calls, [])
        self.assertEqual(client.table_calls, [])

    def test_lease_lost_message_maps_without_body(self) -> None:
        def execute_raise(_params: dict[str, Any]) -> Any:
            exc = Exception(RESPONSE_BODY_MARKER)
            setattr(exc, "message", "lease_lost")
            return exc

        client = FakeClient({UPSERT_SOURCE_OBSERVATIONS: execute_raise})
        with self.assertRaises(LeaseLost) as caught:
            SupabaseIngestStore(client).upsert_source_observations(
                "youthcenter_policy", "r", [_record()], None
            )
        self.assertNotIn(RESPONSE_BODY_MARKER, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


def _source_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "source_id": "youthcenter_policy",
        "enabled": True,
        "permission_status": "testing_only",
        "legacy_curation_source": "youthcenter",
    }
    row.update(overrides)
    return row


def _start_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "run_id": "33333333-3333-3333-3333-333333333333",
        "bootstrap_complete": False,
        "committed_checkpoint": None,
        "skipped": False,
        "skip_reason": None,
    }
    row.update(overrides)
    return row


def _upsert_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "input_index": 0,
        "external_key": "p1",
        "outcome": "new",
        "duplicate_in_batch": False,
    }
    row.update(overrides)
    return row


def _assert_clean(test: unittest.TestCase, exc: BaseException) -> None:
    text = "".join(
        (str(exc), repr(exc), _exc_text(exc))
    )
    for marker in (
        SECRET_MARKER,
        URL_QUERY_MARKER,
        RPC_PAYLOAD_MARKER,
        RESPONSE_BODY_MARKER,
        CONTENT_BODY_MARKER,
    ):
        test.assertNotIn(marker, text)


class StrictSourceParseTests(unittest.TestCase):
    def _get(self, payload: Any) -> Any:
        client = FakeClient({GET_INGEST_SOURCE: lambda _p: payload})
        return SupabaseIngestStore(client), client

    def test_enabled_false_is_kept(self) -> None:
        store, _client = self._get([_source_row(enabled=False)])
        row = store.get_source("youthcenter_policy")
        self.assertIs(row["enabled"], False)

    def test_empty_source_is_not_found(self) -> None:
        store, client = self._get([])
        with self.assertRaises(RpcFailure) as caught:
            store.get_source("youthcenter_policy")
        self.assertEqual(caught.exception.code, "source_not_found")
        self.assertEqual(len(client.calls), 1)

    def test_non_bool_enabled_is_ambiguous(self) -> None:
        for enabled in ("false", 0, 1, None):
            store, client = self._get(
                [_source_row(enabled=enabled, legacy_curation_source=RESPONSE_BODY_MARKER)]
            )
            with self.assertRaises(RpcAmbiguous) as caught:
                store.get_source("youthcenter_policy")
            self.assertEqual(len(client.calls), 1)
            _assert_clean(self, caught.exception)

    def test_missing_field_wrong_id_and_permission(self) -> None:
        missing = _source_row()
        del missing["permission_status"]
        cases = (
            [missing],
            [_source_row(), _source_row()],
            [_source_row(source_id="youthcenter_content")],
            [_source_row(source_id=RESPONSE_BODY_MARKER)],
            [_source_row(permission_status="not_a_status")],
            [_source_row(legacy_curation_source="")],
            [_source_row(legacy_curation_source=RESPONSE_BODY_MARKER[:0])],
        )
        for payload in cases:
            store, client = self._get(payload)
            with self.assertRaises(RpcAmbiguous) as caught:
                store.get_source("youthcenter_policy")
            self.assertEqual(len(client.calls), 1)
            _assert_clean(self, caught.exception)


class StrictStartParseTests(unittest.TestCase):
    def _start(self, payload: Any) -> tuple[SupabaseIngestStore, FakeClient]:
        client = FakeClient({START_INGEST_RUN: lambda _p: payload})
        return SupabaseIngestStore(client), client

    def test_normal_and_skip_rows(self) -> None:
        store, _client = self._start([_start_row()])
        started = store.start_ingest_run("youthcenter_policy")
        self.assertFalse(started.skipped)
        self.assertEqual(started.run_id, "33333333-3333-3333-3333-333333333333")
        self.assertIsNone(started.skip_reason)

        for reason, run_id in (("lease_held", None), ("source_disabled", "")):
            store, _client = self._start(
                [
                    _start_row(
                        run_id=run_id,
                        skipped=True,
                        skip_reason=reason,
                        bootstrap_complete=True,
                    )
                ]
            )
            skipped = store.start_ingest_run("youthcenter_policy")
            self.assertTrue(skipped.skipped)
            self.assertEqual(skipped.run_id, "")
            self.assertEqual(skipped.skip_reason, reason)

    def test_malformed_start_rows(self) -> None:
        missing = _start_row()
        del missing["skipped"]
        cases = (
            [missing],
            [_start_row(skipped="false")],
            [_start_row(bootstrap_complete="false")],
            [_start_row(run_id="")],
            [_start_row(run_id="not-a-uuid")],
            [_start_row(skipped=True, skip_reason="lease_held")],
            [_start_row(skip_reason="lease_held")],
            [
                _start_row(
                    run_id=None,
                    skipped=True,
                    skip_reason="rpc_error",
                )
            ],
            [
                _start_row(
                    run_id=None,
                    skipped=True,
                    skip_reason=RESPONSE_BODY_MARKER,
                )
            ],
            [_start_row(committed_checkpoint=["page"])],
            [_start_row(committed_checkpoint="ckpt")],
            [_start_row(committed_checkpoint=RESPONSE_BODY_MARKER)],
        )
        for payload in cases:
            store, client = self._start(payload)
            with self.assertRaises(RpcAmbiguous) as caught:
                store.start_ingest_run("youthcenter_policy")
            self.assertEqual(len(client.calls), 1)
            _assert_clean(self, caught.exception)


class StrictUpsertParseTests(unittest.TestCase):
    def _upsert(self, payload: Any, records: list[ObservationRecord] | None = None) -> tuple[SupabaseIngestStore, FakeClient, list[ObservationRecord]]:
        client = FakeClient({UPSERT_SOURCE_OBSERVATIONS: lambda _p: payload})
        items = records if records is not None else [_record()]
        return SupabaseIngestStore(client), client, items

    def test_matching_rows_and_empty_batch(self) -> None:
        store, _client, items = self._upsert(
            [
                _upsert_row(),
                _upsert_row(input_index=1, outcome="unchanged", duplicate_in_batch=True),
            ],
            [_record(), _record()],
        )
        results = store.upsert_source_observations(
            "youthcenter_policy", "r", items, None
        )
        self.assertEqual([row.input_index for row in results], [0, 1])
        store, _client, items = self._upsert([], [])
        self.assertEqual(
            store.upsert_source_observations("youthcenter_policy", "r", items, None),
            [],
        )

    def test_malformed_upsert_is_ambiguous_once(self) -> None:
        second = ObservationRecord(**{**_record().__dict__, "external_key": "p2"})
        cases = (
            ([_upsert_row()], [_record(), second]),
            (
                [_upsert_row(), _upsert_row(input_index=1, external_key="p2")],
                [_record()],
            ),
            (
                [
                    _upsert_row(input_index=1, external_key="p2"),
                    _upsert_row(input_index=0),
                ],
                [_record(), second],
            ),
            (
                [
                    _upsert_row(),
                    _upsert_row(input_index=0, external_key="p2"),
                ],
                [_record(), second],
            ),
            ([_upsert_row(external_key="p2")], [_record()]),
            ([_upsert_row(external_key=RESPONSE_BODY_MARKER)], [_record()]),
            ([_upsert_row(outcome="duplicate")], [_record()]),
            ([_upsert_row(duplicate_in_batch="false")], [_record()]),
        )
        for payload, records in cases:
            store, client, items = self._upsert(payload, records)
            with self.assertRaises(RpcAmbiguous) as caught:
                store.upsert_source_observations(
                    "youthcenter_policy", "r", items, None
                )
            self.assertEqual(len(client.calls), 1)
            _assert_clean(self, caught.exception)


class StrictFinishParseTests(unittest.TestCase):
    def test_malformed_finish_values(self) -> None:
        cases = (
            [{"status": "complete", "stop_reason": ""}],
            [{"status": "complete", "stop_reason": None}],
            [{"status": "complete", "stop_reason": 1}],
            [{"status": "complete", "stop_reason": "x" * 65}],
            [{"status": "running", "stop_reason": "empty_batch"}],
        )
        for payload in cases:
            client = FakeClient({FINISH_INGEST_RUN: lambda _p, data=payload: data})
            with self.assertRaises(RpcAmbiguous) as caught:
                SupabaseIngestStore(client).finish_ingest_run(
                    "r",
                    status="complete",
                    stop_reason="empty_batch",
                    http_request_count=0,
                )
            self.assertEqual(len(client.calls), 1)
            _assert_clean(self, caught.exception)


class StrictClaimParseTests(unittest.TestCase):
    def test_empty_and_valid_row(self) -> None:
        empty = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p: []})
        self.assertEqual(
            SupabaseIngestStore(empty).claim_processing_jobs(
                "ai_enrichment", worker_id="w"
            ),
            [],
        )
        client = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p: [_claimed_row()]})
        jobs = SupabaseIngestStore(client).claim_processing_jobs(
            "ai_enrichment", worker_id="w"
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].processing_stage, "ai_enrichment")
        self.assertEqual(client.calls[0][0], CLAIM_PROCESSING_JOBS)
        self.assertEqual(client.calls[0][1]["p_lease_seconds"], 600)

    def test_default_claim_sends_job_lease_600(self) -> None:
        client = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p: []})
        SupabaseIngestStore(client).claim_processing_jobs(
            "ai_enrichment", worker_id="w"
        )
        self.assertEqual(client.calls[0][0], CLAIM_PROCESSING_JOBS)
        params = client.calls[0][1]
        self.assertEqual(params["p_lease_seconds"], 600)
        self.assertEqual(params["p_stage"], "ai_enrichment")
        self.assertEqual(params["p_worker_id"], "w")

    def test_explicit_claim_lease_override_is_kept(self) -> None:
        client = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p: []})
        SupabaseIngestStore(client).claim_processing_jobs(
            "ai_enrichment", worker_id="w", lease_seconds=120
        )
        self.assertEqual(client.calls[0][1]["p_lease_seconds"], 120)

    def test_malformed_claim_is_not_a_job(self) -> None:
        cases = (
            [_claimed_row(processing_stage="region_review")],
            [_claimed_row(job_id=None)],
            [_claimed_row(job_id="not-a-uuid")],
            [_claimed_row(source_item_id=None)],
            [_claimed_row(source_id="")],
            [_claimed_row(external_key="")],
            [_claimed_row(revision_hash="")],
            [_claimed_row(curation_source="")],
            [_claimed_row(normalized_payload=["x"])],
            [_claimed_row(normalized_payload="payload")],
        )
        for payload in cases:
            client = FakeClient({CLAIM_PROCESSING_JOBS: lambda _p, data=payload: data})
            store = SupabaseIngestStore(client)
            with self.assertRaises(RpcAmbiguous) as caught:
                jobs = store.claim_processing_jobs("ai_enrichment", worker_id="w")
                self.assertIsNone(jobs)
            self.assertEqual(len(client.calls), 1)
            _assert_clean(self, caught.exception)


def _decision_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "decision_id": "44444444-4444-4444-4444-444444444444",
        "source_item_id": "22222222-2222-2222-2222-222222222222",
        "revision_hash": "a" * 64,
        "review_type": "relevance",
        "decision": "approve_ai",
        "ai_job_id": "11111111-1111-1111-1111-111111111111",
        "ai_job_status": "queued",
        "review_job_id": None,
        "review_job_status": None,
    }
    row.update(overrides)
    return row


class SupabaseReviewDecisionRpcTests(unittest.TestCase):
    def test_resolve_and_reconcile_use_public_rpc_only(self) -> None:
        client = FakeClient(
            {
                RESOLVE_INGEST_REVIEW_DECISION: lambda _p: [_decision_row()],
                RECONCILE_QUEUED_AI_JOB: lambda _p: [
                    _decision_row(
                        action_result="keep_with_approve",
                        decision="approve_ai",
                    )
                ],
            }
        )
        store = SupabaseIngestStore(client)
        resolved = store.resolve_ingest_review_decision(
            source_item_id="22222222-2222-2222-2222-222222222222",
            revision_hash="a" * 64,
            review_type="relevance",
            decision="approve_ai",
            region_scope="capital",
            audience_relevance=("jp_residents_in_kr",),
            reason_codes=(),
            rule_version="relevance-capital-v1",
            reviewer="classifier:relevance-capital-v1",
        )
        self.assertEqual(resolved.ai_job_status, "queued")
        reconciled = store.reconcile_queued_ai_job(
            "11111111-1111-1111-1111-111111111111",
            action="keep_with_approve",
            review_type="relevance",
            region_scope="capital",
            audience_relevance=("jp_residents_in_kr",),
            rule_version="relevance-capital-v1",
            reviewer="human:reconcile",
        )
        self.assertEqual(reconciled.action_result, "keep_with_approve")
        names = [name for name, _params in client.calls]
        self.assertEqual(
            names,
            [RESOLVE_INGEST_REVIEW_DECISION, RECONCILE_QUEUED_AI_JOB],
        )
        self.assertEqual(client.table_calls, [])
        self.assertNotIn("set_source_permission", names)
        self.assertNotIn("publish_curation_candidate", names)
        self.assertEqual(
            client.calls[0][1]["p_source_item_id"],
            "22222222-2222-2222-2222-222222222222",
        )
        self.assertNotIn("p_plain_text", client.calls[0][1])
        self.assertNotIn("p_normalized_payload", client.calls[0][1])

    def test_resolve_malformed_is_ambiguous(self) -> None:
        client = FakeClient({RESOLVE_INGEST_REVIEW_DECISION: lambda _p: []})
        with self.assertRaises(RpcAmbiguous):
            SupabaseIngestStore(client).resolve_ingest_review_decision(
                source_item_id="22222222-2222-2222-2222-222222222222",
                revision_hash="a" * 64,
                review_type="relevance",
                decision="approve_ai",
                region_scope="capital",
                audience_relevance=("jp_residents_in_kr",),
                rule_version="relevance-capital-v1",
                reviewer="classifier:relevance-capital-v1",
            )


if __name__ == "__main__":
    unittest.main()
