"""운영 ingest CLI 테스트. 실제 HTTP·DB·Gemini를 쓰지 않는다."""

from __future__ import annotations

import inspect
import io
import os
import pathlib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import fetch_and_save as pipeline
import run_ingest_architecture as cli
from ingest.ai_worker import (
    AI_DISABLED,
    AI_PROCESSED,
    AI_SKIPPED_NOT_CONFIGURED,
    AI_SKIPPED_SOURCE_INCOMPLETE,
    AI_STATE_UNKNOWN,
    AiWorkerResult,
)
from ingest.orchestrator import SourceRunResult
from ingest.run import IngestArchitectureResult
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-pipeline.yml"

COMPLETE = SourceRunResult(
    CANONICAL_POLICY_SOURCE,
    status="complete",
    stop_reason="empty_batch",
    batches_ok=1,
    http_request_count=1,
    bootstrap_complete=True,
)


def _result(
    source: SourceRunResult = COMPLETE,
    ai: AiWorkerResult | None = None,
    exit_code: int = 0,
) -> IngestArchitectureResult:
    return IngestArchitectureResult(
        exit_code=exit_code,
        source_results=(source,),
        ai=ai or AiWorkerResult(status=AI_DISABLED),
    )


class CliExitMatrixTests(unittest.TestCase):
    def test_source_complete_ai_off(self) -> None:
        self.assertEqual(cli.cli_exit_code(_result(), run_ai=False), 0)

    def test_ai_processed_clean(self) -> None:
        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_PROCESSED, claimed=0)),
                run_ai=True,
            ),
            0,
        )

    def test_nonzero_cases(self) -> None:
        cases = [
            SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="incomplete",
                stop_reason="max_pages",
                batches_ok=1,
                http_request_count=1,
                bootstrap_complete=False,
            ),
            SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="failed",
                stop_reason="http_403",
                batches_ok=0,
                http_request_count=1,
                bootstrap_complete=False,
            ),
            SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="incomplete",
                stop_reason="finish_failed",
                batches_ok=1,
                http_request_count=1,
                bootstrap_complete=False,
            ),
            SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="incomplete",
                stop_reason="lease_lost",
                batches_ok=1,
                http_request_count=1,
                bootstrap_complete=False,
            ),
            SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="incomplete",
                stop_reason="lease_held",
                batches_ok=0,
                http_request_count=0,
                bootstrap_complete=False,
                skipped=True,
            ),
            SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="failed",
                stop_reason="source_disabled",
                batches_ok=0,
                http_request_count=0,
                bootstrap_complete=False,
                skipped=True,
            ),
        ]
        for source in cases:
            self.assertEqual(cli.cli_exit_code(_result(source=source), run_ai=False), 1)

        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_SKIPPED_SOURCE_INCOMPLETE)),
                run_ai=True,
            ),
            1,
        )
        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_SKIPPED_NOT_CONFIGURED)),
                run_ai=True,
            ),
            1,
        )
        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_DISABLED)),
                run_ai=True,
            ),
            1,
        )
        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_STATE_UNKNOWN, state_unknown=1)),
                run_ai=True,
            ),
            1,
        )
        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_PROCESSED, retried=1, claimed=1)),
                run_ai=True,
            ),
            1,
        )
        self.assertEqual(
            cli.cli_exit_code(
                _result(ai=AiWorkerResult(status=AI_PROCESSED, failed=1, claimed=1)),
                run_ai=True,
            ),
            1,
        )


class CliArgumentTests(unittest.TestCase):
    def test_source_is_required_and_single(self) -> None:
        with self.assertRaises(SystemExit) as missing:
            cli.main([])
        self.assertEqual(missing.exception.code, 2)
        with self.assertRaises(SystemExit) as invalid:
            cli.main(["--source", "not_a_source"])
        self.assertEqual(invalid.exception.code, 2)

    def test_run_ai_execute_limit_combinations(self) -> None:
        with self.assertRaises(SystemExit) as no_execute:
            cli.main(["--source", CANONICAL_POLICY_SOURCE, "--run-ai", "--ai-limit", "1"])
        self.assertEqual(no_execute.exception.code, 2)
        with self.assertRaises(SystemExit) as limit_only:
            cli.main(["--source", CANONICAL_POLICY_SOURCE, "--ai-limit", "1"])
        self.assertEqual(limit_only.exception.code, 2)
        with self.assertRaises(SystemExit) as no_limit:
            cli.main(
                ["--source", CANONICAL_POLICY_SOURCE, "--execute", "--run-ai"]
            )
        self.assertEqual(no_limit.exception.code, 2)
        with self.assertRaises(SystemExit) as zero:
            cli.main(
                [
                    "--source",
                    CANONICAL_POLICY_SOURCE,
                    "--execute",
                    "--run-ai",
                    "--ai-limit",
                    "0",
                ]
            )
        self.assertEqual(zero.exception.code, 2)
        with self.assertRaises(SystemExit) as eleven:
            cli.main(
                [
                    "--source",
                    CANONICAL_POLICY_SOURCE,
                    "--execute",
                    "--run-ai",
                    "--ai-limit",
                    "11",
                ]
            )
        self.assertEqual(eleven.exception.code, 2)

    def test_dry_run_has_no_io(self) -> None:
        with patch("run_ingest_architecture.create_ingest_client") as create:
            with patch("run_ingest_architecture.run_ingest_architecture") as run:
                code = cli.main(["--source", CANONICAL_POLICY_SOURCE])
                content = cli.main(["--source", CANONICAL_CONTENT_SOURCE])
        self.assertEqual(code, 0)
        self.assertEqual(content, 0)
        create.assert_not_called()
        run.assert_not_called()

    def test_missing_env_has_no_io(self) -> None:
        with patch("run_ingest_architecture.create_ingest_client") as create:
            with patch("run_ingest_architecture.run_ingest_architecture") as run:
                with patch.dict(os.environ, {}, clear=True):
                    code = cli.main(
                        ["--source", CANONICAL_POLICY_SOURCE, "--execute"]
                    )
        self.assertEqual(code, 1)
        create.assert_not_called()
        run.assert_not_called()

    def test_missing_gemini_has_no_io(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.invalid",
            "SUPABASE_SERVICE_KEY": "local-test-key",
            "YOUTH_API_KEY": "local-youth-key",
        }
        with patch("run_ingest_architecture.create_ingest_client") as create:
            with patch("run_ingest_architecture.run_ingest_architecture") as run:
                with patch.dict(os.environ, env, clear=True):
                    code = cli.main(
                        [
                            "--source",
                            CANONICAL_POLICY_SOURCE,
                            "--execute",
                            "--run-ai",
                            "--ai-limit",
                            "1",
                        ]
                    )
        self.assertEqual(code, 1)
        create.assert_not_called()
        run.assert_not_called()

    def test_ai_limit_is_passed_through(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.invalid",
            "SUPABASE_SERVICE_KEY": "local-test-key",
            "YOUTH_API_KEY": "local-youth-key",
            "GEMINI_API_KEY": "local-gemini-key",
        }
        fake_result = _result(ai=AiWorkerResult(status=AI_PROCESSED, claimed=0))
        for limit in (1, 10):
            with patch(
                "run_ingest_architecture.create_ingest_client",
                return_value=SimpleNamespace(),
            ):
                with patch(
                    "run_ingest_architecture.YouthcenterPolicyConnector",
                    return_value=object(),
                ):
                    with patch(
                        "run_ingest_architecture._load_legacy_ai_helpers",
                        return_value={
                            "summarize_ko": object(),
                            "translate_ja": object(),
                            "enqueue": object(),
                            "revision_precheck": object(),
                        },
                    ):
                        with patch(
                            "run_ingest_architecture.run_ingest_architecture",
                            return_value=fake_result,
                        ) as run:
                            with patch.dict(os.environ, env, clear=True):
                                code = cli.main(
                                    [
                                        "--source",
                                        CANONICAL_POLICY_SOURCE,
                                        "--execute",
                                        "--run-ai",
                                        "--ai-limit",
                                        str(limit),
                                    ]
                                )
            self.assertEqual(code, 0)
            self.assertEqual(run.call_args.kwargs["ai_limit"], limit)
            self.assertTrue(run.call_args.kwargs["run_ai"])

    def test_legacy_main_default_path_unchanged(self) -> None:
        source = inspect.getsource(pipeline.main)
        self.assertIn("get_supabase_client", source)
        self.assertIn("collect_target_policies", source)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python scripts/fetch_and_save.py", workflow)
        self.assertNotIn("run_ingest_architecture.py", workflow)


SECRET_MARKER = "svc-secret-marker-DoNotLog"
URL_QUERY_MARKER = "apiKeyNm=secret-query-marker"
PAYLOAD_MARKER = "cli-payload-marker-XYZ"
EXECUTE_ARGV = ["--source", CANONICAL_POLICY_SOURCE, "--execute"]
EXECUTE_ENV = {
    "SUPABASE_URL": "https://example.invalid",
    "SUPABASE_SERVICE_KEY": "local-test-key",
    "YOUTH_API_KEY": "local-youth-key",
}
AI_ENV = {
    **EXECUTE_ENV,
    "GEMINI_API_KEY": "local-gemini-key",
}


def _secret_error() -> RuntimeError:
    return RuntimeError(f"{SECRET_MARKER} {URL_QUERY_MARKER} {PAYLOAD_MARKER}")


class CliExecutionBoundaryTests(unittest.TestCase):
    def _run(
        self,
        argv: list[str],
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with patch.dict(os.environ, env if env is not None else EXECUTE_ENV, clear=True):
                code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _assert_fixed_failure(self, stdout: str, stderr: str) -> None:
        self.assertEqual(stderr.strip(), cli.EXECUTION_FAILED_MESSAGE)
        self.assertEqual(stdout, "")
        blob = stdout + stderr
        self.assertNotIn("Traceback", blob)
        for marker in (SECRET_MARKER, URL_QUERY_MARKER, PAYLOAD_MARKER):
            self.assertNotIn(marker, blob)

    def test_create_client_secret_exception_is_swallowed(self) -> None:
        with patch(
            "run_ingest_architecture.create_ingest_client",
            side_effect=_secret_error(),
        ) as create:
            with patch("run_ingest_architecture.YouthcenterPolicyConnector") as connector:
                with patch("run_ingest_architecture._load_legacy_ai_helpers") as helpers:
                    with patch("run_ingest_architecture.run_ingest_architecture") as run:
                        code, stdout, stderr = self._run(EXECUTE_ARGV)
        self.assertEqual(code, 1)
        self._assert_fixed_failure(stdout, stderr)
        create.assert_called_once()
        connector.assert_not_called()
        helpers.assert_not_called()
        run.assert_not_called()

    def test_connector_exception_does_not_run(self) -> None:
        with patch(
            "run_ingest_architecture.create_ingest_client",
            return_value=SimpleNamespace(),
        ):
            with patch(
                "run_ingest_architecture.YouthcenterPolicyConnector",
                side_effect=_secret_error(),
            ):
                with patch("run_ingest_architecture._load_legacy_ai_helpers") as helpers:
                    with patch("run_ingest_architecture.run_ingest_architecture") as run:
                        code, stdout, stderr = self._run(EXECUTE_ARGV)
        self.assertEqual(code, 1)
        self._assert_fixed_failure(stdout, stderr)
        helpers.assert_not_called()
        run.assert_not_called()

    def test_helper_load_exception_does_not_run(self) -> None:
        argv = [
            "--source",
            CANONICAL_POLICY_SOURCE,
            "--execute",
            "--run-ai",
            "--ai-limit",
            "1",
        ]
        with patch(
            "run_ingest_architecture.create_ingest_client",
            return_value=SimpleNamespace(),
        ):
            with patch(
                "run_ingest_architecture.YouthcenterPolicyConnector",
                return_value=object(),
            ):
                with patch(
                    "run_ingest_architecture._load_legacy_ai_helpers",
                    side_effect=_secret_error(),
                ):
                    with patch("run_ingest_architecture.run_ingest_architecture") as run:
                        code, stdout, stderr = self._run(argv, env=AI_ENV)
        self.assertEqual(code, 1)
        self._assert_fixed_failure(stdout, stderr)
        run.assert_not_called()

    def test_architecture_exception_is_not_retried(self) -> None:
        with patch(
            "run_ingest_architecture.create_ingest_client",
            return_value=SimpleNamespace(),
        ):
            with patch(
                "run_ingest_architecture.YouthcenterPolicyConnector",
                return_value=object(),
            ):
                with patch(
                    "run_ingest_architecture.run_ingest_architecture",
                    side_effect=_secret_error(),
                ) as run:
                    code, stdout, stderr = self._run(EXECUTE_ARGV)
        self.assertEqual(code, 1)
        self._assert_fixed_failure(stdout, stderr)
        self.assertEqual(run.call_count, 1)

    def test_summary_exception_is_secret_safe(self) -> None:
        with patch(
            "run_ingest_architecture.create_ingest_client",
            return_value=SimpleNamespace(),
        ):
            with patch(
                "run_ingest_architecture.YouthcenterPolicyConnector",
                return_value=object(),
            ):
                with patch(
                    "run_ingest_architecture.run_ingest_architecture",
                    return_value=_result(),
                ) as run:
                    with patch(
                        "run_ingest_architecture._print_summary",
                        side_effect=_secret_error(),
                    ):
                        code, stdout, stderr = self._run(EXECUTE_ARGV)
        self.assertEqual(code, 1)
        self._assert_fixed_failure(stdout, stderr)
        self.assertEqual(run.call_count, 1)

    def test_argparse_error_still_exits_two(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--source", "not_a_source"])
        self.assertEqual(caught.exception.code, 2)
        blob = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(cli.EXECUTION_FAILED_MESSAGE, blob)
        for marker in (SECRET_MARKER, URL_QUERY_MARKER, PAYLOAD_MARKER):
            self.assertNotIn(marker, blob)

    def test_missing_env_and_dry_run_contracts(self) -> None:
        with patch("run_ingest_architecture.create_ingest_client") as create:
            with patch("run_ingest_architecture.run_ingest_architecture") as run:
                missing_code, missing_out, missing_err = self._run(
                    EXECUTE_ARGV, env={}
                )
                dry_code, dry_out, dry_err = self._run(
                    ["--source", CANONICAL_POLICY_SOURCE], env={}
                )
        self.assertEqual(missing_code, 1)
        self.assertIn("missing required environment variables", missing_err)
        self.assertEqual(missing_out, "")
        self.assertEqual(dry_code, 0)
        self.assertIn("ingest dry-run", dry_out)
        self.assertEqual(dry_err, "")
        create.assert_not_called()
        run.assert_not_called()

    def test_happy_path_summary_and_exit_zero(self) -> None:
        with patch(
            "run_ingest_architecture.create_ingest_client",
            return_value=SimpleNamespace(),
        ):
            with patch(
                "run_ingest_architecture.YouthcenterPolicyConnector",
                return_value=object(),
            ):
                with patch(
                    "run_ingest_architecture.run_ingest_architecture",
                    return_value=_result(),
                ) as run:
                    code, stdout, stderr = self._run(EXECUTE_ARGV)
        self.assertEqual(code, 0)
        self.assertIn("ingest source=", stdout)
        self.assertIn("ingest exit=0", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(run.call_count, 1)
        self.assertIn("ordering=ok", stdout)


class CliOrderingSummaryTests(unittest.TestCase):
    def test_configured_range_complete_is_success(self) -> None:
        source = SourceRunResult(
            CANONICAL_POLICY_SOURCE,
            status="complete",
            stop_reason="configured_range_complete",
            batches_ok=10,
            http_request_count=10,
            bootstrap_complete=True,
        )
        self.assertEqual(cli.cli_exit_code(_result(source=source), run_ai=False), 0)

    def test_ordering_tokens_are_deterministic(self) -> None:
        cases = [
            (frozenset(), "ordering=ok"),
            (frozenset({"missing_stamp"}), "ordering=missing_stamp"),
            (frozenset({"non_monotonic_stamp"}), "ordering=non_monotonic_stamp"),
            (
                frozenset({"non_monotonic_stamp", "missing_stamp"}),
                "ordering=missing_stamp,non_monotonic_stamp",
            ),
        ]
        for diagnostics, token in cases:
            source = SourceRunResult(
                CANONICAL_POLICY_SOURCE,
                status="complete",
                stop_reason="bootstrap_range_complete",
                batches_ok=5,
                http_request_count=5,
                bootstrap_complete=True,
                ordering_diagnostics=diagnostics,
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                cli._print_summary(_result(source=source), run_ai=False, exit_code=0)
            text = stdout.getvalue()
            self.assertIn(token, text)
            self.assertNotIn(" ", token.split("=", 1)[1].replace(",", ""))
            for marker in (SECRET_MARKER, URL_QUERY_MARKER, PAYLOAD_MARKER):
                self.assertNotIn(marker, text)
            self.assertNotIn("plcyNo", text)
            self.assertNotIn("https://", text)


class _SpyMemoryStore(MemoryIngestStore):
    def __init__(self) -> None:
        super().__init__()
        self.get_source_calls = 0
        self.start_calls = 0

    def get_source(self, source_id: str):  # type: ignore[no-untyped-def]
        self.get_source_calls += 1
        return super().get_source(source_id)

    def start_ingest_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.start_calls += 1
        return super().start_ingest_run(*args, **kwargs)


class _MissingOrderingConnector:
    canonical_source_id = CANONICAL_POLICY_SOURCE

    def fetch_batch(self, checkpoint):  # type: ignore[no-untyped-def]
        raise AssertionError("youth_api_called")


class _InvalidOrderingConnector:
    canonical_source_id = CANONICAL_POLICY_SOURCE
    ordering_capability = "guaranteed_descending"

    def fetch_batch(self, checkpoint):  # type: ignore[no-untyped-def]
        raise AssertionError("youth_api_called")


class CliInvalidCapabilityTests(unittest.TestCase):
    def _run_with_connector(self, connector: object) -> tuple[int, str, str, _SpyMemoryStore]:
        spy = _SpyMemoryStore()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with patch.dict(os.environ, EXECUTE_ENV, clear=True):
                with patch(
                    "run_ingest_architecture.create_ingest_client",
                    return_value=SimpleNamespace(),
                ):
                    with patch(
                        "run_ingest_architecture.SupabaseIngestStore",
                        return_value=spy,
                    ):
                        with patch(
                            "run_ingest_architecture.YouthcenterPolicyConnector",
                            return_value=connector,
                        ):
                            code = cli.main(EXECUTE_ARGV)
        return code, stdout.getvalue(), stderr.getvalue(), spy

    def test_missing_capability_is_secret_safe_cli_failure(self) -> None:
        code, stdout, stderr, spy = self._run_with_connector(_MissingOrderingConnector())
        self.assertEqual(code, 1)
        self.assertEqual(stderr.strip(), cli.EXECUTION_FAILED_MESSAGE)
        self.assertEqual(stdout, "")
        self.assertNotIn("Traceback", stdout + stderr)
        self.assertEqual(spy.get_source_calls, 0)
        self.assertEqual(spy.start_calls, 0)
        for marker in (SECRET_MARKER, URL_QUERY_MARKER, PAYLOAD_MARKER):
            self.assertNotIn(marker, stdout + stderr)

    def test_invalid_capability_is_secret_safe_cli_failure(self) -> None:
        code, stdout, stderr, spy = self._run_with_connector(_InvalidOrderingConnector())
        self.assertEqual(code, 1)
        self.assertEqual(stderr.strip(), cli.EXECUTION_FAILED_MESSAGE)
        self.assertEqual(stdout, "")
        self.assertEqual(spy.get_source_calls, 0)
        self.assertEqual(spy.start_calls, 0)
        self.assertNotIn("guaranteed_descending", stdout + stderr)


if __name__ == "__main__":
    unittest.main()
