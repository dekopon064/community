"""운영 ingest CLI. 레거시 fetch_and_save.main()을 바꾸지 않는다."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Sequence

from ingest.ai_worker import (
    AI_DISABLED,
    AI_PROCESSED,
    AI_SKIPPED_NOT_CONFIGURED,
    AI_SKIPPED_SOURCE_INCOMPLETE,
    AI_STATE_UNKNOWN,
)
from ingest.connectors.youthcenter_content import (
    CONTENT_API_KEY_ENV,
    YouthcenterContentConnector,
)
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout, map_rpc_exception
from ingest.run import IngestArchitectureResult, run_ingest_architecture
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.supabase_store import create_ingest_client
from ingest.supabase_store import SupabaseIngestStore

SOURCE_CHOICES = (CANONICAL_POLICY_SOURCE, CANONICAL_CONTENT_SOURCE)
REQUIRED_SUPABASE_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
POLICY_API_KEY_ENV = "YOUTH_API_KEY"
REQUIRED_AI_ENV = ("GEMINI_API_KEY",)
MISSING_ENV_MESSAGE = "missing required environment variables"
MISSING_POLICY_KEY_MESSAGE = "missing_youth_policy_api_key"
MISSING_CONTENT_KEY_MESSAGE = "missing_youth_content_api_key"
EXECUTION_FAILED_MESSAGE = "ingest execution failed"


def _missing_env(names: Sequence[str]) -> bool:
    return any(not os.environ.get(name) for name in names)


def cli_exit_code(result: IngestArchitectureResult, *, run_ai: bool) -> int:
    source = result.source_results[0]
    if source.stop_reason in {"lease_held", "source_disabled"}:
        return 1
    if source.status != "complete":
        return 1
    if source.stop_reason == "finish_failed":
        return 1
    if not run_ai:
        return 0
    ai = result.ai
    if ai.status == AI_SKIPPED_SOURCE_INCOMPLETE:
        return 1
    if ai.status in {AI_SKIPPED_NOT_CONFIGURED, AI_DISABLED}:
        return 1
    if ai.status == AI_STATE_UNKNOWN:
        return 1
    if (
        ai.status == AI_PROCESSED
        and ai.failed == 0
        and ai.retried == 0
        and ai.state_unknown == 0
    ):
        return 0
    return 1


def _print_summary(result: IngestArchitectureResult, *, run_ai: bool, exit_code: int) -> None:
    source = result.source_results[0]
    print(
        "ingest source="
        f"{source.source_id} status={source.status} stop_reason={source.stop_reason} "
        f"skipped={source.skipped} batches_ok={source.batches_ok} "
        f"ordering={source.ordering_cli_token()}"
    )
    if run_ai:
        ai = result.ai
        print(
            "ingest ai="
            f"{ai.status} claimed={ai.claimed} completed={ai.completed} "
            f"retried={ai.retried} failed={ai.failed} state_unknown={ai.state_unknown}"
        )
    print(f"ingest exit={exit_code}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_ingest_architecture")
    parser.add_argument(
        "--source",
        required=True,
        choices=SOURCE_CHOICES,
        help="canonical source id; exactly one source per invocation",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="operator approval to perform Youth/DB I/O",
    )
    parser.add_argument(
        "--run-ai",
        action="store_true",
        help="process global AI queue after source complete",
    )
    parser.add_argument(
        "--ai-limit",
        type=int,
        default=None,
        help="global AI claim limit; required with --run-ai, range 1-10",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.run_ai and not args.execute:
        parser.error("--run-ai requires --execute")
    if args.ai_limit is not None and not args.run_ai:
        parser.error("--ai-limit requires --run-ai")
    if args.run_ai and args.ai_limit is None:
        parser.error("--run-ai requires --ai-limit")
    if args.ai_limit is not None and not (1 <= args.ai_limit <= 10):
        parser.error("--ai-limit must be an integer from 1 to 10")


def _youth_api_key() -> str:
    return os.environ[POLICY_API_KEY_ENV]


def _youth_content_api_key() -> str:
    return os.environ[CONTENT_API_KEY_ENV]


def _missing_execute_message(source: str, *, run_ai: bool) -> str | None:
    if _missing_env(REQUIRED_SUPABASE_ENV):
        return MISSING_ENV_MESSAGE
    if source == CANONICAL_POLICY_SOURCE:
        if _missing_env((POLICY_API_KEY_ENV,)):
            return MISSING_POLICY_KEY_MESSAGE
    elif _missing_env((CONTENT_API_KEY_ENV,)):
        return MISSING_CONTENT_KEY_MESSAGE
    if run_ai and _missing_env(REQUIRED_AI_ENV):
        return MISSING_ENV_MESSAGE
    return None


def _load_legacy_ai_helpers() -> dict[str, Any]:
    from fetch_and_save import (
        ENQUEUE_RPC_NAME,
        is_latest_source_revision,
        parse_enqueue_result,
        summarize_with_gemini,
        translate_with_gemini_ja,
    )

    def enqueue(supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
        mapped: BaseException | None = None
        try:
            response = supabase.rpc(ENQUEUE_RPC_NAME, params).execute()
        except Exception as exc:
            candidate = map_rpc_exception(exc)
            mapped = (
                candidate
                if isinstance(candidate, (RpcTimeout, RpcAmbiguous))
                else RpcAmbiguous()
            )
        if mapped is not None:
            raise mapped
        parsed: dict[str, Any] | None = None
        parse_failed = False
        try:
            parsed = parse_enqueue_result(getattr(response, "data", None))
        except Exception:
            parse_failed = True
        if parse_failed or parsed is None:
            raise RpcAmbiguous()
        return parsed

    return {
        "summarize_ko": summarize_with_gemini,
        "translate_ja": translate_with_gemini_ja,
        "enqueue": enqueue,
        "revision_precheck": is_latest_source_revision,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)

    if not args.execute:
        print(
            "ingest dry-run "
            f"source={args.source} execute=false run_ai={str(args.run_ai).lower()} "
            "no-op"
        )
        return 0

    missing = _missing_execute_message(args.source, run_ai=args.run_ai)
    if missing is not None:
        print(missing, file=sys.stderr)
        return 1

    try:
        client = create_ingest_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
        store = SupabaseIngestStore(client)
        if args.source == CANONICAL_POLICY_SOURCE:
            connector = YouthcenterPolicyConnector(api_key_provider=_youth_api_key)
        else:
            connector = YouthcenterContentConnector(
                api_key_provider=_youth_content_api_key
            )

        ai_helpers: dict[str, Any] = {}
        if args.run_ai:
            ai_helpers = _load_legacy_ai_helpers()

        result = run_ingest_architecture(
            store=store,
            connectors=[connector],
            supabase=client if args.run_ai else None,
            summarize_ko=ai_helpers.get("summarize_ko"),
            translate_ja=ai_helpers.get("translate_ja"),
            enqueue=ai_helpers.get("enqueue"),
            revision_precheck=ai_helpers.get("revision_precheck"),
            run_ai=args.run_ai,
            ai_limit=args.ai_limit if args.ai_limit is not None else 10,
        )
        code = cli_exit_code(result, run_ai=args.run_ai)
        _print_summary(result, run_ai=args.run_ai, exit_code=code)
        return code
    except Exception:
        print(EXECUTION_FAILED_MESSAGE, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
