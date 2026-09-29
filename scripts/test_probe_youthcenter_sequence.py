"""Read-only sequence probe tests. All HTTP responses are synthetic."""

from __future__ import annotations

import json
import pathlib
import unittest
from datetime import datetime, timezone
from typing import Any

from ingest.connectors.youthcenter_content import YouthcenterContentConnector
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.http_client import HttpClient
from probe_youthcenter_sequence import run_sequence


class FakeResponse:
    def __init__(self, status: int, items: list[dict[str, Any]]) -> None:
        self.status_code = status
        self.headers: dict[str, str] = {}
        self.body = json.dumps({"result": {"youthPolicyList": items}}).encode()

    def iter_content(self, **_kwargs):
        yield self.body

    def close(self) -> None:
        pass


class SequenceProbeTests(unittest.TestCase):
    def _run(
        self, *, policy_failure_page: int | None = None,
        policy_early_end_page: int | None = None,
        content_status: int = 200,
    ) -> tuple[int, list[tuple[str, int, int]], list[float], list[str]]:
        calls: list[tuple[str, int, int]] = []
        sleeps: list[float] = []
        lines: list[str] = []
        elapsed = [0.0]

        def transport(source: str):
            def send(_url: str, **kwargs):
                page = kwargs["params"]["pageNum"]
                size = kwargs["params"]["pageSize"]
                calls.append((source, page, size))
                elapsed[0] += 0.2
                if source == "policy":
                    status = 503 if page == policy_failure_page else 200
                    count = 4 if page == policy_early_end_page else 5
                else:
                    status = content_status
                    count = 5
                return FakeResponse(status, [{"id": str(i)} for i in range(count)])
            return send

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            elapsed[0] += seconds

        policy = YouthcenterPolicyConnector(
            http=HttpClient(budget=5, max_attempts=1, transport=transport("policy")),
            api_key_provider=lambda: "local-policy-key",
        )
        content = YouthcenterContentConnector(
            http=HttpClient(budget=1, max_attempts=1, transport=transport("content")),
            api_key_provider=lambda: "local-content-key",
        )
        result = run_sequence(
            policy, content, sleep=fake_sleep, clock=lambda: elapsed[0],
            utc_now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc),
            emit=lines.append,
        )
        return result, calls, sleeps, lines

    def test_five_policy_pages_then_one_content_with_no_transition_sleep(self) -> None:
        result, calls, sleeps, lines = self._run()
        self.assertEqual(result, 0)
        self.assertEqual(calls, [("policy", page, 5) for page in range(1, 6)] + [("content", 1, 5)])
        self.assertEqual(sleeps, [1.0] * 4)
        self.assertEqual(len(calls), 6)
        self.assertIn("after_policy_response_ms=0", lines[-2])
        self.assertIn("started_at=2026-09-29T00:00:00.000Z", lines[0])
        self.assertIn("total_requests=6", lines[-1])

    def test_policy_failure_stops_without_retry_or_content(self) -> None:
        result, calls, sleeps, lines = self._run(policy_failure_page=3)
        self.assertEqual(result, 1)
        self.assertEqual(calls, [("policy", 1, 5), ("policy", 2, 5), ("policy", 3, 5)])
        self.assertEqual(sleeps, [1.0, 1.0])
        self.assertIn("reason=policy_error policy_requests=3 content_requests=0", lines[-1])

    def test_early_natural_end_stops_before_content(self) -> None:
        result, calls, _sleeps, lines = self._run(policy_early_end_page=2)
        self.assertEqual(result, 1)
        self.assertEqual(calls, [("policy", 1, 5), ("policy", 2, 5)])
        self.assertIn("reason=policy_early_end", lines[-1])

    def test_content_failure_is_one_request_only(self) -> None:
        result, calls, sleeps, lines = self._run(content_status=403)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls[-1], ("content", 1, 5))
        self.assertEqual(sleeps, [1.0] * 4)
        self.assertIn("reason=content_error policy_requests=5 content_requests=1", lines[-1])

    def test_workflow_is_manual_and_has_only_source_keys(self) -> None:
        workflow = (
            pathlib.Path(__file__).resolve().parents[1]
            / ".github/workflows/manual-ingest-sequence-probe.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("group: machimoa-ingest-production", workflow)
        self.assertIn("environment: machimoa-ingest-production", workflow)
        self.assertIn("secrets.YOUTH_API_KEY", workflow)
        self.assertIn("secrets.YOUTH_CONTENT_API_KEY", workflow)
        self.assertNotIn("SUPABASE_", workflow)
        self.assertNotIn("ANTHROPIC_API_KEY", workflow)
        self.assertNotIn("--run-ai", workflow)


if __name__ == "__main__":
    unittest.main()
