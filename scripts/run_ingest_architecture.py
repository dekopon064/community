"""운영 ingest CLI. AI provider는 Anthropic만 허용한다."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from typing import Any, Sequence

from ingest.ai_provider import (
    INVALID_AI_PROVIDER,
    PROVIDER_ANTHROPIC,
    ProviderError,
    require_configured_provider,
)
from ingest.ai_worker import (
    AI_DISABLED,
    AI_NO_JOBS,
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
from ingest.run import IngestArchitectureResult, run_ai_only, run_ingest_architecture
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.supabase_store import create_ingest_client
from ingest.supabase_store import SupabaseIngestStore

SOURCE_CHOICES = (CANONICAL_POLICY_SOURCE, CANONICAL_CONTENT_SOURCE)
REQUIRED_SUPABASE_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
POLICY_API_KEY_ENV = "YOUTH_API_KEY"
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
    if ai.status in {AI_SKIPPED_NOT_CONFIGURED, AI_DISABLED, AI_NO_JOBS}:
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


def cli_ai_only_exit_code(
    result: IngestArchitectureResult, *, targeted: bool = False
) -> int:
    ai = result.ai
    if ai.status == AI_NO_JOBS:
        if targeted or any(
            (ai.claimed, ai.completed, ai.failed, ai.retried, ai.state_unknown)
        ):
            return 1
        return 0
    if ai.status != AI_PROCESSED:
        return 1
    if ai.claimed < 1:
        return 1
    if ai.completed != ai.claimed:
        return 1
    if ai.failed or ai.retried or ai.state_unknown:
        return 1
    return 0


def _print_summary(result: IngestArchitectureResult, *, run_ai: bool, exit_code: int) -> None:
    source = result.source_results[0]
    print(
        "ingest source="
        f"{source.source_id} status={source.status} stop_reason={source.stop_reason} "
        f"skipped={source.skipped} batches_ok={source.batches_ok} "
        f"http_requests={source.http_request_count} "
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


def _print_ai_only_summary(result: IngestArchitectureResult, *, exit_code: int) -> None:
    ai = result.ai
    if ai.status == AI_NO_JOBS and exit_code == 0:
        print("작업 내용 없음: 처리할 AI 대기열 항목이 없습니다.")
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
        required=False,
        choices=SOURCE_CHOICES,
        help="canonical source id; exactly one source per invocation",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="operator approval to perform Youth/DB I/O",
    )
    parser.add_argument(
        "--canary-one-page",
        action="store_true",
        help="process at most one API page without completing a truncated bootstrap",
    )
    parser.add_argument(
        "--full-scan-once",
        action="store_true",
        help="manually scan the configured range without the unchanged streak stop; no AI",
    )
    parser.add_argument(
        "--run-ai",
        action="store_true",
        help="process global AI queue after source complete",
    )
    parser.add_argument(
        "--ai-only",
        action="store_true",
        help="process global AI queue without source ingest or Youth API",
    )
    parser.add_argument(
        "--ai-limit",
        type=int,
        default=None,
        help="global AI claim limit; required with --run-ai/--ai-only, range 1-10",
    )
    parser.add_argument(
        "--ai-source-item-id",
        default=None,
        help="current source item UUID for a targeted one-job AI canary",
    )
    parser.add_argument(
        "--ai-revision-hash",
        default=None,
        help="current revision hash for a targeted one-job AI canary",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.canary_one_page and (args.ai_only or args.run_ai):
        parser.error("--canary-one-page cannot be combined with AI options")
    if args.full_scan_once and (args.canary_one_page or args.ai_only or args.run_ai):
        parser.error("--full-scan-once cannot be combined with canary or AI options")
    if args.full_scan_once and not args.execute:
        parser.error("--full-scan-once requires --execute")
    if args.ai_only and args.source:
        parser.error("--ai-only cannot be used with --source")
    if args.ai_only and args.run_ai:
        parser.error("--ai-only cannot be used with --run-ai")
    if not args.ai_only and not args.source:
        parser.error("--source is required unless --ai-only")
    if args.run_ai and not args.execute:
        parser.error("--run-ai requires --execute")
    if args.ai_only and not args.execute:
        parser.error("--ai-only requires --execute")
    if args.ai_limit is not None and not args.run_ai and not args.ai_only:
        parser.error("--ai-limit requires --run-ai or --ai-only")
    if args.run_ai and args.ai_limit is None:
        parser.error("--run-ai requires --ai-limit")
    if args.ai_only and args.ai_limit is None:
        parser.error("--ai-only requires --ai-limit")
    if args.ai_limit is not None and not (1 <= args.ai_limit <= 10):
        parser.error("--ai-limit must be an integer from 1 to 10")
    targeted = args.ai_source_item_id is not None or args.ai_revision_hash is not None
    if targeted:
        if not args.ai_only or args.ai_limit != 1:
            parser.error("AI target requires --ai-only --ai-limit 1")
        try:
            uuid.UUID(args.ai_source_item_id or "")
        except ValueError:
            parser.error("--ai-source-item-id must be a UUID")
        if not args.ai_revision_hash or len(args.ai_revision_hash) != 64 or any(
            character not in "0123456789abcdef" for character in args.ai_revision_hash
        ):
            parser.error("--ai-revision-hash must be a lowercase SHA-256 hash")


def _youth_api_key() -> str:
    return os.environ[POLICY_API_KEY_ENV]


def _youth_content_api_key() -> str:
    return os.environ[CONTENT_API_KEY_ENV]


def _missing_source_execute_message(source: str) -> str | None:
    if _missing_env(REQUIRED_SUPABASE_ENV):
        return MISSING_ENV_MESSAGE
    if source == CANONICAL_POLICY_SOURCE:
        if _missing_env((POLICY_API_KEY_ENV,)):
            return MISSING_POLICY_KEY_MESSAGE
    elif _missing_env((CONTENT_API_KEY_ENV,)):
        return MISSING_CONTENT_KEY_MESSAGE
    return None


def _missing_ai_only_execute_message() -> str | None:
    if _missing_env(REQUIRED_SUPABASE_ENV):
        return MISSING_ENV_MESSAGE
    return None


def _load_anthropic_ai_helpers(api_key: str) -> dict[str, Any]:
    from ingest.ai_claude import ClaudeAdapter
    from ingest.ai_queue_rpc import enqueue_curation_candidate, is_latest_source_revision

    adapter = ClaudeAdapter(api_key=api_key)
    return {
        "summarize_ko": adapter.summarize_ko,
        "translate_ja": adapter.translate_ja,
        "enqueue": enqueue_curation_candidate,
        "revision_precheck": is_latest_source_revision,
    }


def _load_ai_helpers(provider: str, api_key: str) -> dict[str, Any]:
    if provider != PROVIDER_ANTHROPIC:
        raise ProviderError(INVALID_AI_PROVIDER)
    return _load_anthropic_ai_helpers(api_key)


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

    provider: str | None = None
    provider_key: str | None = None
    if args.run_ai or args.ai_only:
        try:
            provider, provider_key = require_configured_provider()
        except ProviderError as exc:
            print(exc.code, file=sys.stderr)
            return 1

    if args.ai_only:
        missing = _missing_ai_only_execute_message()
    else:
        missing = _missing_source_execute_message(args.source)
    if missing is not None:
        print(missing, file=sys.stderr)
        return 1

    try:
        client = create_ingest_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
        store = SupabaseIngestStore(client)
        ai_helpers: dict[str, Any] = {}
        if provider is not None and provider_key is not None:
            ai_helpers = _load_ai_helpers(provider, provider_key)

        if args.ai_only:
            result = run_ai_only(
                store=store,
                supabase=client,
                summarize_ko=ai_helpers.get("summarize_ko"),
                translate_ja=ai_helpers.get("translate_ja"),
                enqueue=ai_helpers.get("enqueue"),
                revision_precheck=ai_helpers.get("revision_precheck"),
                ai_limit=args.ai_limit if args.ai_limit is not None else 1,
                target_source_item_id=args.ai_source_item_id,
                target_revision_hash=args.ai_revision_hash,
            )
            code = cli_ai_only_exit_code(
                result, targeted=args.ai_source_item_id is not None
            )
            _print_ai_only_summary(result, exit_code=code)
            return code

        if args.source == CANONICAL_POLICY_SOURCE:
            connector = YouthcenterPolicyConnector(api_key_provider=_youth_api_key)
        else:
            connector = YouthcenterContentConnector(
                api_key_provider=_youth_content_api_key
            )

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
            page_limit=1 if args.canary_one_page else None,
            force_full_range=args.full_scan_once,
        )
        code = cli_exit_code(result, run_ai=args.run_ai)
        _print_summary(result, run_ai=args.run_ai, exit_code=code)
        return code
    except Exception:
        print(EXECUTION_FAILED_MESSAGE, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
