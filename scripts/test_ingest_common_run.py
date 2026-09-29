"""Bounded, registration-ordered ingest contract without external I/O."""

from __future__ import annotations

import pathlib
import unittest

from ingest.connectors.youthcenter_content import YouthcenterContentConnector
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.ai_worker import AI_DISABLED, AiWorkerResult
from ingest.http_client import HttpClient
from ingest.models import BatchResult, Checkpoint, ObservationResult
from ingest.orchestrator import advance_unchanged_streak, run_connector, run_ingest
from ingest.run import IngestArchitectureResult
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore
from run_ingest_architecture import cli_exit_code
from test_ingest import FakeConnector, FakeStreamResponse, NO_SLEEP, _page_batches, policy_item


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "manual-ingest-both.yml"


def _item(key: str, rank: int, *, created: str | None = None, updated: str = ""):
    return policy_item(
        key,
        zip_cd="11680",
        oper_cd="11680",
        created=created if created is not None else f"2026-09-{30 - rank:02d} 12:00:00",
        updated=updated,
    )


def _connector(source: str, items: list[dict], *, natural_end: bool = False):
    connector = FakeConnector(
        batches=_page_batches(items, page_size=5, natural_end=natural_end),
        source_id=source,
        max_pages=5,
        bootstrap_max_pages=5,
        bootstrap_max_items=25,
    )
    connector.ordering_stamp_basis = "created"
    return connector


class SourceBoundsTests(unittest.TestCase):
    def test_both_sources_request_five_and_scan_at_most_five_pages(self) -> None:
        for cls in (YouthcenterPolicyConnector, YouthcenterContentConnector):
            with self.subTest(source=cls.__name__):
                connector = cls(api_key_provider=lambda: "unused")
                self.assertEqual(connector.page_size, 5)
                self.assertEqual(connector.bootstrap_max_pages, 5)
                self.assertEqual(connector.bootstrap_max_items, 25)
                self.assertEqual(connector.max_pages, 5)
                self.assertEqual(connector.streak_needed, 3)
                self.assertEqual(connector.ordering_stamp_basis, "created")

    def test_bootstrap_observes_25_without_streak_stop(self) -> None:
        for source in (CANONICAL_POLICY_SOURCE, CANONICAL_CONTENT_SOURCE):
            with self.subTest(source=source):
                store = MemoryIngestStore()
                items = [_item(f"{source}-{i}", i) for i in range(25)]
                result = run_connector(_connector(source, items), store, sleep=NO_SLEEP)
                self.assertEqual(result.status, "complete")
                self.assertEqual(result.stop_reason, "bootstrap_range_complete")
                self.assertEqual(result.batches_ok, 5)
                self.assertTrue(store.sync[source].bootstrap_complete)

    def test_content_fake_api_returns_five_per_page_into_local_store(self) -> None:
        requested: list[tuple[int, int]] = []

        def transport(_url: str, **kwargs):
            params = kwargs["params"]
            requested.append((params["pageNum"], params["pageSize"]))
            rows = [
                {
                    "bbsSn": "48",
                    "pstSn": str(i),
                    "pstTtl": f"모의 콘텐츠 {i}",
                    "pstWholCn": "신청 안내 본문입니다.",
                    "pstUrlAddr": f"https://example.org/{i}",
                    "frstRegDt": f"2026-09-{30 - i:02d} 12:00:00",
                }
                for i in range(5)
            ] if params["pageNum"] == 1 else []
            return FakeStreamResponse(200, json_payload={"result": {"youthPolicyList": rows}})

        connector = YouthcenterContentConnector(
            http=HttpClient(budget=15, sleep=NO_SLEEP, transport=transport),
            api_key_provider=lambda: "fake-key",
        )
        store = MemoryIngestStore()
        result = run_connector(connector, store, sleep=NO_SLEEP)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "empty_batch")
        self.assertEqual(requested, [(1, 5), (2, 5)])
        self.assertEqual(len(store.items), 5)

    def test_content_fake_api_oversized_page_is_rejected(self) -> None:
        rows = [{"bbsSn": "48", "pstSn": str(i)} for i in range(6)]

        def transport(_url: str, **_kwargs):
            return FakeStreamResponse(200, json_payload={"result": {"youthPolicyList": rows}})

        connector = YouthcenterContentConnector(
            http=HttpClient(budget=15, sleep=NO_SLEEP, transport=transport),
            api_key_provider=lambda: "fake-key",
        )
        store = MemoryIngestStore()
        result = run_connector(connector, store, sleep=NO_SLEEP)
        self.assertEqual(result.stop_reason, "oversized_page")
        self.assertEqual(result.status, "failed")
        self.assertEqual(store.items, {})

    def test_registration_order_ignores_nonmonotonic_update_times_and_stops(self) -> None:
        for source in (CANONICAL_POLICY_SOURCE, CANONICAL_CONTENT_SOURCE):
            with self.subTest(source=source):
                store = MemoryIngestStore()
                older = [
                    _item(f"{source}-old-{i}", i + 3, updated="2026-10-01 12:00:00")
                    for i in range(7)
                ]
                seed = run_connector(_connector(source, older, natural_end=True), store, sleep=NO_SLEEP)
                self.assertEqual(seed.status, "complete")
                fresh = [_item(f"{source}-new-{i}", i) for i in range(3)]
                connector = _connector(source, fresh + older)
                result = run_connector(connector, store, sleep=NO_SLEEP)
                self.assertEqual(result.status, "complete")
                self.assertEqual(result.stop_reason, "streak_complete")
                self.assertEqual(result.batches_ok, 2)
                self.assertEqual(result.ordering_cli_token(), "ok")

    def test_changed_and_new_reset_streak_within_page(self) -> None:
        def row(index: int, outcome: str, *, duplicate: bool = False):
            return ObservationResult(index, f"row-{index}", outcome, duplicate_in_batch=duplicate)

        first = [row(0, "unchanged"), row(1, "unchanged"), row(2, "changed"), row(3, "unchanged")]
        second = [row(4, "new"), row(5, "unchanged"), row(6, "unchanged")]
        self.assertEqual(advance_unchanged_streak(0, first), 1)
        self.assertEqual(advance_unchanged_streak(1, second), 2)
        self.assertEqual(advance_unchanged_streak(2, [row(7, "unchanged")]), 3)
        self.assertEqual(advance_unchanged_streak(2, [row(8, "unchanged", duplicate=True)]), 2)

    def test_missing_or_reversed_registration_stamp_disables_early_stop(self) -> None:
        for issue in ("missing", "reversed"):
            with self.subTest(issue=issue):
                store = MemoryIngestStore()
                store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
                items = [_item(f"{issue}-{i}", i) for i in range(25)]
                if issue == "missing":
                    items[1] = _item("missing-1", 1, created="")
                else:
                    items[1] = _item("reversed-1", 1, created="2026-10-01 12:00:00")
                result = run_connector(
                    _connector(CANONICAL_POLICY_SOURCE, items),
                    store,
                    sleep=NO_SLEEP,
                )
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.stop_reason, "ordering_anomaly")
                self.assertNotEqual(result.ordering_cli_token(), "ok")

    def test_25_without_boundary_is_range_exceeded(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_CONTENT_SOURCE].bootstrap_complete = True
        items = [_item(f"limit-{i}", i) for i in range(25)]
        result = run_connector(_connector(CANONICAL_CONTENT_SOURCE, items), store, sleep=NO_SLEEP)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "range_exceeded")
        self.assertEqual(result.batches_ok, 5)
        cli_result = IngestArchitectureResult(
            exit_code=0,
            source_results=(result,),
            ai=AiWorkerResult(status=AI_DISABLED),
        )
        self.assertEqual(cli_exit_code(cli_result, run_ai=False), 1)

    def test_oversized_normal_page_fails_before_writes(self) -> None:
        store = MemoryIngestStore()
        connector = FakeConnector(
            batches=[
                BatchResult(
                    items=tuple(_item(f"large-{i}", i) for i in range(6)),
                    next_checkpoint=Checkpoint.for_rest_page(2),
                    natural_end=False,
                )
            ],
            max_pages=5,
        )
        connector.ordering_stamp_basis = "created"
        result = run_connector(connector, store, sleep=NO_SLEEP)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.stop_reason, "oversized_page")
        self.assertEqual(store.items, {})

    def test_source_failure_does_not_skip_other_source(self) -> None:
        store = MemoryIngestStore()
        first = FakeConnector(source_id=CANONICAL_POLICY_SOURCE, fetch_error=RuntimeError(), error_on=1)
        second = _connector(CANONICAL_CONTENT_SOURCE, [_item("isolated", 0)], natural_end=True)
        results = run_ingest([first, second], store, sleep=NO_SLEEP)
        self.assertEqual([result.status for result in results], ["failed", "complete"])
        self.assertEqual(second.calls, 1)


class WorkflowContractTests(unittest.TestCase):
    def test_manual_both_sources_without_ai_or_schedule(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("--run-ai", workflow)
        self.assertNotIn("--ai-only", workflow)
        self.assertNotIn("--canary-one-page", workflow)
        self.assertIn("group: machimoa-ingest-production", workflow)
        self.assertIn("environment: machimoa-ingest-production", workflow)
        self.assertIn("contents: read", workflow)
        self.assertLess(workflow.index("--source youthcenter_policy"), workflow.index("--source youthcenter_content"))
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("steps.policy.outcome", workflow)
        self.assertIn("steps.content.outcome", workflow)
        self.assertIn("YOUTH_API_KEY: ${{ secrets.YOUTH_API_KEY }}", workflow)
        self.assertIn("YOUTH_CONTENT_API_KEY: ${{ secrets.YOUTH_CONTENT_API_KEY }}", workflow)
        self.assertNotIn("ANTHROPIC_API_KEY", workflow)


if __name__ == "__main__":
    unittest.main()
