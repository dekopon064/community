"""Explicit-target entry checks using injected callbacks only; no network."""
import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import run_seoul_program_ai as cli

ARGS = ["--source-item-id", "00000000-0000-4000-8000-000000000002",
        "--revision", "a" * 64, "--project-ref", "abcdefghijklmnopqrst"]


class TargetCLITests(unittest.TestCase):
    def call(self, args, callback):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(args, execute=callback)
        return code, out.getvalue()

    def test_default_does_not_create_clients_or_execute(self):
        with patch.object(cli, "execute_target", side_effect=AssertionError("network")):
            code, output = self.call(ARGS, lambda _: self.fail("executed"))
        self.assertEqual(code, 0)
        self.assertIn('"network_calls": 0', output)

    def test_exact_target_single_call(self):
        calls = []
        def execute(args):
            calls.append(args)
            return SimpleNamespace(status="processed", claimed=1, completed=1, failed=0, retried=0, state_unknown=0)
        code, output = self.call(ARGS + ["--execute"], execute)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].revision, "a" * 64)
        self.assertEqual(calls[0].source_item_id, ARGS[1])
        self.assertIn('"publish": false', output)

    def test_no_retry_and_no_false_success(self):
        for status, claimed, completed, retried, unknown in [
                ("ai_no_jobs", 0, 0, 0, 0), ("ai_state_unknown", 1, 0, 0, 1),
                ("processed", 1, 0, 1, 0), ("processed", 2, 2, 0, 0)]:
            calls = []
            def execute(_):
                calls.append(1)
                return SimpleNamespace(status=status, claimed=claimed, completed=completed, failed=0, retried=retried, state_unknown=unknown)
            code, _ = self.call(ARGS + ["--execute"], execute)
            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 1)

    def test_sensitive_exception_is_not_printed(self):
        def execute(_):
            raise RuntimeError("synthetic-secret https://example.test/private-token")
        code, output = self.call(ARGS + ["--execute"], execute)
        self.assertEqual(code, 1)
        self.assertEqual(output.strip(), "program_target_execution_failed")

    def test_invalid_target_rejected_before_execute(self):
        for index, value in [(1, "not-an-id"), (3, "z" * 64), (5, "wrong-project")]:
            args = ARGS.copy(); args[index] = value
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.call(args + ["--execute"], lambda _: self.fail("executed"))

    def test_wrong_environment_fails_before_clients(self):
        args = SimpleNamespace(project_ref=ARGS[5])
        with patch.dict(cli.os.environ, {"SUPABASE_URL": "https://otherproject.supabase.co", "SUPABASE_SERVICE_KEY": "synthetic-key"}, clear=True):
            with self.assertRaisesRegex(ValueError, "invalid_server_configuration"):
                cli.execute_target(args)


if __name__ == "__main__":
    unittest.main()
